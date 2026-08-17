"""Local bar persistence for backtesting. 
Stores 1-min bars in MongoDB so historical data is available locally."""
import os
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

_mongo = None
_collection = None

def _get_collection():
    global _mongo, _collection
    if _collection is None:
        _mongo = MongoClient()
        _collection = _mongo.momentumx.price_bars
    return _collection

def save_bars(symbol: str, bars: list, timeframe: str = "1Min", source: str = "alpaca_sip"):
    """Store bars for a given symbol+date+timeframe."""
    if not bars:
        return
    try:
        day_str = bars[0].get("timestamp", "")[:10]
        doc = {
            "symbol": symbol.upper(),
            "date": day_str,
            "timeframe": timeframe,
            "source": source,
            "bars": bars,
            "count": len(bars),
            "saved_at": datetime.now(timezone.utc).isoformat()
        }
        _get_collection().update_one(
            {"symbol": symbol.upper(), "date": day_str, "timeframe": timeframe},
            {"$set": doc},
            upsert=True
        )
    except Exception:
        pass

def load_bars(symbol: str, day: str, timeframe: str = "1Min") -> list:
    """Load stored bars. Returns empty list if not found."""
    doc = _get_collection().find_one({
        "symbol": symbol.upper(), "date": day, "timeframe": timeframe
    })
    return doc.get("bars", []) if doc else []

def has_bars(symbol: str, day: str, timeframe: str = "1Min") -> bool:
    """Check if we have stored bars for a given day."""
    return _get_collection().count_documents({
        "symbol": symbol.upper(), "date": day, "timeframe": timeframe
    }) > 0

def count_stored() -> dict:
    """Return stats on stored bar data."""
    coll = _get_collection()
    total = coll.count_documents({})
    symbols = coll.distinct("symbol")
    return {"total_days": total, "symbols": len(symbols), "symbols_list": symbols[:20]}
