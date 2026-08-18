#!/usr/bin/env python3
"""Backtest v2 — reads bars from local MongoDB bar_store instead of Alpaca API."""
import asyncio, sys, os, pathlib, re, datetime as dt
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv(pathlib.Path("/opt/autotrader/backend/.env"))

from services.auto_trader_service import auto_trader as AT
from services.bar_store import load_bars, has_bars

UNIVERSE = [
    # Ross Cameron tickers
    ("SCKT", "2026-08-10"), ("JWEL", "2026-08-10"),
    ("FRTT", "2026-08-11"),
    ("RMCF", "2026-08-12"),
    ("XHG", "2026-08-13"), ("FGI", "2026-08-13"),
    # Bot trades
    ("TNXP", "2026-08-10"), ("GITS", "2026-08-10"), ("XHLD", "2026-08-10"),
    ("QMCO", "2026-08-11"), ("BWEN", "2026-08-11"),
    ("IMTE", "2026-08-12"), ("DRMA", "2026-08-12"), ("GRWG", "2026-08-12"),
    ("BOXL", "2026-08-12"), ("HWH", "2026-08-12"), ("BIVI", "2026-08-12"),
    ("DOGZ", "2026-08-12"), ("SMWB", "2026-08-12"), ("BAOS", "2026-08-12"),
    ("INBS", "2026-08-12"),
    ("OMER", "2026-08-13"), ("GXAI", "2026-08-13"), ("LNSR", "2026-08-13"),
    ("USIO", "2026-08-13"), ("RRGB", "2026-08-13"), ("PTN", "2026-08-13"),
    ("AMPY", "2026-08-13"), ("IPWR", "2026-08-13"), ("PLYX", "2026-08-13"),
    ("EMPD", "2026-08-13"), ("PSQH", "2026-08-13"), ("CYCN", "2026-08-13"),
    ("ARX", "2026-08-13"), ("HCTI", "2026-08-13"), ("PMA", "2026-08-13"),
    ("AZ", "2026-08-13"), ("DFSC", "2026-08-13"), ("MSGY", "2026-08-13"),
    ("FTLF", "2026-08-13"),
    ("GRSD", "2026-08-14"), ("AEYE", "2026-08-14"), ("WETO", "2026-08-14"),
    ("HHS", "2026-08-14"), ("IMXI", "2026-08-14"), ("LFS", "2026-08-14"),
    ("NEXR", "2026-08-14"), ("CGTL", "2026-08-14"), ("NPWR", "2026-08-14"),
]

# ---- exit simulation (same as before, just reads from local) ----
def fmt_ts(ts: str) -> str:
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return ts

def simulate_exit(sig: dict, bars: list, start_idx: int) -> dict:
    entry = sig["entry_price"]
    stop = sig["stop_loss_price"]
    target = sig.get("target_price", entry)
    psych = sig.get("psych_target_price") or sig.get("psych_target")
    is_no_news = sig.get("is_no_news_scalp", False)
    partial_done = False
    trailing_stop = stop
    highest = entry
    partial_events = []
    bailout_seconds = AT.no_news_bailout_seconds if is_no_news else AT.breakout_bailout_seconds
    entry_ts = bars[start_idx]["timestamp"]

    for i in range(start_idx + 1, len(bars)):
        b = bars[i]
        if b["high"] > highest:
            highest = b["high"]
            new_trail = highest * (1 - AT.trailing_stop_pct)
            if new_trail > trailing_stop:
                trailing_stop = new_trail
        cur_close = b["close"]
        cur_low = b["low"]
        try:
            e = dt.datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
            c = dt.datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00"))
            secs = (c - e).total_seconds()
        except Exception:
            secs = 0
        in_profit = cur_close > entry

        topping_tail = False
        if in_profit:
            rng = max(b["high"] - b["low"], 0.01)
            wick = (b["high"] - b["close"]) / rng
            topping_tail = b["high"] > entry and wick >= AT.topping_tail_wick_ratio

        first_stage_target = psych if (psych and not partial_done) else None
        first_stage_hit = first_stage_target is not None and cur_close >= first_stage_target
        final_hit = cur_close >= target

        if not partial_done and first_stage_hit and not final_hit and AT.enable_partial_profit:
            partial_events.append((fmt_ts(b["timestamp"]), "PARTIAL@%.2f" % first_stage_target))
            partial_done = True
            trailing_stop = max(trailing_stop, round(entry * (1 + AT.breakeven_buffer_pct), 2))
            continue

        if not partial_done and (final_hit or topping_tail):
            px = target if final_hit else cur_close
            return {"exit_price": px, "exit_time": fmt_ts(b["timestamp"]),
                    "exit_reason": "PROFIT TARGET" if final_hit else "TOPPING TAIL",
                    "pnl_pct": (px - entry) / entry * 100, "partial_events": partial_events}
        if partial_done and (final_hit or topping_tail):
            px = target if final_hit else cur_close
            return {"exit_price": px, "exit_time": fmt_ts(b["timestamp"]),
                    "exit_reason": "FINAL TARGET (runner)" if final_hit else "TOPPING TAIL (runner)",
                    "pnl_pct": (px - entry) / entry * 100, "partial_events": partial_events}
        if cur_low <= trailing_stop:
            px = trailing_stop
            return {"exit_price": px, "exit_time": fmt_ts(b["timestamp"]),
                    "exit_reason": "BREAKEVEN STOP" if partial_done else "STRUCTURAL STOP",
                    "pnl_pct": (px - entry) / entry * 100, "partial_events": partial_events}
        if not partial_done and cur_close <= entry and secs >= bailout_seconds:
            return {"exit_price": cur_close, "exit_time": fmt_ts(b["timestamp"]),
                    "exit_reason": "BREAKOUT/BAILOUT", "pnl_pct": (cur_close - entry) / entry * 100,
                    "partial_events": partial_events}

    last = bars[-1]
    return {"exit_price": last["close"], "exit_time": fmt_ts(last["timestamp"]),
            "exit_reason": "END OF WINDOW", "pnl_pct": (last["close"] - entry) / entry * 100,
            "partial_events": partial_events}

async def replay_symbol(day_bars: list, symbol: str):
    signals = []
    n = len(day_bars)
    if n < 60:
        return signals
    for i in range(59, n):
        window = day_bars[:i + 1]
        bars_for_check = window[-250:]
        async def _grb(sym, timeframe="1Min", limit=100):
            return bars_for_check[-limit:]
        orig = AT._get_real_bars
        AT._get_real_bars = _grb
        try:
            for strat_name, stock, fn in [
                ("First Pullback", {"symbol": symbol, "criteria_count": 5}, AT.check_entry_signals),
                ("Bull Flag", {"symbol": symbol, "criteria_count": 5}, AT.check_bull_flag_entry),
                ("Front-Side", {"symbol": symbol, "criteria_count": 4}, AT.check_front_side_breakout),
                ("VWAP Bounce", {"symbol": symbol, "criteria_count": 5}, AT.check_vwap_bounce_entry),
                ("ORB", {"symbol": symbol, "criteria_count": 5}, AT.check_orb_entry),
                ("Flat Top", {"symbol": symbol, "criteria_count": 4}, AT.check_flat_top_breakout),
                ("9 EMA Dip", {"symbol": symbol, "criteria_count": 4}, AT.check_9_ema_dip_entry),
            ]:
                sig = await fn(stock)
                if sig:
                    sig["strategy_name"] = strat_name
                    signals.append((strat_name, i, sig))
        finally:
            AT._get_real_bars = orig
    return signals

async def main():
    results = []
    seen = set()
    hits = misses = 0
    for symbol, day in UNIVERSE:
        key = (symbol, day)
        if key in seen:
            continue
        seen.add(key)
        if not has_bars(symbol, day):
            results.append((symbol, day, "NO DATA", "not in local bar_store"))
            misses += 1
            continue
        bars = load_bars(symbol, day)
        if not bars:
            results.append((symbol, day, "NO DATA", "empty bar store entry"))
            misses += 1
            continue
        sigs = await replay_symbol(bars, symbol)
        if not sigs:
            results.append((symbol, day, "NO SIGNAL", f"{len(bars)} bars, no strategy fired"))
            misses += 1
            continue
        hits += 1
        sigs_sorted = sorted(sigs, key=lambda s: s[1])
        strat, idx, sig = sigs_sorted[0]
        entry = sig["entry_price"]
        exit_sim = simulate_exit(sig, bars, idx)
        line = (f"{symbol:5s} {day}  {strat:18s} entry ${entry:.2f} @ {fmt_ts(bars[idx]['timestamp'])} "
                f"| stop ${sig['stop_loss_price']:.2f} | target ${sig.get('target_price',0):.2f} | "
                f"-> exit ${exit_sim['exit_price']:.2f} [{exit_sim['exit_reason']}] "
                f"pnl {exit_sim['pnl_pct']:+.1f}%")
        if exit_sim.get("partial_events"):
            line += " | partials: " + "; ".join(f"{t} {r}" for t, r in exit_sim["partial_events"])
        results.append((symbol, day, strat, line))

    print("=" * 100)
    print("MOMENTUMX BACKTEST — local bar_store (no Alpaca API calls)")
    print("=" * 100)
    trades = []
    for r in results:
        if len(r) == 4 and r[2] in ("NO DATA", "NO SIGNAL"):
            print(f"{r[0]:5s} {r[1]}  {r[2]:9s} {r[3]}")
        else:
            print(r[3])
            m = re.search(r"pnl ([+-][\d.]+)%", r[3])
            if m:
                trades.append(float(m.group(1)))
    print("=" * 100)
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    flat = [t for t in trades if abs(t) < 0.001]
    print(f"TOTAL {hits} fired | {misses} missed (no data / no signal)")
    if trades:
        print(f"P&L: {sum(wins)+sum(losses):+.1f}% | {len(wins)}W/{len(losses)}L/{len(flat)}F")
        print(f"Avg win: {sum(wins)/len(wins):+.1f}% | Avg loss: {sum(losses)/len(losses):+.1f}%" if wins and losses else "")
        print(f"Profit factor: {sum(wins)/abs(sum(losses)):.2f}" if losses else "")

asyncio.run(main())