"""
Trade History Service

Tracks all trades (manual and auto-trader) with detailed P&L information.
Provides analytics and performance metrics.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class TradeHistoryService:
    def __init__(self):
        self.history_file = Path("/app/trade_history.json")
        self.trades = self._load_history()
        
    def _load_history(self) -> List[Dict]:
        """Load trade history from file"""
        try:
            if self.history_file.exists():
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            return []
        except Exception as e:
            logger.error(f"Error loading trade history: {str(e)}")
            return []
    
    def _save_history(self):
        """Save trade history to file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.trades, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving trade history: {str(e)}")
    
    def log_trade(self, trade_data: Dict):
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
            # Calculate additional metrics
            trade = {
                'id': len(self.trades) + 1,
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
                )
            }
            
            self.trades.append(trade)
            self._save_history()
            
            logger.info(f"Logged trade: {trade['symbol']} | P&L: ${trade['pnl']:.2f} ({trade['pnl_pct']:.2f}%)")
            
        except Exception as e:
            logger.error(f"Error logging trade: {str(e)}")
    
    def _calculate_hold_time(self, entry_time: str, exit_time: str) -> str:
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
                
        except:
            return "Unknown"
    
    def get_trades(self, limit: Optional[int] = None, symbol: Optional[str] = None) -> List[Dict]:
        """Get trade history with optional filters"""
        trades = self.trades
        
        # Filter by symbol if provided
        if symbol:
            trades = [t for t in trades if t['symbol'] == symbol]
        
        # Sort by exit time (newest first)
        trades = sorted(trades, key=lambda x: x.get('exit_time', ''), reverse=True)
        
        # Limit results
        if limit:
            trades = trades[:limit]
        
        return trades
    
    def get_analytics(self) -> Dict:
        """Get trading performance analytics"""
        try:
            if not self.trades:
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
            
            winners = [t for t in self.trades if t['pnl'] > 0]
            losers = [t for t in self.trades if t['pnl'] < 0]
            
            total_pnl = sum(t['pnl'] for t in self.trades)
            avg_win = sum(t['pnl'] for t in winners) / len(winners) if winners else 0
            avg_loss = sum(t['pnl'] for t in losers) / len(losers) if losers else 0
            
            # Profit factor (gross profit / gross loss)
            gross_profit = sum(t['pnl'] for t in winners)
            gross_loss = abs(sum(t['pnl'] for t in losers))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
            
            # Best/worst stocks
            stock_pnl = {}
            for trade in self.trades:
                symbol = trade['symbol']
                if symbol not in stock_pnl:
                    stock_pnl[symbol] = 0
                stock_pnl[symbol] += trade['pnl']
            
            best_stock = max(stock_pnl.items(), key=lambda x: x[1]) if stock_pnl else ('N/A', 0)
            worst_stock = min(stock_pnl.items(), key=lambda x: x[1]) if stock_pnl else ('N/A', 0)
            
            return {
                'total_trades': len(self.trades),
                'winners': len(winners),
                'losers': len(losers),
                'win_rate': round((len(winners) / len(self.trades) * 100), 1) if self.trades else 0,
                'total_pnl': round(total_pnl, 2),
                'avg_win': round(avg_win, 2),
                'avg_loss': round(avg_loss, 2),
                'largest_win': round(max((t['pnl'] for t in winners), default=0), 2),
                'largest_loss': round(min((t['pnl'] for t in losers), default=0), 2),
                'profit_factor': round(profit_factor, 2),
                'best_stock': f"{best_stock[0]} (${best_stock[1]:.2f})",
                'worst_stock': f"{worst_stock[0]} (${worst_stock[1]:.2f})",
                'expectancy': round(total_pnl / len(self.trades), 2) if self.trades else 0
            }
            
        except Exception as e:
            logger.error(f"Error calculating analytics: {str(e)}")
            return {}
    
    def get_daily_pnl(self, days: int = 30) -> List[Dict]:
        """Get daily P&L for chart"""
        try:
            from datetime import datetime, timedelta
            from collections import defaultdict
            
            daily_pnl = defaultdict(float)
            
            for trade in self.trades:
                try:
                    exit_time = datetime.fromisoformat(trade['exit_time'].replace('Z', '+00:00'))
                    date_key = exit_time.strftime('%Y-%m-%d')
                    daily_pnl[date_key] += trade['pnl']
                except:
                    continue
            
            # Sort by date
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
