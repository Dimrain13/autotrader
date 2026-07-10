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
For deploying to a self-hosted VPS (recommended: no public internet exposure,
backend/frontend bound to `127.0.0.1`, access via SSH tunnel or RDP), see:
- **[deploy/linux/README.md](deploy/linux/README.md)** — Linux VPS (systemd services or `start.sh`), access via SSH port-forward
- **[deploy/windows/README.md](deploy/windows/README.md)** — Windows Server VPS (NSSM services or `start.bat`), access via RDP

## Strategy
See [WARRIOR_TRADING_STRATEGY.md](WARRIOR_TRADING_STRATEGY.md) for the full
Ross Cameron / Warrior Trading momentum strategy this app implements
(position sizing, entry/exit signals, risk limits).
