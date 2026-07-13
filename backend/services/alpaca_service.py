from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, OrderClass
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockQuotesRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import os
import requests
import time
import threading
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

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

        # Determine paper vs live deliberately - never assume paper=True blindly.
        # ALPACA_PAPER env var takes precedence if explicitly set; otherwise infer
        # from the base URL. This makes going live an intentional, logged action.
        alpaca_paper_env = os.getenv('ALPACA_PAPER')
        if alpaca_paper_env is not None and alpaca_paper_env.strip() != '':
            paper = alpaca_paper_env.strip().lower() == 'true'
        else:
            paper = 'paper' in base_url.lower()
        self.paper = paper
        self.base_url = base_url

        if paper:
            logger.info(f"📝 PAPER TRADING MODE ACTIVE (base_url={base_url}) - no real money at risk")
        else:
            logger.warning("#" * 70)
            logger.warning("# ⚠️  LIVE TRADING MODE ACTIVE — REAL MONEY AT RISK  ⚠️")
            logger.warning(f"# base_url={base_url} | ALPACA_PAPER={alpaca_paper_env}")
            logger.warning("#" * 70)

        if not api_key or not secret_key:
            logger.warning("Alpaca API keys not configured")
            self.trading_client = None
            self.data_client = None
        else:
            self.trading_client = TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)
            self.data_client = StockHistoricalDataClient(api_key=data_api_key, secret_key=data_secret_key)
            data_source = "LIVE account" if os.getenv('ALPACA_DATA_API_KEY') else "same paper account (no ALPACA_DATA_API_KEY set)"
            logger.info(f"📊 Market data client: {data_source} | Trading client: {'PAPER' if paper else 'LIVE'} (orders only)")
    
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
    
    def get_bars(self, symbol: str, timeframe: str = "1Day", limit: int = 100):
        if not self.data_client:
            raise Exception("Alpaca API not configured")
        end_date = datetime.now()
        
        # Map timeframe string to TimeFrame object
        if timeframe == "1Day":
            start_date = end_date - timedelta(days=limit)
            tf = TimeFrame(1, TimeFrameUnit.Day)
        elif timeframe == "1Hour":
            start_date = end_date - timedelta(hours=limit)
            tf = TimeFrame(1, TimeFrameUnit.Hour)
        elif timeframe == "5Min":
            start_date = end_date - timedelta(minutes=limit * 5)
            tf = TimeFrame(5, TimeFrameUnit.Minute)
        elif timeframe == "1Min":
            start_date = end_date - timedelta(minutes=limit)
            tf = TimeFrame(1, TimeFrameUnit.Minute)
        else:
            start_date = end_date - timedelta(days=limit)
            tf = TimeFrame(1, TimeFrameUnit.Day)
        
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
        return result
    
    def get_bars_yahoo(self, symbol: str, interval: str = "5m", range_str: str = "1d"):
        """
        Get intraday chart data from Yahoo Finance.
        Much better coverage than Nasdaq for most stocks.
        Includes pre-market and after-hours data.
        
        Args:
            symbol: Stock ticker
            interval: 1m, 5m, 15m, 30m, 1h, 1d
            range_str: 1d, 5d, 1mo, etc.
        """
        try:
            # includePrePost=true gets pre-market and after-hours data
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={range_str}&includePrePost=true"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = self._http_session.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"Yahoo Finance returned {response.status_code} for {symbol}")
                return None
            
            data = response.json()
            result = data.get('chart', {}).get('result', [])
            
            if not result:
                return None
            
            chart_result = result[0]
            timestamps = chart_result.get('timestamp', [])
            quote = chart_result.get('indicators', {}).get('quote', [{}])[0]
            
            opens = quote.get('open', [])
            highs = quote.get('high', [])
            lows = quote.get('low', [])
            closes = quote.get('close', [])
            volumes = quote.get('volume', [])
            
            if not timestamps or not closes:
                return None
            
            # Convert to our standard bar format
            bars = []
            for i, ts in enumerate(timestamps):
                try:
                    close_price = closes[i] if i < len(closes) and closes[i] else None
                    if close_price is None:
                        continue
                    
                    bars.append({
                        'timestamp': datetime.fromtimestamp(ts).isoformat(),
                        'open': opens[i] if i < len(opens) and opens[i] else close_price,
                        'high': highs[i] if i < len(highs) and highs[i] else close_price,
                        'low': lows[i] if i < len(lows) and lows[i] else close_price,
                        'close': close_price,
                        'volume': int(volumes[i]) if i < len(volumes) and volumes[i] else 0
                    })
                except (ValueError, TypeError, IndexError):
                    continue
            
            if bars:
                valid_closes = [b['close'] for b in bars if b['close']]
                logger.info(f"Yahoo data for {symbol}: {len(bars)} bars, range ${min(valid_closes):.2f}-${max(valid_closes):.2f}")
            return bars if bars else None
            
        except Exception as e:
            logger.error(f"Error fetching Yahoo data for {symbol}: {e}")
            return None

    def get_bars_nasdaq(self, symbol: str):
        """
        Get intraday chart data from Nasdaq's free API.
        This provides consolidated market data (all exchanges), not just IEX.
        Use this as a fallback when Alpaca IEX data is incomplete.
        """
        try:
            url = f"https://api.nasdaq.com/api/quote/{symbol}/chart?assetclass=stocks"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            response = self._http_session.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"Nasdaq API returned {response.status_code} for {symbol}")
                return None
            
            data = response.json()
            chart_data = data.get('data', {}).get('chart', [])
            
            if not chart_data:
                return None
            
            # Convert Nasdaq format to our standard bar format
            bars = []
            for point in chart_data:
                try:
                    z_data = point.get('z') or {}  # Handle None z_data
                    price = float(point.get('y', 0))
                    timestamp_ms = point.get('x', 0)
                    time_str = z_data.get('dateTime', '') if z_data else ''
                    
                    # Skip invalid data points (price=0 or no timestamp)
                    if price <= 0 or not timestamp_ms:
                        continue
                    
                    # Nasdaq provides single price points, not OHLC
                    # We'll use the price for all OHLC values
                    bars.append({
                        'timestamp': datetime.fromtimestamp(timestamp_ms / 1000).isoformat() if timestamp_ms else None,
                        'time_label': time_str,
                        'open': price,
                        'high': price,
                        'low': price,
                        'close': price,
                        'volume': 0  # Nasdaq chart doesn't include volume
                    })
                except (ValueError, TypeError) as e:
                    continue
            
            if bars:
                logger.info(f"Nasdaq data for {symbol}: {len(bars)} points, range ${min(b['close'] for b in bars):.2f}-${max(b['close'] for b in bars):.2f}")
            else:
                logger.warning(f"Nasdaq returned no valid data for {symbol}")
            return bars if bars else None
            
        except Exception as e:
            logger.error(f"Error fetching Nasdaq data for {symbol}: {e}")
            return None
    
    def get_bars_with_fallback(self, symbol: str, timeframe: str = "5Min", limit: int = 100):
        """
        Get bar data with automatic fallback to Nasdaq if Alpaca IEX data is incomplete.
        ONLY returns REAL data - never generates fake/synthetic data.
        This ensures we always show accurate consolidated market data.
        
        For intraday timeframes (1Min, 5Min), uses Nasdaq for today + Alpaca daily for historical.
        """
        alpaca_bars = None
        
        # First try Alpaca
        try:
            alpaca_bars = self.get_bars(symbol, timeframe, limit)
        except Exception as e:
            logger.warning(f"{symbol}: Alpaca bars failed: {e}")
        
        # Check if Alpaca data looks complete AND recent enough to display.
        # IMPORTANT: price-similarity alone is not a reliable freshness
        # signal - a low-volatility stock (e.g. AAPL) can easily stay within
        # 5% of its current price for 15+ minutes, so a stale bar can pass
        # the price check while still being far behind real-time. Alpaca's
        # free-tier data plan embargoes the most recent ~15 minutes of bars
        # (this is a real Alpaca data-plan limit, not a bug), so we must
        # explicitly check the last bar's timestamp age and prefer the
        # Yahoo/Nasdaq fallback (which serves more current data) whenever
        # Alpaca's own data is too far behind "now" for intraday timeframes.
        if alpaca_bars and len(alpaca_bars) > 10:
            is_intraday = timeframe.startswith(("1M", "1m", "5M", "5m"))
            is_stale = False
            if is_intraday:
                try:
                    last_bar_ts = alpaca_bars[-1]['timestamp']
                    last_bar_dt = datetime.fromisoformat(last_bar_ts)
                    if last_bar_dt.tzinfo is None:
                        last_bar_dt = last_bar_dt.replace(tzinfo=timezone.utc)
                    age_minutes = (datetime.now(timezone.utc) - last_bar_dt).total_seconds() / 60
                    if age_minutes > 3:
                        is_stale = True
                        logger.warning(f"{symbol}: Alpaca's latest bar is {age_minutes:.1f} min old (free-tier data delay) - preferring fresher fallback source")
                except Exception:
                    pass  # If timestamp can't be parsed, fall through to price-match check

            if not is_stale:
                # Get the latest quote to verify data accuracy
                quote = self.get_latest_quote(symbol)
                if quote:
                    quote_price = (quote['bid_price'] + quote['ask_price']) / 2 if quote['bid_price'] > 0 and quote['ask_price'] > 0 else quote['bid_price'] or quote['ask_price']

                    # Check if any bar is within 5% of current quote price
                    bar_prices = [b['close'] for b in alpaca_bars[-20:]]  # Check last 20 bars
                    price_match = any(abs(p - quote_price) / quote_price < 0.05 for p in bar_prices)

                    if price_match:
                        # Alpaca data looks accurate AND recent
                        return {'bars': alpaca_bars, 'source': 'alpaca_iex'}
                    else:
                        logger.warning(f"{symbol}: Alpaca bars (${min(bar_prices):.2f}-${max(bar_prices):.2f}) don't match quote (${quote_price:.2f})")
        
        # Fallback to Yahoo Finance first (best free intraday data), then Nasdaq
        logger.info(f"{symbol}: Using Yahoo Finance fallback for intraday data")
        
        # Map timeframe to Yahoo interval - check start of string to avoid false matches
        if timeframe.startswith("1M") or timeframe.startswith("1m"):
            yahoo_interval = "1m"
            yahoo_range = "5d"  # Yahoo allows max 7 days for 1m data
        elif timeframe.startswith("5M") or timeframe.startswith("5m"):
            yahoo_interval = "5m"
            yahoo_range = "5d"  # 5 days of 5-min data
        elif timeframe.startswith("1D") or timeframe.startswith("1d"):
            yahoo_interval = "1d"
            yahoo_range = "1y"  # 1 year of daily data
        else:
            yahoo_interval = "5m"
            yahoo_range = "5d"
        
        fallback_bars = self.get_bars_yahoo(symbol, yahoo_interval, yahoo_range)
        
        # If Yahoo fails, try Nasdaq
        if not fallback_bars or len(fallback_bars) < 10:
            logger.info(f"{symbol}: Yahoo insufficient, trying Nasdaq fallback")
            nasdaq_bars = self.get_bars_nasdaq(symbol)
            if nasdaq_bars and len(nasdaq_bars) > len(fallback_bars or []):
                fallback_bars = nasdaq_bars
        
        if fallback_bars and len(fallback_bars) > 0:
            combined_bars = list(fallback_bars)  # Today's real data
            
            # CRITICAL: Add a real-time bar using the current quote to ensure chart is up-to-date
            try:
                quote = self.get_latest_quote(symbol)
                if quote:
                    current_price = (quote['bid_price'] + quote['ask_price']) / 2 if quote['bid_price'] > 0 and quote['ask_price'] > 0 else quote['bid_price'] or quote['ask_price']
                    
                    # Check if the last bar is stale (more than 5 minutes old)
                    now = datetime.now()
                    last_bar_time = combined_bars[-1].get('timestamp', '')
                    
                    # Add a current-time bar with the real-time quote price
                    realtime_bar = {
                        'timestamp': now.isoformat(),
                        'open': current_price,
                        'high': current_price,
                        'low': current_price,
                        'close': current_price,
                        'volume': 0,
                        'realtime': True  # Mark as real-time quote data
                    }
                    combined_bars.append(realtime_bar)
                    logger.info(f"{symbol}: Added real-time bar @ ${current_price:.2f}")
            except Exception as quote_err:
                logger.warning(f"{symbol}: Could not add real-time bar: {quote_err}")
            
            # Determine source for logging
            source = 'yahoo' if fallback_bars == combined_bars[:-1] or (len(combined_bars) > 10 and any(b.get('volume', 0) > 0 for b in combined_bars)) else 'nasdaq'
            
            # Return ONLY real data - no synthetic/fake historical data
            return {
                'bars': combined_bars[-limit:],
                'source': source,
                'real_bars': len(combined_bars),
            }
        
        # If BOTH Alpaca and Nasdaq fail, return only the real-time quote as a single data point
        # DO NOT generate fake/synthetic historical data
        logger.warning(f"{symbol}: No historical bar data available from Alpaca or Nasdaq")
        try:
            quote = self.get_latest_quote(symbol)
            if quote:
                current_price = (quote['bid_price'] + quote['ask_price']) / 2 if quote['bid_price'] > 0 and quote['ask_price'] > 0 else quote['bid_price'] or quote['ask_price']
                if current_price > 0:
                    # Return ONLY the real-time quote - no fake historical data
                    realtime_bar = {
                        'timestamp': datetime.now().isoformat(),
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