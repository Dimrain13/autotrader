"""
Position Monitor Service - Manages Trailing Stops and Partial Exits

Continuously monitors open positions and:
1. Updates trailing stop losses as price increases
2. Executes partial sells when profit targets are hit
3. Moves stop loss to break even after partial sell
"""
import logging
from typing import Dict, List
import asyncio
from datetime import datetime, timedelta
from services.alpaca_service import alpaca_service

logger = logging.getLogger(__name__)


class PositionMonitorService:
    def __init__(self):
        self.active = False
        self.monitored_positions = {}  # {symbol: position_config}
        
    def add_position(self, symbol: str, config: Dict):
        """
        Add a position to monitor with trailing stop configuration
        
        config = {
            'entry_price': float,
            'shares': int,
            'stop_type': 'fixed' or 'trailing',
            'stop_loss_pct': float (e.g., 5.0 for 5%),
            'trailing_stop_pct': float (e.g., 5.0),
            'take_profit_pct': float (e.g., 10.0),
            'partial_sell_pct': float (e.g., 50.0 for selling 50%),
            'partial_sell_trigger_pct': float (e.g., 10.0 for trigger at +10%),
            'move_to_breakeven': bool,
            'highest_price': float,
            'current_stop': float,
            'partial_sold': bool
        }
        """
        # Check if position is already being monitored - preserve stop levels
        existing = self.monitored_positions.get(symbol)
        if existing:
            # Preserve critical state from existing position
            logger.info(f"📊 Re-syncing {symbol} - preserving stop @ ${existing['current_stop']:.2f}, partial_sold={existing.get('partial_sold', False)}")
            self.monitored_positions[symbol] = {
                **config,
                'highest_price': existing.get('highest_price', config.get('entry_price', 0)),
                'current_stop': existing.get('current_stop', config.get('stop_reference_price', config['entry_price']) * (1 - config['stop_loss_pct'] / 100)),
                'partial_sold': existing.get('partial_sold', False),
                'added_at': existing.get('added_at', datetime.now().isoformat())
            }
        else:
            # New position - calculate initial stop from stop_reference_price (BID) not entry price (ASK)
            # This prevents instant stop triggers due to bid-ask spread
            stop_ref = config.get('stop_reference_price', config.get('entry_price', 0))
            initial_stop = stop_ref * (1 - config['stop_loss_pct'] / 100)
            
            self.monitored_positions[symbol] = {
                **config,
                'highest_price': config.get('entry_price', 0),
                'current_stop': initial_stop,
                'partial_sold': False,
                'added_at': datetime.now().isoformat(),
                'settling_until': (datetime.now() + timedelta(seconds=60)).isoformat()  # 60 second settling period
            }
            
            entry = config.get('entry_price', 0)
            spread = config.get('spread_at_entry', 0)
            logger.info(f"📊 Monitoring {symbol} | Entry: ${entry:.2f} | Stop ref: ${stop_ref:.2f} | Stop: ${initial_stop:.2f} | Spread: {spread:.1f}% | Settling 60s")
        
    def remove_position(self, symbol: str):
        """Remove position from monitoring"""
        if symbol in self.monitored_positions:
            del self.monitored_positions[symbol]
            logger.info(f"🔴 Stopped monitoring {symbol}")
            
    async def monitor_positions(self):
        """Main monitoring loop - checks all positions continuously"""
        while self.active:
            try:
                if not self.monitored_positions:
                    await asyncio.sleep(5)
                    continue
                
                # Get current positions from Alpaca
                alpaca_positions = alpaca_service.get_positions()
                alpaca_symbols = {pos['symbol']: pos for pos in alpaca_positions}
                
                for symbol, config in list(self.monitored_positions.items()):
                    # Check if position still exists
                    if symbol not in alpaca_symbols:
                        logger.info(f"{symbol}: Position closed, removing from monitor")
                        self.remove_position(symbol)
                        continue
                    
                    current_price = alpaca_symbols[symbol]['current_price']
                    entry_price = config['entry_price']
                    shares = config['shares']
                    
                    # Calculate profit percentage
                    profit_pct = ((current_price - entry_price) / entry_price) * 100
                    
                    # Handle Trailing Stop
                    if config['stop_type'] == 'trailing':
                        await self._handle_trailing_stop(symbol, config, current_price, profit_pct)
                    
                    # Check Partial Take Profit - SELL 50% at target, keep rest running
                    if profit_pct >= config.get('take_profit_pct', 2.0) and not config.get('partial_sold'):
                        await self._handle_partial_take_profit(symbol, config, current_price, profit_pct, shares)
                        # Don't continue - keep monitoring the remaining 50%
                    
                    # Check Bearish Crossover Exit - SELL ALL if in loss and SMA20 crosses below SMA50
                    # This is when stock no longer meets bullish conditions
                    if profit_pct < 0:
                        exited = await self._check_bearish_crossover_exit(symbol, config, current_price, profit_pct, shares)
                        if exited:
                            continue  # Position fully closed, skip to next
                    
                    # Check if stop loss hit (both fixed and trailing)
                    current_stop = config['current_stop']
                    
                    # SETTLING PERIOD CHECK - Never insta-sell!
                    # Wait at least 60 seconds after entry before allowing stop loss
                    settling_until = config.get('settling_until')
                    if settling_until:
                        settling_time = datetime.fromisoformat(settling_until)
                        if datetime.now() < settling_time:
                            remaining = (settling_time - datetime.now()).seconds
                            logger.debug(f"⏳ {symbol}: Settling period - {remaining}s remaining, stop loss disabled")
                            continue  # Skip stop loss check during settling
                    
                    logger.debug(f"🔍 {symbol}: Price ${current_price:.2f} | Stop ${current_stop:.2f} | partial_sold={config.get('partial_sold', False)}")
                    if current_price <= current_stop:
                        logger.info(f"🔍 {symbol}: Stop triggered - Price ${current_price:.2f} <= Stop ${current_stop:.2f}")
                        await self._execute_stop_loss(symbol, config, current_price, shares)
                
                await asyncio.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                logger.error(f"Error in position monitor: {str(e)}")
                await asyncio.sleep(5)
    
    async def _handle_trailing_stop(self, symbol: str, config: Dict, current_price: float, profit_pct: float):
        """Update trailing stop as price increases"""
        try:
            # Update highest price seen
            if current_price > config['highest_price']:
                old_highest = config['highest_price']
                config['highest_price'] = current_price
                
                # Calculate new stop (trail by X% from highest price)
                trailing_pct = config['trailing_stop_pct']
                new_stop = current_price * (1 - trailing_pct / 100)
                
                # Only move stop UP, never down
                if new_stop > config['current_stop']:
                    old_stop = config['current_stop']
                    config['current_stop'] = new_stop
                    logger.info(
                        f"📈 {symbol}: Trailing stop updated | "
                        f"Price: ${current_price:.2f} | "
                        f"Stop: ${old_stop:.2f} → ${new_stop:.2f} (+{profit_pct:+.1f}%)"
                    )
        except Exception as e:
            logger.error(f"Error handling trailing stop for {symbol}: {str(e)}")
    
    async def _handle_partial_take_profit(self, symbol: str, config: Dict, current_price: float, profit_pct: float, shares: int):
        """Execute PARTIAL SELL (50%) when profit target is reached, keep rest running"""
        try:
            target_pct = config.get('take_profit_pct', 2.0)
            
            # Only trigger once (check partial_sold flag)
            if config.get('partial_sold'):
                return
            
            if profit_pct >= target_pct:
                # SELL HALF at profit target
                sell_pct = config.get('partial_sell_pct', 50.0)
                shares_to_sell = int(shares * (sell_pct / 100))
                
                if shares_to_sell < 1:
                    shares_to_sell = 1
                
                # Execute partial sell
                logger.info(f"🎯 {symbol}: TAKE PROFIT HIT | Selling {shares_to_sell}/{shares} shares (50%) @ ${current_price:.2f} (+{profit_pct:.1f}%)")
                alpaca_service.place_market_order(symbol, shares_to_sell, "sell")
                
                # Log partial take profit to trade history
                try:
                    from services.trade_history_service import trade_history
                    pnl = (current_price - config['entry_price']) * shares_to_sell
                    trade_history.log_trade({
                        'symbol': symbol,
                        'entry_price': config['entry_price'],
                        'exit_price': current_price,
                        'shares': shares_to_sell,
                        'pnl': pnl,
                        'pnl_pct': profit_pct,
                        'exit_reason': 'Partial Take Profit',
                        'strategy': 'Auto-trader',
                        'trade_type': 'Winner'
                    })
                    logger.info(f"📊 Partial take profit logged: {symbol} | P&L: ${pnl:.2f} ({profit_pct:.2f}%)")
                except Exception as log_error:
                    logger.error(f"Failed to log partial take profit for {symbol}: {log_error}")
                
                # Mark as partial sold and update remaining shares
                config['partial_sold'] = True
                config['shares'] = shares - shares_to_sell
                
                # Move stop to breakeven
                if config.get('move_to_breakeven', True):
                    config['current_stop'] = config['entry_price']
                    logger.info(f"🎯 {symbol}: Stop moved to breakeven @ ${config['entry_price']:.2f}")
                
        except Exception as e:
            logger.error(f"Error handling partial take profit for {symbol}: {str(e)}")
    
    async def _check_bearish_crossover_exit(self, symbol: str, config: Dict, current_price: float, profit_pct: float, shares: int):
        """Exit early if position is negative AND bearish crossover detected (SMA20 crosses below SMA50)"""
        try:
            # Only check if we're in a losing position
            if profit_pct >= 0:
                return False
            
            # Get recent bars to calculate SMAs
            bars = alpaca_service.get_bars_yahoo(symbol, "5m", "1d")
            if not bars or len(bars) < 50:
                return False
            
            closes = [b['close'] for b in bars if b.get('close')]
            if len(closes) < 50:
                return False
            
            # Calculate current SMAs
            sma20_current = sum(closes[-20:]) / 20
            sma50_current = sum(closes[-50:]) / 50
            
            # Calculate previous SMAs (1 bar ago)
            sma20_prev = sum(closes[-21:-1]) / 20
            sma50_prev = sum(closes[-51:-1]) / 50
            
            # Bearish crossover: SMA20 was above SMA50, now below
            if sma20_prev >= sma50_prev and sma20_current < sma50_current:
                logger.info(f"📉 {symbol}: BEARISH CROSSOVER | SMA20 ({sma20_current:.2f}) crossed below SMA50 ({sma50_current:.2f}) while in loss ({profit_pct:.1f}%)")
                
                # Exit the position
                alpaca_service.place_market_order(symbol, shares, "sell")
                
                # Log trade
                try:
                    from services.trade_history_service import trade_history
                    pnl = (current_price - config['entry_price']) * shares
                    trade_history.log_trade({
                        'symbol': symbol,
                        'entry_price': config['entry_price'],
                        'exit_price': current_price,
                        'shares': shares,
                        'pnl': pnl,
                        'pnl_pct': profit_pct,
                        'exit_reason': 'Bearish Crossover Exit',
                        'strategy': 'Auto-trader',
                        'trade_type': 'Loser'
                    })
                    logger.info(f"📊 Bearish crossover exit logged: {symbol} | P&L: ${pnl:.2f} ({profit_pct:.2f}%)")
                except Exception as log_error:
                    logger.error(f"Failed to log bearish crossover exit for {symbol}: {log_error}")
                
                self.remove_position(symbol)
                return True
                
        except Exception as e:
            logger.error(f"Error checking bearish crossover for {symbol}: {str(e)}")
        
        return False
    
    async def _execute_stop_loss(self, symbol: str, config: Dict, current_price: float, shares: int):
        """Execute stop loss order"""
        try:
            entry_price = config['entry_price']
            loss_pct = ((current_price - entry_price) / entry_price) * 100
            
            logger.info(f"🛑 {symbol}: STOP LOSS TRIGGERED | ${current_price:.2f} ({loss_pct:+.1f}%)")
            
            # Sell remaining shares
            remaining_shares = config['shares']
            alpaca_service.place_market_order(symbol, remaining_shares, "sell")
            
            # Log trade to history
            try:
                from services.trade_history_service import trade_history
                pnl = (current_price - config['entry_price']) * remaining_shares
                trade_history.log_trade({
                    'symbol': symbol,
                    'entry_price': config['entry_price'],
                    'exit_price': current_price,
                    'shares': remaining_shares,
                    'pnl': pnl,
                    'pnl_pct': loss_pct,
                    'exit_reason': 'Stop Loss',
                    'strategy': 'Auto-trader',
                    'trade_type': 'Loser'
                })
                logger.info(f"📊 Trade logged: {symbol} | P&L: ${pnl:.2f} ({loss_pct:.2f}%)")
            except Exception as log_error:
                logger.error(f"Failed to log trade for {symbol}: {log_error}")
            
            # Remove from monitoring
            self.remove_position(symbol)
            
        except Exception as e:
            logger.error(f"Error executing stop loss for {symbol}: {str(e)}")
    
    def get_position_status(self, symbol: str) -> Dict:
        """Get current status of a monitored position"""
        if symbol in self.monitored_positions:
            return self.monitored_positions[symbol]
        return None
    
    def start(self):
        """Start the monitoring service"""
        self.active = True
        logger.info("🟢 Position Monitor Service started")
    
    def stop(self):
        """Stop the monitoring service"""
        self.active = False
        logger.info("🔴 Position Monitor Service stopped")


# Global instance
position_monitor = PositionMonitorService()
