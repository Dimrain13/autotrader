#!/usr/bin/env python3
import os, sys, pathlib, asyncio, datetime as dt
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from pymongo import MongoClient
from services.auto_trader_service import auto_trader as AT
from services.bar_store import save_bars, has_bars, load_bars
import httpx

API_KEY, SECRET = os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"]
BASE = "https://data.alpaca.markets"
m = MongoClient(); db = m.momentumx
DAYS = ["2026-08-10","2026-08-11","2026-08-12","2026-08-13","2026-08-14"]

universe = {}
for day in DAYS:
    rows = list(db.missed_opportunities.find({"date": day}).sort("criteria_count", -1))
    for r in rows:
        key = (r["symbol"], day)
        if key not in universe or r["criteria_count"] > universe[key][0]:
            universe[key] = (r["criteria_count"], r.get("current_price",0), r.get("pct_change",0), r.get("volume_ratio",0))

print(f"Universe: {len(universe)} unique ticker-days")

async def ensure(sym, day, cl):
    if has_bars(sym, day): return load_bars(sym, day)
    url = f"{BASE}/v2/stocks/{sym}/bars"
    p = {"timeframe":"1Min","start":f"{day}T11:00:00Z","end":f"{day}T17:00:00Z","limit":5000,"adjustment":"raw","feed":"sip"}
    r = await cl.get(url, params=p, headers={"APCA-API-KEY-ID":API_KEY,"APCA-API-SECRET-KEY":SECRET}, timeout=30)
    if r.status_code != 200: return []
    raw = r.json().get("bars",[])
    bars = [{"timestamp":b["t"],"open":float(b["o"]),"high":float(b["h"]),"low":float(b["l"]),"close":float(b["c"]),"volume":int(b["v"])} for b in raw]
    if bars: save_bars(sym, bars, "1Min", "sip")
    return bars

async def run():
    trades = []; slip = 0.01
    async with httpx.AsyncClient() as client:
        items = sorted(universe.items())
        for key, val in items:
            sym, day = key
            cc, pr, pc, vr = val
            bars = await ensure(sym, day, client)
            if not bars or len(bars) < 60: continue
            sigs = []
            for i in range(59, len(bars)):
                bfc = bars[:i+1][-250:]
                async def grb(s, timeframe="1Min", limit=100): return bfc[-limit:]
                orig = AT._get_real_bars; AT._get_real_bars = grb
                try:
                    for name, fn in [("FP", AT.check_entry_signals),("FS", AT.check_front_side_breakout),("VW", AT.check_vwap_bounce_entry),("ORB", AT.check_orb_entry),("FT", AT.check_flat_top_breakout),("9E", AT.check_9_ema_dip_entry)]:
                        stock = {"symbol": sym, "criteria_count": cc}
                        sig = await fn(stock)
                        if sig: sigs.append((name, i, sig))
                finally: AT._get_real_bars = orig
            if not sigs: continue
            sigs.sort(key=lambda s: s[1])
            name, idx, sig = sigs[0]
            entry = sig["entry_price"]; stop = sig["stop_loss_price"]; target = sig.get("target_price", entry)
            trailing = stop; highest = entry; bail = AT.breakout_bailout_seconds
            pnl = 0; reason = "EOD"
            for j in range(idx+1, len(bars)):
                b = bars[j]
                if b["high"] > highest: highest = b["high"]; nt = highest*(1-AT.trailing_stop_pct); trailing = max(trailing, nt) if nt > trailing else trailing
                cl, lo = b["close"], b["low"]
                try: e=dt.datetime.fromisoformat(bars[idx]["timestamp"].replace("Z","+00:00")); c=dt.datetime.fromisoformat(b["timestamp"].replace("Z","+00:00")); secs=(c-e).total_seconds()
                except: secs=0
                if cl >= target: pnl = (target-entry)/entry*100; reason="TARGET"; break
                if lo <= trailing: px = trailing*(1-slip); pnl = (px-entry)/entry*100; reason="STOP"; break
                if cl <= entry and secs >= bail: pnl = (cl-entry)/entry*100; reason="BAILOUT"; break
                if j == len(bars)-1: pnl = (cl-entry)/entry*100; reason="EOD"
            trades.append((sym, day, cc, name, pnl, reason))
    
    wins = [t[4] for t in trades if t[4] > 0]; losses = [t[4] for t in trades if t[4] < 0]
    print("\n"+"="*80)
    print(f"REAL BACKTEST: 4/5+ scanner data, SIP bars, {slip*100:.0f}% slippage")
    print("="*80)
    for t in trades:
        print(f"{t[0]:6s} {t[1]} {t[2]}* {t[3]:4s} {t[4]:+6.1f}% [{t[5]:8s}]")
    print("="*80)
    s = sum(t[4] for t in trades)
    print(f"Trades: {len(trades)} ({len(wins)}W/{len(losses)}L) | P&L: {s:+.1f}%")
    if wins and losses: print(f"Avg win {sum(wins)/len(wins):+.1f}% | Avg loss {sum(losses)/len(losses):+.1f}% | PF: {sum(wins)/abs(sum(losses)):.2f}")

asyncio.run(run())