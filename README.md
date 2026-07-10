# MomentumX (Internal-Trader)

Web-based algorithmic trading assistant: React frontend + FastAPI backend +
MongoDB, broker integration via Alpaca (paper & live). Built for self-hosted
use on a Windows Server VPS accessed via RDP.

## Security
- Every `/api` route requires `Authorization: Bearer <API_ACCESS_TOKEN>` (see `backend/.env`).
- Alpaca API keys are managed via `backend/.env` only — never exposed in plaintext by the API, never editable at runtime.
- CORS is restricted to explicit origins (no wildcard).
- Rate limiting on order/scan endpoints.
- Hard server-side daily-loss kill switch blocks new buy orders once the daily loss limit is hit.

## Deployment
For deploying to a Windows Server VPS (recommended: RDP-only, backend bound
to `127.0.0.1`, no internet exposure), see **[deploy/windows/README.md](deploy/windows/README.md)**
for full step-by-step instructions (prerequisites, `.env` setup, running via
`start.bat` or as persistent Windows services with NSSM).

## Strategy
See [WARRIOR_TRADING_STRATEGY.md](WARRIOR_TRADING_STRATEGY.md) for the full
Ross Cameron / Warrior Trading momentum strategy this app implements
(position sizing, entry/exit signals, risk limits).
