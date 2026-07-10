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
- **Phase 4** (Logic Quality): reconcile strategy param mismatches (Settings UI says 5%/10%/5%/10%, actual code uses 10%/2%/1%/5%) - decide intended values and align UI+code+comments; decide fate of unused `check_micro_pullback`; extended-hours ±10% limit-order slippage guard for illiquid $2-20 names.
- **Phase 5** (Windows VPS Deployment): NSSM service setup, Caddy/Nginx reverse proxy or `docker-compose.yml` (api+mongo+web), `.env.example`, README deploy section, bind backend to 127.0.0.1 for RDP-only access.
- Alpaca paper API key/secret still not configured — user needs to add real keys to `/app/backend/.env` to fully exercise live order placement, position sizing, and quote/bars endpoints end-to-end.
- Consider splitting `server.py` (1280+ lines) into per-domain routers (orders/settings/auto-trader/market) for maintainability (noted by testing agent, non-blocking).

## Next Action Items
1. Get user's real Alpaca paper API key + secret to verify live order placement/position sizing end-to-end on paper.
2. Proceed to Phase 4 (logic quality/param reconciliation) once user confirms Phase 1-3 is satisfactory.
3. Proceed to Phase 5 (Windows VPS deployment scripts: docker-compose / NSSM / start.bat) when ready to move off the Emergent preview environment.
