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
TWO separate key pairs are now configured, intentionally split by purpose:

**Trading (orders/positions/account) - PAPER, unchanged:**
```
ALPACA_API_KEY="PKRBZGHKVX2SGHWQZZVRJLXRPN"
ALPACA_SECRET_KEY="A5H61qnJEsWrFMomsiG8K69TpZCZJn9HubwdNpnbjDRR"
ALPACA_BASE_URL="https://paper-api.alpaca.markets"
```
Paper account number: `PA30RVV1A2DM`. All actual order execution (auto-trader + manual buy/sell) always uses these paper keys - confirmed via code review and live test that `trading_client` never touches the live keys below.

**Market Data + News (bars/quotes/news) - LIVE account, added 2026-02:**
```
ALPACA_DATA_API_KEY="AK376KQAJ35L675GO4C37WMOXS"
ALPACA_DATA_SECRET_KEY="5Fv3aFi2sKa6mK2Rb5bPToZZhtRwvgzhGihuxLe5SY7G"
```
⚠️ These are LIVE/production Alpaca credentials but are ONLY ever used for read-only market data/news lookups (`StockHistoricalDataClient`/`NewsClient` in `alpaca_service.py` and `scanner_service.py`), never for `TradingClient`/order placement. Since these were shared in plaintext chat, consider rotating them in the Alpaca dashboard once things are stable.

Account is currently FLAT (no open positions) as of 2026-07-10. Auto-trader confirmed OFF by default.

## MongoDB
Uses existing `MONGO_URL` / `DB_NAME` from `/app/backend/.env` (no auth, local instance). No credentials needed.

