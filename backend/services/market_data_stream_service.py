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
        self._sub_lock = asyncio.Lock()

        # In-memory latest-data caches - always fresher than REST for
        # anything actively subscribed.
        self.latest_quotes: Dict[str, dict] = {}
        self.latest_trades: Dict[str, dict] = {}
        self.bar_buffers: Dict[str, deque] = {}

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
            if symbol:
                self.latest_trades[symbol] = {
                    "price": msg.get("p"), "size": msg.get("s"),
                    "timestamp": msg.get("t"), "received_at": now,
                }
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
    async def subscribe(self, symbols: List[str]):
        """
        Add symbols to the live stream (idempotent, safe to call repeatedly).
        Bar subscriptions are unlimited; trade/quote subscriptions are
        capped at MAX_TRADE_QUOTE_SYMBOLS to respect Alpaca's free-tier limit.
        """
        if not self.is_configured or not symbols:
            return
        new_bars, new_tq = [], []
        async with self._sub_lock:
            for s in symbols:
                s = (s or "").upper().strip()
                if not s:
                    continue
                if s not in self._subscribed_bars:
                    self._subscribed_bars.add(s)
                    new_bars.append(s)
                if s not in self._subscribed_tq and len(self._subscribed_tq) < MAX_TRADE_QUOTE_SYMBOLS:
                    self._subscribed_tq.add(s)
                    new_tq.append(s)
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
            "last_message_age_seconds": round(time.time() - self._last_message_at, 1) if self._last_message_at else None,
        }


market_data_stream = MarketDataStreamManager()
