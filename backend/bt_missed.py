#!/usr/bin/env python3
"""Backtest the MISSED (4/5+) scanner tickers with current strategy settings.
Real entry methods, real bars (bar_store -> SIP -> Yahoo), 1% stop slippage."""
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

# Pull missed_opportunities (4/5+ untraded tickers) for the month
universe = {}
rows = list(db.missed_opportunities.find({"date": {"$gte": "2026-07-15", "$lte": "2026-08-14"}}))
for r in rows:
    sym, day = r.get("symbol"), r.get("date")
    if not sym or not day: continue
    key = (sym, day)
    cc = r.get("criteria_count", 4)
    if key not in universe or cc > universe[key][0]:
        universe[key] = (cc, r.get("price_at_scan",0), r.get("pct_change",0), r.get("rel_volume",0))

print(f"Missed 4/5+ ticker-days: {len(universe)}")

def yahoo_range(day):
    a = dt.datetime.fromisoformat(day + "T09:30:00-04:00")
    b = dt.datetime.fromisoformat(day + "T16:00:00-04:00")
    return int(a.timestamp()), int(b.timestamp())

async def ensure_bars(sym, day, client):
    if has_bars(sym, day): return load_bars(sym, day)
    # SIP first
    url = f"{BASE}/v2/stocks/{sym}/bars"
    p = {"timeframe":"1Min","start":f"{day}T11:00:00Z","end":f"{day}T17:00:00Z","limit":5000,"adjustment":"raw","feed":"sip"}
    try:
        r = await client.get(url, params=p, headers={"APCA-API-KEY-ID":API_KEY,"APCA-API-SECRET-KEY":SECRET}, timeout=25)
        if r.status_code == 200:
            raw = r.json().get("bars",[])
            if raw:
                bars = [{"timestamp":b["t"],"open":float(b["o"]),"high":float(b["h"]),"low":float(b["l"]),"close":float(b["c"]),"volume":int(b["v"])} for b in raw]
                if len(bars) >= 60: save_bars(sym, bars, "1Min", "sip"); return bars
    except Exception: pass
    # Yahoo fallback
    p1, p2 = yahoo_range(day)
    try:
        r = await client.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"period1":p1,"period2":p2,"interval":"1m","includePrePost":"false"},
            headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64)"}, timeout=20)
        if r.status_code == 200:
            res = (r.json().get("chart",{}).get("result") or [None])[0]
            if res:
                ts = res.get("timestamp",[]); q = (res.get("indicators",{}).get("quote",[{}]) or [{}])[0]
                bars = []
                for i,t in enumerate(ts):
                    c = q["close"][i]
                    if c is None: continue
                    bars.append({"timestamp":dt.datetime.fromtimestamp(t,tz=dt.timezone.utc).isoformat(),
                                 "open":float(q["open"][i] if q["open"][i] else c),"high":float(q["high"][i] if q["high"][i] else c),
                                 "low":float(q["low"][i] if q["low"][i] else c),"close":float(c),
                                 "volume":int(q["volume"][i]) if q["volume"][i] else 0})
                if len(bars) >= 60: save_bars(sym, bars, "1Min", "yahoo"); return bars
    except Exception: pass
    return []

async def run():
    slip = 0.01; trades = []; nodata = 0
    async with httpx.AsyncClient() as client:
        for key, val in sorted(universe.items()):
            sym, day = key; cc, pr, pc, vr = val
            bars = await ensure_bars(sym, day, client)
            if not bars or len(bars) < 60: nodata += 1; continue
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
            pnl = 0.0; reason = "EOD"
            for j in range(idx+1, len(bars)):
                b = bars[j]
                if b["high"] > highest:
                    highest = b["high"]; nt = highest*(1-AT.trailing_stop_pct)
                    if nt > trailing: trailing = nt
                cl, lo = b["close"], b["low"]
                try:
                    e=dt.datetime.fromisoformat(bars[idx]["timestamp"].replace("Z","+00:00")); c=dt.datetime.fromisoformat(b["timestamp"].replace("Z","+00:00")); secs=(c-e).total_seconds()
                except: secs=0
                if cl >= target: pnl = (target-entry)/entry*100; reason="TARGET"; break
                if lo <= trailing: px = trailing*(1-slip); pnl = (px-entry)/entry*100; reason="STOP"; break
                if cl <= entry and secs >= bail: pnl = (cl-entry)/entry*100; reason="BAILOUT"; break
                if j == len(bars)-1: pnl = (cl-entry)/entry*100; reason="EOD"
            trades.append((sym, day, cc, name, pnl, reason))

    wins = [t[4] for t in trades if t[4] > 0]; losses = [t[4] for t in trades if t[4] < 0]
    print("\n"+"="*80)
    print(f"MISSED 4/5+ TICKERS — current strategy settings, {slip*100:.0f}% slippage")
    print("="*80)
    for t in trades:
        print(f"{t[0]:6s} {t[1]} {t[2]}* {t[3]:4s} {t[4]:+6.1f}% [{t[5]:8s}]")
    print("="*80)
    s = sum(t[4] for t in trades)
    print(f"Trades: {len(trades)} ({len(wins)}W/{len(losses)}L) | No-data/No-signal: {nodata}")
    print(f"Cumulative P&L: {s:+.1f}%")
    if wins and losses:
        print(f"Avg win {sum(wins)/len(wins):+.1f}% | Avg loss {sum(losses)/len(losses):+.1f}% | PF: {sum(wins)/abs(sum(losses)):.2f}")

asyncio.run(run())