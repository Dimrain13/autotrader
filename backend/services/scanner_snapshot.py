"""Scanner Snapshot Service.

Persists EVERY scanner result scoring 3/5 or better, every scan, with its full
metrics (price, %change, volume_ratio, float, criteria_met, ready_to_trade).

This is the canonical historical dataset for backtesting: what the scanner
actually saw each day, stored locally, so backtests replay against REAL
scanner output instead of re-fetching bars from the internet.

Dedups by (symbol, date): keeps the highest criteria_count snapshot per day.
"""
from datetime import datetime, timezone
from typing import List, Dict
import logging
from database import db

logger = logging.getLogger(__name__)


class ScannerSnapshotService:
    def __init__(self):
        self.collection = db.scanner_snapshots
        # compound index on (date, symbol) unique
        db.scanner_snapshots.create_index([("date", 1), ("symbol", 1)], unique=True)

    async def log_snapshot(self, scanner_results: List[Dict]) -> int:
        """Persist all 3/5+ scanner results. Returns count saved."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        saved = 0

        for stock in scanner_results:
            symbol = stock.get("symbol")
            criteria_count = stock.get("criteria_count", 0)
            if criteria_count < 3 or not symbol:
                continue

            doc = {
                "symbol": symbol,
                "date": today,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "current_price": stock.get("current_price", 0),
                "prev_close": stock.get("prev_close", 0),
                "pct_change": stock.get("pct_change", 0),
                "gap_pct": stock.get("gap_pct", 0),
                "is_gapping_up": stock.get("is_gapping_up", False),
                "volume": stock.get("volume", 0),
                "avg_volume": stock.get("avg_volume", 0),
                "volume_ratio": stock.get("volume_ratio", 0),
                "shares_outstanding": stock.get("shares_outstanding", 0),
                "float_data_source": stock.get("float_data_source", ""),
                "has_bull_flag": stock.get("has_bull_flag", False),
                "has_positive_news": stock.get("has_positive_news", False),
                "news_headline": stock.get("news_headline", ""),
                "criteria_met": stock.get("criteria_met", {}),
                "criteria_count": criteria_count,
                "meets_all_criteria": stock.get("meets_all_criteria", False),
                "ready_to_trade": stock.get("ready_to_trade", False),
                "no_news_scalp_candidate": stock.get("no_news_scalp_candidate", False),
                "fully_verified": stock.get("fully_verified", False),
            }

            # Keep highest criteria_count snapshot per (symbol, date)
            existing = await self.collection.find_one({"symbol": symbol, "date": today})
            if existing and existing.get("criteria_count", 0) >= criteria_count:
                continue

            await self.collection.update_one(
                {"symbol": symbol, "date": today},
                {"$set": doc},
                upsert=True,
            )
            saved += 1

        return saved

    async def get_day(self, date: str) -> List[Dict]:
        """Return all 3/5+ snapshots for a given date."""
        cursor = self.collection.find({"date": date}, {"_id": 0}).sort("criteria_count", -1)
        return await cursor.to_list(length=500)

    async def get_days(self, dates: List[str]) -> Dict[str, List[Dict]]:
        """Return snapshots for multiple dates keyed by date."""
        out = {}
        for d in dates:
            out[d] = await self.get_day(d)
        return out


snapshot = ScannerSnapshotService()
