# MomentumX — Linux VPS Deployment (SSH tunnel access, no public exposure)

This guide sets up MomentumX on a **Linux VPS**, accessed by port-forwarding
over SSH to your local machine — matching the security model already built
into this app: **the backend and frontend are bound to `127.0.0.1` only**,
never exposed directly to the internet.

## 1. Install prerequisites (one-time, Ubuntu/Debian example)

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv nodejs npm mongodb-org
npm install -g yarn serve
```
(If `mongodb-org` isn't in your default repos, follow MongoDB's official
Ubuntu install guide, or run MongoDB via Docker instead - either is fine,
only `MONGO_URL` in `.env` needs to point at it.)

## 2. Get the code onto the VPS

```bash
git clone <your-repo-url> /opt/momentumx
cd /opt/momentumx
```

## 3. Configure environment

```bash
cd backend
cp .env.example .env
nano .env
```
Fill in:
- `API_ACCESS_TOKEN` — generate with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — from alpaca.markets (paper keys until verified)
- `CORS_ORIGINS` — leave as `http://localhost:4000,http://127.0.0.1:4000` (the SSH tunnel makes the browser think it's talking to localhost)

```bash
cd ../frontend
cp .env.example .env
```
Leave `REACT_APP_BACKEND_URL=http://127.0.0.1:9001`.

## 4. Install dependencies & build

```bash
cd /opt/momentumx/backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate

cd ../frontend
yarn install
yarn build
```

## 5. Run it

### Option A — Quick manual start (good for a first test)
```bash
cd /opt/momentumx/deploy/linux
chmod +x start.sh
./start.sh
```

### Option B — Persistent systemd services (recommended)
```bash
cd /opt/momentumx/deploy/linux
chmod +x install_systemd_services.sh
sudo ./install_systemd_services.sh
```
This runs the backend and frontend as `systemd` services under a dedicated
`momentumx` system user, auto-starting on boot. Manage with:
```bash
sudo systemctl restart momentumx-backend
sudo systemctl status momentumx-frontend
journalctl -u momentumx-backend -f     # live logs
```
To remove: `sudo ./uninstall_systemd_services.sh`.

**After any backend/frontend change**: `sudo systemctl restart momentumx-backend`
and/or (`cd frontend && yarn build && sudo systemctl restart momentumx-frontend`).

## 6. Access it from your laptop via SSH port-forward

```bash
ssh -L 4000:127.0.0.1:4000 -L 9001:127.0.0.1:9001 your-user@your-vps-ip
```
Then open **http://localhost:4000** in your local browser. Enter the
`API_ACCESS_TOKEN` from your `.env` on the token-gate screen.

Keep that SSH session open while you use the app (or use `-f -N` to run the
tunnel in the background: `ssh -f -N -L 4000:127.0.0.1:4000 -L 9001:127.0.0.1:9001 user@vps-ip`).

## Performance notes (backend already optimized for this)
- Scanner news lookups run in parallel (12 concurrent workers) with a 3-minute
  result cache and pooled HTTP connections - repeated scans are fast.
- Company-name lookups (used to improve news search accuracy) are cached for
  24h since they don't change.
- All Alpaca/requests calls run off the main event loop via `asyncio.to_thread`,
  so slow network calls never block other requests.

## Security recap
- Every `/api` request requires `Authorization: Bearer <API_ACCESS_TOKEN>`.
- Alpaca keys live only in `backend/.env`, never returned by the API in plaintext.
- CORS restricted to explicit origins, rate limiting on order/scan endpoints.
- Hard server-side daily-loss kill switch blocks new buy orders past the limit.
- No port is ever exposed beyond `127.0.0.1` - the SSH tunnel is your only door in.
