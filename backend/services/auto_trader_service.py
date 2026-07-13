"""
Warrior Trading Momentum Auto-Trader
Based on Ross Cameron's Small Cap Momentum Strategy (Warrior Trading "5 Pillars")

STRATEGY RULES (aligned with Ross Cameron's documented Warrior Trading rules,
see warriortrading.com/momentum-day-trading-strategy, /position-sizing,
/daily-goal - reconciled 2026 to remove the earlier 5%/10%/5%/10% doc
mismatch and match what the code actually enforces):
1. Entry: Micro-pullback (1-3 green candles) on the front side of momentum,
   confirmed by MACD bullish crossover + SMA20/50 crossover + volume + 5/5 scanner criteria
2. Position Size: 10% of account per trade (up to 5 concurrent = 50% max exposure)
3. Profit Target: +2% - sell 50% (partial), move stop to break-even
4. Stop Loss: -1% trailing, managed in software (pre-market/extended hours has no broker stops)
   -> 2:1 profit-target:stop-loss ratio, matching Warrior Trading's core risk/reward rule
5. Daily Max Loss: 1% of account (Ross Cameron's conservative starting rule) - HARD KILL SWITCH
6. Max Consecutive Losses: 3 (then done for day) - "three strikes" rule
7. Time Window: entries + position management 7 AM - 3:30 PM EST, all positions closed by 3:30 PM EST
8. Exit Signals: trailing stop hit, MACD bearish crossover while losing, profit target hit, end of window
9. Stock Selection (5 Pillars): $2-$20 price, <20M float, high relative volume, news catalyst, bullish MACD/bull flag

Risk/position state (open_positions, daily_pnl, consecutive_losses,
exited_today, trade_history) is persisted to MongoDB so it survives a
server restart instead of silently resetting to defaults.
"""
from datetime import datetime, timedelta, timezone, date as date_cls
import logging
from typing import Dict, List, Optional
import asyncio
import pytz
from services.alpaca_service import alpaca_service
from services.trade_history_service import trade_history
from database import db

logger = logging.getLogger(__name__)


class AutoTraderService:
    def __init__(self):
        self.active = False
        self.open_positions = {}  # {symbol: position_data}

        # STRATEGY PARAMETERS - Warrior Trading Quick Scalp Style (Ross Cameron)
        # 2:1 profit-target:stop-loss ratio + 1% conservative daily-loss kill switch,
        # matching Ross Cameron's documented risk rules (see file docstring above).
        self.max_positions = 5
        self.position_size_pct = 0.10  # 10% of account per trade (up to 5 concurrent = 50% max exposure)
        self.profit_target_pct = 0.02  # 2% profit target - sell 50% here (2:1 with the 1% stop)
        self.stop_loss_pct = 0.01  # 1% initial stop loss
        self.trailing_stop_pct = 0.01  # 1% trailing stop (default)
        self.partial_sell_pct = 0.50  # Sell 50% at profit target
        self.move_to_breakeven = True  # Move stop to break-even after partial sell
        self.daily_max_loss_pct = 0.01  # 1% max daily loss (Ross Cameron's conservative starting rule) - hard kill switch
        self.max_consecutive_losses = 3  # "Three strikes" rule - done for the day

        # Entry condition settings (adjustable)
        self.pullback_min_candles = 1  # Minimum green candles in pullback
        self.pullback_max_candles = 3  # Maximum green candles in pullback
        self.pullback_lookback_bars = 10  # Number of bars to look back for pullback pattern
        self.require_micro_pullback = True  # Require 1-3 green candle micro-pullback pattern (Warrior Trading core entry trigger)
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
        # Entries allowed and positions managed throughout this window,
        # then all positions closed at 3:30 PM
        self.trading_start_hour = 7
        self.trading_end_hour = 15  # 3 PM (will check minutes too)
        self.trading_end_minute = 30  # 3:30 PM - auto-sell all positions

        self._state_collection = db.auto_trader_state

    # ------------------------------------------------------------------
    # MongoDB persistence (Phase 3 - state survives restarts)
    # ------------------------------------------------------------------
    async def save_state(self):
        """Persist risk/position state to MongoDB so it survives a restart"""
        try:
            await self._state_collection.update_one(
                {'_id': 'singleton'},
                {'$set': {
                    'active': self.active,
                    'open_positions': self.open_positions,
                    'daily_pnl': self.daily_pnl,
                    'consecutive_losses': self.consecutive_losses,
                    'starting_portfolio_value': self.starting_portfolio_value,
                    'last_reset_date': self.last_reset_date.isoformat() if self.last_reset_date else None,
                    'trade_history': self.trade_history,
                    'partial_sold': self.partial_sold,
                    'breakeven_stops': self.breakeven_stops,
                    'exited_today': list(self.exited_today),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Failed to persist auto-trader state: {e}")

    async def load_state(self):
        """Restore risk/position state from MongoDB on startup"""
        try:
            doc = await self._state_collection.find_one({'_id': 'singleton'})
            if not doc:
                logger.info("No saved auto-trader state found - starting fresh")
                return

            self.active = doc.get('active', False)
            self.open_positions = doc.get('open_positions', {}) or {}
            self.daily_pnl = doc.get('daily_pnl', 0.0)
            self.consecutive_losses = doc.get('consecutive_losses', 0)
            self.starting_portfolio_value = doc.get('starting_portfolio_value', 0.0)
            last_reset = doc.get('last_reset_date')
            self.last_reset_date = date_cls.fromisoformat(last_reset) if last_reset else None
            self.trade_history = doc.get('trade_history', []) or []
            self.partial_sold = doc.get('partial_sold', {}) or {}
            self.breakeven_stops = doc.get('breakeven_stops', {}) or {}
            self.exited_today = set(doc.get('exited_today', []) or [])

            logger.info(
                f"🔄 Restored auto-trader state: active={self.active}, "
                f"{len(self.open_positions)} open position(s), daily P&L ${self.daily_pnl:.2f}, "
                f"{self.consecutive_losses} consecutive losses"
            )
        except Exception as e:
            logger.error(f"Failed to load auto-trader state: {e}")

    def update_settings(self, settings: Dict):
        """Update auto-trader settings"""
        # Entry conditions
        if 'pullback_min_candles' in settings:
            self.pullback_min_candles = int(settings['pullback_min_candles'])
        if 'pullback_max_candles' in settings:
            self.pullback_max_candles = int(settings['pullback_max_candles'])
        if 'pullback_lookback_bars' in settings:
            self.pullback_lookback_bars = int(settings['pullback_lookback_bars'])
        if 'require_micro_pullback' in settings:
            self.require_micro_pullback = bool(settings['require_micro_pullback'])
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
        - 7:00 AM - 3:30 PM: Entries allowed + positions managed
        - 3:30 PM: Auto-sell ALL positions

        Manual trading can happen during full extended hours (4 AM - 8 PM ET)
        """
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)

        if now_et.weekday() >= 5:  # Saturday = 5, Sunday = 6 - markets closed
            return False

        if now_et.hour < self.trading_start_hour:
            return False

        if now_et.hour > self.trading_end_hour:
            return False
        if now_et.hour == self.trading_end_hour and now_et.minute >= self.trading_end_minute:
            return False

        return True

    def check_risk_limits(self, portfolio_value: float) -> Dict:
        """
        Check if risk limits are breached (server-side hard kill switch).

        Returns: {
            'can_trade': bool,
            'reason': str,
            'daily_pnl': float,
            'daily_pnl_pct': float,
            'consecutive_losses': int
        }
        """
        daily_pnl_pct = (self.daily_pnl / self.starting_portfolio_value * 100) if self.starting_portfolio_value > 0 else 0

        if daily_pnl_pct <= -self.daily_max_loss_pct * 100:
            return {
                'can_trade': False,
                'reason': f'Daily max loss reached ({daily_pnl_pct:.2f}% / -{self.daily_max_loss_pct * 100:.0f}% limit)',
                'daily_pnl': self.daily_pnl,
                'daily_pnl_pct': daily_pnl_pct,
                'consecutive_losses': self.consecutive_losses
            }

        if self.consecutive_losses >= self.max_consecutive_losses:
            return {
                'can_trade': False,
                'reason': f'{self.consecutive_losses} consecutive losses - done for the day',
                'daily_pnl': self.daily_pnl,
                'daily_pnl_pct': daily_pnl_pct,
                'consecutive_losses': self.consecutive_losses
            }

        return {
            'can_trade': True,
            'reason': 'Risk limits OK',
            'daily_pnl': self.daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'consecutive_losses': self.consecutive_losses
        }

    def calculate_position_size(self, portfolio_value: float, stock_price: float) -> int:
        """
        Calculate shares to buy based on position_size_pct of REAL account value
        (portfolio_value must come from the live Alpaca account - never simulated).
        """
        position_capital = portfolio_value * self.position_size_pct
        shares = int(position_capital / stock_price)
        shares = max(1, shares)  # At least 1 share

        logger.info(f"Position sizing: ${portfolio_value:,.2f} × {self.position_size_pct*100}% = ${position_capital:,.2f} / ${stock_price:.2f} = {shares} shares")

        return shares

    def calculate_macd(self, closes: List[float], fast_period=12, slow_period=26, signal_period=9) -> Dict:
        """
        Calculate MACD (Moving Average Convergence Divergence)
        """
        if len(closes) < slow_period + signal_period:
            return {'macd': 0, 'signal': 0, 'histogram': 0, 'bullish': False, 'crossover': False, 'prev_macd': 0, 'prev_signal': 0}

        def calculate_ema(data, period):
            multiplier = 2 / (period + 1)
            ema = [sum(data[:period]) / period]
            for price in data[period:]:
                ema.append((price - ema[-1]) * multiplier + ema[-1])
            return ema[-1]

        macd_history = []
        for i in range(slow_period, len(closes)):
            ema_f = calculate_ema(closes[:i+1], fast_period)
            ema_s = calculate_ema(closes[:i+1], slow_period)
            macd_history.append(ema_f - ema_s)

        if len(macd_history) < signal_period + 1:
            return {'macd': 0, 'signal': 0, 'histogram': 0, 'bullish': False, 'crossover': False, 'prev_macd': 0, 'prev_signal': 0}

        macd_line = macd_history[-1]
        signal_line = calculate_ema(macd_history, signal_period)
        histogram = macd_line - signal_line

        prev_macd = macd_history[-2]
        prev_signal = calculate_ema(macd_history[:-1], signal_period) if len(macd_history) > signal_period else signal_line

        was_below = prev_macd <= prev_signal
        now_above = macd_line > signal_line
        crossover = was_below and now_above

        bullish = macd_line > signal_line

        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram,
            'bullish': bullish,
            'crossover': crossover,
            'prev_macd': prev_macd,
            'prev_signal': prev_signal
        }

    def check_micro_pullback(self, bars: List[Dict]) -> Dict:
        """
        Check for micro-pullback pattern (1-3 green candles after a move up)
        """
        lookback = self.pullback_lookback_bars
        if len(bars) < lookback:
            return {'is_valid': False, 'green_candles': 0, 'entry_price': 0, 'lookback': lookback}

        recent_bars = bars[-lookback:]

        if len(recent_bars) < 5:
            return {'is_valid': False, 'green_candles': 0, 'entry_price': 0, 'lookback': lookback}

        recent_high = max(b['high'] for b in recent_bars[:-3])

        green_candle_count = 0
        pullback_started = False

        for i in range(len(recent_bars) - 1, max(len(recent_bars) - 5, 0), -1):
            bar = recent_bars[i]
            is_green = bar['close'] > bar['open']
            is_red = bar['close'] < bar['open']

            if is_green:
                green_candle_count += 1
                pullback_started = True
            elif is_red and pullback_started:
                break
            elif is_red and not pullback_started:
                continue

        is_valid_pullback = 1 <= green_candle_count <= 3

        current_price = bars[-1]['close']
        current_bar = bars[-1]
        is_current_green = current_bar['close'] > current_bar['open']

        near_high = current_price >= current_bar['high'] * 0.98

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
        """Check if SMA(short) is above SMA50 (bullish)"""
        sma_fast_period = self.sma_period
        sma_slow_period = 50

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

        sma_fast = sum(closes[-sma_fast_period:]) / sma_fast_period
        sma_slow = sum(closes[-sma_slow_period:]) / sma_slow_period
        current_price = bars[-1]['close']

        prev_sma_fast = sum(closes[-(sma_fast_period+1):-1]) / sma_fast_period
        prev_sma_slow = sum(closes[-(sma_slow_period+1):-1]) / sma_slow_period

        was_below = prev_sma_fast <= prev_sma_slow
        now_above = sma_fast > sma_slow
        crossover = was_below and now_above

        return {
            'confirmed': sma_fast > sma_slow,
            'crossover': crossover,
            'sma_fast': sma_fast,
            'sma_slow': sma_slow,
            'prev_sma_fast': prev_sma_fast,
            'prev_sma_slow': prev_sma_slow,
            'current_price': current_price
        }

    def check_volume_confirmation(self, bars: List[Dict]) -> Dict:
        """Check for green volume bars after a red bar (buying pressure confirmation)"""
        if len(bars) < 5:
            return {'confirmed': False, 'pattern': 'insufficient_data', 'green_after_red': 0}

        recent_bars = bars[-5:]

        green_after_red = 0
        found_red = False

        for i, bar in enumerate(recent_bars[:-1]):
            is_red = bar['close'] < bar['open']
            is_green = bar['close'] > bar['open']

            if is_red:
                found_red = True
                green_after_red = 0
            elif found_red and is_green:
                green_after_red += 1

        last_bar = recent_bars[-1]
        last_is_green = last_bar['close'] > last_bar['open']
        if found_red and last_is_green:
            green_after_red += 1

        confirmed = green_after_red >= 1

        return {
            'confirmed': confirmed,
            'pattern': 'green_after_red' if confirmed else 'no_pattern',
            'green_after_red': green_after_red
        }

    async def _get_real_bars(self, symbol: str, timeframe: str = "5Min", limit: int = 100) -> Optional[List[Dict]]:
        """
        Fetch bars using the real-data-only fallback chain (Alpaca -> Yahoo -> Nasdaq).
        Never fabricates data. Returns None if no real data is available so callers
        can skip the symbol instead of trading on fake bars.
        """
        try:
            result = await asyncio.to_thread(alpaca_service.get_bars_with_fallback, symbol, timeframe, limit)
            if result.get('no_historical_data'):
                logger.warning(f"{symbol}: No real historical data available - skipping")
                return None
            bars = result.get('bars', [])
            return bars if bars else None
        except Exception as e:
            logger.warning(f"{symbol}: Failed to fetch real bars: {e}")
            return None

    async def check_entry_signals(self, stock: Dict) -> Optional[Dict]:
        """
        Check entry conditions (Warrior Trading Strategy):

        1. Stock meets 5/5 scanner criteria
        2. Micro-pullback pattern (1-3 green candles after a move up)
        3. Green volume bars after red bar (buying pressure)
        4. MACD bullish (crossover or above signal)
        5. SMA(short) > SMA50 (crossover or just above)
        6. Within trading hours
        7. Not already in position
        8. Not exited today (no re-entry rule)
        """
        symbol = stock.get('symbol')
        try:
            if symbol in self.open_positions:
                return None

            if symbol in self.exited_today:
                logger.debug(f"{symbol}: Skipped - already exited today (no re-entry rule)")
                return None

            # Real data only - never fabricate bars. Skip symbol if unavailable.
            bars = await self._get_real_bars(symbol, timeframe="5Min", limit=100)
            if not bars or len(bars) < 50:
                logger.debug(f"{symbol}: Skipped - insufficient real market data")
                return None

            criteria_count = stock.get('criteria_count', 0)
            if criteria_count < 5:
                logger.debug(f"{symbol}: Only {criteria_count}/5 criteria met - need 5/5")
                return None

            pullback_check = self.check_micro_pullback(bars)
            if self.require_micro_pullback and not pullback_check['is_valid']:
                logger.debug(f"{symbol}: No valid micro-pullback pattern - {pullback_check.get('reason', 'n/a')}")
                return None

            volume_check = self.check_volume_confirmation(bars)
            if self.require_volume_confirmation and not volume_check['confirmed']:
                logger.debug(f"{symbol}: No volume confirmation (green after red)")
                return None

            closes = [b['close'] for b in bars]
            macd_check = self.calculate_macd(closes)
            if self.require_macd_crossover:
                if not macd_check['crossover']:
                    logger.debug(f"{symbol}: No MACD crossover - no entry")
                    return None
            else:
                if not macd_check['bullish']:
                    logger.debug(f"{symbol}: MACD bearish - no entry")
                    return None

            sma_check = self.check_sma_confirmation(bars)
            if self.require_sma_crossover:
                if not sma_check['crossover']:
                    logger.debug(f"{symbol}: No SMA{self.sma_period}/50 crossover - no entry")
                    return None
            else:
                if not sma_check['confirmed']:
                    logger.debug(f"{symbol}: SMA{self.sma_period} below SMA50 - no entry")
                    return None

            if self.require_bull_flag:
                from services.scanner_service import scanner_service
                has_bull_flag = scanner_service.check_bull_flag_pattern(bars)
                if not has_bull_flag:
                    logger.debug(f"{symbol}: No bull flag pattern - no entry")
                    return None

            current_price = bars[-1]['close']
            entry_signal = {
                'symbol': symbol,
                'entry_price': current_price,
                'criteria_count': criteria_count,
                'micro_pullback': pullback_check,
                'volume_confirmation': volume_check,
                'macd': macd_check['macd'],
                'macd_signal': macd_check['signal'],
                'macd_crossover': macd_check['crossover'],
                'sma_fast': sma_check['sma_fast'],
                'sma_slow': sma_check['sma_slow'],
                'sma_crossover': sma_check['crossover'],
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"🎯 ENTRY SIGNAL: {symbol} @ ${entry_signal['entry_price']:.2f} (5/5 criteria)")
            logger.info(f"   Pullback: {pullback_check.get('pattern', 'n/a')} | Volume: {volume_check['green_after_red']} green after red | MACD: {'crossover' if macd_check['crossover'] else 'bullish'} | SMA{self.sma_period}/50: {'crossover' if sma_check['crossover'] else 'confirmed'}")

            return entry_signal

        except Exception as e:
            logger.error(f"Error checking entry for {symbol}: {str(e)}")
            return None

    async def execute_entry(self, signal: Dict, portfolio_value: float) -> bool:
        """Execute buy order with trailing stop loss management"""
        try:
            symbol = signal['symbol']
            entry_price = signal['entry_price']

            shares = self.calculate_position_size(portfolio_value, entry_price)

            if shares < 1:
                logger.warning(f"Position size too small for {symbol}")
                return False

            initial_stop = entry_price * (1 - self.trailing_stop_pct)
            profit_target = entry_price * (1 + self.profit_target_pct)

            order = await asyncio.to_thread(alpaca_service.place_market_order, symbol, shares, "buy")

            if order and order.get('order_id'):
                self.open_positions[symbol] = {
                    'order_id': order['order_id'],
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'shares': shares,
                    'original_shares': shares,
                    'stop_loss': initial_stop,
                    'trailing_stop': initial_stop,
                    'highest_price': entry_price,
                    'profit_target': profit_target,
                    'partial_sell_done': False,
                    'breakeven_stop_active': False,
                    'entry_time': datetime.now(timezone.utc).isoformat(),
                    'status': 'open'
                }

                self.partial_sold[symbol] = False
                await self.save_state()

                logger.info(f"✅ AUTO-BUY: {symbol} - {shares} shares @ ${entry_price:.2f}")
                logger.info(f"   Trailing Stop: ${initial_stop:.2f} ({self.trailing_stop_pct*100:.1f}%) | Target: ${profit_target:.2f} ({self.profit_target_pct*100:.1f}%)")
                logger.info(f"   At {self.profit_target_pct*100:.0f}% profit: Sell {self.partial_sell_pct*100:.0f}% and move stop to break-even")

                return True

            return False

        except Exception as e:
            logger.error(f"Error executing entry for {signal.get('symbol')}: {str(e)}")
            return False

    async def sell_with_retry(self, symbol: str, shares: int, reason: str, max_retries: int = 3) -> bool:
        """Robust sell with retry logic for slippage handling"""
        for attempt in range(max_retries):
            try:
                order = await asyncio.to_thread(alpaca_service.place_market_order, symbol, shares, "sell")
                if order and order.get('order_id'):
                    logger.info(f"✅ SELL: {symbol} - {shares} shares ({reason}) [attempt {attempt+1}]")
                    return True
                else:
                    logger.warning(f"⚠️ Sell attempt {attempt+1} for {symbol} returned no order_id")
            except Exception as e:
                logger.warning(f"⚠️ Sell attempt {attempt+1} for {symbol} failed: {str(e)}")

            if attempt < max_retries - 1:
                await asyncio.sleep(1)

        logger.error(f"❌ FAILED to sell {symbol} after {max_retries} attempts!")
        return False

    async def verify_position_closed(self, symbol: str) -> bool:
        """Verify a position is actually closed"""
        try:
            positions = await asyncio.to_thread(alpaca_service.get_positions)
            for pos in positions:
                if pos['symbol'] == symbol and float(pos['qty']) > 0:
                    return False
            return True
        except Exception as e:
            logger.error(f"Error verifying position for {symbol}: {str(e)}")
            return False

    async def monitor_exits(self, portfolio_value: float):
        """
        Monitor positions for exit signals (SOFTWARE-MANAGED TRAILING STOP):

        1. Trailing stop hit (trailing_stop_pct below highest price)
        2. Profit target hit - Sell partial_sell_pct, move stop to break-even
        3. End of trading window
        """
        try:
            if not self.open_positions:
                return

            alpaca_positions = await asyncio.to_thread(alpaca_service.get_positions)
            alpaca_symbols = {pos['symbol']: pos for pos in alpaca_positions}

            past_trading_hours = not self.is_trading_hours()
            state_changed = False

            for symbol, position_data in list(self.open_positions.items()):
                if symbol not in alpaca_symbols:
                    logger.info(f"Position {symbol} closed by broker - removing from tracking")
                    del self.open_positions[symbol]
                    state_changed = True
                    continue

                current_position = alpaca_symbols[symbol]
                current_price = current_position['current_price']
                entry_price = position_data['entry_price']
                shares = int(float(current_position['qty']))
                original_shares = position_data.get('original_shares', shares)

                pnl = (current_price - entry_price) * shares
                pnl_pct = ((current_price - entry_price) / entry_price) * 100

                highest_price = position_data.get('highest_price', entry_price)
                if current_price > highest_price:
                    position_data['highest_price'] = current_price
                    new_trailing_stop = current_price * (1 - self.trailing_stop_pct)
                    if new_trailing_stop > position_data.get('trailing_stop', 0):
                        position_data['trailing_stop'] = new_trailing_stop
                        state_changed = True
                        logger.debug(f"{symbol}: Trailing stop updated to ${new_trailing_stop:.2f}")

                trailing_stop = position_data.get('trailing_stop', position_data['stop_loss'])

                if not position_data.get('partial_sell_done', False) and current_price >= position_data['profit_target']:
                    partial_shares = int(shares * self.partial_sell_pct)
                    if partial_shares >= 1:
                        logger.info(f"📈 PARTIAL PROFIT: {symbol} hit {self.profit_target_pct*100:.0f}% target!")

                        success = await self.sell_with_retry(symbol, partial_shares, f"PARTIAL PROFIT ({self.partial_sell_pct*100:.0f}%)")

                        if success:
                            position_data['partial_sell_done'] = True
                            position_data['shares'] = shares - partial_shares

                            if self.move_to_breakeven:
                                position_data['trailing_stop'] = entry_price
                                position_data['breakeven_stop_active'] = True
                                logger.info(f"   ✓ Sold {partial_shares} shares, stop moved to break-even ${entry_price:.2f}")
                            else:
                                logger.info(f"   ✓ Sold {partial_shares} shares, trailing stop at ${trailing_stop:.2f}")

                            self.partial_sold[symbol] = True
                            state_changed = True
                            continue

                should_exit = False
                exit_reason = ""
                shares_to_sell = int(float(current_position['qty']))

                if current_price <= trailing_stop:
                    should_exit = True
                    if position_data.get('breakeven_stop_active'):
                        exit_reason = f"BREAKEVEN STOP HIT ${current_price:.2f} <= ${trailing_stop:.2f}"
                    else:
                        exit_reason = f"TRAILING STOP HIT ${current_price:.2f} <= ${trailing_stop:.2f} ({pnl_pct:.2f}%)"

                elif past_trading_hours:
                    should_exit = True
                    exit_reason = "END OF TRADING WINDOW"

                if should_exit:
                    success = await self.sell_with_retry(symbol, shares_to_sell, exit_reason)

                    if success:
                        if not await self.verify_position_closed(symbol):
                            logger.warning(f"⚠️ {symbol} position still exists after sell - retrying")
                            await self.sell_with_retry(symbol, shares_to_sell, "CLEANUP RETRY")

                    if success:
                        # Use real fill price for P&L, not the last quote, when available
                        exit_price = current_price
                        try:
                            filled_order = await asyncio.to_thread(alpaca_service.get_order, current_position.get('order_id')) if current_position.get('order_id') else None
                            if filled_order and filled_order.get('filled_avg_price'):
                                exit_price = float(filled_order['filled_avg_price'])
                        except Exception:
                            pass

                        pnl = (exit_price - entry_price) * shares
                        pnl_pct = ((exit_price - entry_price) / entry_price) * 100

                        logger.info(f"🔔 EXIT: {symbol} - {exit_reason}")
                        logger.info(f"   Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f}")
                        logger.info(f"   P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")

                        self.daily_pnl += pnl

                        if pnl < 0:
                            self.consecutive_losses += 1
                        else:
                            self.consecutive_losses = 0

                        self.exited_today.add(symbol)
                        logger.info(f"   🚫 No Re-Entry: {symbol} blocked for rest of day")

                        self.trade_history.append({
                            'symbol': symbol,
                            'entry_price': entry_price,
                            'exit_price': exit_price,
                            'shares': original_shares,
                            'pnl': pnl,
                            'pnl_pct': pnl_pct,
                            'exit_reason': exit_reason,
                            'entry_time': position_data.get('entry_time'),
                            'exit_time': datetime.now(timezone.utc).isoformat()
                        })

                        await trade_history.log_trade({
                            'symbol': symbol,
                            'entry_price': entry_price,
                            'exit_price': exit_price,
                            'shares': original_shares,
                            'pnl': pnl,
                            'pnl_pct': pnl_pct,
                            'exit_reason': exit_reason,
                            'entry_time': position_data.get('entry_time'),
                            'exit_time': datetime.now(timezone.utc).isoformat(),
                            'strategy': 'Auto-Trader (Warrior Trading)'
                        })

                        del self.open_positions[symbol]
                        state_changed = True

            if state_changed:
                await self.save_state()

        except Exception as e:
            logger.error(f"Error monitoring exits: {str(e)}")

    async def process_scanner_results(self, scanner_results: List[Dict], portfolio_value: float):
        """Process scanner results and execute trades"""
        try:
            if not self.active:
                return

            self.reset_daily_tracking(portfolio_value)

            if not self.is_trading_hours():
                logger.info(f"Outside trading hours ({self.trading_start_hour} AM - {self.trading_end_hour - 12 if self.trading_end_hour > 12 else self.trading_end_hour}:{self.trading_end_minute:02d} PM EST)")
                if self.open_positions:
                    await self.monitor_exits(portfolio_value)
                return

            # Hard kill switch: risk limits are checked before ANY new entry
            risk_check = self.check_risk_limits(portfolio_value)
            if not risk_check['can_trade']:
                logger.warning(f"⛔ TRADING HALTED: {risk_check['reason']}")
                logger.info(f"   Daily P&L: ${risk_check['daily_pnl']:.2f} ({risk_check['daily_pnl_pct']:.2f}%)")
                logger.info(f"   Consecutive Losses: {risk_check['consecutive_losses']}")
                # Still manage existing positions/exits even when new entries are halted
                if self.open_positions:
                    await self.monitor_exits(portfolio_value)
                return

            if len(self.open_positions) >= self.max_positions:
                logger.info(f"Max positions reached ({self.max_positions})")
                await self.monitor_exits(portfolio_value)
                return

            ready_stocks = [s for s in scanner_results if s.get('ready_to_trade', False)]

            logger.info(f"📊 Scanner: {len(ready_stocks)} ready stocks | Portfolio: ${portfolio_value:,.2f} | Daily P&L: ${self.daily_pnl:.2f}")

            for stock in ready_stocks:
                if len(self.open_positions) >= self.max_positions:
                    break

                entry_signal = await self.check_entry_signals(stock)

                if entry_signal:
                    success = await self.execute_entry(entry_signal, portfolio_value)
                    if success:
                        logger.info(f"✅ Trade executed for {entry_signal['symbol']}")

            await self.monitor_exits(portfolio_value)

        except Exception as e:
            logger.error(f"Error processing scanner results: {str(e)}")


# Global instance
auto_trader = AutoTraderService()
