#!/usr/bin/env python3
"""Data-quality gate: for each backtest ticker, how many 1-min bars does
IEX return vs SIP? Determines whether a reliable backtest is even possible."""
import httpx, os, asyncio
from dotenv import load_dotenv
import pathlib
load_dotenv("/opt/autotrader/backend/.env")

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET = os.environ["ALPACA_SECRET_KEY"]
BASE = "https://data.alpaca.markets"

# The tickers that returned suspiciously few bars last time
TICKERS = ["GITS", "HWH", "PTN", "PMA", "INBS", "FRTT", "XHG", "TNXP", "SMWB"]

async def count_bars(symbol, day, feed, client):
    url = f"{BASE}/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Min", "start": f"{day}T11:00:00Z",
              "end": f"{day}T17:00:00Z", "limit": 5000,
              "adjustment": "raw", "feed": feed}
    r = await client.get(url, params=params,
        headers={"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET}, timeout=30)
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    bars = r.json().get("bars", [])
    if not bars:
        return "0 bars"
    lo = min(float(b["l"]) for b in bars)
    hi = max(float(b["h"]) for b in bars)
    return f"{len(bars)} bars  ${lo:.2f}-${hi:.2f}"

async def main():
    days = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13"]
    async with httpx.AsyncClient() as c:
        print(f"{'SYM':6s} {'DAY':10s} {'IEX':>22s} {'SIP':>22s}")
        print("-" * 66)
        for sym in TICKERS:
            for day in days:
                iex = await count_bars(sym, day, "iex", c)
                sip = await count_bars(sym, day, "sip", c)
                flag = "  <-- MISMATCH" if ("HTTP" in str(sip) or "HTTP" in str(iex)) else ""
                print(f"{sym:6s} {day:10s} IEX: {iex:20s} SIP: {sip:20s}{flag}")

asyncio.run(main())