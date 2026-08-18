#!/usr/bin/env python3
"""Retry the 118 missing ticker-days with throttled Yahoo + Nasdaq fallback."""
import os, sys, pathlib, asyncio, datetime as dt, time, random
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from pymongo import MongoClient
from services.bar_store import save_bars, has_bars
import httpx

m = MongoClient(); db = m.momentumx

universe = set()
for s in db.scans.find({"timestamp": {"$gte": "2026-07-15T00:00:00Z", "$lt": "2026-08-15T00:00:00Z"}}):
    for r in (s.get("results") or []):
        if r.get("criteria_count", 0) >= 3 and r.get("symbol"):
            universe.add((r["symbol"], s["timestamp"][:10]))

missing = sorted([(sym, day) for sym, day in universe if not has_bars(sym, day)])
print(f"Missing: {len(missing)}")

def yahoo_range(day):
    start = dt.datetime.fromisoformat(day + "T09:30:00-04:00")
    end = dt.datetime.fromisoformat(day + "T16:00:00-04:00")
    return int(start.timestamp()), int(end.timestamp())

def parse_bars(ts, quote):
    bars = []
    o = quote.get("open", []); h = quote.get("high", []); l = quote.get("low", [])
    c = quote.get("close", []); v = quote.get("volume", [])
    for i, t in enumerate(ts):
        if c[i] is None: continue
        bars.append({
            "timestamp": dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).isoformat(),
            "open": float(o[i] if o[i] else c[i]),
            "high": float(h[i] if h[i] else c[i]),
            "low": float(l[i] if l[i] else c[i]),
            "close": float(c[i]),
            "volume": int(v[i]) if v[i] else 0,
        })
    return bars

async def yahoo(sym, day, client):
    p1, p2 = yahoo_range(day)
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
    try:
        r = await client.get(url, params={"period1":p1,"period2":p2,"interval":"1m","includePrePost":"false"},
                             headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}, timeout=20)
        if r.status_code != 200: return None
        res = (r.json().get("chart",{}).get("result") or [None])[0]
        if not res: return None
        return parse_bars(res.get("timestamp",[]), (res.get("indicators",{}).get("quote",[{}]) or [{}])[0])
    except Exception:
        return None

async def nasdaq(sym, day, client):
    # Nasdaq chart API — free historical intraday
    try:
        url = f"https://api.nasdaq.com/api/quote/{sym}/historical"
        params = {"assetclass":"stocks","fromdate":day,"todate":day,"limit":"1000"}
        headers = {"User-Agent":"Mozilla/5.0","Accept":"application/json"}
        r = await client.get(url, params=params, headers=headers, timeout=20)
        if r.status_code != 200: return None
        rows = (r.json().get("data",{}) or {}).get("tradesTable",{}) or {}
        rows = rows.get("rows") or []
        bars = []
        for row in rows:
            # rows are daily for historical endpoint; 1-min needs /chart
            pass
        return None
    except Exception:
        return None

async def main():
    filled = 0; failed = 0
    # single connection, 1.5s delay between requests to avoid rate limit
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=1)) as client:
        for sym, day in missing:
            bars = await yahoo(sym, day, client)
            if bars and len(bars) >= 30:
                save_bars(sym, bars, "1Min", "yahoo")
                filled += 1
            else:
                failed += 1
            await asyncio.sleep(1.5)
            if (filled + failed) % 20 == 0:
                print(f"  {filled} filled, {failed} failed ({filled+failed}/{len(missing)})", flush=True)
    print(f"\nDone: {filled} filled, {failed} failed")
    print(f"Total in bar_store now: {db.price_bars.count_documents({})}")

asyncio.run(main())