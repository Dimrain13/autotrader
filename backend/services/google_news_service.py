"""
Google News Service for Stock News

Searches Google News for real news about stocks
Uses web scraping approach since Google News doesn't have a free API
"""

import requests
from requests.adapters import HTTPAdapter
from datetime import datetime, timedelta
import logging
import time
import threading
from typing import Dict, Tuple, Optional
import urllib.parse

logger = logging.getLogger(__name__)


# Tier 1: STRONG CATALYSTS (Score: 10) - Clear positive events (REAL NEWS)
# These are actual news events that explain WHY a stock is moving.
# Shared between Google News and Alpaca/Benzinga news checks so both
# sources apply the identical catalyst-quality bar (Warrior Trading style:
# only real catalysts count, not just "up"/"gains" chatter).
STRONG_CATALYSTS = [
    # FDA & Healthcare
    'fda approval', 'fda approved', 'fda clears', 'fda grants', 'drug approved',
    'clinical trial success', 'positive trial', 'trial results', 'phase 3',
    'breakthrough therapy', 'fast track', 'priority review',
    # M&A
    'acquired', 'acquisition', 'merger', 'buyout', 'takeover', 'tender offer',
    # Earnings & Financials
    'earnings beat', 'beats earnings', 'beats estimates', 'earnings surprise',
    'profit soars', 'revenue beats', 'raised guidance', 'raises outlook',
    # Analyst Actions
    'upgraded', 'upgrade', 'price target raised', 'target increased',
    'initiates coverage', 'buy rating', 'strong buy',
    # Business Wins
    'patent approved', 'patent granted', 'wins patent', 'new patent',
    'contract win', 'wins contract', 'awarded contract', 'secures deal',
    'partnership', 'partners with', 'strategic alliance', 'collaboration',
    'major customer', 'key customer', 'new customer',
    # Product/Tech
    'breakthrough', 'revolutionary', 'game changer', 'first-of-its-kind',
    'launches new', 'unveils', 'announces new product',
    # Capital Markets
    'ipo prices', 'goes public', 'direct listing', 'spac merger completes'
]

# Tier 2: GOOD MOMENTUM (Score: 5) - Positive price action
MOMENTUM_KEYWORDS = [
    'surge', 'soar', 'soars', 'rally', 'rallies', 'spike', 'spikes',
    'jump', 'jumps', 'breakout', 'breaks out', 'all-time high',
    'record high', 'doubles', 'triples'
]

# Tier 3: WEAK SIGNALS (Score: 2) - Generic positive
WEAK_POSITIVE_KEYWORDS = [
    'gains', 'up', 'rises', 'announces', 'launches', 'expands',
    'growth', 'positive', 'partnership', 'deal'
]

# NEGATIVE FILTERS - Automatic rejection
NEGATIVE_KEYWORDS = [
    'plunge', 'plunges', 'crash', 'crashes', 'tumble', 'tumbles',
    'decline', 'declines', 'drop', 'drops', 'fall', 'falls', 'down',
    'miss', 'misses', 'disappoints', 'warning', 'concern', 'worried',
    'lawsuit', 'sued', 'investigation', 'fraud', 'scandal', 'layoffs',
    'bankrupt', 'bankruptcy', 'closes', 'shuts down', 'shut down',
    'failure', 'fails', 'reject', 'rejected', 'denied', 'denies',
    'downgrade', 'downgraded', 'cuts', 'cut', 'suspended', 'halted',
    'loss', 'losses', 'blood bath', 'nightmare'
]


def score_headline(title: str) -> Optional[Dict]:
    """
    Score a headline for Warrior-Trading-style news catalyst strength.

    Returns None if the headline should be rejected (contains negative
    keywords, or doesn't clear the minimum "real catalyst" bar of score>=10 -
    momentum/weak words alone like "surge"/"gains" are just price action,
    not a catalyst). Otherwise returns {'score', 'sentiment', 'catalysts'}.
    """
    title_lower = title.lower()

    score = 0
    matched_catalysts = []

    for catalyst in STRONG_CATALYSTS:
        if catalyst in title_lower:
            score += 10
            matched_catalysts.append(catalyst)

    if score == 0:
        for keyword in MOMENTUM_KEYWORDS:
            if keyword in title_lower:
                score += 5
                matched_catalysts.append(keyword)
                break

    if score == 0:
        for keyword in WEAK_POSITIVE_KEYWORDS:
            if keyword in title_lower:
                score += 2
                matched_catalysts.append(keyword)
                break

    has_negative = any(keyword in title_lower for keyword in NEGATIVE_KEYWORDS)

    if has_negative or score < 10:
        return None

    sentiment_label = 'strong_catalyst' if score >= 10 else ('momentum' if score >= 5 else 'weak')

    return {'score': score, 'sentiment': sentiment_label, 'catalysts': matched_catalysts[:3]}


def classify_freshness(published_at: datetime) -> Tuple[str, Optional[int]]:
    """Classify an article's age into breaking/warm/cold + days_old, shared helper."""
    try:
        now = datetime.now(published_at.tzinfo) if published_at.tzinfo else datetime.now()
        age = now - published_at
        days_old = age.days
        hours_old = age.total_seconds() / 3600
        if days_old <= 1 or hours_old <= 36:
            return 'breaking', days_old
        elif days_old <= 5:
            return 'warm', days_old
        return 'cold', days_old
    except Exception:
        return 'unknown', None


class GoogleNewsService:
    """
    Search Google News for stock-related news
    
    Uses Google News search directly to find publicly visible news
    Perfect for day trading - see what everyone else sees!
    """
    
    # Short TTL cache so repeated scans within a few minutes (e.g. auto-trader
    # loop + manual scans) don't re-hit Google News for the same symbol -
    # faster responses without sacrificing freshness/accuracy.
    NEWS_CACHE_TTL_SECONDS = 180

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        # Reuse a single session for connection pooling/keep-alive - avoids a
        # fresh TCP/TLS handshake on every request when scanning many symbols.
        # Pool size raised to 20 (>= the 12 worker threads used for parallel
        # news checks) - the default of 10 was smaller than the thread count,
        # causing "connection pool full, discarding connection" churn and
        # extra handshake overhead under load.
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
        self._session.mount('https://', adapter)
        self._session.mount('http://', adapter)
        self._cache: Dict[tuple, tuple] = {}  # (symbol, company_name, limit) -> (timestamp, result)
        self._cache_lock = threading.Lock()
    
    def search_stock_news(self, symbol: str, hours_back: int = 24, limit: int = 5, company_name: str = None) -> Dict:
        """
        Search Google News for stock news and return articles with links
        
        Args:
            symbol: Stock ticker (e.g., "AAPL")
            hours_back: How far back to look (default 24 hours)
            limit: Maximum number of articles to return (default 5)
            company_name: Company name (e.g., "Apple Inc") - improves search results
        
        Returns:
            {
                'has_news': bool,
                'articles': [
                    {'title': str, 'link': str, 'source': str, 'pubDate': str, 'sentiment': str},
                    ...
                ]
            }
        """
        try:
            # Fast path: serve from short-TTL cache if we searched this symbol recently
            cache_key = (symbol, company_name, limit)
            with self._cache_lock:
                cached = self._cache.get(cache_key)
            if cached:
                cached_at, cached_result = cached
                if time.time() - cached_at < self.NEWS_CACHE_TTL_SECONDS:
                    logger.debug(f"{symbol}: News cache hit ({time.time() - cached_at:.0f}s old)")
                    return cached_result

            # Build search query using BOTH ticker and company name for better results
            # Example: "AAPL" OR "Apple Inc" (stock OR shares)
            if company_name:
                # Use company name + ticker for better coverage
                query = f'("{symbol}" OR "{company_name}") (stock OR shares) (surge OR breakout OR rally OR gap OR earnings OR FDA OR approval OR deal OR contract OR acquisition OR merger OR upgraded OR wins OR beats)'
            else:
                # Fallback to ticker only
                query = f'"{symbol}" (stock OR shares OR ticker) (surge OR breakout OR rally OR gap OR earnings OR FDA OR approval OR deal OR contract OR acquisition OR merger OR upgraded OR wins OR beats)'
            
            # Use Google News RSS feed (still works!)
            # Format: https://news.google.com/rss/search?q=YOUR_QUERY&hl=en-US&gl=US&ceid=US:en
            encoded_query = urllib.parse.quote(query)
            url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
            
            # Fetch RSS feed - reuse pooled session (keep-alive) for speed
            response = self._session.get(url, timeout=5)
            
            if response.status_code != 200:
                logger.warning(f"{symbol}: Google News returned status {response.status_code}")
                return {'has_news': False, 'articles': []}
            
            # Parse RSS XML (simple parsing - look for first <title> in <item>)
            content = response.text
            
            # Check if there are any results
            if '<item>' not in content:
                # No news found
                result = {'has_news': False, 'articles': []}
                with self._cache_lock:
                    self._cache[cache_key] = (time.time(), result)
                return result
            
            # Extract all news items (up to limit)
            articles = []
            search_pos = 0
            
            for _ in range(limit):
                item_start = content.find('<item>', search_pos)
                if item_start == -1:
                    break
                
                item_end = content.find('</item>', item_start)
                if item_end == -1:
                    break
                
                item_content = content[item_start:item_end]
                
                # Extract title
                title_start = item_content.find('<title>') + 7
                title_end = item_content.find('</title>')
            
                
                if title_start > 6 and title_end > title_start:
                    title = item_content[title_start:title_end]
                    title = title.replace('<![CDATA[', '').replace(']]>', '')
                    
                    # CRITICAL RELEVANCE CHECK - Must mention stock/company in headline
                    title_lower = title.lower()
                    symbol_lower = symbol.lower()
                    
                    # Check if this is actually about the stock
                    is_relevant = (
                        (symbol_lower in title_lower and ('stock' in title_lower or 'shares' in title_lower or 'nasdaq' in title_lower or 'nyse' in title_lower)) or
                        'ticker' in title_lower or
                        'ipo' in title_lower or
                        'market' in title_lower and symbol_lower in title_lower
                    )
                    
                    if not is_relevant:
                        # Skip irrelevant news (e.g., "RIOT" about actual riots, not Riot Platforms stock)
                        continue
                    
                    # ENHANCED SENTIMENT SCORING - shared helper (same catalyst
                    # bar used for the Alpaca/Benzinga news check, so both
                    # sources are judged identically)
                    scored = score_headline(title)
                    if scored is None:
                        logger.debug(f"{symbol}: Rejected news: {title[:50]}")
                        continue
                    score = scored['score']
                    sentiment_label = scored['sentiment']
                    matched_catalysts = scored['catalysts']
                    
                    # Extract link
                    link_start = item_content.find('<link>') + 6
                    link_end = item_content.find('</link>')
                    link = item_content[link_start:link_end] if link_start > 5 and link_end > link_start else ""
                    
                    # Extract source
                    source_start = item_content.find('<source>') + 8
                    source_end = item_content.find('</source>')
                    source = item_content[source_start:source_end] if source_start > 7 and source_end > source_start else "Google News"
                    
                    # Extract pubDate
                    pubDate_start = item_content.find('<pubDate>') + 9
                    pubDate_end = item_content.find('</pubDate>')
                    pubDate = item_content[pubDate_start:pubDate_end] if pubDate_start > 8 and pubDate_end > pubDate_start else ""
                    
                    # Determine news freshness (Breaking/Warm/Cold) - shared helper
                    news_freshness = 'unknown'
                    days_old = None
                    if pubDate:
                        try:
                            # Parse RSS date format: "Mon, 06 Jan 2026 12:00:00 GMT"
                            from email.utils import parsedate_to_datetime
                            pub_datetime = parsedate_to_datetime(pubDate)
                            news_freshness, days_old = classify_freshness(pub_datetime)
                        except Exception as date_err:
                            logger.debug(f"Could not parse date {pubDate}: {date_err}")
                    
                    articles.append({
                        'title': title,
                        'link': link,
                        'source': source,
                        'pubDate': pubDate,
                        'sentiment': sentiment_label,
                        'score': score,
                        'catalysts': matched_catalysts,  # Top 3 matched keywords
                        'freshness': news_freshness,  # breaking, warm, cold
                        'days_old': days_old
                    })
                    
                    logger.info(f"{symbol}: Found {sentiment_label} news (score: {score}, {news_freshness}): {title[:60]}")
                
                # Move to next item
                search_pos = item_end + 7
            
            # Return results
            if articles:
                logger.info(f"{symbol}: Found {len(articles)} news article(s)")
                result = {'has_news': True, 'articles': articles}
            else:
                logger.debug(f"{symbol}: No news found")
                result = {'has_news': False, 'articles': []}

            with self._cache_lock:
                self._cache[cache_key] = (time.time(), result)
            return result
            
        except requests.Timeout:
            logger.warning(f"{symbol}: Google News request timeout")
            return {'has_news': False, 'articles': []}
        except Exception as e:
            logger.error(f"{symbol}: Error searching Google News: {str(e)}")
            return {'has_news': False, 'articles': []}
    
    def batch_search_news(self, symbols: list, max_concurrent: int = 10) -> Dict[str, Dict]:
        """
        Search news for multiple symbols in parallel
        
        Args:
            symbols: List of stock symbols
            max_concurrent: Max concurrent requests (respect rate limits)
        
        Returns:
            Dict mapping symbol to {'has_news': bool, 'articles': []}
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        results = {}
        
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(self.search_stock_news, symbol): symbol 
                      for symbol in symbols}
            
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result = future.result()
                    results[symbol] = result
                except Exception as e:
                    logger.error(f"Error fetching news for {symbol}: {str(e)}")
                    results[symbol] = {'has_news': False, 'articles': []}
        
        logger.info(f"Batch news search: {sum(1 for r in results.values() if r['has_news'])}/{len(symbols)} stocks have news")
        return results


# Global instance
google_news_service = GoogleNewsService()


def search_google_news(symbol: str) -> Dict:
    """
    Convenience function to search Google News for a symbol
    
    Usage:
        has_news, headline = search_google_news("AAPL")
        if has_news:
            print(f"News: {headline}")
    """
    return google_news_service.search_stock_news(symbol)
