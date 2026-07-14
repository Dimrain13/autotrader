# MomentumX — Linux VPS Deployment (SSH tunnel access, no public exposure)

This guide sets up MomentumX on a **Linux VPS**, accessed by port-forwarding
over SSH to your local machine — matching the security model already built
into this app: **the backend and frontend are bound to `127.0.0.1` only**,
never exposed directly to the internet.

## 1. Get the code onto the VPS

```bash
git clone <your-repo-url> /opt/momentumx
cd /opt/momentumx
```
(If you cloned it somewhere else, e.g. your home directory, move it first:
`sudo mv ~/your-repo-folder /opt/momentumx` — the systemd service files
below assume this exact path, and a dedicated low-privilege service user
won't have access to anything under `/root`.)

## 2. Run the one-shot install script (as root/sudo)

```bash
cd /opt/momentumx/deploy/linux
chmod +x install_systemd_services.sh
sudo ./install_systemd_services.sh
```

This single script does **everything** needed on a bare VPS, and re-runs
safely if anything fails partway (every install command is unconditional/
idempotent by nature - it won't destroy anything already configured):
1. Installs system prerequisites via apt, every run: a compiler toolchain
   (`build-essential`, `libssl-dev`, `libffi-dev`), Python 3 + venv + dev
   headers, **Node.js 20 LTS via NodeSource** (the distro's default `nodejs`
   apt package is often years out of date and can't build this app's React
   19 frontend), MongoDB (via its official repo), and `yarn`/`serve`.
2. Creates `backend/.env` from the template (auto-generates a random
   `JWT_SECRET`) and interactively prompts for your login email/password
   plus your Alpaca paper trading keys (and optionally a separate live-
   account key pair used only for market data/news, never trading) - press
   Enter to skip any of these and fill them in later if you don't have
   them yet. **If `backend/.env` already exists, it's left untouched** so
   a re-run never wipes out keys you've already entered (if it predates
   the email+password login feature, the script prints exactly what to
   add manually).
3. Creates the Python virtualenv and installs backend dependencies.
4. Creates `frontend/.env` from the template, installs frontend
   dependencies, and builds it.
5. Creates a dedicated low-privilege `momentumx` system user (the app never
   runs as root - contains the blast radius if it's ever compromised).
6. Installs, enables (auto-start on boot), and starts both systemd services.

At the end it prints service status and a reminder if your Alpaca keys are
still blank. Manage the services with:
```bash
sudo systemctl restart momentumx-backend
sudo systemctl status momentumx-frontend
journalctl -u momentumx-backend -f     # live logs
```
To remove everything: `sudo ./uninstall_systemd_services.sh`.

**After any backend/frontend code change**: `sudo systemctl restart momentumx-backend`
and/or (`cd frontend && yarn build && sudo systemctl restart momentumx-frontend`).

**Prefer a quick manual test run instead of systemd?** Use
`cd /opt/momentumx/deploy/linux && chmod +x start.sh && ./start.sh` — but
you'll still need prerequisites installed and `.env` configured first (run
the install script once, even if you plan to manage it manually afterward).

## 3. Access it from your laptop via SSH port-forward

```bash
ssh -L 4000:127.0.0.1:4000 -L 9001:127.0.0.1:9001 your-user@your-vps-ip
```
Then open **http://localhost:4000** in your local browser. Log in with the
email/password you set as `ADMIN_EMAIL`/`ADMIN_PASSWORD` in your `.env`.

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
- Every `/api` request requires `Authorization: Bearer <JWT>`, issued by `POST /api/auth/login` with your `ADMIN_EMAIL`/`ADMIN_PASSWORD`. Passwords are bcrypt-hashed in MongoDB, never stored in plaintext. 5 failed login attempts locks out further attempts for 15 minutes.
- Alpaca keys live only in `backend/.env`, never returned by the API in plaintext. `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (paper) are used for ALL order execution; the optional `ALPACA_DATA_API_KEY`/`ALPACA_DATA_SECRET_KEY` pair is used only for read-only market data/news, never trading.
- CORS restricted to explicit origins, rate limiting on order/scan endpoints.
- Hard server-side daily-loss kill switch blocks new buy orders past the limit.
- No port is ever exposed beyond `127.0.0.1` - the SSH tunnel is your only door in.
- Both services run as a dedicated no-login `momentumx` system user, never root.
