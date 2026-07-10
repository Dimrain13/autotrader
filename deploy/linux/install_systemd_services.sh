#!/bin/bash
# MomentumX - ONE-SHOT setup: installs system prerequisites (Python, Node,
# MongoDB, yarn/serve), sets up backend + frontend .env files, installs
# dependencies, builds the frontend, then installs + starts both apps as
# persistent systemd services (survive reboot/logout).
#
# Run with sudo. Safe to re-run (idempotent - skips steps already done).
# Assumes the repo lives at /opt/momentumx (adjust paths in the .service
# files if you placed it elsewhere).
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root/sudo: sudo ./install_systemd_services.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
echo "Repo root: $ROOT_DIR"
export DEBIAN_FRONTEND=noninteractive

# ============================================================
# [1/6] System prerequisites
# ============================================================
echo ""
echo "[1/6] Checking/installing system prerequisites..."
apt-get update -qq

MISSING_PKGS=()
command -v python3.11 >/dev/null 2>&1 || MISSING_PKGS+=(python3.11 python3.11-venv)
command -v node >/dev/null 2>&1 || MISSING_PKGS+=(nodejs npm)
command -v curl >/dev/null 2>&1 || MISSING_PKGS+=(curl)
command -v gpg >/dev/null 2>&1 || MISSING_PKGS+=(gnupg)
if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "  Installing: ${MISSING_PKGS[*]}"
    apt-get install -y "${MISSING_PKGS[@]}"
else
    echo "  Python3.11/Node/curl/gnupg already present."
fi

if ! command -v mongod >/dev/null 2>&1; then
    echo "  MongoDB not found - adding MongoDB's official apt repo and installing..."
    UBUNTU_CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME")
    curl -fsSL https://pgp.mongodb.com/server-8.0.asc | gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
    echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${UBUNTU_CODENAME}/mongodb-org/8.0 multiverse" \
        | tee /etc/apt/sources.list.d/mongodb-org-8.0.list
    apt-get update -qq
    if ! apt-get install -y mongodb-org; then
        echo "  WARNING: mongodb-org install failed for codename '$UBUNTU_CODENAME' (your Ubuntu"
        echo "  version may not be supported by MongoDB's repo yet). Install MongoDB manually -"
        echo "  see https://www.mongodb.com/docs/manual/administration/install-on-linux/ - then re-run this script."
        exit 1
    fi
else
    echo "  MongoDB already present."
fi
systemctl enable --now mongod

if ! command -v yarn >/dev/null 2>&1 || ! command -v serve >/dev/null 2>&1; then
    echo "  Installing yarn + serve (npm global packages)..."
    npm install -g yarn serve
else
    echo "  yarn/serve already present."
fi

# ============================================================
# [2/6] Backend: .env, venv, dependencies
# ============================================================
echo ""
echo "[2/6] Setting up backend..."
cd "$ROOT_DIR/backend"

if [ ! -f ".env" ]; then
    cp .env.example .env
    GENERATED_TOKEN=$(python3.11 -c "import secrets; print(secrets.token_urlsafe(48))")
    sed -i "s/REPLACE_WITH_A_LONG_RANDOM_TOKEN/${GENERATED_TOKEN}/" .env
    echo "  Created backend/.env (generated a random API_ACCESS_TOKEN for you)."

    if [ -t 0 ]; then
        echo ""
        echo "  Enter your Alpaca PAPER trading keys (from alpaca.markets) - or press"
        echo "  Enter to skip and fill them into backend/.env manually later:"
        read -rp "    ALPACA_API_KEY: " ALPACA_KEY_INPUT
        read -rp "    ALPACA_SECRET_KEY: " ALPACA_SECRET_INPUT
        if [ -n "$ALPACA_KEY_INPUT" ]; then
            sed -i "s|^ALPACA_API_KEY=\"\"|ALPACA_API_KEY=\"${ALPACA_KEY_INPUT}\"|" .env
        fi
        if [ -n "$ALPACA_SECRET_INPUT" ]; then
            sed -i "s|^ALPACA_SECRET_KEY=\"\"|ALPACA_SECRET_KEY=\"${ALPACA_SECRET_INPUT}\"|" .env
        fi
    fi
else
    echo "  backend/.env already exists - leaving it untouched."
fi

if [ ! -d "venv" ]; then
    python3.11 -m venv venv
fi
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
deactivate
echo "  Backend dependencies installed."

# ============================================================
# [3/6] Frontend: .env, dependencies, build
# ============================================================
echo ""
echo "[3/6] Setting up frontend..."
cd "$ROOT_DIR/frontend"
[ -f ".env" ] || cp .env.example .env
yarn install --silent
yarn build
echo "  Frontend built."

# ============================================================
# [4/6] Dedicated service user
# ============================================================
echo ""
echo "[4/6] Creating service user..."
if ! id -u momentumx >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin momentumx
    echo "  Created 'momentumx' system user."
else
    echo "  'momentumx' system user already exists."
fi

# ============================================================
# [5/6] Install systemd unit files
# ============================================================
echo ""
echo "[5/6] Installing systemd unit files..."
cp "$SCRIPT_DIR/momentumx-backend.service" /etc/systemd/system/
cp "$SCRIPT_DIR/momentumx-frontend.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable momentumx-backend.service momentumx-frontend.service

# ============================================================
# [6/6] Start
# ============================================================
echo ""
echo "[6/6] Starting services..."
systemctl restart momentumx-backend.service
systemctl restart momentumx-frontend.service
sleep 2

echo ""
echo "============================================================"
systemctl status momentumx-backend --no-pager -l | head -5
echo "------------------------------------------------------------"
systemctl status momentumx-frontend --no-pager -l | head -5
echo "============================================================"
if grep -qE '^ALPACA_API_KEY=""$' "$ROOT_DIR/backend/.env" 2>/dev/null; then
    echo "REMINDER: backend/.env still has an empty ALPACA_API_KEY/ALPACA_SECRET_KEY."
    echo "  Edit it, then run: sudo systemctl restart momentumx-backend"
fi
echo ""
echo "Manage with:"
echo "  systemctl status momentumx-backend / momentumx-frontend"
echo "  journalctl -u momentumx-backend -f    (live logs)"
echo ""
echo "From your laptop, tunnel in over SSH:"
echo "  ssh -L 4000:127.0.0.1:4000 -L 9001:127.0.0.1:9001 user@your-vps-ip"
echo "Then open http://localhost:4000"
echo "============================================================"
