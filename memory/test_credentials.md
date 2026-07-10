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

## Alpaca Broker Credentials (Paper Trading — ACTIVE)
Real Alpaca paper trading credentials are now configured in `/app/backend/.env`:
```
ALPACA_API_KEY="PKRBZGHKVX2SGHWQZZVRJLXRPN"
ALPACA_SECRET_KEY="A5H61qnJEsWrFMomsiG8K69TpZCZJn9HubwdNpnbjDRR"
ALPACA_BASE_URL="https://paper-api.alpaca.markets"
```
Paper account number: `PA30RVV1A2DM`. Account is currently FLAT (no open
positions) as of 2026-07-10. NOTE: an earlier version of
`tests/test_security_and_trading.py::TestRateLimiting` placed real (paper)
buy orders on every run, silently accumulating an AAPL position over several
testing passes (grew to 20+ shares) - this has been fixed (test now uses a
non-existent ticker so it never reaches the real broker) and the accumulated
position has been liquidated. Auto-trader is confirmed OFF.

## MongoDB
Uses existing `MONGO_URL` / `DB_NAME` from `/app/backend/.env` (no auth, local instance). No credentials needed.
