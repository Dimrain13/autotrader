"""
Demo Scanner Service - Simulates live market momentum opportunities
This is used when markets are closed or for demonstration purposes
"""
from datetime import datetime, time
from typing import List, Dict
import random
import logging

logger = logging.getLogger(__name__)

class DemoScannerService:
    def __init__(self):
        # Simulated momentum stocks with varying probabilities
        self.momentum_candidates = [
            {"symbol": "PLTR", "base_price": 18.50, "volatility": 0.15},
            {"symbol": "RIVN", "base_price": 12.20, "volatility": 0.18},
            {"symbol": "NIO", "base_price": 8.80, "volatility": 0.20},
            {"symbol": "SOFI", "base_price": 7.45, "volatility": 0.16},
            {"symbol": "LCID", "base_price": 3.20, "volatility": 0.22},
            {"symbol": "PLUG", "base_price": 4.80, "volatility": 0.19},
            {"symbol": "MARA", "base_price": 15.60, "volatility": 0.25},
            {"symbol": "RIOT", "base_price": 11.30, "volatility": 0.24},
        ]
        
        self.scan_counter = 0
        self.previous_movers = []
    
    def is_market_hours(self) -> bool:
        """Check if we're in active trading hours (9:30 AM - 4:00 PM ET)"""
        now = datetime.now().time()
        market_open = time(9, 30)
        market_close = time(16, 0)
        
        # For demo purposes, consider 7 AM - 4 PM as "active"
        demo_open = time(7, 0)
        return demo_open <= now <= market_close
    
    def is_momentum_window(self) -> bool:
        """Check if we're in peak momentum window (7:00 AM - 10:00 AM ET)"""
        now = datetime.now().time()
        momentum_start = time(7, 0)
        momentum_end = time(10, 0)
        return momentum_start <= now <= momentum_end
    
    def generate_momentum_stock(self, candidate: Dict, is_peak: bool) -> Dict:
        """Generate a simulated momentum stock"""
        self.scan_counter += 1
        
        # Higher chance of meeting criteria during peak hours
        probability_multiplier = 1.5 if is_peak else 1.0
        
        # Calculate simulated price movement
        base_price = candidate["base_price"]
        volatility = candidate["volatility"]
        
        # Random price movement (higher during peak hours)
        pct_change = random.uniform(8.0, 18.0) * probability_multiplier if random.random() > 0.3 else random.uniform(2.0, 9.0)
        current_price = base_price * (1 + pct_change / 100)
        prev_close = base_price
        
        # Volume simulation
        avg_volume = random.randint(10_000_000, 30_000_000)
        volume_ratio = random.uniform(4.5, 8.0) if pct_change > 10 else random.uniform(2.0, 5.5)
        current_volume = int(avg_volume * volume_ratio)
        
        # Shares outstanding (always under 20M for our criteria)
        shares_outstanding = random.randint(8_000_000, 19_000_000)
        
        # Bull flag pattern detection (higher probability for stocks up 12%+)
        has_bull_flag = pct_change > 12.0 and volume_ratio > 5.0 and random.random() > 0.4
        
        return {
            "symbol": candidate["symbol"],
            "current_price": round(current_price, 2),
            "prev_close": round(prev_close, 2),
            "pct_change": round(pct_change, 2),
            "volume": current_volume,
            "avg_volume": avg_volume,
            "volume_ratio": round(volume_ratio, 2),
            "shares_outstanding": shares_outstanding,
            "has_bull_flag": has_bull_flag,
            "market_cap": int(shares_outstanding * current_price),
            "last_update": datetime.now().isoformat(),
            "scan_number": self.scan_counter
        }
    
    def scan_stocks(self, criteria: Dict) -> List[Dict]:
        """Generate simulated scan results"""
        results = []
        
        is_peak = self.is_momentum_window()
        in_hours = self.is_market_hours()
        
        # More stocks meet criteria during market hours
        num_candidates = random.randint(3, 6) if in_hours else random.randint(0, 2)
        
        if num_candidates == 0:
            logger.info("Demo scan: No opportunities (simulated quiet market)")
            return []
        
        # Select random candidates
        selected = random.sample(self.momentum_candidates, min(num_candidates, len(self.momentum_candidates)))
        
        for candidate in selected:
            stock = self.generate_momentum_stock(candidate, is_peak)
            
            # Check each criterion individually
            criteria_met = {}
            criteria_count = 0
            
            # 1. Price range
            in_price_range = criteria.get("min_price", 2) <= stock["current_price"] <= criteria.get("max_price", 20)
            criteria_met['price_range'] = in_price_range
            if in_price_range:
                criteria_count += 1
            
            # 2. % change
            meets_change = stock["pct_change"] >= criteria.get("min_change", 10)
            criteria_met['pct_change'] = meets_change
            if meets_change:
                criteria_count += 1
            
            # 3. Volume ratio
            meets_volume = stock["volume_ratio"] >= criteria.get("min_volume_ratio", 5)
            criteria_met['volume_ratio'] = meets_volume
            if meets_volume:
                criteria_count += 1
            
            # 4. Positive news (always true for demo)
            criteria_met['positive_news'] = True
            criteria_count += 1
            
            # 5. Float
            meets_float = stock["shares_outstanding"] <= criteria.get("max_float", 20_000_000)
            criteria_met['float'] = meets_float
            if meets_float:
                criteria_count += 1
            
            # Show stocks with 2+ criteria met
            if criteria_count < 2:
                continue
            
            meets_all_criteria = criteria_count == 5
            
            # Add criteria tracking
            stock["criteria_met"] = criteria_met
            stock["criteria_count"] = criteria_count
            stock["meets_all_criteria"] = meets_all_criteria
            stock["ready_to_trade"] = meets_all_criteria
            stock["has_positive_news"] = True
            stock["news_headline"] = f"{stock['symbol']} shows strong momentum on volume spike"
            
            results.append(stock)
            logger.info(f"Demo scan found: {stock['symbol']} at ${stock['current_price']} (+{stock['pct_change']}%)")
        
        # Track for comparison in next scan
        self.previous_movers = [r["symbol"] for r in results]
        
        return results

demo_scanner = DemoScannerService()
