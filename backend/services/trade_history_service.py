"""
Trade History Service

Tracks all trades (manual and auto-trader) with detailed P&L information.
Provides analytics and performance metrics.

Persisted in MongoDB (collection: trade_history) instead of a flat JSON
file, to avoid concurrency corruption and match the rest of the stack.
"""
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

            await self.collection.insert_one(trade)
            logger.info(f"Logged trade: {trade['symbol']} | P&L: ${trade['pnl']:.2f} ({trade['pnl_pct']:.2f}%)")

        except Exception as e:
            logger.error(f"Error logging trade: {str(e)}")

    async def get_trades(self, limit: Optional[int] = None, symbol: Optional[str] = None) -> List[Dict]:
        """Get trade history with optional filters"""
        query = {'symbol': symbol} if symbol else {}
        cursor = self.collection.find(query, {'_id': 0}).sort('exit_time', -1)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit or 10000)

    async def get_analytics(self, days: Optional[int] = 180) -> Dict:
        """
        Get trading performance analytics.

        Bounded to the last `days` days at the Mongo query level (default 180)
        so this doesn't have to load the entire collection into memory as
        trade history grows. Pass days=None for all-time analytics.
        """
        try:
            query = {}
            if days:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                query = {'exit_time': {'$gte': cutoff}}
            cursor = self.collection.find(query, {'_id': 0}).sort('exit_time', -1).limit(5000)
            trades = await cursor.to_list(length=5000)

            if not trades:
                return {
                    'total_trades': 0,
                    'winners': 0,
                    'losers': 0,
                    'win_rate': 0,
                    'total_pnl': 0,
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

            total_pnl = sum(t['pnl'] for t in trades)
            avg_win = sum(t['pnl'] for t in winners) / len(winners) if winners else 0
            avg_loss = sum(t['pnl'] for t in losers) / len(losers) if losers else 0

            gross_profit = sum(t['pnl'] for t in winners)
            gross_loss = abs(sum(t['pnl'] for t in losers))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

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
                'total_pnl': round(total_pnl, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'largest_win': round(max((t['pnl'] for t in winners), default=0), 2),
                'largest_loss': round(min((t['pnl'] for t in losers), default=0), 2),
                'profit_factor': round(profit_factor, 2),
                'best_stock': f"{best_stock[0]} (${best_stock[1]:.2f})",
                'worst_stock': f"{worst_stock[0]} (${worst_stock[1]:.2f})",
                'expectancy': round(total_pnl / len(trades), 2) if trades else 0
            }

        except Exception as e:
            logger.error(f"Error calculating analytics: {str(e)}")
            return {}

    async def get_daily_pnl(self, days: int = 30) -> List[Dict]:
        """Get daily P&L for chart, bounded to the last `days` days at the query level"""
        try:
            from collections import defaultdict

            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            cursor = self.collection.find({'exit_time': {'$gte': cutoff}}, {'_id': 0}).sort('exit_time', -1).limit(5000)
            trades = await cursor.to_list(length=5000)
            daily_pnl = defaultdict(float)

            for trade in trades:
                try:
                    exit_time = datetime.fromisoformat(trade['exit_time'].replace('Z', '+00:00'))
                    date_key = exit_time.strftime('%Y-%m-%d')
                    daily_pnl[date_key] += trade['pnl']
                except Exception:
                    continue

            sorted_days = sorted(daily_pnl.items())

            return [
                {'date': date, 'pnl': round(pnl, 2)}
                for date, pnl in sorted_days[-days:]
            ]

        except Exception as e:
            logger.error(f"Error calculating daily P&L: {str(e)}")
            return []


# Global instance
trade_history = TradeHistoryService()
