from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import List, Dict
import pandas as pd
import numpy as np
from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed
from alpaca.data.requests import NewsRequest
import os

from services.alpaca_service import data_pool, news_pool

logger = logging.getLogger(__name__)

# Import IB service for real float data
try:
    from services.ib_service import ib_service
    IB_AVAILABLE = True
except ImportError:
    IB_AVAILABLE = False
    logger.warning("IB service not available - float data will be estimated")

# Import Alpaca service for company info
try:
    from services.alpaca_service import alpaca_service
    ALPACA_SERVICE_AVAILABLE = True
except ImportError:
    ALPACA_SERVICE_AVAILABLE = False
    logger.warning("Alpaca service not available for company info")

class ScannerService:
    def __init__(self):
        # Cache for instant results
        self.cached_results = []
        self.cache_timestamp = None
        self.cache_duration = timedelta(seconds=120)  # Cache for 2 minutes (increased from 60s)
        self.is_scanning = False
        # Guards the is_scanning check-and-set below - without this, two
        # concurrent requests (e.g. the auto-trader loop + a manual scan)
        # could both read is_scanning=False before either sets it True,
        # launching two simultaneous full-market scans and tripping
        # Alpaca's "too many requests" rate limit.
        self._scan_lock = threading.Lock()
        
        # Initialize Alpaca clients. Market data/news no longer construct
        # their own client here - they draw from the shared data_pool/
        # news_pool (alpaca_service.py) so requests get load-balanced
        # across every configured Alpaca account (primary + optional
        # secondary speed-boost account) instead of a scanner-local client
        # tied to just one account.
        api_key = os.getenv('ALPACA_API_KEY')
        secret_key = os.getenv('ALPACA_SECRET_KEY')
        if api_key and secret_key:
            from alpaca.trading.client import TradingClient
            self.trading_client = TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
            self._load_stock_universe()
        else:
            self.trading_client = None
            self.stock_universe = []
    
    def _load_stock_universe(self):
        """Load all tradeable stocks from Alpaca and filter by liquidity"""
        try:
            from alpaca.trading.requests import GetAssetsRequest
            from alpaca.trading.enums import AssetClass, AssetStatus
            
            logger.info("Loading full stock universe from Alpaca...")
            
            # Get all active, tradeable US stocks
            request = GetAssetsRequest(
                asset_class=AssetClass.US_EQUITY,
                status=AssetStatus.ACTIVE
            )
            assets = self.trading_client.get_all_assets(request)
            
            # Filter to stocks only (no ETFs, crypto, etc.) and tradeable
            # LESS RESTRICTIVE - Include penny stocks and momentum stocks
            self.stock_universe = [
                asset.symbol for asset in assets 
                if asset.tradable  # Must be tradeable
                and asset.asset_class == AssetClass.US_EQUITY  # US stocks only
                and not asset.symbol.startswith('$')  # Remove special symbols
                and len(asset.symbol) <= 5  # Remove weird tickers
                and '.' not in asset.symbol  # Remove warrants/special classes
                # REMOVED: fractionable and shortable filters
                # These exclude many momentum/penny stocks we want to scan
            ]
            
            logger.info(f"Loaded {len(self.stock_universe)} tradeable stocks")
            
        except Exception as e:
            logger.error(f"Failed to load stock universe: {str(e)}")
            # Fallback to a curated list if API fails
            self.stock_universe = [
                "TSLA", "AMD", "NVDA", "PLTR", "SOFI", "RIVN", "LCID",
                "NIO", "PLUG", "MARA", "RIOT", "COIN", "HOOD", "GME",
                "AMC", "BB", "SPCE", "F", "SNAP", "UBER", "LYFT", "WISH"
            ]
    
    def calculate_sma(self, prices: List[float], period: int = 20) -> float:
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    def check_alpaca_news(self, symbol: str, hours_back: int = 24, limit: int = 5, min_score: int = 10) -> Dict:
        """
        Check Alpaca's real-time news API (Benzinga-powered, already included
        in the Alpaca data subscription) for stock news.

        This is a fast, clean API call (no HTML scraping) - typically
        30-200ms vs 1-3s+ for Google News RSS scraping - so it's checked
        FIRST as the primary news source, with Google News as a fallback
        for illiquid micro-caps Benzinga doesn't cover.

        Uses the same catalyst-scoring bar as Google News (score_headline)
        so both sources are judged identically. Returns the same shape as
        google_news_service.search_stock_news(): {'has_news', 'articles'}.

        `min_score` defaults to 10 (strict "real catalyst only" bar, for
        AUTO-TRADER entry decisions). Callers building an informational
        news feed for a human to read should pass a lower value (e.g. 0) -
        otherwise routine headlines that don't contain one of the ~50 exact
        STRONG_CATALYSTS phrases get silently hidden entirely, which made
        the news panel look empty even on days with plenty of real news.
        """
        if news_pool.configured_count == 0:
            return {'has_news': False, 'articles': []}

        try:
            from services.google_news_service import score_headline, classify_freshness

            # IMPORTANT: must be timezone-aware (UTC) - a naive datetime here
            # previously caused this check to silently return 0 results every
            # time, forcing 100% reliance on the much slower Google News path.
            news_request = NewsRequest(
                symbols=symbol,
                start=datetime.now(timezone.utc) - timedelta(hours=hours_back),
                limit=limit
            )
            alpaca_news_client = news_pool.acquire()
            news_set = alpaca_news_client.get_news(news_request)

            # IMPORTANT: alpaca-py's NewsSet model does NOT expose a `.news`
            # attribute directly (that always raises/misses, silently making
            # this check look like "no news" every single time and forcing
            # 100% reliance on the slower Google News fallback) - the actual
            # articles live under `.data['news']`.
            news_list = news_set.data.get('news', []) if news_set and hasattr(news_set, 'data') else []
            if not news_list:
                return {'has_news': False, 'articles': []}

            articles = []
            for article in news_list[:limit]:
                headline = str(getattr(article, 'headline', '') or '')
                if not headline:
                    continue

                scored = score_headline(headline, min_score=min_score)
                if scored is None:
                    continue

                created_at = getattr(article, 'created_at', None)
                freshness, days_old = classify_freshness(created_at) if created_at else ('unknown', None)

                articles.append({
                    'title': headline,
                    'link': getattr(article, 'url', '') or '',
                    'source': f"benzinga/{getattr(article, 'source', 'alpaca')}",
                    'pubDate': created_at.isoformat() if created_at else '',
                    'sentiment': scored['sentiment'],
                    'score': scored['score'],
                    'catalysts': scored['catalysts'],
                    'freshness': freshness,
                    'days_old': days_old
                })

            if articles:
                # Highest-relevance catalysts first, not just chronological -
                # otherwise a real "FDA approval" headline from an hour ago
                # could sit below 3 routine market-commentary mentions from
                # 5 minutes ago (found 2026-07, user report: "the news is
                # coming in now, but its not being ranked at all").
                articles.sort(key=lambda a: a['score'], reverse=True)
                logger.info(f"{symbol}: Alpaca/Benzinga found {len(articles)} catalyst news article(s)")
                return {'has_news': True, 'articles': articles}
            return {'has_news': False, 'articles': []}

        except Exception as e:
            logger.warning(f"{symbol}: Alpaca/Benzinga news check failed, falling back to Google News: {str(e)}")
            return {'has_news': False, 'articles': []}
    
    def check_bull_flag_pattern(self, bars: List[Dict]) -> bool:
        if len(bars) < 10:
            return False
        
        # Check for initial rally (first 40% of bars)
        rally_period = int(len(bars) * 0.4)
        rally_bars = bars[:rally_period]
        
        # Check if price went up significantly
        if rally_bars:
            rally_start = rally_bars[0]['close']
            rally_end = rally_bars[-1]['close']
            if rally_end > rally_start * 1.08:  # 8% move up
                # Check for consolidation (next 40% of bars)
                consolidation_bars = bars[rally_period:rally_period*2]
                if consolidation_bars:
                    highs = [b['high'] for b in consolidation_bars]
                    lows = [b['low'] for b in consolidation_bars]
                    range_pct = (max(highs) - min(lows)) / min(lows)
                    if range_pct < 0.05:  # Tight consolidation
                        return True
        return False
    
    def scan_stocks(self, criteria: Dict) -> List[Dict]:
        results = []
        
        if data_pool.configured_count == 0:
            logger.error("Alpaca data client not initialized")
            return results
        
        # Pre-filter stocks using Alpaca's bulk snapshot API for efficiency
        logger.info(f"Scanning {len(self.stock_universe)} stocks with criteria: {criteria}")
        
        # Use bulk snapshot request (much faster than individual requests)
        import asyncio
        
        # OPTIMIZED SCANNING: Price → % Change → Sort → Float Filter
        # This approach minimizes expensive API calls and processing
        
        # Split into batches (Alpaca allows up to 100 symbols per request)
        batch_size = 100
        stock_batches = [self.stock_universe[i:i + batch_size] for i in range(0, len(self.stock_universe), batch_size)]
        
        logger.info("🔍 OPTIMIZED SCAN: Price → % Change → Sort → Float filter")
        logger.info(f"Processing {len(stock_batches)} batches of {batch_size} stocks each")
        
        # PARALLEL PROCESSING: Process batches concurrently for massive speedup
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        price_filtered_stocks = []
        total_batches = len(stock_batches)
        lock = threading.Lock()
        
        def process_batch(batch_data):
            """Process a single batch of stocks - rate-limited + retried on
            Alpaca 429s so a transient rate-limit spike drops a batch's
            candidates only as a last resort, not on the first hiccup."""
            batch_num, batch = batch_data
            local_results = []

            snapshots = None
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    alpaca_data_client = data_pool.acquire()
                    # Explicit IEX feed (not relying on the account default)
                    # so this always matches the feed used for the 20-day
                    # average volume lookup below - keeping current_volume
                    # and avg_volume on the same basis for a meaningful ratio.
                    snapshot_request = StockSnapshotRequest(symbol_or_symbols=batch, feed=DataFeed.IEX)
                    snapshots = alpaca_data_client.get_stock_snapshot(snapshot_request)
                    break
                except Exception as e:
                    if "too many requests" in str(e).lower() and attempt < max_retries:
                        wait_s = 5 * (attempt + 1)
                        logger.warning(f"Batch {batch_num}: rate limited, retrying in {wait_s}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_s)
                        continue
                    logger.error(f"Error processing batch {batch_num}: {str(e)}")
                    return []

            try:
                # Filter by PRICE RANGE and % CHANGE
                for symbol in batch:
                    if symbol not in snapshots:
                        continue
                    
                    snapshot = snapshots[symbol]
                    
                    if not snapshot.latest_trade or not snapshot.previous_daily_bar:
                        continue
                    
                    current_price = float(snapshot.latest_trade.price)
                    prev_close = float(snapshot.previous_daily_bar.close)
                    
                    # Price filter ($2-$20)
                    if current_price < criteria.get('min_price', 2) or current_price > criteria.get('max_price', 20):
                        continue
                    
                    # Calculate % change
                    pct_change = ((current_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
                    
                    # Only keep stocks with at least 5% gain
                    if pct_change < 5:
                        continue
                    
                    # Store for sorting
                    local_results.append({
                        'symbol': symbol,
                        'snapshot': snapshot,
                        'current_price': current_price,
                        'prev_close': prev_close,
                        'pct_change': pct_change
                    })
                
                return local_results
                
            except Exception as e:
                logger.error(f"Error processing batch {batch_num}: {str(e)}")
                return []
        
        # Process batches in parallel (6 concurrent workers - tuned to stay
        # under each configured Alpaca account's 200 req/min data-API cap
        # alongside its own pooled rate limiter, instead of just bursting
        # and retrying)
        logger.info(f"⚡ PARALLEL SCAN: Processing {total_batches} batches with 6 concurrent workers")
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            # Submit all batch jobs
            futures = {executor.submit(process_batch, (i, batch)): i 
                      for i, batch in enumerate(stock_batches)}
            
            completed = 0
            for future in as_completed(futures):
                batch_results = future.result()
                
                with lock:
                    price_filtered_stocks.extend(batch_results)
                    completed += 1
                    
                    # Log progress every 20 batches
                    if completed % 20 == 0 or completed == total_batches:
                        logger.info(f"⚡ Progress: {completed}/{total_batches} batches, {len(price_filtered_stocks)} candidates")
                    
                    # EARLY EXIT: If we have 500+ candidates already, cancel remaining jobs
                    if len(price_filtered_stocks) >= 500:
                        logger.info(f"⚡ Early exit: Found {len(price_filtered_stocks)} candidates (enough for top 200)")
                        # Cancel remaining futures
                        for f in futures:
                            f.cancel()
                        break
        
        # STEP 3: SORT by % change (highest first) - focus on best movers
        price_filtered_stocks.sort(key=lambda x: x['pct_change'], reverse=True)
        logger.info(f"✅ Price + % Change filter: {len(price_filtered_stocks)} stocks (sorted by % gain)")
        
        # STEP 4: LIMIT to top 200 candidates (HUGE speed boost!)
        # This is still plenty for finding opportunities while keeping scan fast
        top_candidates = price_filtered_stocks[:200]
        logger.info(f"🎯 Processing top {len(top_candidates)} candidates (sorted by gain)")
        
        # STEP 5: Now process top candidates with FLOAT filter and detailed checks
        for stock_data in top_candidates:
            self._process_stock(stock_data['symbol'], stock_data['snapshot'], criteria, results)
        
        logger.info(f"Initial scan complete: {len(results)} candidates found (2+ base criteria)")
        
        # Second pass: Calculate accurate volume, float and news for promising candidates
        # OPTIMIZATION: Only verify top 50 candidates to save time.
        # These three checks are independent (different criteria_met keys) so
        # they run CONCURRENTLY - this is the "find news ASAP" fix: news no
        # longer waits in line behind volume+float, cutting total second-pass
        # latency roughly in half-to-a-third.
        if results:
            top_results = sorted(results, key=lambda x: x.get('criteria_count', 0), reverse=True)[:50]
            logger.info(f"Verifying volume, float and news for top {len(top_results)} candidates (concurrently)...")

            from concurrent.futures import ThreadPoolExecutor as _OuterPool
            with _OuterPool(max_workers=3) as outer_pool:
                futures = [
                    outer_pool.submit(self._calculate_accurate_volume, top_results, criteria),
                    outer_pool.submit(self._calculate_accurate_float, top_results, criteria),
                    outer_pool.submit(self._check_candidate_news, top_results),
                ]
                for f in futures:
                    f.result()  # propagate any exception, wait for all to finish

            # Recompute criteria_count/meets_all_criteria once, authoritatively,
            # now that all three concurrent checks have finished writing their
            # own criteria_met[...] keys (avoids the shared-counter race that
            # concurrent increments would otherwise cause).
            for r in top_results:
                r['criteria_count'] = sum(1 for v in r['criteria_met'].values() if v)
                r['meets_all_criteria'] = r['criteria_count'] == 5
                r['ready_to_trade'] = r['meets_all_criteria']
            
            # Keep all results but mark which ones were fully verified
            verified_symbols = {r['symbol'] for r in top_results}
            for r in results:
                r['fully_verified'] = r['symbol'] in verified_symbols
        
        # Final filtering after accurate volume calculation
        final_results = [r for r in results if r['criteria_count'] >= 2]
        logger.info(f"Scan complete: {len(final_results)} stocks match 2+ criteria (including volume)")
        return final_results
    
    def _process_stock(self, symbol: str, snapshot, criteria: Dict, results: List[Dict]):
        """Process individual stock with full criteria checks"""
        try:
            current_price = float(snapshot.latest_trade.price)
            prev_close = float(snapshot.previous_daily_bar.close) if snapshot.previous_daily_bar else current_price

            # Reject stale/dormant tickers outright. Alpaca's snapshot endpoint
            # keeps returning the LAST trade it ever saw for illiquid/halted
            # names (often SPAC units) even if that trade is weeks old - a
            # "25% gap" computed from a 3-week-stale print isn't a real
            # intraday move, and every downstream number (volume ratio, etc.)
            # would be equally meaningless. Skip anything whose most recent
            # trade isn't from today's session (US/Eastern trading day).
            if snapshot.latest_trade and snapshot.latest_trade.timestamp:
                import pytz
                eastern = pytz.timezone('US/Eastern')
                trade_date_et = snapshot.latest_trade.timestamp.astimezone(eastern).date()
                today_et = datetime.now(eastern).date()
                if trade_date_et != today_et:
                    return  # Stale ticker with no trades today - not a real mover

            # Calculate all values first
            pct_change = ((current_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            current_volume = int(snapshot.daily_bar.volume) if snapshot.daily_bar else 0
            
            # Quick volume estimate for initial screening
            prev_volume = int(snapshot.previous_daily_bar.volume) if snapshot.previous_daily_bar else current_volume
            avg_volume = prev_volume if prev_volume > 0 else current_volume
            volume_ratio_estimate = current_volume / avg_volume if avg_volume > 0 else 0
            
            # Check each criterion individually (excluding volume for now)
            criteria_met = {}
            criteria_count = 0
            
            # 1. Price range check
            in_price_range = criteria.get('min_price', 2) <= current_price <= criteria.get('max_price', 20)
            criteria_met['price_range'] = in_price_range
            if in_price_range:
                criteria_count += 1
            
            # 2. % change check
            meets_change = pct_change >= criteria.get('min_change', 10)
            criteria_met['pct_change'] = meets_change
            if meets_change:
                criteria_count += 1
            
            # 3. Volume check - use estimate for now, will calculate accurate value later
            meets_volume_estimate = volume_ratio_estimate >= criteria.get('min_volume_ratio', 5)
            criteria_met['volume_ratio'] = meets_volume_estimate
            # Don't count volume in initial criteria_count - will verify later
            # if meets_volume_estimate:
            #     criteria_count += 1
            
            # 4. Check for positive news - skip for now, will check in second pass
            # Assume true for initial filtering (will verify later)
            has_positive_news_estimate = pct_change >= 10  # Likely has news if big move
            news_headline = "News check pending..."
            criteria_met['positive_news'] = has_positive_news_estimate
            # Don't count news in initial criteria_count - will verify later
            # if has_positive_news_estimate:
            #     criteria_count += 1
            
            # 5. Float check (shares outstanding) - deferred to second pass.
            # Real float data (IB or SEC EDGAR) is only fetched for the top
            # candidates that survive the price/change pre-filter, to avoid
            # hundreds of lookups per scan. NEVER fabricate a number here -
            # unresolved stocks are excluded rather than guessed.
            shares_outstanding = None
            float_data_source = "pending"
            criteria_met['float'] = False
            
            # Show stocks that meet at least 2 NON-VOLUME, NON-NEWS, NON-FLOAT criteria
            # Volume, news and float will be verified in the second pass
            if criteria_count < 2:
                return  # Skip this stock - needs price range + % change to be worth a closer look
            
            # Mark for accurate volume, news and float calculation
            needs_volume_calc = True
            needs_news_check = True
            needs_float_calc = True
            meets_all_criteria = False  # Will determine after volume/news/float calc
            
            # Skip expensive API calls (SMA, 5min bars) to speed up full market scan
            # These will be calculated on-demand when stock is selected for trading
            
            # Build result with estimated volume (will be updated)
            result = {
                "symbol": symbol,
                "current_price": float(current_price),
                "prev_close": float(prev_close),
                "pct_change": float(pct_change),
                "gap_pct": float(pct_change),  # Gap % = same as pct_change (from prev close)
                "is_gapping_up": pct_change > 5,  # Flag for significant gaps
                "volume": current_volume,
                "avg_volume": avg_volume,
                "volume_ratio": float(volume_ratio_estimate),  # Estimated - will update
                "volume_needs_calc": needs_volume_calc,
                "shares_outstanding": shares_outstanding,
                "float_data_source": float_data_source,  # "IB", "sec_edgar", or "pending"/"unknown"
                "float_needs_calc": needs_float_calc,
                "has_bull_flag": False,  # Set to false for now, calculated on-demand
                "has_positive_news": has_positive_news_estimate,  # Estimated - will update
                "news_headline": news_headline,
                "news_needs_check": needs_news_check,
                "market_cap": 0,
                "last_update": datetime.now().isoformat(),
                "criteria_met": criteria_met,
                "criteria_count": criteria_count,  # Count without volume
                "meets_all_criteria": meets_all_criteria,
                "ready_to_trade": meets_all_criteria,
                "spread_pct": 0,  # Will be populated with live quote data
                "bid_price": 0,
                "ask_price": 0
            }
            results.append(result)
            
        except Exception as e:
            logger.error(f"Error processing {symbol}: {str(e)}")
            return
    
    def _calculate_accurate_volume(self, results: List[Dict], criteria: Dict):
        """Calculate accurate relative volume using 20-day historical data
        
        Formula: current_volume / (20_day_avg_volume / 390_minutes * minutes_elapsed)
        This compares today's volume SO FAR to what would be expected at this time of day.
        """
        from alpaca.data.timeframe import TimeFrameUnit
        from datetime import datetime, timedelta
        import pytz
        
        # Get current market time for intraday adjustment
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        
        # Calculate minutes elapsed in trading day
        minutes_elapsed = 0
        if market_open <= now_et <= market_close:
            minutes_elapsed = (now_et - market_open).total_seconds() / 60
        else:
            # If after hours, use full trading day
            minutes_elapsed = 390  # 6.5 hours * 60 minutes
        
        # Ensure we don't divide by zero
        if minutes_elapsed <= 0:
            minutes_elapsed = 1
        
        total_trading_minutes = 390  # 6.5 hours
        
        # Batch process symbols
        symbols = [r['symbol'] for r in results if r.get('volume_needs_calc')]
        
        if not symbols:
            return
        
        try:
            # Fetch 20 days of historical data
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)  # 30 days to ensure 20 trading days
            
            bars_request = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                start=start_date,
                # Must match the feed the live snapshot's daily_bar uses
                # (IEX - the free-tier real-time feed) or "today's" volume
                # here would be pulled from full SIP-consolidated tape while
                # current_volume (from the snapshot) is IEX-only, silently
                # deflating every volume_ratio by ~20-50x (IEX is only a
                # few percent of total consolidated market volume) and
                # making the 5x relative-volume criterion nearly unreachable
                # even on genuinely high-volume days.
                feed=DataFeed.IEX
                # No explicit `end`: see get_bars() in alpaca_service.py for
                # why passing end=now() causes SIP data plan rejections.
            )
            
            alpaca_data_client = data_pool.acquire()
            bars = alpaca_data_client.get_stock_bars(bars_request)
            
            # Calculate average volume for each symbol
            for result in results:
                symbol = result['symbol']
                if symbol not in bars.data:
                    continue
                
                # Get last 20 days of volume data
                historical_bars = bars.data[symbol][-20:] if len(bars.data[symbol]) >= 20 else bars.data[symbol]
                
                if not historical_bars:
                    continue
                
                # Calculate 20-day average DAILY volume
                volumes = [float(bar.volume) for bar in historical_bars]
                avg_daily_volume_20d = sum(volumes) / len(volumes)
                
                # Calculate EXPECTED volume at this time of day based on 20-day average
                # Formula: (20-day avg daily volume / 390 minutes) * minutes_elapsed
                expected_volume_now = (avg_daily_volume_20d / total_trading_minutes) * minutes_elapsed
                
                # Calculate RELATIVE volume (actual vs expected)
                current_volume = result['volume']
                accurate_volume_ratio = current_volume / expected_volume_now if expected_volume_now > 0 else 0
                
                result['avg_volume'] = int(avg_daily_volume_20d)
                result['volume_ratio'] = round(accurate_volume_ratio, 2)
                result['volume_needs_calc'] = False
                
                # Re-check volume criterion with accurate data. NOTE: criteria_count
                # is recomputed once from criteria_met in a final pass after
                # volume/float/news all finish (they now run concurrently, so
                # incrementing a shared counter here would race).
                meets_volume = accurate_volume_ratio >= criteria.get('min_volume_ratio', 5)
                result['criteria_met']['volume_ratio'] = meets_volume
                
            logger.info(f"Accurate volume calculated for {len(symbols)} stocks (using {int(minutes_elapsed)} minutes elapsed)")
            
        except Exception as e:
            logger.error(f"Error calculating accurate volume: {str(e)}")
            # Fallback: Use yesterday's volume with intraday projection
            logger.warning("FALLBACK: Using yesterday's volume (not 20-day average) - results may be less accurate")
            
            for result in results:
                if not result.get('volume_needs_calc'):
                    continue
                
                # Use yesterday's volume as a rough estimate
                avg_volume = result['avg_volume']  # Yesterday's volume from snapshot
                
                # Calculate expected volume at this time based on yesterday
                expected_volume_now = (avg_volume / total_trading_minutes) * minutes_elapsed
                
                # Calculate relative volume
                current_volume = result['volume']
                accurate_volume_ratio = current_volume / expected_volume_now if expected_volume_now > 0 else 0
                
                result['volume_ratio'] = round(accurate_volume_ratio, 2)
                result['volume_needs_calc'] = False
                
                # Re-check volume criterion (criteria_count recomputed in final pass)
                meets_volume = accurate_volume_ratio >= criteria.get('min_volume_ratio', 5)
                result['criteria_met']['volume_ratio'] = meets_volume
            
            logger.info(f"Applied fallback intraday projection for {len(results)} stocks")

    def _calculate_accurate_float(self, results: List[Dict], criteria: Dict):
        """
        Look up real float/shares-outstanding data for candidates - PARALLEL.

        Real data only: Interactive Brokers first (if connected), then SEC
        EDGAR (free, no key, real filings). Never fabricates a number - if
        neither source has data for a symbol, the float criterion stays
        unmet (fail-safe) instead of a random guess.
        """
        logger.info(f"Checking real float data for {len(results)} candidates...")

        from concurrent.futures import ThreadPoolExecutor, as_completed

        max_float = criteria.get('max_float', 20_000_000)

        def check_single_float(result):
            if not result.get('float_needs_calc'):
                return result

            symbol = result['symbol']
            shares_outstanding = None
            float_data_source = "unknown"

            try:
                if IB_AVAILABLE and ib_service.use_ib_for_float:
                    float_data = ib_service.get_float_data(symbol)
                    if float_data:
                        shares_outstanding = float_data['float_shares']
                        float_data_source = "IB"

                if shares_outstanding is None and ALPACA_SERVICE_AVAILABLE:
                    sec_data = alpaca_service.get_float_data(symbol)
                    if sec_data:
                        shares_outstanding = sec_data['shares_outstanding']
                        float_data_source = "sec_edgar"
            except Exception as e:
                logger.debug(f"{symbol}: Error fetching real float data: {e}")

            result['shares_outstanding'] = shares_outstanding
            result['float_data_source'] = float_data_source
            result['float_needs_calc'] = False

            meets_float = shares_outstanding is not None and shares_outstanding <= max_float
            result['criteria_met']['float'] = meets_float
            # criteria_count is recomputed once in a final pass after
            # volume/float/news all finish (see scan_stocks) - not incremented
            # here since these three checks now run concurrently.

            return result

        found_count = 0
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(check_single_float, result): result for result in results}
            for future in as_completed(futures):
                try:
                    updated = future.result()
                    if updated.get('shares_outstanding') is not None:
                        found_count += 1
                except Exception as e:
                    logger.error(f"Error processing float future: {str(e)}")

        logger.info(f"Real float data found for {found_count}/{len(results)} candidates")

    def _check_candidate_news(self, results: List[Dict]):
        """Check for actual positive news from news sources for candidates - PARALLEL.

        PRIMARY: Alpaca/Benzinga News API - a clean API call (~30-200ms),
        already included in the Alpaca data subscription. Checked first so
        the news signal is ready as fast as possible instead of lagging
        behind the price/volume/float checks.
        FALLBACK: Google News RSS scraping (~1-3s+) - catches illiquid
        micro-caps Benzinga doesn't cover, but too slow to be primary.
        """
        logger.info(f"Checking news for {len(results)} candidates... (Alpaca/Benzinga first, Google News fallback)")
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from services.google_news_service import google_news_service
        
        checked_count = 0
        news_found_count = 0
        
        def check_single_news(result):
            """Check news for single stock - Alpaca/Benzinga first, Google News fallback"""
            if not result.get('news_needs_check'):
                return result, False
            
            symbol = result['symbol']
            
            try:
                # PRIMARY: Alpaca/Benzinga News API (fast, no scraping)
                news_result = self.check_alpaca_news(symbol, hours_back=24, limit=1)
                news_source = 'Benzinga (Alpaca)'

                # FALLBACK: Google News RSS (slower, but broader coverage for
                # illiquid micro-caps Benzinga doesn't index)
                if not news_result['has_news']:
                    company_name = None
                    try:
                        asset_info = alpaca_service.get_asset(symbol)
                        company_name = asset_info.get('name')
                    except:
                        pass
                    news_result = google_news_service.search_stock_news(symbol, hours_back=24, limit=1, company_name=company_name)
                    news_source = 'Google News'

                has_news = news_result['has_news']
                headline = news_result['articles'][0]['title'] if news_result['articles'] else ""
                
                # Extract freshness from the article
                news_freshness = 'unknown'
                news_days_old = None
                if news_result['articles']:
                    article = news_result['articles'][0]
                    news_freshness = article.get('freshness', 'unknown')
                    news_days_old = article.get('days_old')
                
                result['has_positive_news'] = has_news
                result['news_headline'] = headline if has_news else "No recent news found"
                result['news_needs_check'] = False
                result['news_source'] = news_source if has_news else None
                result['news_freshness'] = news_freshness  # breaking, warm, cold, unknown
                result['news_days_old'] = news_days_old
                
                # Update criteria (criteria_count recomputed in final pass -
                # see scan_stocks - since volume/float/news now run concurrently)
                result['criteria_met']['positive_news'] = has_news
                
                return result, has_news
            except Exception as e:
                logger.error(f"Error checking news for {symbol}: {str(e)}")
                result['has_positive_news'] = False
                result['news_headline'] = "Error checking news"
                result['news_freshness'] = 'unknown'
                return result, False
        
        # Process news checks in parallel (12 workers - I/O-bound Google News/Alpaca
        # calls, higher concurrency = faster scans without overloading either API)
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {executor.submit(check_single_news, result): result for result in results}
            
            for future in as_completed(futures):
                try:
                    updated_result, has_news = future.result()
                    checked_count += 1
                    if has_news:
                        news_found_count += 1
                except Exception as e:
                    logger.error(f"Error processing news future: {str(e)}")
        
        logger.info(f"News check complete: {news_found_count}/{checked_count} candidates have positive news")
    
    def scan_market(self, criteria: Dict = None) -> List[Dict]:
        """
        Scan the market for stocks meeting the given criteria
        Returns list of stocks with their data
        
        Uses aggressive caching for instant results:
        - Returns cached results immediately if less than 60 seconds old
        - Cached results allow sub-second response times
        """
        if criteria is None:
            criteria = {
                'min_price': 2,
                'max_price': 20,
                'min_volume_ratio': 5,
                'max_float': 20_000_000,
                'min_pct_change': 10
            }
        
        # INSTANT RETURN: Check cache first (< 60 seconds old)
        if self.cache_timestamp and self.cached_results:
            age = datetime.now() - self.cache_timestamp
            if age < self.cache_duration:
                logger.info(f"⚡ CACHE HIT: Returning {len(self.cached_results)} cached results (age: {age.seconds}s)")
                return self.cached_results
        
        # If another scan is already running, return cached results (even if stale)
        with self._scan_lock:
            if self.is_scanning:
                logger.info(f"⚡ Scan in progress - returning cached results ({len(self.cached_results)} stocks)")
                return self.cached_results if self.cached_results else []
            
            # Mark as scanning (atomic with the check above)
            self.is_scanning = True
        
        results = []
        
        try:
            # Delegate to the main scan_stocks method
            results = self.scan_stocks(criteria)
            
            # Update cache with fresh results
            self.cached_results = results
            self.cache_timestamp = datetime.now()
            
            logger.info(f"✅ FRESH SCAN: Found {len(results)} stocks, cached for {self.cache_duration.seconds}s")
            
        except Exception as e:
            logger.error(f"Error during market scan: {str(e)}")
            # Return cached results if available, even if stale
            if self.cached_results:
                logger.info("⚠️ Returning stale cached results due to scan error")
                results = self.cached_results
            else:
                results = []
        finally:
            # Always clear scanning flag
            self.is_scanning = False
        
        return results

    def check_higher_highs(self, bars: List[Dict], lookback: int = 10) -> Dict:
        """
        Check if stock is making higher highs (momentum building)
        
        Pattern:
        1. Look at last N bars
        2. Check if we have at least 2 swing highs
        3. Each swing high should be higher than the previous
        
        Returns: {'has_momentum': bool, 'swing_highs': int, 'trend': str}
        """
        if len(bars) < lookback:
            return {'has_momentum': False, 'swing_highs': 0, 'trend': 'insufficient_data'}
        
        recent_bars = bars[-lookback:]
        
        # Find swing highs (local maxima)
        swing_highs = []
        for i in range(1, len(recent_bars) - 1):
            prev_high = recent_bars[i-1]['high']
            curr_high = recent_bars[i]['high']
            next_high = recent_bars[i+1]['high']
            
            # A swing high is when current bar's high is greater than both neighbors
            if curr_high > prev_high and curr_high > next_high:
                swing_highs.append({'index': i, 'price': curr_high})
        
        # Need at least 2 swing highs to determine trend
        if len(swing_highs) < 2:
            return {
                'has_momentum': False, 
                'swing_highs': len(swing_highs), 
                'trend': 'no_pattern',
                'current_price': recent_bars[-1]['close']
            }
        
        # Check if swing highs are getting higher (momentum)
        higher_high_count = 0
        for i in range(1, len(swing_highs)):
            if swing_highs[i]['price'] > swing_highs[i-1]['price']:
                higher_high_count += 1
        
        # Momentum = at least half of the swing highs are higher than previous
        has_momentum = higher_high_count >= len(swing_highs) // 2
        
        # Calculate trend strength
        if len(swing_highs) >= 2:
            first_high = swing_highs[0]['price']
            last_high = swing_highs[-1]['price']
            trend_pct = ((last_high - first_high) / first_high) * 100
        else:
            trend_pct = 0
        
        return {
            'has_momentum': has_momentum,
            'swing_highs': len(swing_highs),
            'higher_highs': higher_high_count,
            'trend': 'bullish' if has_momentum else 'neutral',
            'trend_pct': round(trend_pct, 2),
            'current_price': recent_bars[-1]['close'],
            'last_swing_high': swing_highs[-1]['price'] if swing_highs else 0
        }

    def get_momentum_stocks(self) -> List[Dict]:
        """
        Get stocks that are building momentum (higher highs) with 3/5 criteria
        These are potential pullback candidates
        """
        # Check momentum cache first - use longer cache during after hours
        if hasattr(self, 'momentum_cache') and hasattr(self, 'momentum_cache_time'):
            age = datetime.now() - self.momentum_cache_time
            if age < timedelta(seconds=300):  # 5 minute cache
                logger.info(f"⚡ MOMENTUM CACHE HIT: {len(self.momentum_cache)} stocks (age: {age.seconds}s)")
                return self.momentum_cache
        
        # Get cached scanner results (3/5+ stocks)
        if not self.cached_results:
            # If no scanner cache, return existing momentum cache even if stale
            if hasattr(self, 'momentum_cache') and self.momentum_cache:
                logger.info(f"⚡ MOMENTUM STALE CACHE: {len(self.momentum_cache)} stocks (no scanner results)")
                return self.momentum_cache
            # Only run scan if no cache at all
            self.scan_market()
        
        momentum_stocks = []
        
        # Filter for 3/5 criteria stocks (not yet ready but building)
        candidates = [s for s in self.cached_results if s.get('criteria_count', 0) == 3]
        
        logger.info(f"🔍 Momentum scan: Checking {len(candidates)} stocks with 3/5 criteria")
        
        for stock in candidates:
            try:
                # Get bars for momentum analysis
                from services.alpaca_service import alpaca_service
                result = alpaca_service.get_bars_with_fallback(stock['symbol'], '5Min', 30)
                bars = result.get('bars', [])
                
                if len(bars) < 10:
                    continue
                
                # Check for higher highs pattern
                momentum_check = self.check_higher_highs(bars, lookback=15)
                
                if momentum_check['has_momentum']:
                    momentum_stock = {
                        **stock,
                        'momentum_data': momentum_check,
                        'swing_highs': momentum_check['swing_highs'],
                        'higher_highs': momentum_check['higher_highs'],
                        'trend_pct': momentum_check['trend_pct'],
                        'last_swing_high': momentum_check['last_swing_high'],
                        'momentum_score': momentum_check['higher_highs'] * 10 + momentum_check['swing_highs'] * 5
                    }
                    momentum_stocks.append(momentum_stock)
                    logger.info(f"📈 {stock['symbol']}: Momentum detected - {momentum_check['higher_highs']} higher highs")
            except Exception as e:
                logger.debug(f"Error checking momentum for {stock['symbol']}: {e}")
                continue
        
        # Sort by momentum score (highest first)
        momentum_stocks.sort(key=lambda x: x.get('momentum_score', 0), reverse=True)
        
        # Cache the results
        self.momentum_cache = momentum_stocks
        self.momentum_cache_time = datetime.now()
        
        logger.info(f"✅ Momentum scan complete: {len(momentum_stocks)} stocks building momentum")
        
        return momentum_stocks

scanner_service = ScannerService()