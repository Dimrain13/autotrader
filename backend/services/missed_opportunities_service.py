"""
Missed Opportunities Service
Tracks stocks that met scanner criteria but weren't traded
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class MissedOpportunitiesService:
    def __init__(self):
        self.data_file = Path("/app/missed_opportunities.json")
        self._ensure_file_exists()
    
    def _ensure_file_exists(self):
        if not self.data_file.exists():
            with open(self.data_file, 'w') as f:
                json.dump([], f)
    
    def _load_data(self) -> List[Dict]:
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except:
            return []
    
    def _save_data(self, data: List[Dict]):
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def log_scanner_results(self, scanner_results: List[Dict], traded_symbols: List[str]):
        """
        Log stocks from scanner that weren't traded
        Only tracks stocks with 4/5 or 5/5 criteria met (high quality misses)
        """
        data = self._load_data()
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        logged_count = 0
        
        for stock in scanner_results:
            symbol = stock.get('symbol')
            criteria_count = stock.get('criteria_count', 0)
            
            # Only track high-quality opportunities (4/5 or 5/5 criteria)
            if criteria_count < 4:
                continue
            
            # Skip if we traded this stock
            if symbol in traded_symbols:
                continue
            
            # Check if already logged today
            already_logged = any(
                d.get('symbol') == symbol and 
                d.get('date') == today 
                for d in data
            )
            if already_logged:
                continue
            
            # Get criteria details from scanner result
            criteria = stock.get('criteria_met', {})
            
            # Determine which criteria were missed
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
            
            # Build reason string
            if missed_criteria:
                reason = f"Missing: {', '.join(missed_criteria)}"
            else:
                reason = "All criteria met but not traded"
            
            # Log the missed opportunity
            opportunity = {
                'id': len(data) + 1,
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
            
            data.append(opportunity)
            logged_count += 1
            logger.info(f"📝 Logged missed opportunity: {symbol} ({criteria_count}/5 criteria) - {reason}")
        
        self._save_data(data)
        return logged_count
    
    def log_single_opportunity(self, stock_data: Dict, reason: str = ""):
        """Log a single missed opportunity with optional reason"""
        data = self._load_data()
        
        opportunity = {
            'id': len(data) + 1,
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
        
        data.append(opportunity)
        self._save_data(data)
        return opportunity
    
    def get_opportunities(self, date: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get missed opportunities, optionally filtered by date"""
        data = self._load_data()
        
        if date:
            data = [d for d in data if d.get('date') == date]
        
        # Sort by timestamp descending (most recent first)
        data.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return data[:limit]
    
    def update_opportunity(self, opportunity_id: int, updates: Dict) -> bool:
        """Update an opportunity (add notes, status, close price, etc.)"""
        data = self._load_data()
        
        for opp in data:
            if opp.get('id') == opportunity_id:
                opp.update(updates)
                # Calculate potential P&L if we have close price
                if updates.get('price_at_close') and opp.get('price_at_scan'):
                    entry = opp['price_at_scan']
                    exit_price = updates['price_at_close']
                    # Assume we would have bought 100 shares
                    shares = int(2000 / entry) if entry > 0 else 100
                    opp['potential_pnl'] = round((exit_price - entry) * shares, 2)
                    opp['potential_pnl_pct'] = round(((exit_price - entry) / entry) * 100, 2) if entry > 0 else 0
                self._save_data(data)
                return True
        return False
    
    def get_analytics(self) -> Dict:
        """Get analytics on missed opportunities"""
        data = self._load_data()
        
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
        
        # Group by date
        by_date = {}
        for d in data:
            date = d.get('date', 'unknown')
            if date not in by_date:
                by_date[date] = {'count': 0, 'symbols': []}
            by_date[date]['count'] += 1
            by_date[date]['symbols'].append(d.get('symbol'))
        
        # Count by criteria count (4/5 or 5/5)
        by_criteria = {}
        for d in data:
            criteria = d.get('criteria_count', 0) or 0
            if criteria not in by_criteria:
                by_criteria[criteria] = 0
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
    
    def clear_old_data(self, days_to_keep: int = 30):
        """Remove opportunities older than specified days"""
        from datetime import timedelta
        
        data = self._load_data()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')
        
        filtered = [d for d in data if d.get('date', '') >= cutoff]
        self._save_data(filtered)
        return len(data) - len(filtered)


missed_opportunities = MissedOpportunitiesService()
