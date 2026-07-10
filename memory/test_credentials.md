# MomentumX Test Credentials

## API Access Token (Phase 1 #1 - Bearer Auth)
Single static token protecting the entire `/api` router.
Location: `/app/backend/.env` -> `API_ACCESS_TOKEN`

```
API_ACCESS_TOKEN=sr7sWvLt5MicXQTC0jw-Sy0uwoYxR-i9FLAkOXcuH3VjUpqJ7GyMxhFEyduwFPDu
```

Usage:
- Frontend: enter this token in the "API Access Token" gate screen on first load (stored in browser localStorage key `momentumx_api_token`).
- Backend/curl: send header `Authorization: Bearer <token>`.

## Alpaca Broker Credentials
NOT CONFIGURED in this environment. User declined to share full paper-trading
API key + secret (only a partial key ID was mentioned, no secret). Backend
currently runs with `ALPACA_API_KEY=""` / `ALPACA_SECRET_KEY=""` in
`/app/backend/.env`, so all Alpaca-dependent endpoints (account, positions,
orders, quotes) correctly return `{"detail": "Alpaca API not configured"}`
instead of fabricating data.

To enable full live/paper trading verification, add to `/app/backend/.env`:
```
ALPACA_API_KEY="PK..."
ALPACA_SECRET_KEY="..."
```
then `sudo supervisorctl restart backend`.

## MongoDB
Uses existing `MONGO_URL` / `DB_NAME` from `/app/backend/.env` (no auth, local instance). No credentials needed.
