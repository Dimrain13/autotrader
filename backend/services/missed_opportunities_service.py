"""
Missed Opportunities Service
Tracks stocks that met scanner criteria but weren't traded.

Persisted in MongoDB (collection: missed_opportunities) instead of a flat
JSON file, to avoid concurrency corruption and match the rest of the stack.
"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import logging
from database import db

logger = logging.getLogger(__name__)


class MissedOpportunitiesService:
    def __init__(self):
        self.collection = db.missed_opportunities

    async def _next_id(self) -> int:
        count = await self.collection.count_documents({})
        return count + 1

    async def log_scanner_results(self, scanner_results: List[Dict], traded_symbols: List[str]):
        """
        Log stocks from scanner that weren't traded
        Only tracks stocks with 4/5 or 5/5 criteria met (high quality misses)
        """
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        logged_count = 0

        for stock in scanner_results:
            symbol = stock.get('symbol')
            criteria_count = stock.get('criteria_count', 0)

            if criteria_count < 4:
                continue
            if symbol in traded_symbols:
                continue

            already_logged = await self.collection.find_one({'symbol': symbol, 'date': today})
            if already_logged:
                continue

            criteria = stock.get('criteria_met', {})

            missed_criteria = []
            if not criteria.get('price_range', False):
                missed_criteria.append('Price not $2-$20')
            if not criteria.get('pct_change', False):
                missed_criteria.append('Not up 10%+')
            if not criteria.get('volume_ratio', False):
                missed_criteria.append('Rel Vol < 5x')
            if not criteria.get('positive_news', False):
                missed_criteria.append('No positive news')
            if not criteria.get('float', False):
                missed_criteria.append('Float > 20M')

            reason = f"Missing: {', '.join(missed_criteria)}" if missed_criteria else "All criteria met but not traded"

            opportunity = {
                'id': await self._next_id(),
                'symbol': symbol,
                'date': today,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'price_at_scan': stock.get('current_price', 0),
                'pct_change': stock.get('pct_change', 0),
                'volume': stock.get('volume', 0),
                'rel_volume': stock.get('volume_ratio', 0),
                'float_shares': stock.get('shares_outstanding', 0),
                'criteria_count': criteria_count,
                'criteria_met': criteria,
                'missed_criteria': missed_criteria,
                'reason_not_traded': reason,
                'news_headline': stock.get('news_headline', ''),
                'has_positive_news': stock.get('has_positive_news', False),
                'has_bull_flag': stock.get('has_bull_flag', False),
                'status': 'missed',
                'notes': '',
                'price_at_close': None,
                'potential_pnl': None,
            }

            await self.collection.insert_one(opportunity)
            logged_count += 1
            logger.info(f"📝 Logged missed opportunity: {symbol} ({criteria_count}/5 criteria) - {reason}")

        return logged_count

    async def log_single_opportunity(self, stock_data: Dict, reason: str = ""):
        """Log a single missed opportunity with optional reason"""
        opportunity = {
            'id': await self._next_id(),
            'symbol': stock_data.get('symbol'),
            'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'price_at_scan': stock_data.get('current_price', 0),
            'pct_change': stock_data.get('pct_change', 0),
            'volume': stock_data.get('volume', 0),
            'rel_volume': stock_data.get('rel_volume', 0),
            'float_shares': stock_data.get('float_shares', 0),
            'criteria_met': stock_data.get('criteria_met', 0),
            'criteria_details': {
                'price_in_range': stock_data.get('price_in_range', False),
                'up_10pct': stock_data.get('up_10pct', False),
                'high_rel_volume': stock_data.get('high_rel_volume', False),
                'low_float': stock_data.get('low_float', False),
                'has_news': stock_data.get('has_news', False),
            },
            'news_headline': stock_data.get('news_headline', ''),
            'news_sentiment': stock_data.get('news_sentiment', 0),
            'status': 'missed',
            'reason_not_traded': reason,
            'notes': '',
            'price_at_close': None,
            'potential_pnl': None,
        }

        await self.collection.insert_one(opportunity)
        return {k: v for k, v in opportunity.items() if k != '_id'}

    async def get_opportunities(self, date: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get missed opportunities, optionally filtered by date"""
        query = {'date': date} if date else {}
        cursor = self.collection.find(query, {'_id': 0}).sort('timestamp', -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def update_opportunity(self, opportunity_id: int, updates: Dict) -> bool:
        """Update an opportunity (add notes, status, close price, etc.)"""
        opp = await self.collection.find_one({'id': opportunity_id})
        if not opp:
            return False

        if updates.get('price_at_close') and opp.get('price_at_scan'):
            entry = opp['price_at_scan']
            exit_price = updates['price_at_close']
            shares = int(2000 / entry) if entry > 0 else 100
            updates['potential_pnl'] = round((exit_price - entry) * shares, 2)
            updates['potential_pnl_pct'] = round(((exit_price - entry) / entry) * 100, 2) if entry > 0 else 0

        await self.collection.update_one({'id': opportunity_id}, {'$set': updates})
        return True

    async def get_analytics(self) -> Dict:
        """Get analytics on missed opportunities"""
        data = await self.collection.find({}, {'_id': 0}).to_list(length=10000)

        if not data:
            return {
                'total_missed': 0,
                'total_would_have_won': 0,
                'total_would_have_lost': 0,
                'total_potential_pnl': 0,
                'avg_criteria_met': 0,
                'by_criteria': {},
                'by_date': {},
            }

        would_have_won = [d for d in data if d.get('status') == 'would_have_won']
        would_have_lost = [d for d in data if d.get('status') == 'would_have_lost']

        total_potential_pnl = sum(d.get('potential_pnl', 0) or 0 for d in data)
        avg_criteria = sum(d.get('criteria_count', 0) or 0 for d in data) / len(data)

        by_date = {}
        for d in data:
            date = d.get('date', 'unknown')
            by_date.setdefault(date, {'count': 0, 'symbols': []})
            by_date[date]['count'] += 1
            by_date[date]['symbols'].append(d.get('symbol'))

        by_criteria = {}
        for d in data:
            criteria = d.get('criteria_count', 0) or 0
            by_criteria.setdefault(criteria, 0)
            by_criteria[criteria] += 1

        return {
            'total_missed': len(data),
            'total_would_have_won': len(would_have_won),
            'total_would_have_lost': len(would_have_lost),
            'total_potential_pnl': round(total_potential_pnl, 2),
            'avg_criteria_met': round(avg_criteria, 1),
            'by_criteria': by_criteria,
            'by_date': by_date,
        }

    async def clear_old_data(self, days_to_keep: int = 30):
        """Remove opportunities older than specified days"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
        result = await self.collection.delete_many({'date': {'$lt': cutoff}})
        return result.deleted_count


missed_opportunities = MissedOpportunitiesService()
