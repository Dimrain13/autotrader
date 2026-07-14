# MomentumX — Windows Server VPS Deployment (RDP-only, no NSSM required to try it, NSSM recommended for production)

This guide sets up MomentumX on a **Windows Server VPS accessed via RDP**,
matching the security model recommended in the remediation plan:
**the backend is bound to `127.0.0.1` and only reachable from the server's
own browser over RDP** — this removes internet exposure entirely.

## 1. Install prerequisites (one-time)

1. **Python 3.11+** — https://www.python.org/downloads/windows/ (check "Add to PATH")
2. **Node.js LTS + Yarn** — https://nodejs.org/, then `npm install -g yarn`
3. **MongoDB Community Server** — https://www.mongodb.com/try/download/community
   During install, keep **"Install MongoDB as a Service"** checked (default).
4. **NSSM** (only needed for the persistent-service setup) — https://nssm.cc/download
   Unzip and put `nssm.exe` on your `PATH` (e.g. `C:\Windows\System32`).

## 2. Get the code onto the VPS

Copy/clone the repository to e.g. `C:\MomentumX\`. This `deploy\windows\`
folder assumes that layout (`backend\`, `frontend\`, `deploy\windows\` as
siblings under the repo root).

## 3. Configure environment

```powershell
cd C:\MomentumX\backend
copy .env.example .env
notepad .env
```

Fill in:
- `JWT_SECRET` — a long random string used to sign login sessions. Generate one with:
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — the single login account for this app (used on the login screen)
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — from alpaca.markets (use **paper**
  keys until you've verified everything works) - used for ALL order execution
- `ALPACA_DATA_API_KEY` / `ALPACA_DATA_SECRET_KEY` — optional, a separate key pair (can be a live account) used only for read-only market data/news, never trading
- `CORS_ORIGINS` — leave as `http://localhost:3000,http://127.0.0.1:3000` for
  the RDP-only setup

```powershell
cd ..\frontend
copy .env.example .env
```
Leave `REACT_APP_BACKEND_URL=http://127.0.0.1:8001` for the RDP-only setup.

## 4. Install dependencies & build

```powershell
cd C:\MomentumX\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
deactivate

cd ..\frontend
yarn install
yarn build
```

## 5. Run it

### Option A — Quick manual start (good for a first test)
```powershell
cd C:\MomentumX\deploy\windows
start.bat
```
This opens 3 windows (MongoDB, backend, frontend). Closing the windows /
logging out of RDP stops them — use Option B for something persistent.

### Option B — Persistent Windows services via NSSM (recommended)
Run PowerShell **as Administrator**:
```powershell
cd C:\MomentumX\deploy\windows
.\install_nssm_service.ps1
```
This registers `MomentumXBackend` and `MomentumXFrontend` as auto-starting
Windows services (survive reboot and RDP logout). Manage them via
`services.msc` or:
```powershell
nssm restart MomentumXBackend
nssm stop MomentumXFrontend
```
To remove them: `.\uninstall_nssm_service.ps1` (as Administrator).

**After any frontend code change**, re-run `yarn build` in `frontend\` and
`nssm restart MomentumXFrontend` to pick it up (backend hot-reloads are
disabled in production mode — restart `MomentumXBackend` after backend changes).

## 6. Verify

Open a browser **on the VPS itself** (via RDP) and go to:
```
http://127.0.0.1:3000
```
You should see the MomentumX login screen — sign in with the
`ADMIN_EMAIL`/`ADMIN_PASSWORD` you set in your `.env` file.

## 7. Alternative: Docker Desktop

If you'd rather use containers instead of native Windows services, a
`docker-compose.yml` (api + mongo + web) can be added on request — this
native/NSSM path was chosen per your preference, but Docker Desktop for
Windows is a fully supported alternative if you change your mind later.

## Security notes (Phase 1 recap)
- The backend rejects **every** `/api` request without a valid
  `Authorization: Bearer <JWT>` header, obtained by logging in at `/api/auth/login`.
- Alpaca API key/secret are **never** returned by the API in plaintext, and
  are managed **only** via `backend\.env` — there is no in-app way to edit
  or view them (by design, to remove the runtime `.env`-rewriting risk).
- `ALPACA_PAPER` / `ALPACA_BASE_URL` controls paper vs. live trading — going
  live is logged with a bold warning banner on backend startup, so it's
  never accidental.
- If you ever need remote access beyond RDP, front this with HTTPS (e.g.
  Caddy/Nginx reverse proxy with a real TLS cert) rather than exposing
  `127.0.0.1:8001`/`3000` directly to the internet.
