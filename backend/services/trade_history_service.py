"""
Trade History Service

Tracks all trades (manual and auto-trader) with detailed P&L information.
Provides analytics and performance metrics.

Persisted in MongoDB (collection: trade_history) instead of a flat JSON
file, to avoid concurrency corruption and match the rest of the stack.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from database import db

logger = logging.getLogger(__name__)


class TradeHistoryService:
    def __init__(self):
        self.collection = db.trade_history

    def _calculate_hold_time(self, entry_time: Optional[str], exit_time: Optional[str]) -> str:
        """Calculate how long position was held"""
        try:
            if not entry_time or not exit_time:
                return "Unknown"

            entry = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
            exit = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))

            delta = exit - entry
            hours = delta.total_seconds() / 3600

            if hours < 1:
                return f"{int(delta.total_seconds() / 60)} minutes"
            elif hours < 24:
                return f"{hours:.1f} hours"
            else:
                return f"{hours / 24:.1f} days"

        except Exception:
            return "Unknown"

    async def log_trade(self, trade_data: Dict):
        """
        Log a completed trade

        trade_data should include:
        - symbol: str
        - entry_price: float
        - exit_price: float
        - shares: float
        - entry_time: str (ISO format)
        - exit_time: str (ISO format)
        - pnl: float
        - pnl_pct: float
        - exit_reason: str
        - strategy: str (optional)
        """
        try:
            trade = {
                'symbol': trade_data['symbol'],
                'entry_price': round(trade_data['entry_price'], 2),
                'exit_price': round(trade_data['exit_price'], 2),
                'shares': trade_data['shares'],
                'entry_time': trade_data.get('entry_time', datetime.now(timezone.utc).isoformat()),
                'exit_time': trade_data.get('exit_time', datetime.now(timezone.utc).isoformat()),
                'pnl': round(trade_data['pnl'], 2),
                'pnl_pct': round(trade_data['pnl_pct'], 2),
                'exit_reason': trade_data.get('exit_reason', 'Manual exit'),
                'strategy': trade_data.get('strategy', 'Manual'),
                'trade_type': 'Winner' if trade_data['pnl'] > 0 else 'Loser',
                'hold_time': self._calculate_hold_time(
                    trade_data.get('entry_time'),
                    trade_data.get('exit_time')
                ),
                'logged_at': datetime.now(timezone.utc).isoformat()
            }

            # Dedup guard: skip if this exact trade already logged.
            # reconcile can re-adopt the same position repeatedly, and
            # monitor_exits would re-log it each time.
            try:
                dup = await self.collection.find_one({
                    'symbol': trade['symbol'],
                    'entry_time': trade.get('entry_time'),
                    'shares': trade['shares'],
                    'entry_price': trade['entry_price'],
                })
                if dup:
                    logger.info(
                        f"Skip duplicate log: {trade['symbol']} "
                        f"({trade.get('entry_time')}) - already recorded"
                    )
                    return
            except Exception:
                pass  # dedup check failed - log anyway (don't drop real trades)
            
            await self.collection.insert_one(trade)
            logger.info(f"Logged trade: {trade['symbol']} | P&L: ${trade['pnl']:.2f} ({trade['pnl_pct']:.2f}%)")

        except Exception as e:
            logger.error(f"Error logging trade: {str(e)}")

    async def get_trades(self, limit: Optional[int] = None, symbol: Optional[str] = None,
                         date: Optional[str] = None, days: int = 0, source: str = 'current') -> List[Dict]:
        """Get trade history with optional date/day filters.

        `source`: 'current' (default) reads the live `trade_history`
        collection; any `trade_history_backup_*` name reads an archived
        snapshot from a prior account/API swap.
        """
        collection = self._resolve_collection(source)
        query = {}
        if symbol:
            query["symbol"] = symbol
        if not date and not days:
            # default to last 30 days when no filter specified
            days = 30
        if date:
            import pytz
            eastern = pytz.timezone("US/Eastern")
            d = datetime.strptime(date, "%Y-%m-%d")
            start = datetime(d.year, d.month, d.day, tzinfo=eastern).astimezone(timezone.utc)
            end = start + timedelta(days=1)
            query["entry_time"] = {"$gte": start.isoformat(), "$lt": end.isoformat()}
        elif days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query["entry_time"] = {"$gte": cutoff}
        cursor = collection.find(query, {"_id": 0}).sort("entry_time", -1)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit or 10000)

    def _resolve_collection(self, source: Optional[str]):
        """Map a history source id to a Mongo collection.

        'current' (or None/empty) -> the live `trade_history` collection.
        Otherwise only allow known `trade_history_backup_*` collections so a
        caller can never point the query at an arbitrary collection.
        """
        if source and source != 'current' and source.startswith('trade_history_backup_'):
            return db[source]
        return self.collection

    async def list_sources(self) -> List[Dict]:
        """List available history sources: the live account + one entry per
        archived `trade_history_backup_*` snapshot (prior account/API swaps).
        """
        import re
        sources = [{
            'id': 'current',
            'label': 'Current Account',
            'count': await self.collection.count_documents({}),
        }]
        try:
            names = await db.list_collection_names()
        except Exception:
            names = []
        # Only surface clean per-account snapshots (created at each account/API
        # swap, named `..._pre_account_swap`). Ad-hoc pre-cleanup dumps (e.g.
        # the 1681-doc phantom-filled backup) are intentionally excluded so a
        # reviewer never sees fake shares=100 backtest records.
        for name in sorted(names, reverse=True):
            if not name.startswith('trade_history_backup_') or not name.endswith('_pre_account_swap'):
                continue
            m = re.match(r'trade_history_backup_(\d{8})_', name)
            label = 'Previous Account'
            if m:
                label = f"Previous Account (before {m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]})"
            sources.append({
                'id': name,
                'label': label,
                'count': await db[name].count_documents({}),
            })
        return sources

    async def _get_daily_fees(self) -> Dict[str, float]:
        """Fetch Alpaca regulatory fees and aggregate to {date: amount}.

        Fees (SEC REG, FINRA TAF, CAT) are reported by Alpaca as daily
        aggregates keyed by the ET trading date, with net_amount <= 0. This
        maps them to {date: negative_amount} so callers can net them against
        gross trade P&L for the same date. Returns {} on any failure so a fee
        fetch problem can never crash analytics.
        """
        try:
            from services.alpaca_service import alpaca_service
            fees = await asyncio.to_thread(alpaca_service.get_fee_activities)
            daily: Dict[str, float] = {}
            for f in fees or []:
                d = f.get('date')
                if not d:
                    continue
                daily[d] = daily.get(d, 0.0) + float(f.get('net_amount', 0) or 0)
            return daily
        except Exception as e:
            logger.error(f"Error fetching daily fees: {e}")
            return {}

    async def get_fees(self, days: Optional[int] = 180) -> Dict:
        """Return regulatory fees for a window: {'fees': {date: amt}, 'total_fees': float}.

        `days` mirrors get_analytics: None/0 = all-time, else last N days.
        The window is applied on the ET trading date (how Alpaca keys fees),
        matching the ET date grouping the History page uses for trades.
        """
        daily_fees = await self._get_daily_fees()
        fee_cutoff_date = None
        if days:
            import pytz
            et = pytz.timezone('US/Eastern')
            fee_cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).astimezone(et).strftime('%Y-%m-%d')
        fees: Dict[str, float] = {}
        total = 0.0
        for d, amt in daily_fees.items():
            if fee_cutoff_date and d < fee_cutoff_date:
                continue
            amt = round(amt, 2)
            fees[d] = amt
            total += amt
        return {'fees': fees, 'total_fees': round(total, 2)}

    async def get_analytics(self, days: Optional[int] = 180, source: str = 'current') -> Dict:
        """
        Get trading performance analytics.

        Bounded to the last `days` days at the Mongo query level (default 180)
        so this doesn't have to load the entire collection into memory as
        trade history grows. Pass days=None for all-time analytics.

        `source`: 'current' reads the live collection; a historical
        `trade_history_backup_*` name reads an archived snapshot. Fees
        are only applied for the current account.
        """
        try:
            collection = self._resolve_collection(source)
            query = {}
            if days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                query = {'exit_time': {'$gte': cutoff}}
            cursor = collection.find(query, {'_id': 0}).sort('exit_time', -1).limit(5000)
            trades = await cursor.to_list(length=5000)

            if not trades:
                return {
                    'total_trades': 0,
                    'winners': 0,
                    'losers': 0,
                    'win_rate': 0,
                    'total_pnl': 0,
                    'gross_pnl': 0,
                    'total_fees': 0,
                    'avg_win': 0,
                    'avg_loss': 0,
                    'largest_win': 0,
                    'largest_loss': 0,
                    'avg_hold_time': 'N/A',
                    'profit_factor': 0,
                    'best_stock': 'N/A',
                    'worst_stock': 'N/A'
                }

            winners = [t for t in trades if t['pnl'] > 0]
            losers = [t for t in trades if t['pnl'] < 0]

            gross_pnl = sum(t['pnl'] for t in trades)
            avg_win = sum(t['pnl'] for t in winners) / len(winners) if winners else 0
            avg_loss = sum(t['pnl'] for t in losers) / len(losers) if losers else 0

            gross_profit = sum(t['pnl'] for t in winners)
            gross_loss = abs(sum(t['pnl'] for t in losers))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

            # Net P&L: subtract Alpaca regulatory fees (SEC REG, FINRA TAF,
            # CAT). Fees are daily aggregates keyed by ET trading date; the
            # same window as the trades is applied in get_fees(). Fees are
            # only available for the CURRENT account — archived snapshots
            # show gross P&L (their fee data belongs to a retired API key).
            if source and source != 'current':
                total_fees = 0.0
            else:
                total_fees = (await self.get_fees(days=days))['total_fees']
            net_pnl = gross_pnl + total_fees  # total_fees <= 0, so this nets down

            stock_pnl = {}
            for trade in trades:
                symbol = trade['symbol']
                stock_pnl.setdefault(symbol, 0)
                stock_pnl[symbol] += trade['pnl']

            best_stock = max(stock_pnl.items(), key=lambda x: x[1]) if stock_pnl else ('N/A', 0)
            worst_stock = min(stock_pnl.items(), key=lambda x: x[1]) if stock_pnl else ('N/A', 0)

            return {
                'total_trades': len(trades),
                'winners': len(winners),
                'losers': len(losers),
                'win_rate': round((len(winners) / len(trades) * 100), 1) if trades else 0,
                'total_pnl': round(net_pnl, 2),
                'gross_pnl': round(gross_pnl, 2),
                'total_fees': total_fees,
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'largest_win': round(max((t['pnl'] for t in winners), default=0), 2),
                'largest_loss': round(min((t['pnl'] for t in losers), default=0), 2),
                'profit_factor': round(profit_factor, 2),
                'best_stock': f"{best_stock[0]} (${best_stock[1]:.2f})",
                'worst_stock': f"{worst_stock[0]} (${worst_stock[1]:.2f})",
                'expectancy': round(net_pnl / len(trades), 2) if trades else 0
            }

        except Exception as e:
            logger.error(f"Error calculating analytics: {str(e)}")
            return {}

    async def get_daily_pnl(self, days: int = 30) -> List[Dict]:
        """Get daily P&L for chart, bounded to the last `days` days at the query level.

        Returns net P&L per day (gross trade P&L minus Alpaca regulatory fees).
        Dates are US/Eastern trading dates, matching how the History page groups
        trades and how Alpaca keys its daily fee activity.
        """
        try:
            from collections import defaultdict
            import pytz

            et = pytz.timezone('US/Eastern')
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            cursor = self.collection.find({'exit_time': {'$gte': cutoff}}, {'_id': 0}).sort('exit_time', -1).limit(5000)
            trades = await cursor.to_list(length=5000)
            daily_pnl = defaultdict(float)

            for trade in trades:
                try:
                    exit_time = datetime.fromisoformat(trade['exit_time'].replace('Z', '+00:00'))
                    if exit_time.tzinfo is None:
                        exit_time = exit_time.replace(tzinfo=timezone.utc)
                    date_key = exit_time.astimezone(et).strftime('%Y-%m-%d')
                    daily_pnl[date_key] += trade['pnl']
                except Exception:
                    continue

            daily_fees = await self._get_daily_fees()

            sorted_days = sorted(daily_pnl.items())

            result = []
            for date, gross in sorted_days[-days:]:
                fees = round(daily_fees.get(date, 0.0), 2)
                result.append({
                    'date': date,
                    'pnl': round(gross + fees, 2),
                    'gross_pnl': round(gross, 2),
                    'fees': fees,
                })
            return result

        except Exception as e:
            logger.error(f"Error calculating daily P&L: {str(e)}")
            return []


# Global instance
trade_history = TradeHistoryService()
