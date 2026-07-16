"""
Real-time Alpaca WebSocket market data streaming.

Replaces REST polling (subject to Alpaca's free-tier ~15 minute embargo on
recent bars/quotes) with a persistent WebSocket connection to Alpaca's IEX
real-time feed, so the "First Pullback" auto-trader strategy and the
Trading page can react to genuinely live price ticks instead of stale data.

ALWAYS authenticates with the LIVE/data key pair (ALPACA_DATA_API_KEY /
ALPACA_DATA_SECRET_KEY, falling back to the paper keys only if unset) -
this matches how alpaca_service.py already sources historical market data,
and is independent of which account (paper vs live) is currently executing
orders. Streaming market data access is never affected by the paper/live
trading-mode toggle.

Alpaca free-tier limits (see docs.alpaca.markets/docs/streaming-market-data):
- Only the IEX feed is available (not full SIP consolidated tape)
- Only 30 concurrent trade+quote symbol subscriptions per connection
  (minute-bar subscriptions are NOT limited) - enforced here via
  MAX_TRADE_QUOTE_SYMBOLS so a busy scanner day never breaks the stream.
"""
import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import websockets

logger = logging.getLogger(__name__)

ALPACA_STREAM_URL = "wss://stream.data.alpaca.markets/v2/iex"
MAX_BARS_PER_SYMBOL = 300  # ~5 hours of 1-min bars per symbol, in-memory
MAX_TICKS_PER_SYMBOL = 3000  # raw trade ticks kept for 10-sec bar construction + large-trade detection
MAX_LARGE_TRADES_PER_SYMBOL = 50
TRADE_SIZE_HISTORY_LEN = 100  # rolling window used to compute the dynamic "large trade" threshold
LARGE_TRADE_MIN_SIZE = 500  # absolute floor regardless of a symbol's rolling average
LARGE_TRADE_MULTIPLIER = 5  # a print is "large" if size >= 5x this symbol's recent average
MAX_TRADE_QUOTE_SYMBOLS = 25  # stay under Alpaca's free-tier 30-symbol cap


def _to_epoch(ts) -> Optional[float]:
    """Normalize an Alpaca/REST bar timestamp (str or number) to a UTC epoch
    float. Naive datetimes are treated as UTC (consistent with how the rest
    of this app already stores/compares timestamps)."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            s = ts.replace('Z', '+00:00')
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return None
    return None


class MarketDataStreamManager:
    def __init__(self):
        self.api_key = os.getenv('ALPACA_DATA_API_KEY') or os.getenv('ALPACA_API_KEY')
        self.secret_key = os.getenv('ALPACA_DATA_SECRET_KEY') or os.getenv('ALPACA_SECRET_KEY')
        self.ws_url = ALPACA_STREAM_URL

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._outgoing: asyncio.Queue = asyncio.Queue()
        self._listeners: Set[asyncio.Queue] = set()

        # What we've told Alpaca we're subscribed to (survives reconnects -
        # re-sent immediately after every re-auth).
        self._subscribed_bars: Set[str] = set()
        self._subscribed_tq: Set[str] = set()  # trades + quotes (capped)
        self._tq_order: deque = deque()  # insertion order, for FIFO eviction of non-priority symbols
        self._tq_priority: Set[str] = set()  # symbols that must always keep a live trade/quote slot
        # (open positions + whatever chart is currently on-screen) - never evicted to make room for a scanner-only symbol.
        self._sub_lock = asyncio.Lock()

        # In-memory latest-data caches - always fresher than REST for
        # anything actively subscribed.
        self.latest_quotes: Dict[str, dict] = {}
        self.latest_trades: Dict[str, dict] = {}
        self.bar_buffers: Dict[str, deque] = {}

        # Raw trade ticks (for self-constructed sub-minute bars, since
        # Alpaca's Bars API has no "seconds" timeframe) + large block-trade
        # detection (a real-data proxy for order-flow support/resistance,
        # since true Level 2 depth isn't available on the IEX/free tier).
        self.trade_ticks: Dict[str, deque] = {}
        self._trade_size_history: Dict[str, deque] = {}
        self.large_trades: Dict[str, deque] = {}

        self.connected = False
        self.authenticated = False
        self._last_message_at = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if not self.is_configured:
            logger.warning("⚠️ Market data stream NOT started - ALPACA_DATA_API_KEY/SECRET (or ALPACA_API_KEY/SECRET) not configured")
            return
        if os.getenv('MARKET_STREAM_ENABLED', 'true').lower() == 'false':
            # Alpaca only allows ONE active WebSocket connection per API key
            # pair at a time. Set MARKET_STREAM_ENABLED=false on any
            # environment (e.g. a dev/preview instance) that shares the same
            # ALPACA_DATA_API_KEY with a production deployment you don't want
            # to contest the connection slot with (causes repeated "406
            # connection limit exceeded" / "401 not authenticated" errors on
            # whichever side loses the race).
            logger.info("📡 Market data stream disabled via MARKET_STREAM_ENABLED=false")
            return
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_forever())
            logger.info(f"📡 Market data stream starting → {self.ws_url}")

    async def stop(self):
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run_forever(self):
        backoff = 5
        while not self._stop_event.is_set():
            consumer = producer = None
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.connected = True
                    await self._authenticate(ws)

                    async with self._sub_lock:
                        resub_bars = list(self._subscribed_bars)
                        resub_tq = list(self._subscribed_tq)
                    if resub_bars or resub_tq:
                        await self._queue_subscribe(resub_bars, resub_tq)
                        logger.info(f"📡 Re-subscribed after reconnect: {len(resub_bars)} bar symbols, {len(resub_tq)} trade/quote symbols")

                    consumer = asyncio.create_task(self._consume(ws))
                    producer = asyncio.create_task(self._produce(ws))
                    await asyncio.wait({consumer, producer}, return_when=asyncio.FIRST_COMPLETED)
                    backoff = 5
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"📡 Market data stream error/disconnect: {e} - reconnecting in {backoff}s")
            finally:
                # Always cancel + await the consumer/producer tasks on every
                # exit path (normal, exception, or outer cancellation) so
                # they never become orphaned "Task exception was never
                # retrieved" warnings on shutdown/reconnect.
                for t in (consumer, producer):
                    if t and not t.done():
                        t.cancel()
                for t in (consumer, producer):
                    if t:
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass
                self.connected = False
                self.authenticated = False

            if self._stop_event.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _authenticate(self, ws):
        await ws.send(json.dumps({"action": "auth", "key": self.api_key, "secret": self.secret_key}))

    async def _consume(self, ws):
        async for raw in ws:
            self._last_message_at = time.time()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    await self._handle_message(item)

    async def _produce(self, ws):
        while True:
            msg = await self._outgoing.get()
            await ws.send(json.dumps(msg))

    async def _handle_message(self, msg: dict):
        msg_type = msg.get("T")

        if msg_type == "success":
            if msg.get("msg") == "authenticated":
                self.authenticated = True
                logger.info("✅ Market data stream authenticated with Alpaca (IEX real-time feed)")
            return
        if msg_type == "error":
            logger.error(f"📡 Alpaca stream error: {msg}")
            return
        if msg_type == "subscription":
            return

        now = time.time()
        if msg_type == "t":
            symbol = msg.get("S")
            price = msg.get("p")
            size = msg.get("s")
            if symbol and price is not None and size:
                self.latest_trades[symbol] = {
                    "price": price, "size": size,
                    "timestamp": msg.get("t"), "received_at": now,
                }

                tick_buf = self.trade_ticks.setdefault(symbol, deque(maxlen=MAX_TICKS_PER_SYMBOL))
                tick_buf.append({"price": price, "size": size, "timestamp": msg.get("t")})

                # Tick rule (Lee-Ready): compare the trade price to the
                # quote in effect at the time to infer buyer/seller
                # aggression - the closest real-data proxy to true order-flow
                # without paid Level 2 depth-of-book access.
                quote = self.latest_quotes.get(symbol)
                side = "neutral"
                if quote and quote.get("bid_price") and quote.get("ask_price"):
                    if price >= quote["ask_price"]:
                        side = "buy"
                    elif price <= quote["bid_price"]:
                        side = "sell"

                size_hist = self._trade_size_history.setdefault(symbol, deque(maxlen=TRADE_SIZE_HISTORY_LEN))
                avg_size = (sum(size_hist) / len(size_hist)) if size_hist else size
                size_hist.append(size)

                if size >= max(LARGE_TRADE_MIN_SIZE, avg_size * LARGE_TRADE_MULTIPLIER):
                    large_buf = self.large_trades.setdefault(symbol, deque(maxlen=MAX_LARGE_TRADES_PER_SYMBOL))
                    large_buf.append({
                        "price": price, "size": size, "side": side,
                        "timestamp": msg.get("t"), "avg_size_at_time": round(avg_size, 1),
                    })
        elif msg_type == "q":
            symbol = msg.get("S")
            if symbol:
                bid = msg.get("bp") or 0
                ask = msg.get("ap") or 0
                spread = ask - bid if (bid and ask) else 0
                midpoint = (bid + ask) / 2 if (bid and ask) else 0
                self.latest_quotes[symbol] = {
                    "bid_price": bid, "ask_price": ask,
                    "bid_size": msg.get("bs", 0), "ask_size": msg.get("as", 0),
                    "spread": round(spread, 4),
                    "spread_pct": round((spread / midpoint) * 100, 2) if midpoint else 0,
                    "midpoint": round(midpoint, 4),
                    "timestamp": msg.get("t"), "received_at": now,
                }
        elif msg_type == "b":
            symbol = msg.get("S")
            if symbol:
                bar = {
                    "timestamp": msg.get("t"),
                    "open": msg.get("o"), "high": msg.get("h"),
                    "low": msg.get("l"), "close": msg.get("c"),
                    "volume": msg.get("v", 0) or 0,
                }
                buf = self.bar_buffers.setdefault(symbol, deque(maxlen=MAX_BARS_PER_SYMBOL))
                buf.append(bar)

        await self._broadcast(msg)

    async def _broadcast(self, data):
        for q in list(self._listeners):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------
    # Consumer registration (used by the /api/ws/market-data endpoint)
    # ------------------------------------------------------------------
    def register_listener(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._listeners.add(q)
        return q

    def unregister_listener(self, q: asyncio.Queue):
        self._listeners.discard(q)

    # ------------------------------------------------------------------
    # Dynamic subscription (scanner/auto-trader/frontend driven)
    # ------------------------------------------------------------------
    async def subscribe(self, symbols: List[str], priority: bool = False):
        """
        Add symbols to the live stream (idempotent, safe to call repeatedly).
        Bar subscriptions are unlimited; trade/quote subscriptions are
        capped at MAX_TRADE_QUOTE_SYMBOLS to respect Alpaca's free-tier limit.

        `priority=True` marks symbols that must ALWAYS have a live trade/quote
        slot - open positions and whatever chart is currently on-screen. If
        the cap is already full of scanner-only (non-priority) symbols, the
        oldest one is evicted to make room instead of the priority symbol
        silently never getting real tick data (this was the root cause of
        "10-second chart never loads" - the selected symbol could lose the
        race for a slot to whatever scanner candidates streamed in first).
        """
        if not self.is_configured or not symbols:
            return
        new_bars, new_tq, evicted = [], [], []
        async with self._sub_lock:
            for s in symbols:
                s = (s or "").upper().strip()
                if not s:
                    continue
                if priority:
                    self._tq_priority.add(s)
                if s not in self._subscribed_bars:
                    self._subscribed_bars.add(s)
                    new_bars.append(s)
                if s in self._subscribed_tq:
                    continue
                if len(self._subscribed_tq) < MAX_TRADE_QUOTE_SYMBOLS:
                    self._subscribed_tq.add(s)
                    self._tq_order.append(s)
                    new_tq.append(s)
                elif priority:
                    victim = next((c for c in self._tq_order if c not in self._tq_priority), None)
                    if victim:
                        self._tq_order.remove(victim)
                        self._subscribed_tq.discard(victim)
                        evicted.append(victim)
                        self._subscribed_tq.add(s)
                        self._tq_order.append(s)
                        new_tq.append(s)
                    else:
                        logger.warning(f"📡 Trade/quote slots are full of priority symbols - can't add {s} for live ticks")
        if evicted:
            await self._queue_unsubscribe(evicted)
            logger.info(f"📡 Evicted {evicted} from live trade/quote stream to make room for priority symbol(s)")
        if new_bars or new_tq:
            await self._queue_subscribe(new_bars, new_tq)

    async def _queue_subscribe(self, bar_symbols: List[str], tq_symbols: List[str]):
        msg = {"action": "subscribe"}
        if tq_symbols:
            msg["trades"] = tq_symbols
            msg["quotes"] = tq_symbols
        if bar_symbols:
            msg["bars"] = bar_symbols
        if len(msg) > 1:
            await self._outgoing.put(msg)

    async def _queue_unsubscribe(self, tq_symbols: List[str]):
        if not tq_symbols:
            return
        await self._outgoing.put({"action": "unsubscribe", "trades": tq_symbols, "quotes": tq_symbols})

    # ------------------------------------------------------------------
    # Read access for REST endpoints / auto-trader (real-time-first data)
    # ------------------------------------------------------------------
    def get_cached_quote(self, symbol: str, max_age_seconds: float = 8.0) -> Optional[dict]:
        q = self.latest_quotes.get(symbol.upper())
        if not q:
            return None
        if time.time() - q.get("received_at", 0) > max_age_seconds:
            return None
        return {k: v for k, v in q.items() if k != "received_at"}

    def get_cached_bars_aggregated(self, symbol: str, group_minutes: int = 1, limit: int = 100) -> List[dict]:
        """Return the rolling 1-min bar buffer for `symbol`, optionally
        re-aggregated into `group_minutes`-minute buckets (e.g. 5 for 5Min)."""
        buf = self.bar_buffers.get(symbol.upper())
        if not buf:
            return []
        bars_1m = list(buf)
        if group_minutes <= 1:
            return bars_1m[-limit:]

        buckets: Dict[int, dict] = {}
        for b in bars_1m:
            epoch = _to_epoch(b['timestamp'])
            if epoch is None:
                continue
            bucket_epoch = int(epoch // (60 * group_minutes)) * (60 * group_minutes)
            if bucket_epoch not in buckets:
                buckets[bucket_epoch] = {
                    'timestamp': datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat(),
                    'open': b['open'], 'high': b['high'], 'low': b['low'],
                    'close': b['close'], 'volume': b.get('volume', 0) or 0,
                }
            else:
                agg = buckets[bucket_epoch]
                agg['high'] = max(agg['high'], b['high'])
                agg['low'] = min(agg['low'], b['low'])
                agg['close'] = b['close']
                agg['volume'] += (b.get('volume', 0) or 0)
        return [buckets[k] for k in sorted(buckets.keys())][-limit:]

    def get_tick_bars(self, symbol: str, bucket_seconds: int = 10, limit: int = 100) -> List[dict]:
        """
        Construct sub-minute OHLCV bars (e.g. 10-second) directly from raw
        trade ticks. Alpaca's REST/streaming Bars API has no "seconds"
        timeframe at all, so this is the only way to get a genuinely
        real-data 10-second chart - built entirely from real Alpaca trade
        prints, just bucketed client-side instead of fabricated.
        """
        ticks = list(self.trade_ticks.get(symbol.upper(), []))
        if not ticks:
            return []

        buckets: Dict[int, dict] = {}
        for tick in ticks:
            epoch = _to_epoch(tick['timestamp'])
            if epoch is None:
                continue
            bucket_epoch = int(epoch // bucket_seconds) * bucket_seconds
            price = tick['price']
            if bucket_epoch not in buckets:
                buckets[bucket_epoch] = {
                    'timestamp': datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat(),
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'volume': tick.get('size', 0) or 0,
                }
            else:
                agg = buckets[bucket_epoch]
                agg['high'] = max(agg['high'], price)
                agg['low'] = min(agg['low'], price)
                agg['close'] = price
                agg['volume'] += (tick.get('size', 0) or 0)
        return [buckets[k] for k in sorted(buckets.keys())][-limit:]

    def get_large_trades(self, symbol: str, limit: int = 20) -> List[dict]:
        """
        Recent unusually-large trade prints (block trades) for `symbol` -
        a real-data proxy for order-flow support/resistance, since true
        Level 2 depth-of-book isn't available on Alpaca's IEX/free tier.
        Each print is tagged buy/sell via the tick rule (trade price vs.
        the bid/ask in effect at that moment).
        """
        buf = self.large_trades.get(symbol.upper())
        if not buf:
            return []
        return list(buf)[-limit:]

    def merge_with_stream(self, symbol: str, rest_bars: List[dict], timeframe: str, limit: int) -> List[dict]:
        """
        Fill the free-tier REST embargo gap (~last 15 min) with real-time
        stream bars. `rest_bars` provides bulk history; stream bars cover
        whatever's arrived since this symbol was subscribed. Never removes
        real REST data - only appends newer bars the stream has that REST
        doesn't (deduped by minute bucket).
        """
        symbol = symbol.upper()
        if timeframe.startswith(("5M", "5m")):
            group_minutes = 5
        elif timeframe.startswith(("1M", "1m")):
            group_minutes = 1
        else:
            return rest_bars  # daily/other timeframes: stream buffer doesn't apply

        stream_bars = self.get_cached_bars_aggregated(symbol, group_minutes, limit=60)
        if not stream_bars:
            return rest_bars
        if not rest_bars:
            return stream_bars[-limit:]

        existing_keys = set()
        for b in rest_bars:
            epoch = _to_epoch(b.get('timestamp'))
            if epoch is not None:
                existing_keys.add(int(epoch // (60 * group_minutes)))

        merged = list(rest_bars)
        for b in stream_bars:
            epoch = _to_epoch(b['timestamp'])
            if epoch is None:
                continue
            key = int(epoch // (60 * group_minutes))
            if key not in existing_keys:
                merged.append(b)
                existing_keys.add(key)

        merged.sort(key=lambda b: _to_epoch(b.get('timestamp')) or 0)
        return merged[-limit:]

    def get_status(self) -> dict:
        return {
            "configured": self.is_configured,
            "connected": self.connected,
            "authenticated": self.authenticated,
            "bar_subscribed_count": len(self._subscribed_bars),
            "trade_quote_subscribed_count": len(self._subscribed_tq),
            "trade_quote_limit": MAX_TRADE_QUOTE_SYMBOLS,
            "trade_quote_priority_symbols": sorted(self._tq_priority),
            "last_message_age_seconds": round(time.time() - self._last_message_at, 1) if self._last_message_at else None,
        }


market_data_stream = MarketDataStreamManager()
