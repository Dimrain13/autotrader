# News Catalyst Threshold Fix — 2026-08-15

## What changed
Lowered the news catalyst threshold (min_score) from 10 to 5:
- services/scanner_service.py     -> check_alpaca_news()   (Benzinga/Alpaca news)
- services/google_news_service.py -> search_stock_news()   (Google News fallback)

## Why
min_score=10 meant ONLY strong_catalyst-tier headlines (score >= 10: FDA
approval, merger, buyout) counted as a real catalyst. Momentum-tier headlines
(score >= 5: 'jumps', 'launches', 'partnership', etc.) — which Ross Cameron
trades every day — were rejected.

Case (Aug 14, STKH): legit momentum headline 'STKH Stock Jumps As Steakholder
Foods Launches Perfecta In US' scored 5, below the 10 bar -> stuck at 4/5
criteria, never ready_to_trade.

Lowering to 5 includes momentum-tier (score >= 5) while still excluding weak
(2), neutral (0), and negative. Ross-aligned.

## Revert (run this)
cd /opt/autotrader/backend
sed -i 's/min_score: int = 5/min_score: int = 10/' services/scanner_service.py services/google_news_service.py
systemctl stop momentumx-backend && systemctl start momentumx-backend

Backups: services/scanner_service.py.bak_20260815_230829
         services/google_news_service.py.bak_20260815_230829
