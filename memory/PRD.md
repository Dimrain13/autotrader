# MomentumX (Internal-Trader) — PRD & Remediation Log

## Original Problem Statement
Internal-Trader (MomentumX): React + FastAPI + MongoDB algorithmic trading app,
self-hosted on Windows Server VPS (RDP), broker Alpaca. Goal: remediate a
5-phase security/correctness/reliability audit, in order, staying on PAPER
trading until Phases 1-3 are done and verified. Source repo:
https://github.com/Dimrain13/Internal-trader

Phases: 1) Critical Security, 2) Critical Trading Correctness,
3) Architecture/Reliability, 4) Logic Quality/Trust, 5) Windows-VPS Deployment.

## User Choices (gathered via ask_human)
- Remote access: RDP/localhost only, no external exposure needed.
- Auto-trader: keep full auto-trader with real background loop.
- Daily-loss kill switch: YES, hard kill switch (blocks new BUY orders).
- Session scope: Phase 1-3 only (Security + Trading Correctness + Architecture/Reliability). Phase 4/5 deferred.
- Alpaca paper credentials: NOT provided (only a partial key ID, no secret) — ALPACA_API_KEY/SECRET intentionally blank; app gracefully errors "Alpaca API not configured" instead of faking data.

## Architecture
- Backend: FastAPI (`/app/backend/server.py`), services in `/app/backend/services/*`
- New shared modules: `database.py` (Motor client), `auth.py` (bearer token dependency)
- Frontend: React (`/app/frontend/src`), axios global interceptor in `lib/axiosConfig.js`
- DB: MongoDB — `auto_trader_state`, `monitored_positions`, `trade_history`, `missed_opportunities`, `app_config`, `scans` collections

## What's Been Implemented (2026-07-10)

### Phase 1 — Critical Security ✅
1. Bearer token auth (`API_ACCESS_TOKEN` in `.env`) via `Depends(verify_token)` on entire `api_router`. Frontend token gate screen + axios interceptor + 401 auto-logout.
2. `/api/settings` GET masks both `api_key` and `secret_key` (never plaintext). POST only accepts `sma_short`/`sma_long` (Pydantic `SmaSettingsUpdate`), persisted to Mongo `app_config` — runtime `.env` rewriting of secrets removed entirely.
3. CORS: explicit `CORS_ORIGINS` env list, no `*` default, verified reflects only whitelisted origins.
4. `slowapi` rate limiting (20/min orders, 10/min scan/cancel/process, 20/min demo). `TradeOrder`/`ScanCriteria` now strict Pydantic models (qty>0, side literal buy/sell, pct bounds, price bounds).

### Phase 2 — Trading Correctness ✅
5. `alpaca_service.py`: `paper` flag driven by `ALPACA_PAPER` env or inferred from `base_url`; bold LIVE_TRADING warning banner + startup log.
6. Removed all synthetic/random-OHLC generation (`get_bars`, `check_entry_conditions`). Standardized on `get_bars_with_fallback` (Alpaca→Yahoo→Nasdaq, real data only); explicit "no data" errors, auto-trader skips symbol on missing data.
7. `close_close` NameError bug: moot — entire fake-data block removed.
8. Removed `DAY_TRADING_MODE` fake buying-power simulation from `/account`.

### Phase 3 — Architecture/Reliability ✅
9. Real `asyncio.create_task(auto_trader_loop())` on startup, 60s interval, gated by `auto_trader.active`. `/auto-trader/process` kept as manual trigger only. Fixed pre-existing arity bug (was called with 3 args, signature takes 2).
10. `auto_trader` + `position_monitor` state (`open_positions`, `daily_pnl`, `consecutive_losses`, `exited_today`, `monitored_positions`) persisted to MongoDB, restored on startup — verified surviving an actual backend restart.
11. Wrapped all sync Alpaca/requests calls in `asyncio.to_thread` across `server.py` and all services. Removed blocking `asyncio.sleep(2)` fill-wait in `place_order`.
12. `trade_history` and `missed_opportunities` migrated from flat JSON files to MongoDB collections (fully async).

### Extras implemented
- Hard server-side kill switch: blocks new BUY orders via `/api/orders` once daily loss limit / consecutive losses hit (per user's explicit choice), in addition to auto-trader's own gating.
- Real fill price (`filled_avg_price`) used for P&L logging instead of last quote, where available.
- Fixed missing `alpaca_service.cancel_all_orders()` method (was called by EOD closer but never defined).
- Phase 5 quick wins: removed committed `.gitconfig` and junk `=` file; confirmed `.env` gitignored.

### Testing
- Existing `test_auto_trader_exit_logic.py` (16 tests): PASS.
- New `test_security_and_trading.py` (25 tests, added by testing agent): PASS — covers auth, CORS, rate limiting, validation, no-fake-data, kill switch, state persistence, unified persistence.
- Fixed 1 HIGH bug found by testing: logout button was unreachable (nested inside `{account && ...}`), hoisted PAPER badge + logout button outside that conditional.

## Session 4 Update (2026-07-10) — Token Confusion UX Fix
- User reported: "what API access token is needed to unlock the site? PKRBZGHKVX2SGHWQZZVRJLXRPN didn't work" — this was the Alpaca broker key, not the site's `API_ACCESS_TOKEN`. Correctly rejected by design (broker credentials must never double as site auth).
- Fix: clarified `TokenGate` copy in `frontend/src/App.js` (intro text, footer note, error message) to explicitly distinguish the site's `API_ACCESS_TOKEN` (backend/.env) from the Alpaca API key/secret.
- Testing agent verified 100% pass (41/41 pytest + full TokenGate UX flow) — no functional regression, copy renders correctly.
- Cleaned up test-artifact positions/trade-history entries left in the live paper account from verification testing.

## Session 5 Update (2026-07-10) — VPS Deployment Readiness Check
- Ran `deployment_agent` health check. Result: no real blockers for the Windows VPS target. One flagged "BLOCKER" (CORS_ORIGINS should be `*`) is a **false positive** — that rule is calibrated for Emergent's own `*.emergent.host` hosting, not this app's actual self-hosted-VPS target, and applying it would violate the explicit Phase 1 #3 security requirement (no `*` + credentials). Correctly NOT applied.
- Fixed legitimate finding: added `/memory/` and `test_credentials.md` to `.gitignore` (contains live Alpaca paper secret + API_ACCESS_TOKEN, was not previously excluded from git).
- Confirmed installed stack: Python 3.11.15, Node 20.20.2/Yarn 1.22.22, MongoDB 7.0.37; key backend deps `fastapi==0.110.1`, `alpaca-py==0.30.1`, `motor==3.3.1`, `slowapi==0.1.10`, `pydantic==2.12.4`; key frontend deps `react==19`, `react-router-dom==7`, `axios`, `lightweight-charts==4.1.3`, `tailwindcss==3.4`.
- Backlog (non-blocking): unbounded Mongo `.to_list(length=10000)` reads in `trade_history_service.get_analytics()` / `missed_opportunities_service.get_analytics()` — add projections/date-bounding as trade volume grows.

## Session 6 Update (2026-07-10) — Performance + Linux Deployment
- User moving VPS target to Linux (SSH port-forward for access, same 127.0.0.1-only security model as RDP). Added `/app/deploy/linux/` (systemd services, `start.sh`, install/uninstall scripts, README) alongside the existing Windows artifacts. Root README now links both.
- Performance: `google_news_service.py` now uses a pooled `requests.Session()` + 3-minute TTL cache per (symbol, company_name, limit) - repeated news lookups ~30x faster (645ms → ~20-100ms cache hit). Fixed a latent bug where two early-return paths returned a bare tuple instead of the documented `{'has_news', 'articles'}` dict (would have crashed callers if ever hit).
- `alpaca_service.py`: `get_asset()` (company name lookup) now has a 24h TTL cache; Yahoo/Nasdaq fallback bar-fetching now reuses a pooled session too.
- `scanner_service.py`: news-check `ThreadPoolExecutor` increased from 5→12 concurrent workers.
- **Safety catch**: found the auto-trader unexpectedly `active=true` (leftover from an old persistence test, now with real Alpaca keys live) — turned off, confirmed OFF and persists across restart.
- **Critical bug found+fixed by testing agent**: `tests/test_security_and_trading.py::TestRateLimiting` placed real (paper) BUY orders on every test run with no broker mocking, silently accumulating an AAPL position (1→20→28 shares across sessions). Fixed to use a non-existent ticker (still exercises the rate-limiter, never reaches a real tradable symbol). Liquidated the accumulated 20-share position — account is now flat. All 41 tests still pass.

## Session 8 Update (2026-07-10) — "Find News ASAP" Fix (Warrior Trading Timing)
- **User concern**: news detection was lagging behind the other scanner metrics (price/volume/float flagged first, news confirmation came much later) — problematic for Warrior Trading, where news is usually the root catalyst, not a lagging confirmation.
- **Root cause found**: the scanner checked Google News (slow HTML/RSS scraping, ~1-3s/symbol, ~40s total for 50 candidates under connection-pool contention) as PRIMARY, and only fell back to Alpaca's real-time News API (Benzinga-powered, already included in the existing Alpaca data subscription) if Google News found nothing. The Alpaca fallback itself had a **timezone-naive datetime bug** that made it silently return 0 results every single time — so it never actually rescued anything, and the slow scraper carried 100% of the load.
- **Fix**: flipped priority — `check_alpaca_news()` (new, fixed timezone bug, ~30-200ms/symbol, clean API call) is now checked FIRST; Google News RSS is now the fallback only for illiquid micro-caps Benzinga doesn't cover. Extracted the catalyst-scoring logic (`score_headline`/`classify_freshness`) into shared module-level functions in `google_news_service.py` so both sources apply an identical "real catalyst" quality bar. Also fixed a Google-News connection-pool size mismatch (10 vs 12 worker threads).
- **Concurrency**: volume/float/news second-pass checks now run in 3 parallel threads instead of sequentially (previously: volume → float → news, one after another). Found and fixed a resulting **shared-counter race condition** (all three previously did `criteria_count += 1` on the same dict from different threads) by having each check only write to its own `criteria_met[...]` key, then doing one authoritative `criteria_count` recompute pass after all three finish.
- **Bonus fix**: found and fixed a real (pre-existing, unrelated) race condition in `scan_market()`'s `is_scanning` check-and-set (no lock — two concurrent requests could both bypass the "scan already running" guard and trigger two simultaneous full-market scans, causing Alpaca 429s). Added `threading.Lock`.
- **Result**: real scan latency dropped from ~40-60s to ~6-25s (measured across multiple live scans). This also fixed a previously-flaky pytest test that was timing out due to the old slow news path.
- Testing: 47/47 pytest passing (no flake), 0 criteria_count mismatches across 100 fully-verified scan results in live testing, frontend regression clean. Found + fixed test hygiene bug: `test_manual_process_trigger_no_arity_bug` could leave the auto-trader `active=true` if its assertion failed (no try/finally) — fixed with try/finally, always disables afterward now.

## Session 9 Update (2026-02) — Linux Frontend Systemd Deployment Fix (P0 Blocker Resolved)
- **Bug reported**: on user's live Linux VPS, `momentumx-backend.service` started fine but `momentumx-frontend.service` failed with `status=1/FAILURE`. Previous agent (before this fork) suspected an `EACCES` npm/npx permission error from the low-privilege `momentumx` system user.
- **Actual root cause found+reproduced**: `serve` v14.2.6's `-l`/`--listen` flag changed its parsing — a bare `host:port` string (e.g. `127.0.0.1:4000`, used in the old `ExecStart`) now REQUIRES a URI scheme prefix and throws `Error: Unknown --listen endpoint scheme (protocol): 127.0.0.1:` (exit code 1) otherwise. Reproduced verbatim even as root — confirmed unrelated to file permissions.
- **Fix**: `/app/deploy/linux/momentumx-frontend.service` `ExecStart` changed to `/usr/bin/serve -s build -l tcp://127.0.0.1:4000` (direct binary path, bypassing `npx`; correct `tcp://` scheme). Added `Environment=HOME=/tmp` as defensive hardening (guaranteed-writable dir via `PrivateTmp=true`, protects against any update-notifier cache-write issue for the `--no-create-home` momentumx user under real systemd sandboxing, which can't be fully replicated in this sandbox — no systemd PID1 available here).
- Same `-l host:port` → `-l tcp://host:port` fix applied for consistency to the 3 other places with the identical bug: `/app/deploy/linux/start.sh`, `/app/deploy/windows/install_nssm_service.ps1`, `/app/deploy/windows/start.bat`.
- `install_systemd_services.sh` step [7/7]: added `chown -R momentumx:momentumx "$ROOT_DIR"` after `useradd`, so the service user is guaranteed read access to built frontend/backend files regardless of who ran the installer.
- **Testing**: `testing_agent_v4` validated via bash simulation (no systemd daemon in this sandbox) — reproduced original crash, verified fix resolves it (HTTP 200 as an unprivileged throwaway system user), confirmed all 4 files consistent, confirmed no regression in the running sandbox app. 100% pass, no action items. See `/app/test_reports/iteration_8.json`.

## Session 10 Update (2026-02) — Trading Hours Timezone/Weekday Clarification + Weekend Bug Fix
- User asked whether the 7AM-3:30PM trading window uses their local timezone. Clarified: intentionally hardcoded to `US/Eastern` (not user-local) since the Warrior Trading window is anchored to real NYSE/NASDAQ market hours, which are always defined in ET regardless of trader location.
- **Bug found+fixed while verifying**: `auto_trader_service.is_trading_hours()` and `is_entry_window()` had no weekday check — would treat Saturday/Sunday 7AM-3:30PM ET as valid trading hours (unlike `eod_closer_service.py`, which already correctly skips weekends). Added `now_et.weekday() >= 5` guard to both methods, matching the EOD closer's existing pattern.
- Also investigated user's earlier observation that "scanning only runs when on the page" — confirmed via live backend logs that the real auto-trader engine (`auto_trader_loop()`, 60s interval) already runs fully decoupled from the frontend (started at server boot, gated only by DB-persisted `active` flag) - not a bug. Only the Scanner page's own visual "Auto-Scan" results table is page-scoped (normal SPA component lifecycle), which is a UX nuance, not a functional trading gap.
- Added 4 new regression tests (`TestTradingHours` in `test_auto_trader_exit_logic.py`) covering weekend rejection (Sat/Sun) and weekday acceptance for both `is_trading_hours()`/`is_entry_window()`. Full suite: 20/20 passing in that file.

## Session 11 Update (2026-02) — "7-11 AM" Misleading Label Fix + Trading Hours Display Bug
- User asked why they see an "Outside 7-11 AM ET" warning and confirmed they want entries allowed any time within the full EST trading window. Investigation confirmed: the actual entry logic was ALREADY correct — `is_entry_window()` (7-11 AM restriction) was dead code, never wired into `process_scanner_results()`/`check_entry_signals()`, which only ever gated on `is_trading_hours()` (7 AM-3:30 PM). The bug was purely a misleading UI label.
- **Removed** the unused `is_entry_window()` method entirely (dead code, contradicted actual/desired behavior) and its now-obsolete docstring/comment references to a "7-11 AM entry-only" window in `auto_trader_service.py`.
- **Fixed misleading text** in `Trading.js` ("⏰ Outside 7-11 AM ET" → "Outside Trading Hours (7 AM - 3:30 PM ET)"), `Settings.js` (strategy card + trading hours row), `Scanner.js` (fallback text) to correctly state entries+management run the full 7 AM-3:30 PM ET window.
- **Fixed a separate display bug** found while in this area: `trading_hours` strings in `/auto-trader/status` and `/auto-trader/entry-conditions/{symbol}` rendered as nonsensical `"15:30 PM EST"` (used the 24h end-hour with a "PM" suffix). Now correctly converts to 12h format → `"7:00 AM - 3:30 PM EST"`. Same fix applied to the backend log line in `process_scanner_results()`.
- Removed the corresponding `test_entry_window_false_on_weekend` test (method deleted); kept the 3 weekend/weekday `is_trading_hours()` regression tests from Session 10. 19/19 passing in `test_auto_trader_exit_logic.py`. Verified live via curl: both endpoints now return `"7:00 AM - 3:30 PM EST"`.

## Session 12 Update (2026-02) — Global Scanner Architecture + History Date Bug (Verified)
- **Bug**: Scanner page's Auto-Scan (60s scan loop + notification beep for new 5/5 stocks) was scoped to the Scanner page's own React component lifecycle - it stopped whenever the user navigated to any other page. Dashboard.js also ran its OWN independent, redundant scan-fetch loop.
- **Fix**: Created `/app/frontend/src/hooks/useGlobalScanner.js` - a custom hook called ONCE at the `App.js` root (never unmounts across route changes). It owns autoScan/demoMode/autoTrade/results/criteria/traderStatus state and the 60s interval + new-stock alert beep. `App.js` passes the resulting `scanner` object down as a prop to both `Dashboard` and `Scanner` routes. `Scanner.js` and `Dashboard.js` were refactored to consume this shared prop instead of owning independent state/fetches - eliminates the duplicate parallel scans and makes scanning genuinely app-wide/session-persistent.
- Also lifted `positions`/`recentOrders` fetching from Dashboard-local to a global 30s poller in `App.js` (alongside the existing `account` poller), so this data stays fresh regardless of which page is active.
- **Separate bug found+fixed**: History page's "TODAY" badge on the Daily P&L Tracker assumed the first/most-recent row was always today (`idx === 0`), rather than comparing actual dates - would mislabel e.g. Friday's data as "TODAY" on a later day with no new trades. Fixed with a proper `getETDateKey()` comparison against the real current US/Eastern date (trading days are ET-anchored, so this is the correct timezone to use, not raw UTC or browser-local). Also fixed the underlying naive-timestamp bug in `auto_trader_service.py` (`datetime.now()` → `datetime.now(timezone.utc)` for `entry_time`/`exit_time`/signal `timestamp`) which could shift calendar-date computation depending on browser timezone; confirmed NOT site-wide (isolated to History's daily-grouping + auto-trader source data).
- **Verified via `testing_agent_v4`** (`iteration_10.json`): live 70-second test confirmed a `/api/scanner/scan` background request fired while sitting on Dashboard (not Scanner), scan count incremented from navigating away and back, Dashboard's shared data matched Scanner's exactly. History's TODAY badge correctly applied only to the real current date. 100% pass, no regressions, no action items.
- Trading.js intentionally left with its own page-scoped polling (positions/scanner/momentum every 15-60s) - this only runs while actively on the trading terminal itself, which is the expected/desired behavior for that page (not the "stops when I leave" pattern the user was reporting), and changing it risked regressions in the buy/sell order flow for limited additional benefit.

## Deferred / Backlog (P1/P2)
- Consider splitting `server.py` (1280+ lines) into per-domain routers (orders/settings/auto-trader/market) for maintainability (noted by testing agent, non-blocking).
- Docker Desktop / `docker-compose.yml` path was NOT built (user chose Windows-native/NSSM) — available on request if preference changes later.
- Pre-existing scanner performance issue (found this session, not fixed - separate scope): `_check_candidate_news` (Google News scraping) can take ~40s under connection-pool contention with news.google.com, occasionally causing `/auto-trader/process` to exceed the ingress gateway timeout (502). Real float lookup (this session's fix) only adds ~0.1-2s, confirmed via logs — not the bottleneck. Candidate future fix: swap/augment Google News scraping with a proper news API, or increase gateway timeout.
- Optional (still open, not actioned): LLM-based news-catalyst sentiment classification to replace the current keyword-match approach — bigger scope, needs a new LLM key integration.

## Session 7 Update (2026-07-10) — Warrior Trading Review + Real Float Data Fix
- **CRITICAL FIX**: The scanner's "Float < 20M shares" criterion (one of the 5 required Warrior Trading pillars) was silently using `random.randint()` fake data every time the optional Interactive Brokers float service wasn't connected (which it always was, in this setup) — directly violating the "no fake data" mandate from Phase 2 and corrupting the strategy's stock-selection quality. Root-caused during a Ross Cameron strategy review requested by the user.
- Fix: added `alpaca_service.get_float_data()` — real shares-outstanding data from **SEC EDGAR** (`data.sec.gov`, free, no API key, real company filings via `dei/EntityCommonStockSharesOutstanding` with `us-gaap/CommonStockSharesOutstanding` fallback), 24h TTL cache, ticker→CIK mapping cached once/24h. `scanner_service._calculate_accurate_float()` runs this in parallel (10 workers) for the top 50 candidates, same pattern as the existing volume/news second-pass verification. If no real data is found (unknown ticker, no filings), the float criterion is marked **unmet** (fail-safe) — never guessed. IB float service (if ever connected) still takes priority as source #1.
- Verified real & consistent (not random) via two consecutive scans returning identical `shares_outstanding` for the same symbols; added regression test `tests/test_float_and_analytics.py::TestScannerRealFloat`.
- Frontend: Scanner.js Float column now shows "N/A" (not misleading "0.0M") when float data is unknown.
- Updated stale PDT (Pattern Day Trader) messaging in `Dashboard.js` ("Account Leverage" card) — SEC/FINRA eliminated the classic $25k-minimum/3-day-trades-per-5-days PDT rule in 2026 (effective June 2026, broker rollout phases in through Oct 2027), replaced by real-time intraday margin monitoring. Old absolute claim removed.
- **P1 backlog closed**: bounded `trade_history`/`missed_opportunities` analytics Mongo queries — `get_analytics()` now filters by date at the query level (default last 180 days, `days=0`/`None` for all-time) instead of loading up to 10,000 raw docs into memory. New `?days=` query param on both `/trade-history/analytics` and `/missed-opportunities/analytics`.
- **P2 backlog closed**: kill-switch notification — `App.js` polls `/auto-trader/status` every 30s app-wide (any page) and fires a `sonner` toast (edge-triggered, once per true→false transition) when the daily-loss/consecutive-loss kill switch halts trading. Toast-only per user's choice (no email integration).
- Testing: 47/47 backend pytest passing (41 previous + 6 new), full frontend regression clean (Dashboard/Scanner/Trading/History/Missed/Settings/Demo). One pre-existing minor React key-prop warning on History page noted (cosmetic, unrelated to this session).

## Next Action Items
1. Follow `/app/deploy/windows/README.md` to actually deploy on the Windows Server VPS once ready to leave the Emergent preview environment.
2. After a period of verified paper trading, flip `ALPACA_PAPER=false` deliberately (bold warning banner logs on startup) to go live with tiny size, per the rollout/safety plan in the original problem statement.

## Session 3 Update (2026-07-10) — Real Alpaca Paper Verification
- User provided real Alpaca paper credentials (key `PKRBZGHKVX2SGHWQZZVRJLXRPN`, account `PA30RVV1A2DM`). Configured in `backend/.env`.
- Found + fixed a real bug during first live call: `alpaca_service.get_account()` crashed with `float() argument ... NoneType` because this paper account's `daytrading_buying_power`/`pattern_day_trader` fields come back as `None` from Alpaca (cash/non-margin account) — now defaults gracefully to `0.0`/`False` instead of crashing.
- Verified end-to-end with a real order round trip: BUY 1 AAPL → real fill price ($313.07) → position auto-added to monitor with real stop config → real buying-power deduction → SELL 1 AAPL → real trade-history entry logged with real P&L. Real market bars confirmed via Yahoo fallback (Alpaca free-tier IEX data was stale) — no fake data anywhere.
- Fixed one stale test assertion in `test_security_and_trading.py` that hardcoded an empty-API-key expectation; now environment-agnostic. All 41 tests still pass.


## Session 2 Update (2026-07-10) — Phase 4 & 5

### Phase 4 — Logic Quality/Trust ✅
- **#13 Reconciled strategy params** with Ross Cameron's documented Warrior Trading rules (user's explicit choice): kept code's 10% position size / 2% profit target / 1% stop loss (already a correct 2:1 R:R), changed `daily_max_loss_pct` from 5% → **1%** (Ross's "conservative starting" daily-loss rule) as a hard kill switch. Fixed all stale UI text (`Settings.js` info card) and `WARRIOR_TRADING_STRATEGY.md` doc to match the reconciled values exactly (was showing stale 5%/10%/5%/10%/11 AM).
- **check_micro_pullback wired in** as a REQUIRED entry condition (`require_micro_pullback=True`) — was previously computed but unused (diagnostic-only). Now gates real auto-trader entries in `check_entry_signals()`, checked first (after 5/5 scanner criteria, before volume/MACD/SMA).
- **#15 Extended-hours slippage guard**: tightened the market-order limit-price buffer from ±10% → ±3%, and added a hard reject when bid/ask spread > 8% (protects against illiquid $2-$20 low-float names in extended hours).
- **Bonus bug fix**: `POST /api/auto-trader/settings` was silently broken (AttributeError referencing non-existent `pullback_min_pct`/`pullback_max_pct`) — fixed to use the real attribute names and added `require_micro_pullback` to the response.
- **#14 (real fill prices for P&L)** was already implemented during the Phase 1-3 pass (server.py sell logging, auto_trader monitor_exits, position_monitor partial/stop/bearish-exit paths all already read `filled_avg_price` when available).

### Phase 5 — Windows-VPS Deployment (Windows-native, per user choice — no Docker) ✅
- `/app/deploy/windows/README.md` — full step-by-step guide (prereqs, `.env` setup, build, run)
- `/app/deploy/windows/start.bat` — one-touch manual startup (MongoDB + backend + frontend, 3 windows)
- `/app/deploy/windows/install_nssm_service.ps1` / `uninstall_nssm_service.ps1` — persistent Windows services via NSSM (auto-start, survives reboot/RDP logout), backend bound to `127.0.0.1` only (RDP-only network model, no internet exposure)
- `backend/.env.example`, `frontend/.env.example` — deployment templates
- Root `/app/README.md` rewritten with security summary + link to deploy guide

### Testing (Session 2)
- Testing agent independently re-verified: 41/41 pytest pass, auto-trader/status reflects new params, settings bug fix confirmed, code-review of micro-pullback gating + slippage guard ordering, Settings.js UI text reconciled, all 7 frontend pages smoke-tested, logout regression re-confirmed. Zero bugs found (1 cosmetic stale code comment, fixed).

