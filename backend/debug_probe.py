#!/usr/bin/env python3
"""Debug probe: why didn't XHG / FRTT fire any strategies?"""
import asyncio, httpx, os, sys
sys.path.insert(0, "/opt/autotrader/backend")
from dotenv import load_dotenv
load_dotenv("/opt/autotrader/backend/.env")

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET = os.environ["ALPACA_SECRET_KEY"]
BASE = "https://data.alpaca.markets"

from services.auto_trader_service import auto_trader as AT

async def probe(symbol, day):
    url = f"{BASE}/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Min", "start": f"{day}T11:00:00Z",
              "end": f"{day}T17:00:00Z", "limit": 5000, "adjustment": "raw", "feed": "iex"}
    async with httpx.AsyncClient() as c:
        r = await c.get(url, params=params,
            headers={"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET}, timeout=30)
    if r.status_code != 200:
        print(f"{symbol} {day}: HTTP {r.status_code}")
        return
    bars_raw = r.json().get("bars", [])
    bars = [{"open": float(b["o"]), "high": float(b["h"]), "low": float(b["l"]),
             "close": float(b["c"]), "volume": int(b["v"]), "timestamp": b["t"]} for b in bars_raw]
    print(f"\n=== {symbol} {day}: {len(bars)} bars, range ${min(b['low'] for b in bars):.2f}-${max(b['high'] for b in bars):.2f} ===")

    # Test front-side specifically at bars where we'd expect it
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    volumes = [b["volume"] for b in bars]

    print(f"Checking whole-dollar breakouts (prev_c < $1.00, cur_c >= $1.00, cur_c <= $1.10, vol>=1.2x):")
    for i in range(30, len(bars)):
        prev_c = closes[i-1] if i >= 1 else 0
        cur_c = closes[i]
        cur_v = volumes[i]
        avg_v = sum(volumes[max(0,i-21):i]) / max(1, len(volumes[max(0,i-21):i]))
        ve = cur_v / avg_v if avg_v > 0 else 0
        if prev_c < 1.0 and cur_c >= 1.0 and cur_c <= 1.10 and ve >= 1.2:
            print(f"  BAR {i}: prev=${prev_c:.2f} cur=${cur_c:.2f} vol_exp={ve:.1f}x  @ {bars[i]['timestamp']}")

    print(f"Checking blue-sky ATH (cur_c > period_high, vol>=1.3x):")
    for i in range(60, len(bars)):
        cur_c = closes[i]
        cur_h = highs[i]
        cur_v = volumes[i]
        avg_v = sum(volumes[max(0,i-21):i]) / max(1, len(volumes[max(0,i-21):i]))
        ve = cur_v / avg_v if avg_v > 0 else 0
        # Period high = max of all prior bars (up to 390)
        ph = max(highs[max(0,i-390):i]) if i > 0 else highs[0]
        if cur_c > ph and cur_h > ph and ve >= 1.3:
            print(f"  BAR {i}: cur=${cur_c:.2f} > prior_high=${ph:.2f} vol_exp={ve:.1f}x @ {bars[i]['timestamp']}")

    print(f"Checking MA-wall SMA200 crossover (prev_c < SMA200, cur_c > SMA200, vol>=1.5x):")
    for i in range(200, len(bars)):
        prev_c = closes[i-1]
        cur_c = closes[i]
        cur_v = volumes[i]
        avg_v = sum(volumes[max(0,i-21):i]) / max(1, len(volumes[max(0,i-21):i]))
        ve = cur_v / avg_v if avg_v > 0 else 0
        sma200 = sum(closes[i-199:i+1]) / 200.0
        if prev_c < sma200 and cur_c > sma200 and ve >= 1.5:
            print(f"  BAR {i}: prev=${prev_c:.2f} sma200=${sma200:.2f} cur=${cur_c:.2f} vol_exp={ve:.1f}x @ {bars[i]['timestamp']}")

    # Also run the ACTUAL check_front_side_breakout directly at a few key bars
    print("\nRunning actual check_front_side_breakout at key volatility bars:")
    highest_vol_bars = sorted(range(30, len(bars)), 
        key=lambda i: volumes[i] / max(0.01, sum(volumes[max(0,i-21):i]) / max(1, len(volumes[max(0,i-21):i]))), reverse=True)[:5]
    for idx in highest_vol_bars:
        bfc = bars[:idx+1][-250:]
        async def grb(sym, tf="1Min", limit=100):
            return bfc[-limit:]
        old_grb = AT._get_real_bars
        AT._get_real_bars = grb
        stock4 = {"symbol": symbol, "criteria_count": 4}
        fs = await AT.check_front_side_breakout(stock4)
        AT._get_real_bars = old_grb
        cur_v = volumes[idx]
        avg_v = sum(volumes[max(0,idx-21):idx]) / max(1, len(volumes[max(0,idx-21):idx]))
        ve = cur_v / max(0.01, avg_v)
        print(f"  BAR {idx}: close=${closes[idx]:.2f} vol_exp={ve:.1f}x -> check_front_side: {'FIRED entry='+str(fs['entry_price']) if fs else 'None (did not fire)'}")


async def main():
    await probe("XHG", "2026-08-13")
    await probe("FRTT", "2026-08-11")

asyncio.run(main())