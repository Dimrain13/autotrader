#!/usr/bin/env python3
"""Fetch 1-min bars from Yahoo Finance for tickers Alpaca SIP can't cover."""
import httpx, json, datetime as dt, asyncio, os, sys, pathlib
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from pymongo import MongoClient
from services.bar_store import save_bars, has_bars

m = MongoClient(); db = m.momentumx
DAYS = ["2026-08-10","2026-08-11","2026-08-12","2026-08-13","2026-08-14"]

# Build the 3/5+ universe and find which are missing from bar_store
universe = {}
for day in DAYS:
    scans = db.scans.find({"timestamp": {"$gte": day+"T00:00:00Z", "$lt": day+"T23:59:59Z"}})
    for s in scans:
        for r in (s.get("results") or []):
            if r.get("criteria_count", 0) < 3: continue
            sym = r.get("symbol")
            if not sym: continue
            key = (sym, day)
            if key not in universe:
                universe[key] = r.get("criteria_count", 3)

missing = [(sym, day) for (sym, day) in universe if not has_bars(sym, day)]
print(f"Universe: {len(universe)} | Missing bars: {len(missing)}")

def yahoo_epoch_range(day):
    """Yahoo uses Unix epoch seconds. Trading day 9:30-16:00 ET."""
    start = dt.datetime.fromisoformat(day + "T09:30:00-04:00")
    end = dt.datetime.fromisoformat(day + "T16:00:00-04:00")
    return int(start.timestamp()), int(end.timestamp())

async def fetch_yahoo(sym, day, client):
    p1, p2 = yahoo_epoch_range(day)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    params = {"period1": p1, "period2": p2, "interval": "1m", "includePrePost": "false"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    r = await client.get(url, params=params, headers=headers, timeout=20)
    if r.status_code != 200:
        return None
    data = r.json()
    result = data.get("chart", {}).get("result", [])
    if not result: return None
    res = result[0]
    ts = res.get("timestamp", [])
    quote = (res.get("indicators", {}).get("quote", [{}]) or [{}])[0]
    if not ts: return None
    bars = []
    o = quote.get("open", []); h = quote.get("high", []); l = quote.get("low", [])
    c = quote.get("close", []); v = quote.get("volume", [])
    for i, t in enumerate(ts):
        if c[i] is None: continue
        bars.append({
            "timestamp": dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).isoformat(),
            "open": float(o[i]) if o[i] else float(c[i]),
            "high": float(h[i]) if h[i] else float(c[i]),
            "low": float(l[i]) if l[i] else float(c[i]),
            "close": float(c[i]),
            "volume": int(v[i]) if v[i] else 0,
        })
    return bars

async def main():
    filled = 0; failed = 0
    async with httpx.AsyncClient() as client:
        for sym, day in sorted(missing):
            bars = await fetch_yahoo(sym, day, client)
            if bars and len(bars) >= 60:
                save_bars(sym, bars, "1Min", "yahoo")
                filled += 1
            else:
                failed += 1
            if (filled + failed) % 25 == 0:
                print(f"  progress: {filled} filled, {failed} failed")
    print(f"\nDone: {filled} filled from Yahoo, {failed} still missing")

asyncio.run(main())