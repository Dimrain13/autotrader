"""
Google News Service for Stock News

Searches Google News for real news about stocks
Uses web scraping approach since Google News doesn't have a free API
"""

import requests
from requests.adapters import HTTPAdapter
from datetime import datetime, timedelta
import logging
import re
import time
import threading
from typing import Dict, Tuple, Optional
import urllib.parse
from services import news_grader_service

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

# Large quantified business deal - real dollar figure attached to a deal/
# contract/transaction word. Found 2026-07: VIVK secured $289M in crude-oil
# marketing deals (a real catalyst - shares surged 187% on it per Google
# News), but Alpaca/Benzinga's own headline phrased it as "Vivakor Expands
# Recurring Crude Oil Marketing Programs" / "Announces...Transactions...
# Worth Combined $289M" - dry corporate wording that only matched the WEAK
# tier ('expands'/'announces', score 2), completely missing that a
# quantified $289M figure makes this materially different from a routine
# announcement. A headline naming a specific large dollar amount tied to a
# deal-type word is a real catalyst regardless of which exact verb the
# newswire used - the DOLLAR FIGURE is the signal, the phrasing is noise.
DEAL_INDICATOR_WORDS = [
    'deal', 'deals', 'contract', 'contracts', 'agreement', 'agreements',
    'transaction', 'transactions', 'notes', 'purchase', 'secures', 'secured',
    'securing', 'lands', 'landed', 'wins', 'won', 'order', 'orders',
    'marketing', 'worth', 'financing'
]
_DOLLAR_AMOUNT_RE = re.compile(r'\$\s?(\d+(?:\.\d+)?)\s?(million|billion|m|b)\b', re.IGNORECASE)
MIN_MATERIAL_DEAL_MILLIONS = 10  # $10M+ is material for the $2-$20/low-float names this app trades


def score_headline(title: str) -> Dict:
    """
    Score a headline for Warrior-Trading-style news catalyst strength.

    IMPORTANT: this NEVER discards a headline - it always returns a result,
    for every headline, no exceptions. Raw news should always flow through
    unfiltered; sorting it into a tier (Hot/Medium/Cold/Negative/Neutral) is
    a separate concern from whether to show it at all (user feedback,
    2026-07: "we shouldn't be filtering the news we receive on a stock - we
    should have raw news come in, then it's sorted into different levels").
    Filtering IS still legitimate for a strict yes/no TRADING decision (the
    auto-trader still needs a boolean "is there a real catalyst here" to
    gate entries) - that filtering now happens in the CALLER (e.g. scanner's
    `_check_candidate_news`), which checks `score >= threshold and not
    is_negative` on the full, already-returned article list, instead of
    this function silently dropping headlines before the caller ever sees
    them. A human-facing news feed should just render every article,
    tagged by its sentiment/temperature - nothing pre-filtered away.
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

    # Large quantified business deal - see DEAL_INDICATOR_WORDS comment
    # above. A specific large dollar figure tied to a deal/contract word
    # is a real catalyst regardless of which dry corporate verb the
    # newswire used (found 2026-07: VIVK's $289M crude-marketing deal
    # only hit WEAK via 'expands'/'announces' despite being big enough to
    # drive a 187% surge per Google News' own framing of the same story).
    if score < 10:
        dollar_match = _DOLLAR_AMOUNT_RE.search(title_lower)
        if dollar_match:
            amount = float(dollar_match.group(1))
            unit = dollar_match.group(2).lower()
            amount_millions = amount * 1000 if unit.startswith('b') else amount
            if amount_millions >= MIN_MATERIAL_DEAL_MILLIONS and any(w in title_lower for w in DEAL_INDICATOR_WORDS):
                score = 10
                matched_catalysts.append(f"${amount:.0f}{unit[0].upper()} deal")

    is_negative = any(keyword in title_lower for keyword in NEGATIVE_KEYWORDS)

    if is_negative:
        sentiment_label = 'negative'
    elif score >= 10:
        sentiment_label = 'strong_catalyst'
    elif score >= 5:
        sentiment_label = 'momentum'
    elif score >= 2:
        sentiment_label = 'weak'
    else:
        sentiment_label = 'neutral'

    # "Temperature" for the UI's flame icon - catalyst STRENGTH (hot=real
    # catalyst, medium=price-action momentum, cold=weak generic mention,
    # negative=risk/warning flag), never article age. See classify_freshness
    # below for age, tracked and shown separately as plain text ("2d ago").
    temperature = {'strong_catalyst': 'hot', 'momentum': 'medium', 'weak': 'cold', 'negative': 'negative'}.get(sentiment_label)

    return {
        'score': score,
        'sentiment': sentiment_label,
        'temperature': temperature,
        'catalysts': matched_catalysts[:3],
        'is_negative': is_negative
    }


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
    
    def search_stock_news(self, symbol: str, hours_back: int = 24, limit: int = 5, company_name: str = None, min_score: int = 10) -> Dict:
        """
        Search Google News for stock news and return articles with links

        Args:
            symbol: Stock ticker (e.g., "AAPL")
            hours_back: How far back to look (default 24 hours)
            limit: Maximum number of articles to return (default 5)
            company_name: Company name (e.g., "Apple Inc") - improves search results
            min_score: threshold used ONLY to compute the returned `has_news`
                convenience boolean (a real catalyst exists, score>=min_score
                and not negative) - default 10, the strict bar AUTO-TRADER
                entry decisions need. The `articles` list itself is ALWAYS
                the full raw set (every relevant headline found, unfiltered
                by score) - raw news is never dropped here, only classified
                per-article (sentiment/temperature) for the caller/UI to
                sort and display however it needs (user feedback, 2026-07:
                "we shouldn't be filtering the news we receive on a stock -
                raw news should come in, then it's sorted into levels").

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
            cache_key = (symbol, company_name, limit, min_score)
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

                    # EXCHANGE-COLLISION GUARD (fixed 2026-08-13): the same
                    # ticker can exist on multiple exchanges (e.g. JWEL =
                    # NASDAQ "Jowell Global Ltd." vs JWEL.TO TSX "Jamieson
                    # Wellness Inc."). Alpaca only trades US equities
                    # (NASDAQ/NYSE/AMEX), so ANY headline carrying a
                    # foreign-exchange suffix on our symbol is guaranteed to
                    # be about a different company - reject it outright
                    # regardless of the generic ticker/company-name match
                    # above.
                    foreign_suffix_pattern = re.compile(
                        r'\b' + re.escape(symbol) + r'\.(TO|V|CN|AX|L|HK|SI|SS|SZ|PA|DE|MI)\b',
                        re.IGNORECASE
                    )
                    if foreign_suffix_pattern.search(title):
                        logger.debug(f"{symbol}: rejecting foreign-exchange collision headline: {title[:80]}")
                        continue

                    # COMPANY-NAME CORROBORATION: when we know the correct
                    # company name from Alpaca (the authoritative exchange
                    # source), require the headline to reference it too -
                    # not just the bare ticker - whenever the match so far
                    # came from a generic ticker/keyword hit rather than an
                    # explicit NASDAQ/NYSE mention. This catches collisions
                    # that don't carry an obvious ".TO"-style suffix in the
                    # headline text.
                    if company_name and 'nasdaq' not in title_lower and 'nyse' not in title_lower:
                        # Strip common corporate suffixes to get a
                        # significant, comparable word from the company name.
                        stopwords = {
                            'inc', 'inc.', 'ltd', 'ltd.', 'corp', 'corp.',
                            'corporation', 'company', 'co', 'co.', 'plc',
                            'group', 'holdings', 'holding', 'limited',
                            'the', 'ordinary', 'shares', 'class', 'a', 'b'
                        }
                        name_words = [
                            w.strip('().,').lower()
                            for w in company_name.split()
                            if w.strip('().,').lower() not in stopwords and len(w.strip('().,')) > 2
                        ]
                        if name_words and not any(w in title_lower for w in name_words):
                            logger.debug(
                                f"{symbol}: rejecting headline with no corroborating company-name match "
                                f"(expected one of {name_words[:3]}): {title[:80]}"
                            )
                            continue
                    
                    # ENHANCED SENTIMENT SCORING - shared helper (same catalyst
                    # bar used for the Alpaca/Benzinga news check, so both
                    # sources are judged identically). Every relevant headline
                    # is scored and kept - nothing is dropped for being a
                    # weak/negative/neutral signal, it's just tagged as such.
                    scored = score_headline(title)
                    score = scored['score']
                    sentiment_label = scored['sentiment']
                    temperature = scored['temperature']
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
                        'temperature': temperature,  # hot, medium, cold, negative (catalyst strength - drives flame color)
                        'catalysts': matched_catalysts,  # Top 3 matched keywords
                        'is_negative': scored['is_negative'],
                        'freshness': news_freshness,  # breaking, warm, cold (article age - text only)
                        'days_old': days_old
                    })
                    
                    logger.info(f"{symbol}: Found {sentiment_label} news (score: {score}, {news_freshness}): {title[:60]}")
                
                # Move to next item
                search_pos = item_end + 7
            
            # Return results (highest-relevance catalysts first, not just
            # chronological RSS order - see the identical fix/reasoning in
            # scanner_service.check_alpaca_news()). `articles` is the FULL
            # raw set (nothing dropped for sentiment/score) - `has_news` is
            # just a derived convenience boolean for strict-decision callers.
            if articles:
                articles.sort(key=lambda a: a['score'], reverse=True)
                has_real_catalyst = any(a['score'] >= min_score and not a['is_negative'] for a in articles)
                logger.info(f"{symbol}: Found {len(articles)} news article(s), has_real_catalyst={has_real_catalyst}")
                result = {'has_news': has_real_catalyst, 'articles': articles}
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
