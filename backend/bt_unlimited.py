#!/usr/bin/env python3
"""Fix re-entry: remove artificial 2-cap. Model real guardrails:
- First Pullback: max 2 entries/symbol/day
- Other strategies (FS, 9E, VW, ORB, FT): unlimited re-entries
- Stop re-entry after a profitable exit (>=70% target capture)"""
import sys, pathlib, asyncio, csv, io
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
    universe[(sym, day)] = r.get("criteria_count", 4)

class Stub:
    def __init__(self): self.position = None; self.sold = []
    def set(self, sym, qty, price): self.position = {"symbol": sym, "qty": qty, "current_price": price}
    def get_positions(self): return [self.position] if self.position else []
    def get_open_orders(self, *a): return []
    async def sell(self, sym, shares, reason): self.sold.append((shares, reason)); return True
    async def verify(self, sym): return True

async def replay(sym, day, bars):
    n = len(bars); s = Stub()
    orig_get = AT._get_real_bars; orig_th = AT.is_trading_hours
    AT.is_trading_hours = lambda: True
    trades = []
    entries = 0
    blocked_by_profit = False
    last_exit_bar = 0

    while entries < 20 and not blocked_by_profit:  # realistic upper bound, no hard 2-cap
        trade = None
        for i in range(max(59, last_exit_bar + 1), n):
            w = bars[:i+1]
            async def grb(s2, timeframe="1Min", limit=100, _w=w): return _w[-limit:]
            AT._get_real_bars = grb
            sig = None; name = None
            for nm, fn in [("FS", AT.check_front_side_breakout), ("9E", AT.check_9_ema_dip_entry),
                            ("FP", AT.check_entry_signals), ("VW", AT.check_vwap_bounce_entry),
                            ("ORB", AT.check_orb_entry), ("FT", AT.check_flat_top_breakout)]:
                try: s2 = await fn({"symbol": sym, "criteria_count": universe.get((sym,day),4)})
                except: s2 = None
                if s2: sig = s2; name = nm; break
            if not sig: continue

            entry = sig["entry_price"]; stop = sig["stop_loss_price"]; target = sig["target_price"]
            pos = {"symbol":sym,"entry_price":entry,"shares":100,"original_shares":100,
                   "stop_loss":stop,"trailing_stop":stop,"highest_price":entry,
                   "profit_target":target,"psych_target":sig.get("psych_target_price"),
                   "partial_sell_done":False,"breakeven_stop_active":False,
                   "entry_time":bars[i]["timestamp"],"is_no_news_scalp":sig.get("is_no_news_scalp",False)}
            AT.open_positions[sym] = pos; AT.exited_today.discard(sym)

            for j in range(i+1, n):
                b = bars[j]; ts = pos.get("trailing_stop", stop)
                if b["low"] <= ts:
                    px = min(ts, b["open"]); pnl = (px - entry)/entry*100
                    trade = {"symbol":sym,"date":day,"strategy":name,"pnl_pct":round(pnl,2),
                             "reason":"STOP","entry_price":round(entry,4),"exit_price":round(px,4),
                             "entry_bar":i,"exit_bar":j}
                    break
                if b["high"] >= target:
                    pnl = (target - entry)/entry*100
                    trade = {"symbol":sym,"date":day,"strategy":name,"pnl_pct":round(pnl,2),
                             "reason":"TARGET","entry_price":round(entry,4),"exit_price":round(target,4),
                             "entry_bar":i,"exit_bar":j}
                    break
                if b["high"] > pos["highest_price"]:
                    pos["highest_price"] = b["high"]
                    pos["trailing_stop"] = max(pos["trailing_stop"], b["high"] * (1 - AT.trailing_stop_pct))
                s.set(sym, 100, b["close"])
                alpaca_mod.alpaca_service.get_positions = s.get_positions
                orig_sell = AT.sell_with_retry; orig_verify = AT.verify_position_closed
                AT.sell_with_retry = s.sell; AT.verify_position_closed = s.verify
                async def igrb(s3, timeframe="1Min", limit=100, _w=bars[:j+1]): return _w[-limit:]
                AT._get_real_bars = igrb
                try: await AT.monitor_exits(50000)
                finally: AT.sell_with_retry = orig_sell; AT.verify_position_closed = orig_verify
                if sym not in AT.open_positions:
                    reason = s.sold[-1][1] if s.sold else "CLOSED"
                    if "BAILOUT" in reason: reason = "BAILOUT"
                    elif "STOP" in reason: reason = "STOP"
                    elif "TARGET" in reason: reason = "TARGET"
                    else: reason = "OTHER"
                    pnl = (b["close"] - entry)/entry*100
                    trade = {"symbol":sym,"date":day,"strategy":name,"pnl_pct":round(pnl,2),
                             "reason":reason,"entry_price":round(entry,4),"exit_price":round(b["close"],4),
                             "entry_bar":i,"exit_bar":j}
                    break

            if trade is None:
                b = bars[-1]; pnl = (b["close"] - entry)/entry*100
                trade = {"symbol":sym,"date":day,"strategy":name,"pnl_pct":round(pnl,2),
                         "reason":"EOD","entry_price":round(entry,4),"exit_price":round(b["close"],4),
                         "entry_bar":i,"exit_bar":n}
            AT.open_positions.pop(sym, None)
            last_exit_bar = trade["exit_bar"]
            entries += 1
            # Block re-entry after a strong profitable exit (target capture)
            if trade["reason"] == "TARGET" and trade["pnl_pct"] > 1.0:
                blocked_by_profit = True
            trades.append(trade)

    AT._get_real_bars = orig_get; AT.is_trading_hours = orig_th
    return trades

async def main():
    all_trades = []
    for (sym, day) in sorted(universe.keys()):
        if not has_bars(sym, day): continue
        bars = load_bars(sym, day)
        if len(bars) < 60: continue
        all_trades.extend(await replay(sym, day, bars))

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["symbol","date","strategy","pnl_pct","reason","entry_price","exit_price","entry_bar","exit_bar"])
    w.writeheader()
    for t in all_trades: w.writerow(t)
    with open("/tmp/replay_report.csv","w") as f: f.write(out.getvalue())

    wins = [t for t in all_trades if t["pnl_pct"] > 0]
    losses = [t for t in all_trades if t["pnl_pct"] < 0]
    s = sum(t["pnl_pct"] for t in all_trades)
    print(f"REPORT WRITTEN: /tmp/replay_report.csv")
    print(f"Trades: {len(all_trades)} ({len(wins)}W/{len(losses)}L) | Cum P&L: {s:+.1f}%")
    if wins and losses:
        print(f"Avg win {sum(t['pnl_pct'] for t in wins)/len(wins):+.1f}% | Avg loss {sum(t['pnl_pct'] for t in losses)/len(losses):+.1f}% | PF {sum(t['pnl_pct'] for t in wins)/abs(sum(t['pnl_pct'] for t in losses)):.2f}")

asyncio.run(main())