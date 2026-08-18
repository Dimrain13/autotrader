#!/usr/bin/env python3
"""Clean replay v3: exchange stop is the primary exit. monitor_exits only runs
for software triggers (target, bailout, topping tail). No double-counting."""
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
    key = (sym, day); universe[key] = r.get("criteria_count", 4)

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
    trade = None
    for i in range(59, n):
        w = bars[:i+1]
        async def grb(s2, timeframe="1Min", limit=100, _w=w): return _w[-limit:]
        AT._get_real_bars = grb
        sig = None; name = None
        for nm, fn in [("FP", AT.check_entry_signals),("FS", AT.check_front_side_breakout),
                        ("VW", AT.check_vwap_bounce_entry),("ORB", AT.check_orb_entry),
                        ("FT", AT.check_flat_top_breakout),("9E", AT.check_9_ema_dip_entry)]:
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
        
        # Walk forward: exchange stop check first, then software exit
        for j in range(i+1, n):
            b = bars[j]
            ts = pos.get("trailing_stop", stop)
            # PRIORITY 1: Exchange stop hit? Bar low pierces stop price.
            if b["low"] <= ts:
                px = min(ts, b["open"])  # if gapped, fill at open
                pnl = (px - entry)/entry*100
                trade = {"symbol":sym,"date":day,"strategy":name,
                         "entry_time":bars[i]["timestamp"][11:16],"entry_price":round(entry,4),
                         "stop":round(stop,4),"target":round(target,4),
                         "exit_time":b["timestamp"][11:16],"exit_price":round(px,4),
                         "reason":"STOP (exchange)","pnl_pct":round(pnl,2),"no_news":False}
                AT.open_positions.pop(sym, None); break
            
            # PRIORITY 2: Profit target hit mid-bar?
            if b["high"] >= target:
                pnl = (target - entry)/entry*100
                trade = {"symbol":sym,"date":day,"strategy":name,
                         "entry_time":bars[i]["timestamp"][11:16],"entry_price":round(entry,4),
                         "stop":round(stop,4),"target":round(target,4),
                         "exit_time":b["timestamp"][11:16],"exit_price":round(target,4),
                         "reason":"TARGET","pnl_pct":round(pnl,2),"no_news":False}
                AT.open_positions.pop(sym, None); break
            
            # PRIORITY 3: Run software monitor_exits on bar close
            # (bailout, trailing stop update, topping tail, etc.)
            # Update highest_price for trailing stop calculation
            if b["high"] > pos["highest_price"]:
                pos["highest_price"] = b["high"]
                pos["trailing_stop"] = max(pos["trailing_stop"], b["high"] * (1 - AT.trailing_stop_pct))
            
            s.set(sym, 100, b["close"])
            alpaca_mod.alpaca_service.get_positions = s.get_positions
            orig_sell = AT.sell_with_retry; orig_verify = AT.verify_position_closed
            AT.sell_with_retry = s.sell; AT.verify_position_closed = s.verify
            AT._get_real_bars = (lambda s2, timeframe="1Min", limit=100, _w=bars[:j+1]: _w[-limit:])
            try: await AT.monitor_exits(50000)
            finally: AT.sell_with_retry = orig_sell; AT.verify_position_closed = orig_verify
            if sym not in AT.open_positions:
                px = b["close"]
                reason = s.sold[-1][1] if s.sold else "CLOSED"
                pnl = (px - entry)/entry*100
                trade = {"symbol":sym,"date":day,"strategy":name,
                         "entry_time":bars[i]["timestamp"][11:16],"entry_price":round(entry,4),
                         "stop":round(stop,4),"target":round(target,4),
                         "exit_time":b["timestamp"][11:16],"exit_price":round(px,4),
                         "reason":reason,"pnl_pct":round(pnl,2),"no_news":False}
                AT.open_positions.pop(sym, None); break
        
        if trade is None:
            px = bars[-1]["close"]; pnl = (px - entry)/entry*100
            trade = {"symbol":sym,"date":day,"strategy":name,
                     "entry_time":bars[i]["timestamp"][11:16],"entry_price":round(entry,4),
                     "stop":round(stop,4),"target":round(target,4),
                     "exit_time":bars[-1]["timestamp"][11:16],"exit_price":round(px,4),
                     "reason":"EOD","pnl_pct":round(pnl,2),"no_news":False}
        AT.open_positions.pop(sym, None); break
    
    AT._get_real_bars = orig_get; AT.is_trading_hours = orig_th
    return trade

async def main():
    trades = []
    for (sym, day) in sorted(universe.keys()):
        if not has_bars(sym, day): continue
        bars = load_bars(sym, day)
        if len(bars) < 60: continue
        t = await replay(sym, day, bars)
        if t: trades.append(t)
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=["symbol","date","strategy","entry_time","entry_price","stop","target","exit_time","exit_price","reason","pnl_pct","no_news"])
    w.writeheader()
    for t in trades: w.writerow(t)
    with open("/tmp/replay_report.csv","w") as f: f.write(out.getvalue())
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] < 0]
    s = sum(t["pnl_pct"] for t in trades)
    print(f"REPORT WRITTEN: /tmp/replay_report.csv")
    print(f"Trades: {len(trades)} ({len(wins)}W/{len(losses)}L) | Cum P&L: {s:+.1f}%")
    if wins and losses:
        print(f"Avg win {sum(t['pnl_pct'] for t in wins)/len(wins):+.1f}% | Avg loss {sum(t['pnl_pct'] for t in losses)/len(losses):+.1f}% | PF {sum(t['pnl_pct'] for t in wins)/abs(sum(t['pnl_pct'] for t in losses)):.2f}")

asyncio.run(main())