"""
Position Monitor Service - Manages Trailing Stops and Partial Exits

Continuously monitors open positions and:
1. Updates trailing stop losses as price increases
2. Executes partial sells when profit targets are hit
3. Moves stop loss to break even after partial sell

Monitored position state is persisted to MongoDB (collection:
monitored_positions) so real stop configs survive a server restart instead
of resetting to defaults.
"""
import logging
from typing import Dict
import asyncio
from datetime import datetime, timedelta
from services.alpaca_service import alpaca_service
from database import db

logger = logging.getLogger(__name__)


class PositionMonitorService:
    def __init__(self):
        self.active = False
        self.monitored_positions = {}  # {symbol: position_config}
        self._collection = db.monitored_positions

    # ------------------------------------------------------------------
    # MongoDB persistence (Phase 3 - state survives restarts)
    # ------------------------------------------------------------------
    async def save_state(self):
        """Persist monitored positions to MongoDB"""
        try:
            await self._collection.update_one(
                {'_id': 'singleton'},
                {'$set': {'monitored_positions': self.monitored_positions}},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Failed to persist position monitor state: {e}")

    async def load_state(self):
        """Restore monitored positions from MongoDB on startup"""
        try:
            doc = await self._collection.find_one({'_id': 'singleton'})
            if doc and doc.get('monitored_positions'):
                self.monitored_positions = doc['monitored_positions']
                logger.info(f"🔄 Restored {len(self.monitored_positions)} monitored position(s) from MongoDB")
            else:
                logger.info("No saved monitored positions found - starting fresh")
        except Exception as e:
            logger.error(f"Failed to load position monitor state: {e}")

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
        }
        """
        existing = self.monitored_positions.get(symbol)
        if existing:
            logger.info(f"📊 Re-syncing {symbol} - preserving stop @ ${existing['current_stop']:.2f}, partial_sold={existing.get('partial_sold', False)}")
            self.monitored_positions[symbol] = {
                **config,
                'highest_price': existing.get('highest_price', config.get('entry_price', 0)),
                'current_stop': existing.get('current_stop', config.get('stop_reference_price', config['entry_price']) * (1 - config['stop_loss_pct'] / 100)),
                'partial_sold': existing.get('partial_sold', False),
                'added_at': existing.get('added_at', datetime.now().isoformat())
            }
        else:
            stop_ref = config.get('stop_reference_price', config.get('entry_price', 0))
            initial_stop = stop_ref * (1 - config['stop_loss_pct'] / 100)

            self.monitored_positions[symbol] = {
                **config,
                'highest_price': config.get('entry_price', 0),
                'current_stop': initial_stop,
                'partial_sold': False,
                'added_at': datetime.now().isoformat(),
                'settling_until': (datetime.now() + timedelta(seconds=60)).isoformat()
            }

            entry = config.get('entry_price', 0)
            spread = config.get('spread_at_entry', 0)
            logger.info(f"📊 Monitoring {symbol} | Entry: ${entry:.2f} | Stop ref: ${stop_ref:.2f} | Stop: ${initial_stop:.2f} | Spread: {spread:.1f}% | Settling 60s")

        asyncio.create_task(self.save_state())

    def remove_position(self, symbol: str):
        """Remove position from monitoring"""
        if symbol in self.monitored_positions:
            del self.monitored_positions[symbol]
            logger.info(f"🔴 Stopped monitoring {symbol}")
            asyncio.create_task(self.save_state())

    async def monitor_positions(self):
        """Main monitoring loop - checks all positions continuously"""
        while self.active:
            try:
                if not self.monitored_positions:
                    await asyncio.sleep(5)
                    continue

                alpaca_positions = await asyncio.to_thread(alpaca_service.get_positions)
                alpaca_symbols = {pos['symbol']: pos for pos in alpaca_positions}

                # Re-assert priority on every tick (cheap/idempotent) so
                # every open position - however it was entered - always
                # keeps a live trade/quote slot, evicting a scanner-only
                # symbol if the 25-symbol cap is otherwise full.
                if alpaca_symbols:
                    from services.market_data_stream_service import market_data_stream
                    asyncio.create_task(market_data_stream.subscribe(list(alpaca_symbols.keys()), priority=True))

                for symbol, config in list(self.monitored_positions.items()):
                    if symbol not in alpaca_symbols:
                        logger.info(f"{symbol}: Position closed, removing from monitor")
                        self.remove_position(symbol)
                        continue

                    current_price = alpaca_symbols[symbol]['current_price']
                    entry_price = config['entry_price']
                    shares = config['shares']

                    profit_pct = ((current_price - entry_price) / entry_price) * 100

                    if config['stop_type'] == 'trailing':
                        await self._handle_trailing_stop(symbol, config, current_price, profit_pct)

                    if profit_pct >= config.get('take_profit_pct', 2.0) and not config.get('partial_sold'):
                        await self._handle_partial_take_profit(symbol, config, current_price, profit_pct, shares)

                    if profit_pct < 0:
                        exited = await self._check_bearish_crossover_exit(symbol, config, current_price, profit_pct, shares)
                        if exited:
                            continue

                    current_stop = config['current_stop']

                    settling_until = config.get('settling_until')
                    if settling_until:
                        settling_time = datetime.fromisoformat(settling_until)
                        if datetime.now() < settling_time:
                            remaining = (settling_time - datetime.now()).seconds
                            logger.debug(f"⏳ {symbol}: Settling period - {remaining}s remaining, stop loss disabled")
                            continue

                    logger.debug(f"🔍 {symbol}: Price ${current_price:.2f} | Stop ${current_stop:.2f} | partial_sold={config.get('partial_sold', False)}")
                    if current_price <= current_stop:
                        logger.info(f"🔍 {symbol}: Stop triggered - Price ${current_price:.2f} <= Stop ${current_stop:.2f}")
                        await self._execute_stop_loss(symbol, config, current_price, shares)

                await self.save_state()
                await asyncio.sleep(2)  # Check every 2 seconds

            except Exception as e:
                logger.error(f"Error in position monitor: {str(e)}")
                await asyncio.sleep(5)

    async def _handle_trailing_stop(self, symbol: str, config: Dict, current_price: float, profit_pct: float):
        """Update trailing stop as price increases"""
        try:
            if current_price > config['highest_price']:
                old_highest = config['highest_price']
                config['highest_price'] = current_price

                trailing_pct = config['trailing_stop_pct']
                new_stop = current_price * (1 - trailing_pct / 100)

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
        """Execute PARTIAL SELL when profit target is reached, keep rest running"""
        try:
            target_pct = config.get('take_profit_pct', 2.0)

            if config.get('partial_sold'):
                return

            if profit_pct >= target_pct:
                sell_pct = config.get('partial_sell_pct', 50.0)
                shares_to_sell = int(shares * (sell_pct / 100))

                if shares_to_sell < 1:
                    shares_to_sell = 1

                logger.info(f"🎯 {symbol}: TAKE PROFIT HIT | Selling {shares_to_sell}/{shares} shares ({sell_pct:.0f}%) @ ${current_price:.2f} (+{profit_pct:.1f}%)")
                order = await asyncio.to_thread(alpaca_service.place_market_order, symbol, shares_to_sell, "sell")

                # Use the real fill price for P&L when available, not just the last quote
                exit_price = current_price
                if order and order.get('filled_avg_price'):
                    exit_price = float(order['filled_avg_price'])

                try:
                    from services.trade_history_service import trade_history
                    pnl = (exit_price - config['entry_price']) * shares_to_sell
                    await trade_history.log_trade({
                        'symbol': symbol,
                        'entry_price': config['entry_price'],
                        'exit_price': exit_price,
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

                config['partial_sold'] = True
                config['shares'] = shares - shares_to_sell

                if config.get('move_to_breakeven', True):
                    config['current_stop'] = config['entry_price']
                    logger.info(f"🎯 {symbol}: Stop moved to breakeven @ ${config['entry_price']:.2f}")

        except Exception as e:
            logger.error(f"Error handling partial take profit for {symbol}: {str(e)}")

    async def _check_bearish_crossover_exit(self, symbol: str, config: Dict, current_price: float, profit_pct: float, shares: int):
        """Exit early if position is negative AND bearish crossover detected (SMA20 crosses below SMA50)"""
        try:
            if profit_pct >= 0:
                return False

            result = await asyncio.to_thread(alpaca_service.get_bars_with_fallback, symbol, "5Min", 100)
            bars = [] if result.get('no_historical_data') else result.get('bars', [])
            try:
                from services.market_data_stream_service import market_data_stream
                await market_data_stream.subscribe([symbol])
                if bars:
                    bars = market_data_stream.merge_with_stream(symbol, bars, "5Min", 100)
            except Exception as e:
                logger.debug(f"{symbol}: real-time stream merge skipped: {e}")

            if not bars or len(bars) < 50:
                return False

            closes = [b['close'] for b in bars if b.get('close')]
            if len(closes) < 50:
                return False

            sma20_current = sum(closes[-20:]) / 20
            sma50_current = sum(closes[-50:]) / 50

            sma20_prev = sum(closes[-21:-1]) / 20
            sma50_prev = sum(closes[-51:-1]) / 50

            if sma20_prev >= sma50_prev and sma20_current < sma50_current:
                logger.info(f"📉 {symbol}: BEARISH CROSSOVER | SMA20 ({sma20_current:.2f}) crossed below SMA50 ({sma50_current:.2f}) while in loss ({profit_pct:.1f}%)")

                order = await asyncio.to_thread(alpaca_service.place_market_order, symbol, shares, "sell")
                exit_price = current_price
                if order and order.get('filled_avg_price'):
                    exit_price = float(order['filled_avg_price'])

                try:
                    from services.trade_history_service import trade_history
                    pnl = (exit_price - config['entry_price']) * shares
                    await trade_history.log_trade({
                        'symbol': symbol,
                        'entry_price': config['entry_price'],
                        'exit_price': exit_price,
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

            logger.info(f"🛑 {symbol}: STOP LOSS TRIGGERED | ${current_price:.2f}")

            remaining_shares = config['shares']
            order = await asyncio.to_thread(alpaca_service.place_market_order, symbol, remaining_shares, "sell")

            # Use the real fill price for P&L when available, not just the last quote
            exit_price = current_price
            if order and order.get('filled_avg_price'):
                exit_price = float(order['filled_avg_price'])
            loss_pct = ((exit_price - entry_price) / entry_price) * 100

            try:
                from services.trade_history_service import trade_history
                pnl = (exit_price - entry_price) * remaining_shares
                await trade_history.log_trade({
                    'symbol': symbol,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
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

            self.remove_position(symbol)

        except Exception as e:
            logger.error(f"Error executing stop loss for {symbol}: {str(e)}")

    def get_position_status(self, symbol: str) -> Dict:
        """Get current status of a monitored position"""
        return self.monitored_positions.get(symbol)

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
