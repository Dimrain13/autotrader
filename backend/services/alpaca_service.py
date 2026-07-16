from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockQuotesRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from requests.adapters import HTTPAdapter
import os
import requests
import time
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class AlpacaRateLimiter:
    """
    Sliding-window rate limiter shared by every Alpaca Market Data API caller
    in this app (scanner batch scans, quotes, bars, news) so concurrent usage
    across services never collectively exceeds Alpaca's real account-level
    cap (200 requests/minute on the free/Basic data plan). Without this,
    bursty parallel scanning (10 ThreadPoolExecutor workers x 128+ batches)
    reliably triggers "too many requests" 429s and silently drops candidates.
    Capped below the real 200/min limit to leave headroom for other Alpaca
    calls happening at the same time (Trading page quotes, auto-trader).
    190 leaves a 10/min buffer for sliding-window timing jitter while still
    using ~95% of the Basic plan's real ceiling for faster scans.
    """
    def __init__(self, max_per_minute: int = 190):
        self.max_per_minute = max_per_minute
        self._timestamps = deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] > 60:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_per_minute:
                    self._timestamps.append(now)
                    return
                wait_time = 60 - (now - self._timestamps[0]) + 0.05
            time.sleep(max(wait_time, 0.05))


alpaca_rate_limiter = AlpacaRateLimiter(max_per_minute=190)


def mount_larger_connection_pool(session, pool_size: int = 60):
    """
    Alpaca's SDK clients each own a single shared `requests.Session()` used
    by every concurrent ThreadPoolExecutor worker. The default urllib3
    HTTPAdapter pool_maxsize is only 10, so 10 concurrent threads hitting
    the same host can exceed it and trigger noisy "Connection pool is full,
    discarding connection" warnings/churn. 60 comfortably covers the busiest
    observed burst (multi-tile dashboard x 4 timeframes + scanner's own
    6-12 concurrent workers hitting the same client). This is a purely
    local resource cap, independent of Alpaca's real 200/min rate limit.
    """
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount('https://', adapter)
    session.mount('http://', adapter)

class AlpacaService:
    def __init__(self):
        api_key = os.getenv('ALPACA_API_KEY')
        secret_key = os.getenv('ALPACA_SECRET_KEY')
        base_url = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

        # Market data (bars/quotes) is intentionally sourced from a SEPARATE
        # live-account key pair (better data plan/access than the free paper
        # account), while all actual order execution below still uses the
        # paper trading_client above. Falls back to the paper keys if the
        # live data keys aren't configured, so data fetches never silently
        # break if ALPACA_DATA_API_KEY is left unset.
        data_api_key = os.getenv('ALPACA_DATA_API_KEY') or api_key
        data_secret_key = os.getenv('ALPACA_DATA_SECRET_KEY') or secret_key

        # Reuse a single session for the Yahoo/Nasdaq fallback data paths -
        # connection pooling/keep-alive avoids a fresh TCP/TLS handshake per
        # symbol when scanning many stocks, meaningfully speeding up scans.
        self._http_session = requests.Session()

        # Asset info (company name) rarely changes - cache it so repeated
        # scans/news-lookups for the same symbol are instant instead of
        # re-querying Alpaca every time.
        self._asset_cache = {}
        self._asset_cache_lock = threading.Lock()
        self.ASSET_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours

        # Float/shares-outstanding data - real data only, sourced from SEC EDGAR
        # (free, no API key required, sourced from actual company filings).
        # Never fabricated: if SEC has no data for a symbol, callers get None
        # and must treat the float criterion as unknown/not-met rather than
        # guessing a number.
        self._float_cache = {}
        self._float_cache_lock = threading.Lock()
        self._sec_ticker_to_cik = None
        self._sec_ticker_map_fetched_at = 0
        self._sec_headers = {'User-Agent': 'MomentumX-Trading-App (contact: admin@momentumx.local)'}

        # Determine paper vs live TRADING ACCOUNT explicitly. This app now
        # maintains TWO separate, always-instantiated TradingClient objects -
        # one for each key pair - and switches which one actually executes
        # orders via set_trading_mode()/self.trading_mode, controlled by the
        # Settings page UI toggle (persisted in MongoDB by server.py, not by
        # this env var). ALPACA_PAPER is only used to decide the SAFE DEFAULT
        # on a completely fresh install (no persisted mode yet) - it can
        # never silently leave the app in live mode; every explicit switch
        # to live is a deliberate, logged, confirmed action.
        self.base_url = base_url
        self.trading_mode = 'paper'
        self.paper = True

        if not api_key or not secret_key:
            logger.warning("Alpaca PAPER trading keys not configured (ALPACA_API_KEY/ALPACA_SECRET_KEY)")
            self._paper_client = None
        else:
            self._paper_client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
            logger.info("📝 Paper trading client ready (no real money at risk)")

        # A LIVE trading client only counts as "available" if a genuinely
        # separate key pair is configured - falling back to the paper keys
        # for data (ALPACA_DATA_API_KEY unset) must NEVER enable live trading.
        live_api_key = os.getenv('ALPACA_DATA_API_KEY')
        live_secret_key = os.getenv('ALPACA_DATA_SECRET_KEY')
        if live_api_key and live_secret_key and live_api_key != api_key:
            self._live_client = TradingClient(api_key=live_api_key, secret_key=live_secret_key, paper=False)
            logger.info("🔴 Live trading client ready (available for manual use only, via the Settings toggle)")
        else:
            self._live_client = None

        # trading_client is an alias to whichever client is currently
        # active - reassigned by set_trading_mode(). Every order/position/
        # account method below reads through self.trading_client, so
        # switching modes requires touching nothing else in this file.
        self.trading_client = self._paper_client

        self.data_client = StockHistoricalDataClient(api_key=data_api_key, secret_key=data_secret_key) if (data_api_key and data_secret_key) else None
        if self.data_client:
            mount_larger_connection_pool(self.data_client._session)
        data_source = "LIVE account" if os.getenv('ALPACA_DATA_API_KEY') else "same paper account (no ALPACA_DATA_API_KEY set)"
        logger.info(f"📊 Market data client: {data_source}")

    def get_trading_mode_info(self) -> dict:
        """Current trading mode + which account(s) are actually configured."""
        return {
            "mode": self.trading_mode,
            "paper_available": self._paper_client is not None,
            "live_available": self._live_client is not None,
        }

    def set_trading_mode(self, mode: str):
        """
        Switch which real Alpaca account actually executes orders.
        Market data (self.data_client) is completely unaffected by this -
        it always uses the configured data keys regardless of trading mode.
        """
        if mode not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")

        if mode == "live":
            if not self._live_client:
                raise ValueError("Live trading keys not configured (ALPACA_DATA_API_KEY/ALPACA_DATA_SECRET_KEY)")
            self.trading_client = self._live_client
            self.trading_mode = "live"
            self.paper = False
            logger.warning("#" * 70)
            logger.warning("# 🔴 SWITCHED TO LIVE TRADING MODE — REAL MONEY AT RISK  ⚠️")
            logger.warning("#" * 70)
        else:
            if not self._paper_client:
                raise ValueError("Paper trading keys not configured (ALPACA_API_KEY/ALPACA_SECRET_KEY)")
            self.trading_client = self._paper_client
            self.trading_mode = "paper"
            self.paper = True
            logger.info("📝 Switched to PAPER trading mode - no real money at risk")
    
    def get_account(self):
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        account = self.trading_client.get_account()
        return {
            "account_number": account.account_number,
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "status": account.status,
            # Not all accounts (e.g. cash/non-margin) have day-trading buying power -
            # Alpaca returns None in that case. Default to 0 rather than crashing.
            "day_trading_buying_power": float(account.daytrading_buying_power) if account.daytrading_buying_power is not None else 0.0,
            "pattern_day_trader": bool(account.pattern_day_trader)
        }
    
    def _is_extended_hours(self):
        """Check if we're in extended trading hours (pre-market or after-hours)"""
        import pytz
        et = pytz.timezone('America/New_York')
        now_et = datetime.now(et)
        hour = now_et.hour
        minute = now_et.minute
        
        # Regular market hours: 9:30 AM - 4:00 PM ET
        regular_open = (hour == 9 and minute >= 30) or (hour > 9 and hour < 16)
        
        # Extended hours: 4:00 AM - 9:30 AM ET (pre-market) and 4:00 PM - 8:00 PM ET (after-hours)
        return not regular_open
    
    def place_market_order(self, symbol: str, qty: float, side: str = "buy"):
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        
        if self._is_extended_hours():
            # During extended hours, Alpaca only allows DAY limit orders
            # Get current quote to set a limit price that will fill immediately
            try:
                quote = self.get_latest_quote(symbol)
                if not quote:
                    raise Exception(f"No quote data available for {symbol} - cannot safely place an extended-hours limit order")
                ask_price = quote.get('ask_price', 0)
                bid_price = quote.get('bid_price', 0)

                # Max-slippage guard: the scanner targets illiquid $2-$20 low-float
                # names where a wide bid/ask spread means a "market-like" limit
                # order can fill far from the last trade. Reject outright rather
                # than blindly cross a dangerously wide spread.
                MAX_SPREAD_PCT = 8.0
                spread_pct = quote.get('spread_pct', 0)
                if ask_price > 0 and bid_price > 0 and spread_pct > MAX_SPREAD_PCT:
                    raise Exception(
                        f"Spread too wide for {symbol} during extended hours "
                        f"({spread_pct:.1f}% > {MAX_SPREAD_PCT}% max) - bid ${bid_price:.2f} / ask ${ask_price:.2f}. "
                        f"Refusing to place order to avoid excessive slippage."
                    )

                # Tightened buffer (was +/-10%, now +/-3%) - still aggressive enough
                # to fill fast-moving pre-market names without exposing the account
                # to double-digit slippage on a single fill.
                SLIPPAGE_BUFFER = 0.03
                if side.lower() == "buy":
                    # For buy: use ask price + buffer (aggressive to ensure fill in pre-market)
                    if ask_price > 0:
                        limit_price = round(ask_price * (1 + SLIPPAGE_BUFFER), 2)
                    elif bid_price > 0:
                        limit_price = round(bid_price * (1 + SLIPPAGE_BUFFER), 2)
                    else:
                        raise Exception(f"No liquidity for {symbol} during extended hours - no bid or ask available")
                else:
                    # For sell: use bid price - buffer (aggressive to ensure fill in pre-market)
                    if bid_price > 0:
                        limit_price = round(bid_price * (1 - SLIPPAGE_BUFFER), 2)
                    elif ask_price > 0:
                        limit_price = round(ask_price * (1 - SLIPPAGE_BUFFER), 2)
                    else:
                        raise Exception(f"No liquidity for {symbol} during extended hours - no bid or ask available")
                
                if limit_price <= 0:
                    raise Exception(f"Unable to get valid quote for {symbol} during extended hours")
                
                logger.info(f"📊 Extended hours: {side.upper()} {qty} {symbol} - using limit order @ ${limit_price:.2f} (ask: ${ask_price}, bid: ${bid_price})")
                
                order_data = LimitOrderRequest(
                    symbol=symbol,
                    qty=qty,
                    side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                    extended_hours=True
                )
                
                order = self.trading_client.submit_order(order_data=order_data)
                order_id = str(order.id)
                
                # Wait briefly and check if order filled (extended hours orders may not fill instantly)
                import time
                max_wait_seconds = 5
                check_interval = 0.5
                elapsed = 0
                
                while elapsed < max_wait_seconds:
                    time.sleep(check_interval)
                    elapsed += check_interval
                    
                    # Check order status
                    try:
                        updated_order = self.trading_client.get_order_by_id(order_id)
                        if updated_order.status.value == 'filled':
                            logger.info(f"✅ Extended hours order filled: {symbol} @ ${updated_order.filled_avg_price}")
                            return {
                                "order_id": order_id,
                                "symbol": updated_order.symbol,
                                "qty": float(updated_order.qty) if updated_order.qty else None,
                                "side": updated_order.side.value,
                                "status": updated_order.status.value,
                                "filled_avg_price": float(updated_order.filled_avg_price) if updated_order.filled_avg_price else None,
                                "created_at": updated_order.created_at.isoformat() if updated_order.created_at else None
                            }
                        elif updated_order.status.value in ['canceled', 'rejected', 'expired']:
                            raise Exception(f"Order {updated_order.status.value}: {symbol}")
                    except Exception as check_err:
                        if 'Order' in str(check_err) and ('canceled' in str(check_err) or 'rejected' in str(check_err)):
                            raise
                        # Continue waiting
                        pass
                
                # Order didn't fill in time - cancel it
                try:
                    self.trading_client.cancel_order_by_id(order_id)
                    logger.warning(f"⚠️ Extended hours order not filled, cancelled: {symbol} @ ${limit_price:.2f}")
                except Exception as cancel_err:
                    logger.error(f"Failed to cancel unfilled order {order_id}: {cancel_err}")
                
                raise Exception(f"Extended hours order not filled - price moved too fast. Limit was ${limit_price:.2f}, order cancelled. Try again or wait for market hours.")
                
            except Exception as e:
                logger.error(f"Extended hours order error for {symbol}: {e}")
                raise
        else:
            # Regular hours: use standard market order
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
        
            order = self.trading_client.submit_order(order_data=order_data)
            return {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty) if order.qty else None,
                "side": order.side.value,
                "status": order.status.value,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "created_at": order.created_at.isoformat() if order.created_at else None
            }
    
    def place_bracket_order(self, symbol: str, qty: float, stop_loss_price: float, take_profit_price: float):
        """
        Place a bracket order with automatic stop loss and take profit
        
        Args:
            symbol: Stock ticker
            qty: Number of shares
            stop_loss_price: Price to trigger stop loss
            take_profit_price: Price to trigger take profit
            
        Returns:
            Dict with order details
        """
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        
        # Use GTC for extended hours, DAY for regular hours
        # Note: Bracket orders have limited support during extended hours
        time_in_force = TimeInForce.GTC if self._is_extended_hours() else TimeInForce.DAY
        
        # Ensure prices are rounded to 2 decimal places (penny increments) - Alpaca requirement
        stop_loss_price = round(stop_loss_price, 2)
        take_profit_price = round(take_profit_price, 2)
        
        # Create bracket order (market buy with stop loss and take profit)
        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=time_in_force,
            order_class=OrderClass.BRACKET,
            stop_loss={'stop_price': stop_loss_price},
            take_profit={'limit_price': take_profit_price}
        )
        
        try:
            order = self.trading_client.submit_order(order_data=order_data)
            logger.info(f"✅ Bracket order placed: {symbol} - Stop: ${stop_loss_price:.2f}, Target: ${take_profit_price:.2f}")
            
            return {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty) if order.qty else None,
                "side": order.side.value,
                "status": order.status.value,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
                "order_class": "bracket"
            }
        except Exception as e:
            logger.error(f"Failed to place bracket order for {symbol}: {str(e)}")
            raise
    
    def get_position(self, symbol: str):
        """Get a single position by symbol"""
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        try:
            pos = self.trading_client.get_open_position(symbol)
            return {
                'symbol': pos.symbol,
                'qty': float(pos.qty),
                'avg_entry_price': float(pos.avg_entry_price),
                'current_price': float(pos.current_price),
                'unrealized_pl': float(pos.unrealized_pl),
                'side': 'long' if float(pos.qty) > 0 else 'short'
            }
        except Exception as e:
            logger.warning(f"Position not found for {symbol}: {e}")
            return None
    
    def get_positions(self):
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        positions = self.trading_client.get_all_positions()
        
        # Get fresh quotes for all position symbols to ensure accurate current prices
        position_symbols = [pos.symbol for pos in positions]
        fresh_quotes = {}
        if position_symbols and self.data_client:
            try:
                fresh_quotes = self.get_quotes(position_symbols)
            except Exception as e:
                logger.warning(f"Failed to fetch fresh quotes: {e}")
        
        result = []
        for pos in positions:
            symbol = pos.symbol
            qty = float(pos.qty)
            entry_price = float(pos.avg_entry_price)
            alpaca_current_price = float(pos.current_price)
            
            # Use fresh quote if available and valid
            current_price = alpaca_current_price  # Default to Alpaca's price
            if symbol in fresh_quotes:
                quote = fresh_quotes[symbol]
                bid = quote['bid_price']
                ask = quote['ask_price']
                
                # Handle cases where bid or ask is zero (illiquid/extended hours)
                if bid > 0 and ask > 0:
                    # Both valid - use midpoint
                    current_price = (bid + ask) / 2
                elif bid > 0:
                    # Only bid available - use bid
                    current_price = bid
                elif ask > 0:
                    # Only ask available - use ask
                    current_price = ask
                # else: keep Alpaca's current_price
                
                logger.debug(f"{symbol}: bid=${bid:.2f}, ask=${ask:.2f}, using ${current_price:.2f}")
            
            # Recalculate P&L with fresh price
            unrealized_pl = (current_price - entry_price) * qty
            unrealized_plpc = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            
            result.append({
                "symbol": symbol,
                "qty": qty,
                "avg_entry_price": entry_price,
                "market_value": current_price * qty,
                "current_price": round(current_price, 2),
                "unrealized_pl": round(unrealized_pl, 2),
                "unrealized_plpc": round(unrealized_plpc, 2),
                "side": pos.side,
                "cost_basis": float(pos.cost_basis) if hasattr(pos, 'cost_basis') else None,
            })
        
        return result
    
    def get_position_entry_time(self, symbol: str):
        """Get the entry time for a position by looking at filled buy orders"""
        if not self.trading_client:
            return None
        try:
            # Get recent filled orders for this symbol
            request = GetOrdersRequest(
                status=OrderStatus.FILLED,
                limit=100,
                symbols=[symbol]
            )
            orders = self.trading_client.get_orders(request)
            
            # Find the most recent buy order for this symbol
            buy_orders = [o for o in orders if o.side.value == 'buy' and o.symbol == symbol]
            if buy_orders:
                # Sort by filled_at and get the most recent
                buy_orders.sort(key=lambda x: x.filled_at if x.filled_at else x.created_at, reverse=True)
                order = buy_orders[0]
                return order.filled_at.isoformat() if order.filled_at else order.created_at.isoformat()
        except Exception as e:
            logger.error(f"Error getting entry time for {symbol}: {e}")
        return None
    
    def get_order(self, order_id: str):
        """Get a single order by ID"""
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        try:
            order = self.trading_client.get_order_by_id(order_id)
            return {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty) if order.qty else None,
                "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                "side": order.side.value,
                "status": order.status.value,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "created_at": order.created_at.isoformat() if order.created_at else None
            }
        except Exception as e:
            logger.warning(f"Could not get order {order_id}: {e}")
            return None

    def get_orders(self, status="all", limit=50):
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        request = GetOrdersRequest(
            status=OrderStatus(status) if status != "all" else None,
            limit=limit
        )
        orders = self.trading_client.get_orders(request)
        return [
            {
                "order_id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty) if order.qty else None,
                "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                "side": order.side.value,
                "status": order.status.value,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
                "created_at": order.created_at.isoformat() if order.created_at else None
            }
            for order in orders
        ]
    
    def cancel_order(self, order_id: str):
        """Cancel an order by ID"""
        if not self.trading_client:
            raise Exception("Alpaca API not configured")
        
        try:
            self.trading_client.cancel_order_by_id(order_id)
            logger.info(f"Order {order_id} cancelled successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {str(e)}")
            raise

    def cancel_all_orders(self):
        """Cancel all open orders. Returns the number of orders cancelled."""
        if not self.trading_client:
            raise Exception("Alpaca API not configured")

        try:
            responses = self.trading_client.cancel_orders()
            count = len(responses) if responses else 0
            logger.info(f"Cancelled {count} open order(s)")
            return count
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {str(e)}")
            raise
    
    def get_asset(self, symbol: str):
        """Get asset information including company name (24h TTL cache - company names don't change)"""
        if not self.trading_client:
            raise Exception("Alpaca API not configured")

        with self._asset_cache_lock:
            cached = self._asset_cache.get(symbol)
        if cached:
            cached_at, cached_result = cached
            if time.time() - cached_at < self.ASSET_CACHE_TTL_SECONDS:
                return cached_result

        try:
            asset = self.trading_client.get_asset(symbol)
            result = {
                'symbol': asset.symbol,
                'name': asset.name if hasattr(asset, 'name') else None,
                'exchange': asset.exchange if hasattr(asset, 'exchange') else None,
                'asset_class': asset.asset_class if hasattr(asset, 'asset_class') else None
            }
            with self._asset_cache_lock:
                self._asset_cache[symbol] = (time.time(), result)
            return result
        except Exception as e:
            logger.error(f"Failed to get asset info for {symbol}: {str(e)}")
            return {'symbol': symbol, 'name': None}

    def _get_sec_cik(self, symbol: str):
        """Lazily fetch and cache the SEC ticker->CIK mapping (refreshed every 24h)."""
        now = time.time()
        with self._float_cache_lock:
            needs_refresh = self._sec_ticker_to_cik is None or (now - self._sec_ticker_map_fetched_at) > self.ASSET_CACHE_TTL_SECONDS
        if needs_refresh:
            with self._float_cache_lock:
                # Re-check inside the lock in case another thread already refreshed it
                if self._sec_ticker_to_cik is None or (time.time() - self._sec_ticker_map_fetched_at) > self.ASSET_CACHE_TTL_SECONDS:
                    try:
                        resp = self._http_session.get(
                            'https://www.sec.gov/files/company_tickers.json',
                            headers=self._sec_headers, timeout=15
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            self._sec_ticker_to_cik = {v['ticker']: v['cik_str'] for v in data.values()}
                            self._sec_ticker_map_fetched_at = time.time()
                        else:
                            logger.warning(f"SEC ticker map fetch returned {resp.status_code}")
                    except Exception as e:
                        logger.warning(f"Failed to fetch SEC ticker map: {e}")
        if not self._sec_ticker_to_cik:
            return None
        return self._sec_ticker_to_cik.get(symbol)

    def get_float_data(self, symbol: str):
        """
        Get real shares-outstanding data for a symbol from SEC EDGAR company
        filings (free, no API key, real data - never fabricated).

        Used as a conservative proxy for float: actual free float is always
        <= total shares outstanding, so this can only make the low-float
        scanner criterion stricter, never falsely pass a large-float stock.

        Returns None if SEC has no data for this symbol - callers must treat
        that as "unknown", never guess/estimate a number.
        """
        with self._float_cache_lock:
            cached = self._float_cache.get(symbol)
        if cached:
            cached_at, cached_result = cached
            if time.time() - cached_at < self.ASSET_CACHE_TTL_SECONDS:
                return cached_result

        result = None
        try:
            cik = self._get_sec_cik(symbol)
            if cik:
                for taxonomy, concept in [
                    ('dei', 'EntityCommonStockSharesOutstanding'),
                    ('us-gaap', 'CommonStockSharesOutstanding'),
                ]:
                    url = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{taxonomy}/{concept}.json'
                    resp = self._http_session.get(url, headers=self._sec_headers, timeout=10)
                    if resp.status_code == 200:
                        facts = resp.json().get('units', {}).get('shares', [])
                        # Use the most recent fact with a sane positive value -
                        # some filings report a stale/zero value for certain
                        # share classes (e.g. warrants), which would otherwise
                        # look like a fake "ultra-low float" pass.
                        valid_facts = [f for f in facts if f.get('val', 0) > 0]
                        if valid_facts:
                            result = {
                                'shares_outstanding': int(valid_facts[-1]['val']),
                                'source': 'sec_edgar'
                            }
                            break
        except Exception as e:
            logger.debug(f"SEC EDGAR float lookup failed for {symbol}: {e}")

        with self._float_cache_lock:
            self._float_cache[symbol] = (time.time(), result)
        return result
    
    def get_quotes(self, symbols):
        if not self.data_client:
            raise Exception("Alpaca API not configured")
        alpaca_rate_limiter.acquire()
        request = StockLatestQuoteRequest(symbol_or_symbols=symbols)
        quotes = self.data_client.get_stock_latest_quote(request)
        result = {}
        for symbol in symbols:
            if symbol in quotes:
                quote = quotes[symbol]
                bid = float(quote.bid_price)
                ask = float(quote.ask_price)
                
                # Calculate spread
                spread = 0
                spread_pct = 0
                midpoint = 0
                if bid > 0 and ask > 0:
                    spread = ask - bid
                    midpoint = (bid + ask) / 2
                    spread_pct = (spread / midpoint) * 100 if midpoint > 0 else 0
                
                result[symbol] = {
                    "ask_price": ask,
                    "bid_price": bid,
                    "ask_size": int(quote.ask_size),
                    "bid_size": int(quote.bid_size),
                    "spread": round(spread, 4),
                    "spread_pct": round(spread_pct, 2),
                    "midpoint": round(midpoint, 4)
                }
        return result
    
    def get_latest_quote(self, symbol: str):
        """Get latest quote for a single symbol with spread calculation"""
        if not self.data_client:
            raise Exception("Alpaca API not configured")
        alpaca_rate_limiter.acquire()
        request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
        quotes = self.data_client.get_stock_latest_quote(request)
        if symbol in quotes:
            quote = quotes[symbol]
            bid = float(quote.bid_price)
            ask = float(quote.ask_price)
            
            # Calculate spread
            spread = 0
            spread_pct = 0
            midpoint = 0
            if bid > 0 and ask > 0:
                spread = ask - bid
                midpoint = (bid + ask) / 2
                spread_pct = (spread / midpoint) * 100 if midpoint > 0 else 0
            
            return {
                "ask_price": ask,
                "bid_price": bid,
                "ask_size": int(quote.ask_size),
                "bid_size": int(quote.bid_size),
                "spread": round(spread, 4),
                "spread_pct": round(spread_pct, 2),
                "midpoint": round(midpoint, 4)
            }
        return None
    
    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100, since: Optional[datetime] = None):
        if not self.data_client:
            raise Exception("Alpaca API not configured")
        alpaca_rate_limiter.acquire()
        end_date = datetime.now()
        
        # Map timeframe string to TimeFrame object
        if timeframe == "1Day":
            start_date = end_date - timedelta(days=limit)
            tf = TimeFrame(1, TimeFrameUnit.Day)
        elif timeframe == "1Hour":
            start_date = end_date - timedelta(hours=limit)
            tf = TimeFrame(1, TimeFrameUnit.Hour)
        elif timeframe == "5Min":
            # ~78 5-min bars per regular trading day. Look back enough
            # CALENDAR days (not literal elapsed minutes) to guarantee
            # `limit` actual bars exist, padding generously for weekends/
            # holidays that may fall inside the window.
            trading_days_needed = max(1, -(-limit // 78))  # ceil division
            start_date = end_date - timedelta(days=trading_days_needed * 2 + 3)
            tf = TimeFrame(5, TimeFrameUnit.Minute)
        elif timeframe == "1Min":
            # ~390 1-min bars per regular trading day - same calendar-day padding.
            trading_days_needed = max(1, -(-limit // 390))  # ceil division
            start_date = end_date - timedelta(days=trading_days_needed * 2 + 3)
            tf = TimeFrame(1, TimeFrameUnit.Minute)
        else:
            start_date = end_date - timedelta(days=limit)
            tf = TimeFrame(1, TimeFrameUnit.Day)

        # Incremental refresh: caller already has bars up to `since`, so only
        # ask Alpaca for what's newer instead of re-pulling the whole window -
        # much smaller/faster request on every periodic UI poll.
        if since is not None:
            start_date = since

        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start_date
            # Deliberately no `end` param: passing an explicit end=now() makes
            # Alpaca's free-tier data plan hard-reject the WHOLE request with
            # "subscription does not permit querying recent SIP data" (even
            # though older data in the same range is available). Omitting
            # `end` lets Alpaca silently serve everything it's allowed to
            # (respecting its own real-time embargo internally) instead of
            # erroring out and forcing a fallback to Yahoo every time.
        )
        bars = self.data_client.get_stock_bars(request)
        df = bars.df
        if df.empty:
            return []
        
        df = df.reset_index()
        result = []
        for _, row in df.iterrows():
            result.append({
                "timestamp": row['timestamp'].isoformat() if hasattr(row, 'timestamp') else None,
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": int(row['volume'])
            })

        # The calendar-day padding above can return more bars than asked for
        # (e.g. extra trading days inside the weekend/holiday buffer) - trim
        # to the most RECENT `limit` bars, not the oldest ones in the window.
        # Skip this trim for incremental `since` requests - the caller wants
        # everything newer than `since`, not just the tail `limit` of it.
        if since is None and timeframe in ("1Min", "5Min") and len(result) > limit:
            result = result[-limit:]

        return result
    
    def get_bars_with_fallback(self, symbol: str, timeframe: str = "5Min", limit: int = 100, since: Optional[datetime] = None):
        """
        Get bar data - ALPACA ONLY (the real production market-data feed).

        No Yahoo/Nasdaq fallback: that was a stopgap used during testing,
        before the real-time Alpaca WebSocket stream existed. Now that the
        stream (services/market_data_stream_service.py) fills the free-tier
        REST embargo's ~15 minute gap with genuine live Alpaca data - merged
        in by callers via market_data_stream.merge_with_stream() - a second
        data PROVIDER is no longer needed or wanted. If Alpaca has no
        historical bars at all (rate-limited, unknown symbol, etc.), this
        returns an explicit "no data" response rather than ever mixing in
        data from a different provider.
        """
        try:
            alpaca_bars = self.get_bars(symbol, timeframe, limit, since)
        except Exception as e:
            logger.warning(f"{symbol}: Alpaca bars failed: {e}")
            alpaca_bars = None

        if alpaca_bars:
            return {'bars': alpaca_bars, 'source': 'alpaca_iex'}

        # No historical bars from Alpaca - fall back to just the real-time
        # Alpaca quote (still Alpaca, still real data, just a single point)
        # rather than showing a completely blank chart.
        logger.warning(f"{symbol}: No historical bar data available from Alpaca")
        try:
            quote = self.get_latest_quote(symbol)
            if quote:
                current_price = (quote['bid_price'] + quote['ask_price']) / 2 if quote['bid_price'] > 0 and quote['ask_price'] > 0 else quote['bid_price'] or quote['ask_price']
                if current_price > 0:
                    realtime_bar = {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'open': current_price,
                        'high': current_price,
                        'low': current_price,
                        'close': current_price,
                        'volume': 0,
                        'realtime': True
                    }
                    logger.info(f"{symbol}: Returning real-time quote only @ ${current_price:.2f} - NO historical data available")
                    return {
                        'bars': [realtime_bar],
                        'source': 'realtime_quote_only',
                        'real_bars': 1,
                        'no_historical_data': True,
                        'warning': 'NO HISTORICAL DATA AVAILABLE - Only showing current price'
                    }
        except Exception as e:
            logger.error(f"{symbol}: Failed to get quote: {e}")

        # No data at all
        return {
            'bars': [],
            'source': 'none',
            'no_historical_data': True,
            'warning': 'NO DATA AVAILABLE'
        }
    
alpaca_service = AlpacaService()