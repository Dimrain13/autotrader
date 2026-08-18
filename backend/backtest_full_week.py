#!/usr/bin/env python3
"""Full-week backtest: top 20 scanner-flagged tickers per day, replay strategies."""
import os, sys, pathlib, re, asyncio, datetime as dt
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv(pathlib.Path("/opt/autotrader/backend/.env"))
from pymongo import MongoClient
from services.auto_trader_service import auto_trader as AT
from services.bar_store import save_bars, has_bars, load_bars
import httpx

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET = os.environ["ALPACA_SECRET_KEY"]
BASE = "https://data.alpaca.markets"

m = MongoClient()
db = m.momentumx

DAYS = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]
TOP_N = 20

# Build universe: top 20 tickers per day from missed_opportunities
universe = []
for day in DAYS:
    rows = list(db.missed_opportunities.find({"date": day}).sort([("criteria_count", -1), ("rel_volume", -1)]).limit(TOP_N))
    for r in rows:
        universe.append((r["symbol"], day))

print(f"Universe: {len(universe)} ticker-days (top {TOP_N}/day from scanner)")

def fmt_ts(ts):
    try: return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
    except: return ts

async def fetch_save(symbol, day, client):
    if has_bars(symbol, day):
        return load_bars(symbol, day)
    url = f"{BASE}/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Min", "start": f"{day}T11:00:00Z", "end": f"{day}T17:00:00Z",
              "limit": 5000, "adjustment": "raw", "feed": "sip"}
    r = await client.get(url, params=params,
        headers={"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET}, timeout=30)
    if r.status_code != 200:
        return []
    raw = r.json().get("bars", [])
    bars = [{"timestamp": b["t"], "open": float(b["o"]), "high": float(b["h"]),
             "low": float(b["l"]), "close": float(b["c"]), "volume": int(b["v"])} for b in raw]
    if bars:
        save_bars(symbol, bars, "1Min", "sip_seed")
    return bars

def simulate_exit(sig, bars, start_idx, slippage_pct=0.0):
    entry = sig["entry_price"]
    stop = sig["stop_loss_price"]
    target = sig.get("target_price", entry)
    psych = sig.get("psych_target_price") or sig.get("psych_target")
    is_no_news = sig.get("is_no_news_scalp", False)
    partial_done = False
    trailing_stop = stop
    highest = entry
    partial_events = []
    bailout = AT.no_news_bailout_seconds if is_no_news else AT.breakout_bailout_seconds
    entry_ts = bars[start_idx]["timestamp"]

    for i in range(start_idx + 1, len(bars)):
        b = bars[i]
        if b["high"] > highest:
            highest = b["high"]
            nt = highest * (1 - AT.trailing_stop_pct)
            if nt > trailing_stop: trailing_stop = nt
        cur_close, cur_low = b["close"], b["low"]
        try:
            e = dt.datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
            c = dt.datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00"))
            secs = (c - e).total_seconds()
        except: secs = 0
        in_profit = cur_close > entry
        topping = False
        if in_profit:
            rng = max(b["high"] - b["low"], 0.01)
            wick = (b["high"] - b["close"]) / rng
            topping = b["high"] > entry and wick >= AT.topping_tail_wick_ratio
        first_t = psych if (psych and not partial_done) else None
        first_hit = first_t is not None and cur_close >= first_t
        final_hit = cur_close >= target
        if not partial_done and first_hit and not final_hit and AT.enable_partial_profit:
            partial_events.append((fmt_ts(b["timestamp"]), "PARTIAL"))
            partial_done = True
            trailing_stop = max(trailing_stop, round(entry * (1 + AT.breakeven_buffer_pct), 2))
            continue
        if not partial_done and (final_hit or topping):
            px = target if final_hit else cur_close
            return (px - entry)/entry*100, "PROFIT TARGET" if final_hit else "TOPPING TAIL"
        if partial_done and (final_hit or topping):
            px = target if final_hit else cur_close
            return (px - entry)/entry*100, "FINAL/RUNNER"
        if cur_low <= trailing_stop:
            px = trailing_stop * (1 - slippage_pct)  # apply slippage on stop fills
            return (px - entry)/entry*100, "BREAKEVEN" if partial_done else "STOP"
        if not partial_done and cur_close <= entry and secs >= bailout:
            return (cur_close - entry)/entry*100, "BAILOUT"
    last = bars[-1]
    return (last["close"] - entry)/entry*100, "EOD"

async def replay(bars, symbol):
    sigs = []
    n = len(bars)
    if n < 60: return sigs
    for i in range(59, n):
        bfc = bars[:i+1][-250:]
        async def grb(s, timeframe="1Min", limit=100): return bfc[-limit:]
        orig = AT._get_real_bars
        AT._get_real_bars = grb
        try:
            for name, stock, fn in [
                ("First Pullback", {"symbol": symbol, "criteria_count": 5}, AT.check_entry_signals),
                ("Bull Flag", {"symbol": symbol, "criteria_count": 5}, AT.check_bull_flag_entry),
                ("Front-Side", {"symbol": symbol, "criteria_count": 4}, AT.check_front_side_breakout),
                ("VWAP", {"symbol": symbol, "criteria_count": 5}, AT.check_vwap_bounce_entry),
                ("ORB", {"symbol": symbol, "criteria_count": 5}, AT.check_orb_entry),
                ("Flat Top", {"symbol": symbol, "criteria_count": 4}, AT.check_flat_top_breakout),
                ("9EMA", {"symbol": symbol, "criteria_count": 4}, AT.check_9_ema_dip_entry),
            ]:
                sig = await fn(stock)
                if sig:
                    sig["strat"] = name
                    sigs.append((name, i, sig))
        finally:
            AT._get_real_bars = orig
    return sigs

async def main():
    slippage = 0.01  # 1% slippage on stop fills (conservative for microcaps)
    results = []
    async with httpx.AsyncClient() as c:
        for sym, day in universe:
            bars = await fetch_save(sym, day, c)
            if not bars or len(bars) < 60:
                results.append((sym, day, "SKIP", f"{len(bars)} bars"))
                continue
            sigs = await replay(bars, sym)
            if not sigs:
                results.append((sym, day, "NO SIG", f"{len(bars)} bars"))
                continue
            sigs.sort(key=lambda s: s[1])
            strat, idx, sig = sigs[0]
            pnl, reason = simulate_exit(sig, bars, idx, slippage)
            results.append((sym, day, strat, pnl, reason, len(bars)))

    # aggregate
    trades = [r for r in results if len(r) == 6 and isinstance(r[3], float)]
    wins = [t for t in trades if t[3] > 0]
    losses = [t for t in trades if t[3] < 0]
    flat = [t for t in trades if abs(t[3]) < 0.0001]
    total = sum(t[3] for t in trades)

    print("\n" + "=" * 90)
    print(f"FULL-WEEK BACKTEST — top {TOP_N} scanner tickers/day, {slippage*100:.0f}% stop slippage")
    print("=" * 90)
    for r in results:
        if len(r) == 6 and isinstance(r[3], float):
            print(f"{r[0]:6s} {r[1]}  {r[2]:14s} pnl {r[3]:+6.1f}%  [{r[4]:16s}]  ({r[5]} bars)")
        else:
            print(f"{r[0]:6s} {r[1]}  {r[2]:8s} {r[3]}")
    print("=" * 90)
    print(f"Trades: {len(trades)} ({len(wins)}W/{len(losses)}L/{len(flat)}F)")
    print(f"Cumulative P&L: {total:+.1f}%")
    if wins and losses:
        print(f"Avg win {sum(t[3] for t in wins)/len(wins):+.1f}% | Avg loss {sum(t[3] for t in losses)/len(losses):+.1f}%")
        print(f"Profit factor: {sum(t[3] for t in wins)/abs(sum(t[3] for t in losses)):.2f}")
    # dollar equivalent at 50% sizing on ~$25k effective
    if total:
        print(f"\\n~Dollar equivalent (50% of ~$50K margin BP per trade): roughly ${total/100 * 25000:+,.0f}")

asyncio.run(main())