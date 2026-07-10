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

## Deferred / Backlog (P1/P2)
- Alpaca paper API key/secret still not configured — user needs to add real keys to `/app/backend/.env` to fully exercise live order placement, position sizing, and quote/bars endpoints end-to-end, and to live-verify the micro-pullback gating + extended-hours slippage guard (currently code-inspection-verified only).
- Consider splitting `server.py` (1280+ lines) into per-domain routers (orders/settings/auto-trader/market) for maintainability (noted by testing agent, non-blocking).
- Docker Desktop / `docker-compose.yml` path was NOT built (user chose Windows-native/NSSM) — available on request if preference changes later.

## Next Action Items
1. Get user's real Alpaca paper API key + secret to verify live order placement, micro-pullback entry gating, and extended-hours slippage guard end-to-end on paper.
2. Follow `/app/deploy/windows/README.md` to actually deploy on the Windows Server VPS once ready to leave the Emergent preview environment.
3. After a period of verified paper trading, flip `ALPACA_PAPER=false` deliberately (bold warning banner logs on startup) to go live with tiny size, per the rollout/safety plan in the original problem statement.

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

