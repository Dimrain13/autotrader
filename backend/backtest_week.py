#!/usr/bin/env python3
"""
MomentumX last-week backtest (Aug 10-14, 2026).

For every (symbol, date) the bot actually traded, PLUS Ross Cameron's tickers,
replay the CURRENTLY-DEPLOYED strategy code against historical 1-min bars to
answer: under today's settings (no-news scalp OFF, volume-inferred catalyst,
front-side/flat-top/9-ema fixes, 11:30 cutoff, no consecutive-loss halt),
what entries and exits WOULD the bot have made?

Runs on the VPS (real venv, real Alpaca keys, real deployed strategy methods).
"""
import asyncio
import sys
import pathlib
import datetime as dt
import json

sys.path.insert(0, "/opt/autotrader/backend")
from dotenv import load_dotenv
load_dotenv(pathlib.Path("/opt/autotrader/backend/.env"))

import httpx
import os

from services.auto_trader_service import auto_trader as AT

API_KEY = os.environ["ALPACA_API_KEY"]
SECRET = os.environ["ALPACA_SECRET_KEY"]
BASE = "https://data.alpaca.markets"

# ---------------------------------------------------------------- universe
# (symbol, date) pairs: Ross's tickers first, then every bot AUTO-BUY ticker.
UNIVERSE = [
    # Ross Cameron's tickers (the ones we kept missing)
    ("SCKT", "2026-08-10"), ("JWEL", "2026-08-10"),
    ("FRTT", "2026-08-11"),
    ("RMCF", "2026-08-12"),
    ("XHG", "2026-08-13"), ("FGI", "2026-08-13"),
    # Bot's actual trades
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

# Trading window in UTC. Bot trades 7:00 AM - 1:00 PM ET (entries cutoff 11:30 ET).
# ET = UTC-4 in August (EDT). 7:00 ET = 11:00 UTC, 13:00 ET = 17:00 UTC.
DAY_START_UTC = "11:00:00Z"
DAY_END_UTC = "17:00:00Z"


async def fetch_day_bars(symbol: str, day: str, client: httpx.AsyncClient):
    """Fetch one full day of 1-min bars (regular session) for a historical day."""
    url = f"{BASE}/v2/stocks/{symbol}/bars"
    params = {
        "timeframe": "1Min",
        "start": f"{day}T{DAY_START_UTC}",
        "end": f"{day}T{DAY_END_UTC}",
        "limit": 1000,
        "adjustment": "raw",
        "feed": "sip",
    }
    h = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET}
    r = await client.get(url, params=params, headers=h, timeout=30)
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:120]}"}
    bars = r.json().get("bars", [])
    out = []
    for b in bars:
        out.append({
            "timestamp": b["t"],
            "open": float(b["o"]), "high": float(b["h"]),
            "low": float(b["l"]), "close": float(b["c"]),
            "volume": int(b["v"]),
        })
    return {"bars": out}


def fmt_ts(ts: str) -> str:
    """UTC ISO -> HH:MM (UTC)."""
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        return ts


def simulate_exit(sig: dict, bars: list, start_idx: int) -> dict:
    """
    Replicate monitor_exits() rules on the bars AFTER entry.
    Returns dict(exit_price, exit_time, exit_reason, pnl_pct, partial_events).
    """
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
        # update highest / trailing (1% trail)
        if b["high"] > highest:
            highest = b["high"]
            new_trail = highest * (1 - AT.trailing_stop_pct)
            if new_trail > trailing_stop:
                trailing_stop = new_trail

        cur_close = b["close"]
        cur_high = b["high"]
        cur_low = b["low"]

        # seconds since entry (for bailout)
        try:
            e = dt.datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
            c = dt.datetime.fromisoformat(b["timestamp"].replace("Z", "+00:00"))
            secs = (c - e).total_seconds()
        except Exception:
            secs = 0

        in_profit = cur_close > entry

        # --- topping tail (in profit, long upper wick)
        topping_tail = False
        if in_profit:
            rng = max(b["high"] - b["low"], 0.01)
            wick = (b["high"] - b["close"]) / rng
            topping_tail = b["high"] > entry and wick >= AT.topping_tail_wick_ratio

        # --- first red candle exit (in profit, not yet partial-sold)
        red_candle = False
        if AT.red_candle_exit_enabled and not partial_done and in_profit and i >= 1:
            prev = bars[i - 1]
            if prev["close"] < prev["open"]:
                red_candle = True

        # --- extension bar spike exit (in profit)
        spike = False
        if AT.extension_bar_spike_exit_enabled and in_profit and i >= 6:
            ranges = [abs(bars[j]["high"] - bars[j]["low"]) for j in range(i - 5, i)]
            avg = sum(ranges) / len(ranges) if ranges else 0.01
            cur = abs(b["high"] - b["low"])
            if avg > 0 and cur >= avg * AT.extension_bar_spike_multiplier:
                spike = True

        first_stage_target = psych if (psych and not partial_done) else None
        first_stage_hit = first_stage_target is not None and cur_close >= first_stage_target
        final_hit = cur_close >= target

        # --- partial profit at psych target
        if not partial_done and first_stage_hit and not final_hit and AT.enable_partial_profit:
            partial_events.append((fmt_ts(b["timestamp"]), "PARTIAL@%.2f" % first_stage_target))
            partial_done = True
            trailing_stop = max(trailing_stop, round(entry * (1 + AT.breakeven_buffer_pct), 2))
            continue  # partial: keep running the runner

        # --- full exits
        if not partial_done and (final_hit or topping_tail):
            if final_hit:
                return {"exit_price": target, "exit_time": fmt_ts(b["timestamp"]),
                        "exit_reason": "PROFIT TARGET HIT", "pnl_pct": (target - entry) / entry * 100,
                        "partial_events": partial_events}
            else:
                return {"exit_price": cur_close, "exit_time": fmt_ts(b["timestamp"]),
                        "exit_reason": "TOPPING TAIL", "pnl_pct": (cur_close - entry) / entry * 100,
                        "partial_events": partial_events}

        if partial_done and (final_hit or topping_tail):
            px = target if final_hit else cur_close
            return {"exit_price": px, "exit_time": fmt_ts(b["timestamp"]),
                    "exit_reason": "FINAL TARGET HIT (runner)" if final_hit else "TOPPING TAIL (runner)",
                    "pnl_pct": (px - entry) / entry * 100, "partial_events": partial_events}

        # red candle / spike full exits (or partial if enabled)
        if red_candle:
            if AT.enable_partial_profit and not partial_done:
                partial_events.append((fmt_ts(b["timestamp"]), "RED-CANDLE PARTIAL"))
                partial_done = True
                trailing_stop = max(trailing_stop, round(entry * (1 + AT.breakeven_buffer_pct), 2))
            else:
                return {"exit_price": cur_close, "exit_time": fmt_ts(b["timestamp"]),
                        "exit_reason": "FIRST RED CANDLE", "pnl_pct": (cur_close - entry) / entry * 100,
                        "partial_events": partial_events}
        if spike:
            if AT.enable_partial_profit and not partial_done:
                partial_events.append((fmt_ts(b["timestamp"]), "SPIKE PARTIAL"))
                partial_done = True
                trailing_stop = max(trailing_stop, round(entry * (1 + AT.breakeven_buffer_pct), 2))
            else:
                return {"exit_price": cur_close, "exit_time": fmt_ts(b["timestamp"]),
                        "exit_reason": "EXTENSION SPIKE", "pnl_pct": (cur_close - entry) / entry * 100,
                        "partial_events": partial_events}

        # structural / trailing stop (bar low pierced)
        if cur_low <= trailing_stop:
            px = trailing_stop
            return {"exit_price": px, "exit_time": fmt_ts(b["timestamp"]),
                    "exit_reason": "BREAKEVEN STOP" if partial_done else "STRUCTURAL STOP",
                    "pnl_pct": (px - entry) / entry * 100, "partial_events": partial_events}

        # breakout or bailout
        if not partial_done and cur_close <= entry and secs >= bailout_seconds:
            return {"exit_price": cur_close, "exit_time": fmt_ts(b["timestamp"]),
                    "exit_reason": "BREAKOUT/BAILOUT", "pnl_pct": (cur_close - entry) / entry * 100,
                    "partial_events": partial_events}

    # ran out of bars -> end of trading window (1 PM ET = 17:00 UTC)
    last = bars[-1]
    return {"exit_price": last["close"], "exit_time": fmt_ts(last["timestamp"]),
            "exit_reason": "END OF WINDOW", "pnl_pct": (last["close"] - entry) / entry * 100,
            "partial_events": partial_events}


async def replay_symbol(day_bars: list, symbol: str):
    """Slide a window over the day, run each strategy at every bar, return all signals."""
    signals = []  # list of (strategy, bar_idx, sig_dict)
    n = len(day_bars)
    if n < 60:
        return signals

    # Pre-compute cumulative volume ratio once (approximate scanner volume_ratio):
    # session cumulative volume vs first 30-min volume pace. We mainly use it to
    # decide 5/5 (>=10x) vs 4/5 for the volume-inferred catalyst rule.
    total_vol = sum(b["volume"] for b in day_bars)

    for i in range(59, n):
        window = day_bars[:i + 1]
        bars_for_check = window[-250:]  # front-side needs up to 250

        # Monkeypatch _get_real_bars so the REAL strategy methods use our window.
        async def _grb(sym, timeframe="1Min", limit=100):
            return bars_for_check[-limit:]

        orig = AT._get_real_bars
        AT._get_real_bars = _grb
        try:
            # ---- Strategy 1: First Pullback (needs 5/5)
            stock5 = {"symbol": symbol, "criteria_count": 5}
            es = await AT.check_entry_signals(stock5)
            if es:
                es["strategy_name"] = "First Pullback"
                signals.append(("First Pullback", i, es))

            # ---- Strategy 3: Bull Flag
            stock5b = {"symbol": symbol, "criteria_count": 5}
            bf = await AT.check_bull_flag_entry(stock5b)
            if bf:
                bf["strategy_name"] = "Bull Flag"
                signals.append(("Bull Flag", i, bf))

            # ---- Strategy 8: Front-Side Breakout (4+/5)
            stock4 = {"symbol": symbol, "criteria_count": 4}
            fs = await AT.check_front_side_breakout(stock4)
            if fs:
                fs["strategy_name"] = "Front-Side Breakout"
                signals.append(("Front-Side", i, fs))

            # ---- Strategy 4: VWAP Bounce
            vw = await AT.check_vwap_bounce_entry(stock5b)
            if vw:
                vw["strategy_name"] = "VWAP Bounce"
                signals.append(("VWAP Bounce", i, vw))

            # ---- Strategy 5: ORB
            orb = await AT.check_orb_entry(stock5b)
            if orb:
                orb["strategy_name"] = "ORB"
                signals.append(("ORB", i, orb))

            # ---- Strategy 7: Flat Top (4+/5)
            ft = await AT.check_flat_top_breakout(stock4)
            if ft:
                ft["strategy_name"] = "Flat Top"
                signals.append(("Flat Top", i, ft))

            # ---- Strategy 6: 9 EMA Dip (4+/5)
            e9 = await AT.check_9_ema_dip_entry(stock4)
            if e9:
                e9["strategy_name"] = "9 EMA Dip"
                signals.append(("9 EMA Dip", i, e9))
        finally:
            AT._get_real_bars = orig

    return signals


async def main():
    async with httpx.AsyncClient() as client:
        results = []
        seen = set()
        for symbol, day in UNIVERSE:
            key = (symbol, day)
            if key in seen:
                continue
            seen.add(key)

            fd = await fetch_day_bars(symbol, day, client)
            if "error" in fd:
                results.append((symbol, day, "NO DATA", fd["error"]))
                continue
            bars = fd["bars"]
            if not bars:
                results.append((symbol, day, "NO DATA", "no bars (inactive/delisted)"))
                continue

            sigs = await replay_symbol(bars, symbol)
            if not sigs:
                results.append((symbol, day, "NO SIGNAL", f"{len(bars)} bars, no strategy fired"))
                continue

            # take first signal (earliest bar) as the entry the bot would take
            sigs_sorted = sorted(sigs, key=lambda s: s[1])
            first = sigs_sorted[0]
            strat, idx, sig = first
            entry = sig["entry_price"]
            exit_sim = simulate_exit(sig, bars, idx)
            line = (
                f"{symbol:5s} {day}  {strat:18s} entry ${entry:.2f} @ {fmt_ts(bars[idx]['timestamp'])} "
                f"(bar {idx}) | stop ${sig['stop_loss_price']:.2f} | target ${sig.get('target_price',0):.2f} | "
                f"-> exit ${exit_sim['exit_price']:.2f} [{exit_sim['exit_reason']}] "
                f"pnl {exit_sim['pnl_pct']:+.1f}%"
            )
            if exit_sim["partial_events"]:
                line += " | partials: " + "; ".join(f"{t} {r}" for t, r in exit_sim["partial_events"])
            results.append((symbol, day, strat, line))

    # print
    print("=" * 100)
    print("MOMENTUMX LAST-WEEK BACKTEST — current settings replayed on historical 1-min bars")
    print("=" * 100)
    for r in results:
        if len(r) == 4 and r[2] in ("NO DATA", "NO SIGNAL"):
            print(f"{r[0]:5s} {r[1]}  {r[2]:9s} {r[3]}")
        else:
            print(r[3])
    print("=" * 100)
    n_sig = sum(1 for r in results if len(r) == 4 and r[2] not in ("NO DATA", "NO SIGNAL"))
    n_nodata = sum(1 for r in results if len(r) == 4 and r[2] == "NO DATA")
    n_nosig = sum(1 for r in results if len(r) == 4 and r[2] == "NO SIGNAL")
    print(f"TOTAL {len(results)} ticker-days | {n_sig} fired | {n_nosig} no-signal | {n_nodata} no-data")


asyncio.run(main())
