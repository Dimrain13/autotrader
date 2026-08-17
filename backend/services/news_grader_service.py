"""
AI news-grade lookup for the scanner.

Grades are written by the Hermes-side grader (news_grader.py over SSH) into
momentumx.news_grades, keyed by headline MD5. This service reads those grades
and decides whether an article is a real, important catalyst (Ross-faithful):

- If an AI grade exists: catalyst iff freshness in (breaking, warm, unknown)
  AND level in (strong, momentum). weak/negative/none never pass.
- Else: fall back to the keyword score (score >= min_score AND not negative).

The in-memory cache is refreshed every 5 min; the API endpoint queries Mongo
directly for on-demand display (so a just-graded article shows immediately).
"""
import hashlib
import threading
import time
from datetime import datetime, timezone

from pymongo import MongoClient

_DB = MongoClient('mongodb://localhost:27017').momentumx
_cache = {}
_cache_time = 0.0
_CACHE_TTL = 300.0
_lock = threading.Lock()

_IMPORTANT = ('strong', 'momentum')
_FRESH = ('breaking', 'warm', 'unknown')


def hhash(title):
    return hashlib.md5((title or '').strip().lower().encode()).hexdigest()


def ensure_index():
    _DB.news_grades.create_index('headline_hash', unique=True)


def _refresh():
    global _cache, _cache_time
    with _lock:
        if time.time() - _cache_time < _CACHE_TTL:
            return
        try:
            _cache = {g['headline_hash']: g for g in _DB.news_grades.find({})}
            _cache_time = time.time()
        except Exception:
            pass


def get_grade(headline):
    """Return the cached AI grade dict for a headline, or None."""
    _refresh()
    return _cache.get(hhash(headline))


def get_grade_direct(headline):
    """Query Mongo directly (no cache) — used by the on-demand API path."""
    return _DB.news_grades.find_one({'headline_hash': hhash(headline)})


def article_is_catalyst(article, min_score=5):
    """True if the article is a fresh, important catalyst."""
    g = get_grade(article.get('title', ''))
    if g:
        fresh = article.get('freshness') in _FRESH
        return fresh and g.get('level') in _IMPORTANT
    return (article.get('score') or 0) >= min_score and not article.get('is_negative')


ensure_index()


def enqueue_articles(items):
    """Add ungraded articles to the on-demand queue (fire-and-forget from API)."""
    now = datetime.now(timezone.utc).isoformat()
    for it in items:
        h = hhash(it.get('headline'))
        if _DB.news_grades.find_one({'headline_hash': h}):
            continue
        _DB.news_grade_queue.update_one(
            {'headline_hash': h},
            {'$set': {'headline': it.get('headline', ''), 'symbol': it.get('symbol', ''),
                       'freshness': it.get('freshness'), 'score': it.get('score'),
                       'link': it.get('link', ''), 'requested_at': now}},
            upsert=True
        )
