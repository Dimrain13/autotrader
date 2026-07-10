"""
Warrior Trading Momentum Auto-Trader
Based on Ross Cameron's Small Cap Momentum Strategy

STRATEGY RULES (from documents):
1. Entry: Micro-pullbacks on front side of momentum (1-3% pullback)
2. Position Size: 5% of account per trade
3. Profit Target: 10% of account per trade  
4. Stop Loss: 5% managed in software (pre-market has no broker stops)
5. Daily Max Loss: 10% of account
6. Max Consecutive Losses: 3 (then done for day)
7. Time Window: 7 AM - 11 AM EST (pre-market/morning momentum)
8. Exit Signals: MACD bearish cross, jackknife rejection, profit target hit
"""
from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, List, Optional
import asyncio
import os
import pytz
from services.alpaca_service import alpaca_service
from services.scanner_service import scanner_service
from services.trade_history_service import trade_history

logger = logging.getLogger(__name__)

class AutoTraderService:
    def __init__(self):
        self.active = False
        self.open_positions = {}  # {symbol: position_data}
        
        # STRATEGY PARAMETERS - Warrior Trading Quick Scalp Style
        # Ross Cameron focuses on quick 1-3% moves with tight stops
        self.max_positions = 5
        self.position_size_pct = 0.10  # 10% of account per trade (larger size for smaller % gains)
        self.profit_target_pct = 0.02  # 2% profit target - sell 50% here
        self.stop_loss_pct = 0.01  # 1% initial stop loss
        self.trailing_stop_pct = 0.01  # 1% trailing stop (default)
        self.partial_sell_pct = 0.50  # Sell 50% at profit target
        self.move_to_breakeven = True  # Move stop to break-even after partial sell
        self.daily_max_loss_pct = 0.05  # 5% max daily loss (conservative)
        self.max_consecutive_losses = 3
        
        # Entry condition settings (adjustable)
        self.pullback_min_candles = 1  # Minimum green candles in pullback
        self.pullback_max_candles = 3  # Maximum green candles in pullback
        self.pullback_lookback_bars = 10  # Number of bars to look back for pullback pattern
        self.require_macd_crossover = True  # Require MACD to cross above signal (not just be above)
        self.require_sma_crossover = True   # Require price to cross above SMA (not just be above)
        self.require_bull_flag = False  # Require bull flag pattern (bonus condition)
        self.require_volume_confirmation = True  # Require green volume bars after red
        self.sma_period = 20
        
        # Daily tracking
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.starting_portfolio_value = 0.0
        self.last_reset_date = None
        self.trade_history = []  # Track all trades for the day
        
        # Position management tracking
        self.partial_sold = {}  # {symbol: True/False} - track if we've taken partial profits
        self.breakeven_stops = {}  # {symbol: breakeven_price} - track breakeven stop levels
        
        # No Re-Entry tracking - prevent buying back stocks we've exited today
        self.exited_today = set()  # Symbols we've exited during current trading day
        
        # Trading Hours: 7 AM - 3:30 PM EST
        # Entry signals evaluated during morning momentum (7-11 AM)
        # Positions managed until 3:30 PM, then all positions closed
        self.trading_start_hour = 7
        self.trading_end_hour = 15  # 3 PM (will check minutes too)
        self.trading_end_minute = 30  # 3:30 PM - auto-sell all positions
    
    def update_settings(self, settings: Dict):
        """Update auto-trader settings"""
        # Entry conditions
        if 'pullback_min_candles' in settings:
            self.pullback_min_candles = int(settings['pullback_min_candles'])
        if 'pullback_max_candles' in settings:
            self.pullback_max_candles = int(settings['pullback_max_candles'])
        if 'pullback_lookback_bars' in settings:
            self.pullback_lookback_bars = int(settings['pullback_lookback_bars'])
        if 'require_macd_crossover' in settings:
            self.require_macd_crossover = bool(settings['require_macd_crossover'])
        if 'require_sma_crossover' in settings:
            self.require_sma_crossover = bool(settings['require_sma_crossover'])
        if 'require_bull_flag' in settings:
            self.require_bull_flag = bool(settings['require_bull_flag'])
        if 'require_volume_confirmation' in settings:
            self.require_volume_confirmation = bool(settings['require_volume_confirmation'])
        if 'sma_period' in settings:
            self.sma_period = int(settings['sma_period'])
        if 'trading_start_hour' in settings:
            self.trading_start_hour = int(settings['trading_start_hour'])
        if 'trading_end_hour' in settings:
            self.trading_end_hour = int(settings['trading_end_hour'])
        
        # Trade management settings
        if 'profit_target_pct' in settings:
            self.profit_target_pct = float(settings['profit_target_pct']) / 100
        if 'stop_loss_pct' in settings:
            self.stop_loss_pct = float(settings['stop_loss_pct']) / 100
        if 'trailing_stop_pct' in settings:
            self.trailing_stop_pct = float(settings['trailing_stop_pct']) / 100
        if 'partial_sell_pct' in settings:
            self.partial_sell_pct = float(settings['partial_sell_pct']) / 100
        if 'move_to_breakeven' in settings:
            self.move_to_breakeven = bool(settings['move_to_breakeven'])
        if 'max_positions' in settings:
            self.max_positions = int(settings['max_positions'])
        if 'position_size_pct' in settings:
            self.position_size_pct = float(settings['position_size_pct']) / 100
        if 'daily_max_loss_pct' in settings:
            self.daily_max_loss_pct = float(settings['daily_max_loss_pct']) / 100
            
        logger.info(f"Auto-trader settings updated: {settings}")
        
    def reset_daily_tracking(self, portfolio_value: float):
        """Reset daily tracking at start of new trading day"""
        today = datetime.now(pytz.timezone('US/Eastern')).date()
        
        if self.last_reset_date != today:
            # Log previous day summary if we had trades
            if self.trade_history:
                winners = [t for t in self.trade_history if t['pnl'] > 0]
                losers = [t for t in self.trade_history if t['pnl'] < 0]
                logger.info(f"📊 YESTERDAY SUMMARY: {len(winners)}W / {len(losers)}L | Daily P&L: ${self.daily_pnl:.2f}")
            
            logger.info(f"🔄 Resetting daily tracking for {today}")
            self.daily_pnl = 0.0
            self.consecutive_losses = 0
            self.starting_portfolio_value = portfolio_value
            self.last_reset_date = today
            self.trade_history = []
            self.exited_today = set()  # Reset exited stocks for new trading day
            
    def is_trading_hours(self) -> bool:
        """Check if within trading window (7 AM - 3:30 PM EST)
        
        Trading Schedule:
        - 7:00 AM - 11:00 AM: Entry signals (morning momentum)
        - 11:00 AM - 3:30 PM: Position management only (no new entries)
        - 3:30 PM: Auto-sell ALL positions
        
        Manual trading can happen during full extended hours (4 AM - 8 PM ET)
        """
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        
        # Check if before trading starts (7 AM)
        if now_et.hour < self.trading_start_hour:
            return False
        
        # Check if at or after 3:30 PM (end of auto-trading)
        if now_et.hour > self.trading_end_hour:
            return False
        if now_et.hour == self.trading_end_hour and now_et.minute >= self.trading_end_minute:
            return False
            
        return True
    
    def is_entry_window(self) -> bool:
        """Check if within entry window (7 AM - 11 AM EST)
        
        Only take new entries during morning momentum.
        After 11 AM, only manage existing positions.
        """
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        
        # Entry window: 7 AM - 11 AM
        return 7 <= now_et.hour < 11
        
    def check_risk_limits(self, portfolio_value: float) -> Dict:
        """
        Check if risk limits are breached
        
        Returns: {
            'can_trade': bool,
            'reason': str,
            'daily_pnl': float,
            'daily_pnl_pct': float,
            'consecutive_losses': int
        }
        """
        # Calculate daily P&L percentage
        daily_pnl_pct = (self.daily_pnl / self.starting_portfolio_value * 100) if self.starting_portfolio_value > 0 else 0
        
        # Check daily max loss (-10%)
        if daily_pnl_pct <= -self.daily_max_loss_pct * 100:
            return {
                'can_trade': False,
                'reason': f'Daily max loss reached ({daily_pnl_pct:.2f}% / -10% limit)',
                'daily_pnl': self.daily_pnl,
                'daily_pnl_pct': daily_pnl_pct,
                'consecutive_losses': self.consecutive_losses
            }
        
        # Check consecutive losses (max 3)
        if self.consecutive_losses >= self.max_consecutive_losses:
            return {
                'can_trade': False,
                'reason': f'{self.consecutive_losses} consecutive losses - done for the day',
                'daily_pnl': self.daily_pnl,
                'daily_pnl_pct': daily_pnl_pct,
                'consecutive_losses': self.consecutive_losses
            }
        
        # All clear
        return {
            'can_trade': True,
            'reason': 'Risk limits OK',
            'daily_pnl': self.daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'consecutive_losses': self.consecutive_losses
        }
        
    def calculate_position_size(self, portfolio_value: float, stock_price: float) -> int:
        """
        Calculate shares to buy: 5% of account per trade
        
        Example: $2,000 account × 5% = $100 per trade
                 $100 / $5 stock = 20 shares
        """
        position_capital = portfolio_value * self.position_size_pct
        shares = int(position_capital / stock_price)
        shares = max(1, shares)  # At least 1 share
        
        logger.info(f"Position sizing: ${portfolio_value:,.2f} × {self.position_size_pct*100}% = ${position_capital:,.2f} / ${stock_price:.2f} = {shares} shares")
        
        return shares
    
    def calculate_macd(self, closes: List[float], fast_period=12, slow_period=26, signal_period=9) -> Dict:
        """
        Calculate MACD (Moving Average Convergence Divergence)
        
        MACD Line = 12-period EMA - 26-period EMA
        Signal Line = 9-period EMA of MACD Line
        
        Bullish Crossover: MACD crosses above signal (was below, now above)
        Bearish Crossover: MACD crosses below signal
        """
        if len(closes) < slow_period + signal_period:
            return {'macd': 0, 'signal': 0, 'histogram': 0, 'bullish': False, 'crossover': False, 'prev_macd': 0, 'prev_signal': 0}
        
        # Calculate EMAs
        def calculate_ema(data, period):
            multiplier = 2 / (period + 1)
            ema = [sum(data[:period]) / period]  # First EMA is SMA
            
            for price in data[period:]:
                ema.append((price - ema[-1]) * multiplier + ema[-1])
            
            return ema[-1]
        
        # Calculate MACD history for signal line AND crossover detection
        macd_history = []
        for i in range(slow_period, len(closes)):
            ema_f = calculate_ema(closes[:i+1], fast_period)
            ema_s = calculate_ema(closes[:i+1], slow_period)
            macd_history.append(ema_f - ema_s)
        
        if len(macd_history) < signal_period + 1:
            return {'macd': 0, 'signal': 0, 'histogram': 0, 'bullish': False, 'crossover': False, 'prev_macd': 0, 'prev_signal': 0}
        
        # Current values
        macd_line = macd_history[-1]
        signal_line = calculate_ema(macd_history, signal_period)
        histogram = macd_line - signal_line
        
        # Previous values (for crossover detection)
        prev_macd = macd_history[-2]
        prev_signal = calculate_ema(macd_history[:-1], signal_period) if len(macd_history) > signal_period else signal_line
        
        # Check for bullish crossover (MACD was below signal, now above)
        was_below = prev_macd <= prev_signal
        now_above = macd_line > signal_line
        crossover = was_below and now_above
        
        # Bullish = either crossover happened OR MACD is above signal (depending on settings)
        bullish = macd_line > signal_line
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram,
            'bullish': bullish,
            'crossover': crossover,  # True if MACD just crossed above signal
            'prev_macd': prev_macd,
            'prev_signal': prev_signal
        }
    
    def check_micro_pullback(self, bars: List[Dict]) -> Dict:
        """
        Check for micro-pullback pattern (1-3 green candles after a move up)
        
        Pattern:
        1. Stock has made a move up (established momentum)
        2. Pullback of 1-3 GREEN candles (not percentage-based)
        3. Current candle showing strength (potential breakout)
        
        Returns: {'is_valid': bool, 'green_candles': int, 'entry_price': float}
        """
        lookback = self.pullback_lookback_bars
        if len(bars) < lookback:
            return {'is_valid': False, 'green_candles': 0, 'entry_price': 0, 'lookback': lookback}
        
        recent_bars = bars[-lookback:]
        
        # Find recent high (exclude last 3 bars to allow for pullback)
        if len(recent_bars) < 5:
            return {'is_valid': False, 'green_candles': 0, 'entry_price': 0, 'lookback': lookback}
        
        recent_high = max(b['high'] for b in recent_bars[:-3])
        
        # Count consecutive green candles in the pullback (going backwards from current bar)
        # A green candle is where close > open
        green_candle_count = 0
        pullback_started = False
        
        # Look at the last few bars to count green candles in pullback
        for i in range(len(recent_bars) - 1, max(len(recent_bars) - 5, 0), -1):
            bar = recent_bars[i]
            is_green = bar['close'] > bar['open']
            is_red = bar['close'] < bar['open']
            
            if is_green:
                green_candle_count += 1
                pullback_started = True
            elif is_red and pullback_started:
                # Red candle after green means pullback ended
                break
            elif is_red and not pullback_started:
                # Haven't started counting greens yet, skip
                continue
        
        # Valid pullback is 1-3 green candles
        is_valid_pullback = 1 <= green_candle_count <= 3
        
        current_price = bars[-1]['close']
        current_bar = bars[-1]
        is_current_green = current_bar['close'] > current_bar['open']
        
        # Check if current bar is showing strength (green and near high)
        near_high = current_price >= current_bar['high'] * 0.98  # Within 2% of bar high
        
        if is_valid_pullback and is_current_green and near_high:
            return {
                'is_valid': True,
                'green_candles': green_candle_count,
                'entry_price': current_price,
                'recent_high': recent_high,
                'lookback': lookback,
                'pattern': f'{green_candle_count} green candle pullback'
            }
        
        return {
            'is_valid': False, 
            'green_candles': green_candle_count,
            'entry_price': 0,
            'reason': 'Not 1-3 green candles' if not is_valid_pullback else 'Current bar not showing strength',
            'lookback': lookback
        }
    
    def check_sma_confirmation(self, bars: List[Dict]) -> Dict:
        """
        Check if SMA20 is above SMA50 (fast SMA over slow SMA = bullish)
        
        Crossover: SMA20 was below SMA50, now above (bullish golden cross)
        """
        sma_fast_period = self.sma_period  # Default 20
        sma_slow_period = 50  # Fixed slow SMA at 50
        
        if len(bars) < sma_slow_period + 1:
            return {
                'confirmed': False, 
                'crossover': False, 
                'sma_fast': 0, 
                'sma_slow': 0,
                'prev_sma_fast': 0,
                'prev_sma_slow': 0,
                'current_price': 0
            }
        
        closes = [b['close'] for b in bars]
        
        # Current SMAs
        sma_fast = sum(closes[-sma_fast_period:]) / sma_fast_period
        sma_slow = sum(closes[-sma_slow_period:]) / sma_slow_period
        current_price = bars[-1]['close']
        
        # Previous SMAs (for crossover detection)
        prev_sma_fast = sum(closes[-(sma_fast_period+1):-1]) / sma_fast_period
        prev_sma_slow = sum(closes[-(sma_slow_period+1):-1]) / sma_slow_period
        
        # Check for crossover (SMA20 was below SMA50, now above)
        was_below = prev_sma_fast <= prev_sma_slow
        now_above = sma_fast > sma_slow
        crossover = was_below and now_above
        
        return {
            'confirmed': sma_fast > sma_slow,  # SMA20 > SMA50
            'crossover': crossover,  # True if SMA20 just crossed above SMA50
            'sma_fast': sma_fast,
            'sma_slow': sma_slow,
            'prev_sma_fast': prev_sma_fast,
            'prev_sma_slow': prev_sma_slow,
            'current_price': current_price
        }
    
    def check_volume_confirmation(self, bars: List[Dict]) -> Dict:
        """
        Check for green volume bars after a red bar (buying pressure confirmation)
        
        Pattern: Red bar followed by 1+ green bars with increasing/strong volume
        """
        if len(bars) < 5:
            return {'confirmed': False, 'pattern': 'insufficient_data', 'green_after_red': 0}
        
        recent_bars = bars[-5:]
        
        # Find if there's a red bar followed by green bars
        green_after_red = 0
        found_red = False
        
        for i, bar in enumerate(recent_bars[:-1]):  # Exclude last bar for now
            is_red = bar['close'] < bar['open']
            is_green = bar['close'] > bar['open']
            
            if is_red:
                found_red = True
                green_after_red = 0  # Reset count
            elif found_red and is_green:
                green_after_red += 1
        
        # Check last bar
        last_bar = recent_bars[-1]
        last_is_green = last_bar['close'] > last_bar['open']
        if found_red and last_is_green:
            green_after_red += 1
        
        # Confirmed if we have at least 1 green bar after a red bar
        confirmed = green_after_red >= 1
        
        return {
            'confirmed': confirmed,
            'pattern': 'green_after_red' if confirmed else 'no_pattern',
            'green_after_red': green_after_red
        }
    
    async def check_entry_signals(self, stock: Dict) -> Optional[Dict]:
        """
        Check entry conditions (Warrior Trading Strategy):
        
        1. Stock meets 5/5 scanner criteria
        2. Green volume bars after red bar (buying pressure)
        3. MACD bullish (crossover or above signal)
        4. SMA20 > SMA50 (crossover or just above)
        5. Within trading hours
        6. Not already in position
        7. Not exited today (no re-entry rule)
        """
        try:
            symbol = stock['symbol']
            
            # Already in position? Don't double buy!
            if symbol in self.open_positions:
                return None
            
            # No Re-Entry Rule: Don't buy back stocks we've already exited today
            if symbol in self.exited_today:
                logger.debug(f"{symbol}: Skipped - already exited today (no re-entry rule)")
                return None
            
            # Get 5-minute bars
            bars = alpaca_service.get_bars(symbol, timeframe="5Min", limit=100)
            
            if not bars or len(bars) < 50:
                return None
            
            # Check 0: Stock must meet 5/5 scanner criteria
            criteria_count = stock.get('criteria_count', 0)
            if criteria_count < 5:
                logger.debug(f"{symbol}: Only {criteria_count}/5 criteria met - need 5/5")
                return None
            
            # Check 1: Volume confirmation (green bars after red)
            volume_check = self.check_volume_confirmation(bars)
            if self.require_volume_confirmation and not volume_check['confirmed']:
                logger.debug(f"{symbol}: No volume confirmation (green after red)")
                return None
            
            # Check 2: MACD bullish (crossover or just above, based on settings)
            closes = [b['close'] for b in bars]
            macd_check = self.calculate_macd(closes)
            if self.require_macd_crossover:
                # Require actual crossover (MACD just crossed above signal)
                if not macd_check['crossover']:
                    logger.debug(f"{symbol}: No MACD crossover - no entry")
                    return None
            else:
                # Just require MACD above signal
                if not macd_check['bullish']:
                    logger.debug(f"{symbol}: MACD bearish - no entry")
                    return None
            
            # Check 3: SMA confirmation (SMA20 > SMA50, crossover or just above)
            sma_check = self.check_sma_confirmation(bars)
            if self.require_sma_crossover:
                # Require actual crossover (SMA20 just crossed above SMA50)
                if not sma_check['crossover']:
                    logger.debug(f"{symbol}: No SMA{self.sma_period}/50 crossover - no entry")
                    return None
            else:
                # Just require SMA20 above SMA50
                if not sma_check['confirmed']:
                    logger.debug(f"{symbol}: SMA{self.sma_period} below SMA50 - no entry")
                    return None
            
            # Check 4: Bull flag (optional, based on settings)
            if self.require_bull_flag:
                from services.scanner_service import scanner_service
                has_bull_flag = scanner_service.check_bull_flag_pattern(bars)
                if not has_bull_flag:
                    logger.debug(f"{symbol}: No bull flag pattern - no entry")
                    return None
            
            # ALL CONDITIONS MET - 5/5 criteria + volume + indicators
            current_price = bars[-1]['close']
            entry_signal = {
                'symbol': symbol,
                'entry_price': current_price,
                'criteria_count': criteria_count,
                'volume_confirmation': volume_check,
                'macd': macd_check['macd'],
                'macd_signal': macd_check['signal'],
                'macd_crossover': macd_check['crossover'],
                'sma_fast': sma_check['sma_fast'],
                'sma_slow': sma_check['sma_slow'],
                'sma_crossover': sma_check['crossover'],
                'timestamp': datetime.now().isoformat()
            }
            
            logger.info(f"🎯 ENTRY SIGNAL: {symbol} @ ${entry_signal['entry_price']:.2f} (5/5 criteria)")
            logger.info(f"   Volume: {volume_check['green_after_red']} green after red | MACD: {'crossover' if macd_check['crossover'] else 'bullish'} | SMA20/50: {'crossover' if sma_check['crossover'] else 'confirmed'}")
            
            return entry_signal
            
        except Exception as e:
            logger.error(f"Error checking entry for {symbol}: {str(e)}")
            return None
    
    async def execute_entry(self, signal: Dict, portfolio_value: float) -> bool:
        """Execute buy order with trailing stop loss management"""
        try:
            symbol = signal['symbol']
            entry_price = signal['entry_price']
            
            # Calculate position size
            shares = self.calculate_position_size(portfolio_value, entry_price)
            
            if shares < 1:
                logger.warning(f"Position size too small for {symbol}")
                return False
            
            # Calculate targets using trailing stop
            initial_stop = entry_price * (1 - self.trailing_stop_pct)  # 1% trailing stop
            profit_target = entry_price * (1 + self.profit_target_pct)  # 2% target for partial sell
            
            # Place MARKET order (no bracket order for pre-market)
            # We'll manage trailing stop and partial sells in software
            order = alpaca_service.place_market_order(symbol, shares, "buy")
            
            if order and order.get('order_id'):
                # Store position for software-managed exits with trailing stop
                self.open_positions[symbol] = {
                    'order_id': order['order_id'],
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'shares': shares,
                    'original_shares': shares,
                    'stop_loss': initial_stop,
                    'trailing_stop': initial_stop,
                    'highest_price': entry_price,  # Track highest for trailing
                    'profit_target': profit_target,
                    'partial_sell_done': False,
                    'breakeven_stop_active': False,
                    'entry_time': datetime.now().isoformat(),
                    'status': 'open'
                }
                
                # Reset partial sold tracking for this symbol
                self.partial_sold[symbol] = False
                
                logger.info(f"✅ AUTO-BUY: {symbol} - {shares} shares @ ${entry_price:.2f}")
                logger.info(f"   Trailing Stop: ${initial_stop:.2f} ({self.trailing_stop_pct*100:.1f}%) | Target: ${profit_target:.2f} ({self.profit_target_pct*100:.1f}%)")
                logger.info(f"   At 2% profit: Sell {self.partial_sell_pct*100:.0f}% and move stop to break-even")
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error executing entry for {symbol}: {str(e)}")
            return False
    
    async def sell_with_retry(self, symbol: str, shares: int, reason: str, max_retries: int = 3) -> bool:
        """
        Robust sell with retry logic for slippage handling
        """
        for attempt in range(max_retries):
            try:
                order = alpaca_service.place_market_order(symbol, shares, "sell")
                if order and order.get('order_id'):
                    logger.info(f"✅ SELL: {symbol} - {shares} shares ({reason}) [attempt {attempt+1}]")
                    return True
                else:
                    logger.warning(f"⚠️ Sell attempt {attempt+1} for {symbol} returned no order_id")
            except Exception as e:
                logger.warning(f"⚠️ Sell attempt {attempt+1} for {symbol} failed: {str(e)}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(1)  # Wait 1 second before retry
        
        logger.error(f"❌ FAILED to sell {symbol} after {max_retries} attempts!")
        return False
    
    async def verify_position_closed(self, symbol: str) -> bool:
        """
        Verify a position is actually closed
        """
        try:
            positions = alpaca_service.get_positions()
            for pos in positions:
                if pos['symbol'] == symbol and float(pos['qty']) > 0:
                    return False  # Still have position
            return True  # Position is closed
        except Exception as e:
            logger.error(f"Error verifying position for {symbol}: {str(e)}")
            return False
    
    async def monitor_exits(self, portfolio_value: float):
        """
        Monitor positions for exit signals (SOFTWARE-MANAGED TRAILING STOP):
        
        1. Trailing stop hit (1% below highest price)
        2. Profit target hit (2%) - Sell 50%, move stop to break-even
        3. End of trading window (11 AM EST)
        """
        try:
            if not self.open_positions:
                return
            
            # Get current positions from Alpaca
            alpaca_positions = alpaca_service.get_positions()
            alpaca_symbols = {pos['symbol']: pos for pos in alpaca_positions}
            
            # Check if past trading hours
            past_trading_hours = not self.is_trading_hours()
            
            for symbol, position_data in list(self.open_positions.items()):
                # Check if position still exists
                if symbol not in alpaca_symbols:
                    logger.info(f"Position {symbol} closed by broker - removing from tracking")
                    del self.open_positions[symbol]
                    continue
                
                # Get current price
                current_position = alpaca_symbols[symbol]
                current_price = current_position['current_price']
                entry_price = position_data['entry_price']
                shares = int(float(current_position['qty']))  # Use actual shares from broker
                original_shares = position_data.get('original_shares', shares)
                
                # Calculate P&L
                pnl = (current_price - entry_price) * shares
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                
                # Update trailing stop if price went higher
                highest_price = position_data.get('highest_price', entry_price)
                if current_price > highest_price:
                    position_data['highest_price'] = current_price
                    # Update trailing stop
                    new_trailing_stop = current_price * (1 - self.trailing_stop_pct)
                    if new_trailing_stop > position_data.get('trailing_stop', 0):
                        position_data['trailing_stop'] = new_trailing_stop
                        logger.debug(f"{symbol}: Trailing stop updated to ${new_trailing_stop:.2f}")
                
                trailing_stop = position_data.get('trailing_stop', position_data['stop_loss'])
                
                # Check 1: Partial sell at profit target (2%)
                if not position_data.get('partial_sell_done', False) and current_price >= position_data['profit_target']:
                    partial_shares = int(shares * self.partial_sell_pct)
                    if partial_shares >= 1:
                        logger.info(f"📈 PARTIAL PROFIT: {symbol} hit {self.profit_target_pct*100:.0f}% target!")
                        
                        success = await self.sell_with_retry(symbol, partial_shares, f"PARTIAL PROFIT ({self.partial_sell_pct*100:.0f}%)")
                        
                        if success:
                            position_data['partial_sell_done'] = True
                            position_data['shares'] = shares - partial_shares
                            
                            # Move stop to break-even if enabled
                            if self.move_to_breakeven:
                                position_data['trailing_stop'] = entry_price
                                position_data['breakeven_stop_active'] = True
                                logger.info(f"   ✓ Sold {partial_shares} shares, stop moved to break-even ${entry_price:.2f}")
                            else:
                                logger.info(f"   ✓ Sold {partial_shares} shares, trailing stop at ${trailing_stop:.2f}")
                            
                            self.partial_sold[symbol] = True
                            continue  # Don't check other exits this cycle
                
                should_exit = False
                exit_reason = ""
                shares_to_sell = int(float(current_position['qty']))  # Sell remaining shares
                
                # Check 2: Trailing stop hit
                if current_price <= trailing_stop:
                    should_exit = True
                    if position_data.get('breakeven_stop_active'):
                        exit_reason = f"BREAKEVEN STOP HIT ${current_price:.2f} <= ${trailing_stop:.2f}"
                    else:
                        exit_reason = f"TRAILING STOP HIT ${current_price:.2f} <= ${trailing_stop:.2f} ({pnl_pct:.2f}%)"
                
                # Check 3: Past trading hours (11 AM)
                elif past_trading_hours:
                    should_exit = True
                    exit_reason = "END OF TRADING WINDOW (11 AM EST)"
                
                # Execute full exit if needed
                if should_exit:
                    success = await self.sell_with_retry(symbol, shares_to_sell, exit_reason)
                    
                    # Verify position is closed
                    if success:
                        await asyncio.sleep(2)  # Wait for order to process
                        if not await self.verify_position_closed(symbol):
                            # Retry if position still exists
                            logger.warning(f"⚠️ {symbol} position still exists after sell - retrying")
                            await self.sell_with_retry(symbol, shares_to_sell, "CLEANUP RETRY")
                    
                    if success:
                        logger.info(f"🔔 EXIT: {symbol} - {exit_reason}")
                        logger.info(f"   Entry: ${entry_price:.2f} → Exit: ${current_price:.2f}")
                        logger.info(f"   P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
                        
                        # Update daily tracking
                        self.daily_pnl += pnl
                        
                        if pnl < 0:
                            self.consecutive_losses += 1
                        else:
                            self.consecutive_losses = 0  # Reset on winner
                        
                        # Add to exited_today set (No Re-Entry Rule)
                        self.exited_today.add(symbol)
                        logger.info(f"   🚫 No Re-Entry: {symbol} blocked for rest of day")
                        
                        # Add to trade history
                        self.trade_history.append({
                            'symbol': symbol,
                            'entry_price': entry_price,
                            'exit_price': current_price,
                            'shares': original_shares,
                            'pnl': pnl,
                            'pnl_pct': pnl_pct,
                            'exit_reason': exit_reason,
                            'entry_time': position_data.get('entry_time'),
                            'exit_time': datetime.now().isoformat()
                        })
                        
                        # Log to persistent trade history service
                        trade_history.log_trade({
                            'symbol': symbol,
                            'entry_price': entry_price,
                            'exit_price': current_price,
                            'shares': original_shares,
                            'pnl': pnl,
                            'pnl_pct': pnl_pct,
                            'exit_reason': exit_reason,
                            'entry_time': position_data.get('entry_time'),
                            'exit_time': datetime.now().isoformat(),
                            'strategy': 'Auto-Trader (Warrior Trading)'
                        })
                        
                        # Remove from open positions
                        del self.open_positions[symbol]
                        
        except Exception as e:
            logger.error(f"Error monitoring exits: {str(e)}")
    
    async def process_scanner_results(self, scanner_results: List[Dict], portfolio_value: float):
        """Process scanner results and execute trades"""
        try:
            if not self.active:
                return
            
            # Reset daily tracking if new day
            self.reset_daily_tracking(portfolio_value)
            
            # Check trading hours
            if not self.is_trading_hours():
                logger.info("Outside trading hours (7 AM - 11 AM EST)")
                # Close any open positions at end of window
                if self.open_positions:
                    await self.monitor_exits(portfolio_value)
                return
            
            # Check risk limits
            risk_check = self.check_risk_limits(portfolio_value)
            if not risk_check['can_trade']:
                logger.warning(f"⛔ TRADING HALTED: {risk_check['reason']}")
                logger.info(f"   Daily P&L: ${risk_check['daily_pnl']:.2f} ({risk_check['daily_pnl_pct']:.2f}%)")
                logger.info(f"   Consecutive Losses: {risk_check['consecutive_losses']}")
                return
            
            # Check if we can take more positions
            if len(self.open_positions) >= self.max_positions:
                logger.info(f"Max positions reached ({self.max_positions})")
                await self.monitor_exits(portfolio_value)
                return
            
            # Filter to ready-to-trade stocks (5/5 criteria)
            ready_stocks = [s for s in scanner_results if s.get('ready_to_trade', False)]
            
            logger.info(f"📊 Scanner: {len(ready_stocks)} ready stocks | Portfolio: ${portfolio_value:,.2f} | Daily P&L: ${self.daily_pnl:.2f}")
            
            # Check each ready stock for entry signals
            for stock in ready_stocks:
                if len(self.open_positions) >= self.max_positions:
                    break
                
                entry_signal = await self.check_entry_signals(stock)
                
                if entry_signal:
                    success = await self.execute_entry(entry_signal, portfolio_value)
                    if success:
                        logger.info(f"✅ Trade executed for {entry_signal['symbol']}")
            
            # Monitor existing positions
            await self.monitor_exits(portfolio_value)
            
        except Exception as e:
            logger.error(f"Error processing scanner results: {str(e)}")

# Global instance
auto_trader = AutoTraderService()
