#!/usr/bin/env python3
"""Fetch 1-min bars from Yahoo Finance for ALL 3/5+ scanner tickers, last month.
Saves to bar_store on the VPS for persistent local backtesting."""
import os, sys, pathlib, asyncio, datetime as dt
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from pymongo import MongoClient
from services.bar_store import save_bars, has_bars
import httpx

m = MongoClient(); db = m.momentumx

# Collect all unique 3/5+ ticker-days from scans (Jul 15 → Aug 14)
universe = set()
for s in db.scans.find({"timestamp": {"$gte": "2026-07-15T00:00:00Z", "$lt": "2026-08-15T00:00:00Z"}}):
    for r in (s.get("results") or []):
        if r.get("criteria_count", 0) >= 3 and r.get("symbol"):
            day = s["timestamp"][:10]
            universe.add((r["symbol"], day))

print(f"Total 3/5+ ticker-days in scans: {len(universe)}")

# Find which are missing from bar_store
missing = [(sym, day) for sym, day in universe if not has_bars(sym, day)]
print(f"Already stored: {len(universe) - len(missing)}")
print(f"Need to fetch: {len(missing)}")

def yahoo_epoch_range(day):
    start = dt.datetime.fromisoformat(day + "T09:30:00-04:00")
    end = dt.datetime.fromisoformat(day + "T16:00:00-04:00")
    return int(start.timestamp()), int(end.timestamp())

async def fetch(sym, day, client):
    p1, p2 = yahoo_epoch_range(day)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    params = {"period1": p1, "period2": p2, "interval": "1m", "includePrePost": "false"}
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    try:
        r = await client.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200: return None
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result: return None
        res = result[0]
        ts = res.get("timestamp", [])
        quote = (res.get("indicators", {}).get("quote", [{}]) or [{}])[0]
        if not ts: return None
        bars = []
        for i, t in enumerate(ts):
            c = quote["close"][i]
            if c is None: continue
            bars.append({
                "timestamp": dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).isoformat(),
                "open": float(quote["open"][i] if quote["open"][i] else c),
                "high": float(quote["high"][i] if quote["high"][i] else c),
                "low": float(quote["low"][i] if quote["low"][i] else c),
                "close": float(c),
                "volume": int(quote["volume"][i]) if quote["volume"][i] else 0,
            })
        return bars
    except Exception:
        return None

async def main():
    filled, failed = 0, 0
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=3)) as client:
        for sym, day in sorted(missing):
            bars = await fetch(sym, day, client)
            if bars and len(bars) >= 30:
                save_bars(sym, bars, "1Min", "yahoo")
                filled += 1
            else:
                failed += 1
            if (filled + failed) % 50 == 0:
                print(f"  {filled} filled, {failed} failed ({(filled+failed)/len(missing)*100:.0f}%)")
    print(f"\nDone: {filled} filled, {failed} failed")
    print(f"Total in bar_store: {len(universe) - failed - (len(missing) - filled - failed)}/{len(universe)}")

asyncio.run(main())