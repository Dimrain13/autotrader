#!/usr/bin/env python3
"""VPS-side helper for AI news grader — pymongo + local MongoDB access.
Hermes grader SSHs in:
  --fetch  : return ungraded headlines (queue first, then scans backlog) as JSON
  --apply  : read grades from stdin, upsert into news_grades, clear queue entries
  --enqueue: read {headline, symbol, freshness, score, link}[] from stdin, add to news_grade_queue
"""
import sys, json, hashlib
from datetime import datetime, timezone
from pymongo import MongoClient

DB = MongoClient('mongodb://localhost:27017').momentumx

def hhash(title):
    return hashlib.md5((title or '').strip().lower().encode()).hexdigest()

def fetch_ungraded():
    graded = {g['headline_hash'] for g in DB.news_grades.find({}, {'headline_hash': 1})}
    seen = {}
    order = []
    # 1) on-demand queue first (priority)
    for q in DB.news_grade_queue.find({}).sort('requested_at', 1):
        h = q['headline_hash']
        if h in graded or h in seen:
            continue
        seen[h] = {'headline_hash': h, 'headline': q.get('headline',''), 'symbol': q.get('symbol',''),
                   'freshness': q.get('freshness'), 'score': q.get('score'), 'link': q.get('link','')}
        order.append(h)
    # 2) scans backlog
    for scan in DB.scans.find({'results.news_articles': {'$exists': True}}):
        for r in scan.get('results', []):
            sym = r.get('symbol', '')
            for a in r.get('news_articles') or []:
                t = (a.get('title') or '').strip()
                if not t or len(t) < 5:
                    continue
                h = hhash(t)
                if h in graded or h in seen:
                    continue
                seen[h] = {'headline_hash': h, 'headline': t, 'symbol': sym,
                           'freshness': a.get('freshness'), 'score': a.get('score'),
                           'link': a.get('link', '')}
                order.append(h)
    return [seen[h] for h in order]

def apply_grades(grades):
    now = datetime.now(timezone.utc).isoformat()
    for g in grades:
        g['graded_at'] = now
        DB.news_grades.update_one({'headline_hash': g['headline_hash']}, {'$set': g}, upsert=True)
        DB.news_grade_queue.delete_many({'headline_hash': g['headline_hash']})

def enqueue(items):
    now = datetime.now(timezone.utc).isoformat()
    for it in items:
        h = hhash(it.get('headline'))
        if DB.news_grades.find_one({'headline_hash': h}):
            continue  # already graded
        DB.news_grade_queue.update_one(
            {'headline_hash': h},
            {'$set': {'headline': it.get('headline',''), 'symbol': it.get('symbol',''),
                       'freshness': it.get('freshness'), 'score': it.get('score'),
                       'link': it.get('link',''), 'requested_at': now}},
            upsert=True
        )

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == '--fetch':
        print(json.dumps(fetch_ungraded()))
    elif mode == '--apply':
        apply_grades(json.load(sys.stdin))
        print(json.dumps({'applied': 'ok'}))
    elif mode == '--enqueue':
        enqueue(json.load(sys.stdin))
        print(json.dumps({'enqueued': 'ok'}))
    else:
        print('usage: --fetch | --apply | --enqueue', file=sys.stderr)
        sys.exit(1)
