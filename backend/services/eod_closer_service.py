"""
End-of-Day Position Closer Service

Automatically closes ALL positions before extended hours end (8:00 PM EST)
Critical for day trading to avoid overnight risk and margin requirements.

Alpaca Paper Trading Extended Hours: 4:00 AM - 8:00 PM ET
"""
import asyncio
import logging
from datetime import datetime, time
import pytz
from services.alpaca_service import alpaca_service

logger = logging.getLogger(__name__)

# Import at module level to avoid circular imports
def get_trade_history():
    from services.trade_history_service import trade_history
    return trade_history

class EODCloserService:
    def __init__(self):
        self.active = False
        self.eastern = pytz.timezone('US/Eastern')
        # Market close time for regular hours
        self.market_close_time = time(16, 0)  # 4:00 PM EST
        # Auto-trader stops and sells all positions at 3:30 PM EST
        self.auto_close_time = time(15, 30)  # 3:30 PM EST
        self.close_before_minutes = 0  # Close exactly at the time
        
    def start(self):
        """Start the EOD closer service"""
        self.active = True
        logger.info("EOD Closer Service started - will close all positions at 3:30 PM EST")
        
    def stop(self):
        """Stop the EOD closer service"""
        self.active = False
        logger.info("EOD Closer Service stopped")
        
    def is_close_to_market_close(self) -> bool:
        """Check if we're at or past the auto-close time (3:30 PM EST)"""
        now_et = datetime.now(self.eastern)
        
        # Check if it's a weekday
        if now_et.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        # Get current time
        current_time = now_et.time()
        
        # Trigger at or after 3:30 PM EST
        if current_time >= self.auto_close_time:
            return True
            
        return False
    
    def is_after_market_close(self) -> bool:
        """Check if market has closed"""
        now_et = datetime.now(self.eastern)
        current_time = now_et.time()
        
        # After 4:00 PM EST
        return current_time >= self.market_close_time
        
    async def close_all_positions(self, reason: str = "End of day"):
        """Close all open positions"""
        try:
            positions = alpaca_service.get_positions()
            
            if not positions:
                logger.info("No positions to close at end of day")
                return
            
            logger.info(f"🔔 {reason.upper()}: Closing {len(positions)} positions")
            
            # IMPORTANT: Cancel all existing orders first to free up shares
            # Shares can be "held_for_orders" by stop-loss/take-profit orders
            try:
                cancelled = alpaca_service.cancel_all_orders()
                if cancelled > 0:
                    logger.info(f"📛 Cancelled {cancelled} existing orders before EOD close")
                    # Small delay to let the cancellation process
                    await asyncio.sleep(1)
            except Exception as cancel_error:
                logger.warning(f"Error cancelling orders before EOD close: {cancel_error}")
            
            for position in positions:
                symbol = position['symbol']
                qty = position['qty']
                current_price = position['current_price']
                unrealized_pl = position['unrealized_pl']
                
                # Get actual entry time before selling
                entry_time = alpaca_service.get_position_entry_time(symbol)
                
                try:
                    # Place market order to close
                    order = alpaca_service.place_market_order(symbol, qty, "sell")
                    
                    if order:
                        logger.info(f"✅ Closed {symbol}: {qty} shares @ ${current_price:.2f} | P&L: ${unrealized_pl:.2f}")
                        
                        # Log trade to history
                        try:
                            trade_hist = get_trade_history()
                            trade_hist.log_trade({
                                'symbol': symbol,
                                'entry_price': position.get('avg_entry_price', current_price),
                                'exit_price': current_price,
                                'shares': qty,
                                'entry_time': entry_time,
                                'exit_time': datetime.now().isoformat(),
                                'pnl': unrealized_pl,
                                'pnl_pct': position.get('unrealized_plpc', 0),
                                'exit_reason': reason,
                                'strategy': 'EOD Close'
                            })
                        except Exception as log_error:
                            logger.error(f"Failed to log trade: {str(log_error)}")
                    else:
                        logger.error(f"❌ Failed to close {symbol}")
                        
                except Exception as e:
                    logger.error(f"Error closing {symbol}: {str(e)}")
            
            logger.info(f"✅ EOD Close Complete: All positions closed")
            
        except Exception as e:
            logger.error(f"Error in EOD position closure: {str(e)}")
    
    async def monitor_eod(self):
        """Monitor for end of day and close positions at 3:30 PM EST"""
        logger.info("EOD Monitor started - will sell all positions at 3:30 PM EST")
        
        already_closed_today = False
        last_check_date = None
        
        while self.active:
            try:
                eastern = pytz.timezone('US/Eastern')
                now_et = datetime.now(eastern)
                today = now_et.date()
                
                # Reset the flag at the start of a new day
                if last_check_date != today:
                    already_closed_today = False
                    last_check_date = today
                
                # Check if it's 3:30 PM or later and we haven't closed yet today
                if self.is_close_to_market_close() and not already_closed_today:
                    logger.info(f"⏰ 3:30 PM EST reached - closing all positions")
                    await self.close_all_positions("3:30 PM Auto-Close")
                    already_closed_today = True
                    logger.info("✅ All positions closed for the day")
                
                # Sleep for 30 seconds before next check
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"Error in EOD monitor: {str(e)}")
                await asyncio.sleep(30)

# Global instance
eod_closer = EODCloserService()
