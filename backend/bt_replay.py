#!/usr/bin/env python3
"""
Faithful minute-by-minute replay.

For each missed 4/5+ ticker-day:
  1. Walk every 1-min bar. At each bar, run the REAL entry checks
     (check_entry_signals, check_front_side_breakout, ...) with _get_real_bars
     monkeypatched to return bars up to that minute.
  2. On a signal, populate open_positions EXACTLY as execute_entry does,
     then walk forward bar-by-bar calling the REAL monitor_exits() with
     alpaca_service.get_positions + sell_with_retry + verify_position_closed
     stubbed so the real decision tree runs against replayed bars.

Only I/O is stubbed. Entry/exit DECISIONS are the deployed code paths.
"""
import os, sys, pathlib, asyncio, datetime as dt, types
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from pymongo import MongoClient
from services.auto_trader_service import auto_trader as AT
from services.bar_store import load_bars, has_bars
import services.trade_history_service as ths
import services.alpaca_service as alpaca_mod

m = MongoClient(); db = m.momentumx

# Pull missed 4/5+ ticker-days
universe = {}
for r in db.missed_opportunities.find({"date": {"$gte": "2026-07-15", "$lte": "2026-08-14"}}):
    sym, day = r.get("symbol"), r.get("date")
    if not sym or not day: continue
    key = (sym, day)
    if key not in universe:
        universe[key] = r.get("criteria_count", 4)

print(f"Universe: {len(universe)} missed 4/5+ ticker-days")

class ReplayState:
    """Stub the Alpaca I/O so monitor_exits() runs its real decision tree."""
    def __init__(self, bars):
        self.bars = bars
        self.current_idx = 0
        self.sold = []  # list of (shares, reason) for exit recording
        self.position = None  # fake alpaca position dict

    def set_position(self, sym, qty, price):
        self.position = {"symbol": sym, "qty": qty, "current_price": price}

    def get_positions(self):
        return [self.position] if self.position else []

    def get_open_orders(self, symbol=None):
        return []

    async def sell(self, symbol, shares, reason):
        self.sold.append((shares, reason))
        return True

    async def verify_closed(self, symbol):
        return True

async def replay_day(sym, day, bars):
    """Run real entry checks bar-by-bar, then real monitor_exits on entry."""
    rs = ReplayState(bars)
    n = len(bars)
    results = []

    # Patch AT._get_real_bars to serve bars up to the current replay index
    orig_get_bars = AT._get_real_bars

    for i in range(59, n):
        window = bars[:i+1]
        async def grb(s, timeframe="1Min", limit=100):
            return window[-limit:]
        AT._get_real_bars = grb

        entry_sig = None
        entry_name = None
        for name, fn in [
            ("First Pullback", AT.check_entry_signals),
            ("Front-Side", AT.check_front_side_breakout),
            ("VWAP Bounce", AT.check_vwap_bounce_entry),
            ("ORB", AT.check_orb_entry),
            ("Flat Top", AT.check_flat_top_breakout),
            ("9 EMA Dip", AT.check_9_ema_dip_entry),
        ]:
            try:
                sig = await fn({"symbol": sym, "criteria_count": universe.get((sym, day), 4)})
            except Exception:
                sig = None
            if sig:
                entry_sig = sig
                entry_name = name
                break

        if not entry_sig:
            continue

        # Entry found at bar i. Build position_data exactly as execute_entry does.
        entry_price = entry_sig["entry_price"]
        stop = entry_sig["stop_loss_price"]
        target = entry_sig["target_price"]
        psych = entry_sig.get("psych_target_price")
        is_no_news = entry_sig.get("is_no_news_scalp", False)

        pos = {
            "symbol": sym, "entry_price": entry_price,
            "shares": 100, "original_shares": 100,
            "stop_loss": stop, "trailing_stop": stop,
            "highest_price": entry_price, "profit_target": target,
            "psych_target": psych, "partial_sell_done": False,
            "breakeven_stop_active": False,
            "entry_time": bars[i]["timestamp"],
            "is_no_news_scalp": is_no_news,
            "is_bull_flag": entry_sig.get("is_bull_flag", False),
            "is_front_side_breakout": entry_sig.get("is_front_side_breakout", False),
        }
        AT.open_positions[sym] = pos
        AT.exited_today.discard(sym)

        # Stub is_trading_hours to True so monitor_exits doesn't fire
        # "END OF TRADING WINDOW" on the real wall clock (it's after hours now).
        orig_is_th = AT.is_trading_hours
        AT.is_trading_hours = lambda: True

        # Now walk forward, calling real monitor_exits each bar.
        exit_info = None
        for j in range(i+1, n):
            b = bars[j]
            rs.set_position(sym, 100, b["close"])
            # stub get_positions + sell + verify
            alpaca_mod.alpaca_service.get_positions = rs.get_positions
            orig_sell = AT.sell_with_retry
            orig_verify = AT.verify_position_closed
            AT.sell_with_retry = rs.sell
            AT.verify_position_closed = rs.verify_closed
            AT._get_real_bars = (lambda s, timeframe="1Min", limit=100, _w=bars[:j+1]: _w[-limit:])
            try:
                orig_log = ths.trade_history.log_trade
                async def _nln(*a,**kw): return None
                ths.trade_history.log_trade = _nln  # backtest, do not pollute live trade_history
                try:
                    await AT.monitor_exits(50000)
                finally:
                    ths.trade_history.log_trade = orig_log
            finally:
                AT.sell_with_retry = orig_sell
                AT.verify_position_closed = orig_verify
            if sym not in AT.open_positions:
                # position closed this bar
                exit_price = b["close"]
                reason = rs.sold[-1][1] if rs.sold else "CLOSED"
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                exit_info = (bars[j]["timestamp"], exit_price, reason, pnl_pct)
                break

        if exit_info is None:
            # still open at end of day
            exit_price = bars[-1]["close"]
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            exit_info = (bars[-1]["timestamp"], exit_price, "EOD STILL OPEN", pnl_pct)

        # record
        results.append({
            "sym": sym, "day": day, "strategy": entry_name,
            "entry_time": bars[i]["timestamp"], "entry": entry_price,
            "stop": stop, "target": target,
            "exit_time": exit_info[0], "exit": exit_info[1],
            "reason": exit_info[2], "pnl_pct": exit_info[3],
        })

        # reset state for potential re-entry (match real bot's 2-entry max — we only do 1 here)
        AT.open_positions.pop(sym, None)
        AT._get_real_bars = orig_get_bars
        AT.is_trading_hours = orig_is_th
        # stop after first entry per day (real bot has re-entry rules; we capture the primary trade)
        break

    AT._get_real_bars = orig_get_bars
    return results

async def main():
    all_trades = []
    nodata = 0
    for (sym, day) in sorted(universe.keys()):
        if not has_bars(sym, day):
            nodata += 1
            continue
        bars = load_bars(sym, day)
        if len(bars) < 60:
            nodata += 1
            continue
        trades = await replay_day(sym, day, bars)
        all_trades.extend(trades)

    wins = [t for t in all_trades if t["pnl_pct"] > 0]
    losses = [t for t in all_trades if t["pnl_pct"] < 0]
    print("\n" + "="*100)
    print("FAITHFUL MINUTE-BY-MINUTE REPLAY — real check_* entry + real monitor_exits() exit")
    print("="*100)
    for t in all_trades:
        print(f"{t['sym']:6s} {t['day']}  {t['strategy']:14s} "
              f"entry ${t['entry']:.2f} @ {t['entry_time'][11:16]} → "
              f"exit ${t['exit']:.2f} @ {t['exit_time'][11:16]} "
              f"[{t['reason'][:40]:40s}] {t['pnl_pct']:+.1f}%")
    print("="*100)
    s = sum(t["pnl_pct"] for t in all_trades)
    print(f"Trades: {len(all_trades)} ({len(wins)}W/{len(losses)}L) | No-data/signal: {nodata}")
    print(f"Cumulative P&L: {s:+.1f}%")
    if wins and losses:
        print(f"Avg win {sum(t['pnl_pct'] for t in wins)/len(wins):+.1f}% | "
              f"Avg loss {sum(t['pnl_pct'] for t in losses)/len(losses):+.1f}% | "
              f"PF: {sum(t['pnl_pct'] for t in wins)/abs(sum(t['pnl_pct'] for t in losses)):.2f}")

asyncio.run(main())