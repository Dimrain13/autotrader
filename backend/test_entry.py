import sys, asyncio
sys.path.insert(0, "/opt/autotrader/backend")
import dotenv; dotenv.load_dotenv("/opt/autotrader/backend/.env")
from services.bar_store import load_bars
from services.auto_trader_service import auto_trader as AT

async def test():
    for sym in ["CGTL", "GRSD", "AEYE"]:
        bars = load_bars(sym, "2026-08-14")
        if not bars:
            print(f"{sym}: NO BARS")
            continue
        w = bars[:]
        AT._get_real_bars = lambda s, timeframe="1Min", limit=100: w[-limit:]
        for cc in [2, 3, 4, 5]:
            fp = await AT.check_entry_signals({"symbol": sym, "criteria_count": cc})
            fs = await AT.check_front_side_breakout({"symbol": sym, "criteria_count": cc})
            f9 = await AT.check_9_ema_dip_entry({"symbol": sym, "criteria_count": cc})
            vw = await AT.check_vwap_bounce_entry({"symbol": sym, "criteria_count": cc})
            any_hit = "fp" if fp else "" + " fs" if fs else "" + " f9" if f9 else "" + " vw" if vw else "none"
            print(f"  cc={cc}: {any_hit.strip() or 'none'}")
            if fp: print(f"    FP: entry={fp.get('entry_price')} stop={fp.get('stop_loss_price')} target={fp.get('target_price')}")

asyncio.run(test())