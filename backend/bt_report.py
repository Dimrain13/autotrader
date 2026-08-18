#!/usr/bin/env python3
"""Faithful minute-by-minute replay -> writes a full per-stock report CSV + summary."""
import os, sys, pathlib, asyncio, datetime as dt, csv, io
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from pymongo import MongoClient
from services.auto_trader_service import auto_trader as AT
from services.bar_store import load_bars, has_bars
import services.alpaca_service as alpaca_mod

m = MongoClient(); db = m.momentumx

universe = {}
for r in db.missed_opportunities.find({"date": {"$gte": "2026-07-15", "$lte": "2026-08-14"}}):
    sym, day = r.get("symbol"), r.get("date")
    if not sym or not day: continue
    key = (sym, day)
    if key not in universe:
        universe[key] = r.get("criteria_count", 4)

class ReplayState:
    def __init__(self):
        self.position = None
        self.sold = []
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

async def replay_day(sym, day, bars, rs):
    n = len(bars)
    orig_get_bars = AT._get_real_bars
    orig_is_th = AT.is_trading_hours
    AT.is_trading_hours = lambda: True

    trade = None
    for i in range(59, n):
        window = bars[:i+1]
        async def grb(s, timeframe="1Min", limit=100, _w=window):
            return _w[-limit:]
        AT._get_real_bars = grb

        entry_sig = None; entry_name = None
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
                entry_sig = sig; entry_name = name; break
        if not entry_sig:
            continue

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

        exit_info = None
        for j in range(i+1, n):
            b = bars[j]
            # Re-read trailing_stop (monitor_exits updates it when price moves higher)
            trailing_stop = pos.get("trailing_stop", stop)
            effective_price = b["close"]
            stop_hit = b["low"] <= trailing_stop
            if stop_hit:
                # Exchange StopOrderRequest fires at the stop price mid-bar.
                # If bar gapped below stop, fill is at the open (conservative).
                effective_price = min(trailing_stop, b["open"])
            rs.set_position(sym, 100, effective_price)
            alpaca_mod.alpaca_service.get_positions = rs.get_positions
            orig_sell = AT.sell_with_retry
            orig_verify = AT.verify_position_closed
            AT.sell_with_retry = rs.sell
            AT.verify_position_closed = rs.verify_closed
            AT._get_real_bars = (lambda s, timeframe="1Min", limit=100, _w=bars[:j+1]: _w[-limit:])
            try:
                await AT.monitor_exits(50000)
            finally:
                AT.sell_with_retry = orig_sell
                AT.verify_position_closed = orig_verify
            if sym not in AT.open_positions:
                exit_price = effective_price
                reason = rs.sold[-1][1] if rs.sold else "CLOSED"
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                exit_info = (bars[j]["timestamp"], exit_price, reason, pnl_pct)
                break

        if exit_info is None:
            exit_price = bars[-1]["close"]
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            exit_info = (bars[-1]["timestamp"], exit_price, "EOD STILL OPEN", pnl_pct)

        trade = {
            "symbol": sym, "date": day, "strategy": entry_name,
            "entry_time": bars[i]["timestamp"][11:16],
            "entry_price": round(entry_price, 4),
            "stop": round(stop, 4),
            "target": round(target, 4),
            "exit_time": exit_info[0][11:16],
            "exit_price": round(exit_info[1], 4),
            "reason": exit_info[2],
            "pnl_pct": round(exit_info[3], 2),
            "no_news": is_no_news,
        }
        AT.open_positions.pop(sym, None)
        break

    AT._get_real_bars = orig_get_bars
    AT.is_trading_hours = orig_is_th
    return trade

async def main():
    rs = ReplayState()
    trades = []
    for (sym, day) in sorted(universe.keys()):
        if not has_bars(sym, day):
            continue
        bars = load_bars(sym, day)
        if len(bars) < 60:
            continue
        t = await replay_day(sym, day, bars, rs)
        if t:
            trades.append(t)

    # Write CSV
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["symbol","date","strategy","entry_time","entry_price","stop","target","exit_time","exit_price","reason","pnl_pct","no_news"])
    w.writeheader()
    for t in trades:
        w.writerow(t)
    with open("/tmp/replay_report.csv", "w") as f:
        f.write(out.getvalue())

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] < 0]
    s = sum(t["pnl_pct"] for t in trades)
    print(f"REPORT WRITTEN: /tmp/replay_report.csv")
    print(f"Trades: {len(trades)} ({len(wins)}W/{len(losses)}L)")
    print(f"Cumulative P&L: {s:+.1f}%")
    if wins and losses:
        print(f"Avg win {sum(t['pnl_pct'] for t in wins)/len(wins):+.1f}% | Avg loss {sum(t['pnl_pct'] for t in losses)/len(losses):+.1f}% | PF {sum(t['pnl_pct'] for t in wins)/abs(sum(t['pnl_pct'] for t in losses)):.2f}")

asyncio.run(main())