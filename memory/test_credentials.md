# MomentumX Test Credentials

## App Login (Email + Password JWT Auth) - REPLACED the old static API token
Single hardcoded user account, seeded on backend startup from `.env`:
```
ADMIN_EMAIL="daniel.r.millner@gmail.com"
ADMIN_PASSWORD="Black0rkid5!"
```
Usage:
- Frontend: enter this email/password on the Login screen (`POST /api/auth/login`). The returned JWT is stored in browser localStorage (same key/mechanism as before: `momentumx_api_token`), sent as `Authorization: Bearer <jwt>` on every request. Token expires after 30 days.
- Backend/curl: `curl -X POST $URL/api/auth/login -H "Content-Type: application/json" -d '{"email":"daniel.r.millner@gmail.com","password":"Black0rkid5!"}'` -> returns `{"access_token": "...", "email": "..."}`.
- Brute-force lockout: 5 failed attempts (per IP+email) locks out login for 15 minutes. `db.login_attempts` collection tracks this; clear via `db.login_attempts.delete_many({})` if you need to reset during testing.
- The OLD static `API_ACCESS_TOKEN` (`sr7sWvLt5MicXQTC0jw-...`) NO LONGER WORKS - fully removed from `.env` and code.

## Alpaca Broker Credentials
THREE key pairs now configured, intentionally split by purpose:

**Trading (orders/positions/account) - PAPER, ROTATED 2026-07 (this session):**
```
ALPACA_API_KEY="PKBNCHRXSP6JSLZ4Q35ODCHTWE"
ALPACA_SECRET_KEY="FVNN9B3PSsSUaQouqDWjAPsot43bqC3Pkb1UiFLrVzey"
ALPACA_BASE_URL="https://paper-api.alpaca.markets"
```
Paper account number: `PA36RNHPHRUZ` (replaces the old `PA30RVV1A2DM` - user rotated this key mid-session). This account has REAL margin active (~4x buying power vs equity). All actual order execution (auto-trader + manual buy/sell) always uses these paper keys.

**Market Data + News (bars/quotes/news, PRIMARY) - LIVE account, added 2026-02:**
```
ALPACA_DATA_API_KEY="AK376KQAJ35L675GO4C37WMOXS"
ALPACA_DATA_SECRET_KEY="5Fv3aFi2sKa6mK2Rb5bPToZZhtRwvgzhGihuxLe5SY7G"
```
⚠️ These are LIVE/production Alpaca credentials but are ONLY ever used for read-only market data/news lookups, never for order placement.

**Market Data + News (bars/quotes/news, SECONDARY/speed-boost) - added 2026-07 (this session):**
```
ALPACA_SECONDARY_DATA_API_KEY="PKRBZGHKVX2SGHWQZZVRJLXRPN"
ALPACA_SECONDARY_DATA_SECRET_KEY="A5H61qnJEsWrFMomsiG8K69TpZCZJn9HubwdNpnbjDRR"
```
This is the OLD (now-retired) paper trading key pair, repurposed data/news-only - round-robined alongside the primary data key via `data_pool`/`news_pool` (`alpaca_service.py`) purely to roughly double combined scan/news/chart throughput (Alpaca rate-limits are per-account). Never used for `TradingClient`/order placement - confirmed via code review.

Since real credentials were shared in plaintext chat, consider rotating all of these in the Alpaca dashboard once things are stable.

Account is currently FLAT (no open positions, no open orders) as of 2026-07-16. Auto-trader confirmed OFF by default.

## MongoDB
Uses existing `MONGO_URL` / `DB_NAME` from `/app/backend/.env` (no auth, local instance). No credentials needed.

