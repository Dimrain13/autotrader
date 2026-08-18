#!/usr/bin/env python3
"""Validate replay against known Aug 14 actual trades."""
import sys, pathlib, asyncio
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from pymongo import MongoClient
from services.auto_trader_service import auto_trader as AT
from services.bar_store import load_bars, has_bars
import services.alpaca_service as alpaca_mod

m = MongoClient(); db = m.momentumx

# Actual Aug 14 traded tickers (unique)
traded = ["CGTL","GRSD","AEYE","WETO","HHS","DFSC","IMXI","VALN","NEXR","NPWR"]
day = "2026-08-14"

class Stub:
    def __init__(self): self.position = None; self.sold = []
    def set(self, sym, qty, price): self.position = {"symbol": sym, "qty": qty, "current_price": price}
    def get_positions(self): return [self.position] if self.position else []
    def get_open_orders(self, *a): return []
    async def sell(self, sym, shares, reason): self.sold.append((shares, reason)); return True
    async def verify(self, sym): return True

async def replay(sym, bars):
    s = Stub(); n = len(bars)
    orig_get = AT._get_real_bars; orig_th = AT.is_trading_hours
    AT.is_trading_hours = lambda: True
    trade = None
    for i in range(59, n):
        w = bars[:i+1]
        async def grb(s2, timeframe="1Min", limit=100, _w=w): return _w[-limit:]
        AT._get_real_bars = grb
        sig = None; name = None
        for nm, fn in [("FS", AT.check_front_side_breakout), ("9E", AT.check_9_ema_dip_entry),
                        ("FP", AT.check_entry_signals), ("VW", AT.check_vwap_bounce_entry)]:
            try: s2 = await fn({"symbol": sym, "criteria_count": 5})
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
            # Exchange stop
            if b["low"] <= ts:
                px = min(ts, b["open"])
                pnl = (px - entry)/entry*100
                trade = {"symbol":sym,"entry_price":round(entry,2),"stop":round(stop,2),"target":round(target,2),
                         "exit_price":round(px,2),"pnl_pct":round(pnl,1),"reason":"STOP","exit_bar":j-i}
                break
            # Target
            if b["high"] >= target:
                pnl = (target - entry)/entry*100
                trade = {"symbol":sym,"entry_price":round(entry,2),"stop":round(stop,2),"target":round(target,2),
                         "exit_price":round(target,2),"pnl_pct":round(pnl,1),"reason":"TARGET","exit_bar":j-i}
                break
            # Software exit
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
                reason = s.sold[-1][1] if s.sold else "CLOSED"
                # Simplify reason
                if "BAILOUT" in reason: reason = "BAILOUT"
                elif "STOP" in reason: reason = "STOP"
                elif "TARGET" in reason: reason = "TARGET"
                else: reason = "OTHER"
                pnl = (b["close"] - entry)/entry*100
                trade = {"symbol":sym,"entry_price":round(entry,2),"stop":round(stop,2),"target":round(target,2),
                         "exit_price":round(b["close"],2),"pnl_pct":round(pnl,1),"reason":reason,"exit_bar":j-i}
                break
        
        if trade is None:
            b = bars[-1]; pnl = (b["close"] - entry)/entry*100
            trade = {"symbol":sym,"entry_price":round(entry,2),"stop":round(stop,2),"target":round(target,2),
                     "exit_price":round(b["close"],2),"pnl_pct":round(pnl,1),"reason":"EOD","exit_bar":n-i}
        AT.open_positions.pop(sym, None); break
    
    AT._get_real_bars = orig_get; AT.is_trading_hours = orig_th
    return trade

async def main():
    print(f"{'SYM':6s} {'REPLAY ENTRY':>8s} {'STOP':>8s} {'TARGET':>8s} {'REPLAY EXIT':>8s} {'REPLAY %':>7s} {'REASON':12s} || {'ACTUAL P&L':>10s}")
    print("-" * 95)
    for sym in traded:
        if not has_bars(sym, day): continue
        bars = load_bars(sym, day)
        if len(bars) < 60: continue
        t = await replay(sym, bars)
        if t:
            # Get actual results
            actual = list(db.trade_history.find({
                "symbol": sym, "entry_time": {"$gte": "2026-08-14T11:00:00Z", "$lt": "2026-08-14T20:00:00Z"},
                "exit_time": {"$lt": "2026-08-14T20:00:00Z"}
            }).sort("entry_time", 1).limit(3))
            actual_str = " | ".join(f"${a['pnl']:.0f} {a['exit_reason'][:20]}" for a in actual)
            print(f"{t['symbol']:6s} ${t['entry_price']:>7.2f} ${t['stop']:>7.2f} ${t['target']:>7.2f} ${t['exit_price']:>7.2f} {t['pnl_pct']:>+6.1f}% {t['reason']:12s} || {actual_str}")
        else:
            print(f"{sym:6s} NO ENTRY SIGNAL")

asyncio.run(main())