#!/usr/bin/env python3
"""Seed the bar_store with SIP historical bars for backtest ticker-days."""
import os, sys, pathlib, httpx, asyncio
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv(pathlib.Path("/opt/autotrader/backend/.env"))
from services.bar_store import save_bars, has_bars, count_stored

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET = os.environ["ALPACA_SECRET_KEY"]
BASE = "https://data.alpaca.markets"

UNIVERSE = [("SCKT","2026-08-10"),("JWEL","2026-08-10"),("FRTT","2026-08-11"),
("RMCF","2026-08-12"),("XHG","2026-08-13"),("FGI","2026-08-13"),
("TNXP","2026-08-10"),("GITS","2026-08-10"),("XHLD","2026-08-10"),
("QMCO","2026-08-11"),("BWEN","2026-08-11"),
("IMTE","2026-08-12"),("DRMA","2026-08-12"),("GRWG","2026-08-12"),
("BOXL","2026-08-12"),("HWH","2026-08-12"),("BIVI","2026-08-12"),
("DOGZ","2026-08-12"),("SMWB","2026-08-12"),("BAOS","2026-08-12"),("INBS","2026-08-12"),
("OMER","2026-08-13"),("GXAI","2026-08-13"),("LNSR","2026-08-13"),
("USIO","2026-08-13"),("RRGB","2026-08-13"),("PTN","2026-08-13"),
("AMPY","2026-08-13"),("IPWR","2026-08-13"),("PLYX","2026-08-13"),
("EMPD","2026-08-13"),("PSQH","2026-08-13"),("CYCN","2026-08-13"),
("ARX","2026-08-13"),("HCTI","2026-08-13"),("PMA","2026-08-13"),
("AZ","2026-08-13"),("DFSC","2026-08-13"),("MSGY","2026-08-13"),("FTLF","2026-08-13"),
("GRSD","2026-08-14"),("AEYE","2026-08-14"),("WETO","2026-08-14"),
("HHS","2026-08-14"),("IMXI","2026-08-14"),("LFS","2026-08-14"),
("NEXR","2026-08-14"),("CGTL","2026-08-14"),("NPWR","2026-08-14")]

async def seed():
    saved = skipped = 0
    async with httpx.AsyncClient() as c:
        for sym, day in UNIVERSE:
            if has_bars(sym, day):
                skipped += 1
                continue
            url = f"{BASE}/v2/stocks/{sym}/bars"
            params = {"timeframe": "1Min", "start": f"{day}T11:00:00Z",
                      "end": f"{day}T17:00:00Z", "limit": 5000,
                      "adjustment": "raw", "feed": "sip"}
            r = await c.get(url, params=params,
                headers={"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET},
                timeout=30)
            if r.status_code != 200:
                print(f"  {sym} {day}: HTTP {r.status_code}")
                continue
            raw = r.json().get("bars", [])
            if not raw:
                print(f"  {sym} {day}: no bars (delisted/inactive)")
                continue
            bars = [{"timestamp": b["t"], "open": float(b["o"]), "high": float(b["h"]),
                     "low": float(b["l"]), "close": float(b["c"]), "volume": int(b["v"])}
                    for b in raw]
            save_bars(sym, bars, "1Min", "sip_seed")
            saved += 1
            print(f"  {sym} {day}: {len(bars)} bars saved")
    print(f"\nSeeded: {saved} | Skipped (existing): {skipped} | Total in store: {count_stored()}")

asyncio.run(seed())