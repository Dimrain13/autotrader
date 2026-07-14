#!/bin/bash
# MomentumX - TRUE one-shot setup for a bare Linux VPS (Ubuntu/Debian).
# Assumes NOTHING is pre-installed. Every dependency install command below
# runs unconditionally, every time - no "is it already installed?" checks,
# since apt/npm installs are safe/idempotent to repeat. The only exceptions
# (clearly marked below) are: not overwriting an already-configured
# backend/.env (would destroy your entered Alpaca keys), and not letting
# `useradd` hard-fail if the service user already exists.
#
# Run with sudo. Works from wherever you clone the repo - it auto-detects
# its own location and patches the systemd unit files to match (no need to
# use /opt/momentumx specifically, though that's the recommended default).
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root/sudo: sudo ./install_systemd_services.sh"
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "ERROR: this script targets Debian/Ubuntu (apt-get not found)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
echo "Repo root: $ROOT_DIR"
export DEBIAN_FRONTEND=noninteractive

# ============================================================
# [1/7] Base system packages + Python (unconditional)
# ============================================================
echo ""
echo "[1/7] Installing base system packages + Python 3..."
apt-get update -qq
apt-get install -y \
    curl gnupg ca-certificates \
    build-essential pkg-config libssl-dev libffi-dev \
    python3 python3-venv python3-dev python3-pip

# ============================================================
# [2/7] Node.js 20 LTS via NodeSource (unconditional - the distro's
# default apt "nodejs" package is years out of date and can't build
# this app's React 19 frontend)
# ============================================================
echo ""
echo "[2/7] Installing Node.js 20 LTS via NodeSource..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
echo "  Installed $(node -v)."

# ============================================================
# [3/7] MongoDB via its official apt repo (unconditional)
# ============================================================
echo ""
echo "[3/7] Installing MongoDB..."
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
systemctl enable --now mongod

# ============================================================
# [4/7] yarn + serve (unconditional)
# ============================================================
echo ""
echo "[4/7] Installing yarn + serve..."
npm install -g yarn serve

# ============================================================
# [5/7] Backend setup (.env preserved if it already exists, deps
# installed unconditionally)
# ============================================================
echo ""
echo "[5/7] Setting up backend..."
cd "$ROOT_DIR/backend"

if [ -f ".env" ]; then
    echo "  backend/.env already exists - leaving it untouched (won't overwrite your keys)."
    if ! grep -q "^JWT_SECRET=" .env; then
        echo "  WARNING: your existing .env predates email+password login and is missing"
        echo "  JWT_SECRET/ADMIN_EMAIL/ADMIN_PASSWORD - add these lines to backend/.env"
        echo "  manually, then restart momentumx-backend:"
        echo '    JWT_SECRET="'$(python3 -c "import secrets; print(secrets.token_hex(32))")'"'
        echo '    ADMIN_EMAIL="your-email@example.com"'
        echo '    ADMIN_PASSWORD="your-chosen-password"'
        echo "  Also remove the old API_ACCESS_TOKEN line if present - it's no longer used."
    fi
else
    # Written directly here (not `cp .env.example`) so this script never
    # depends on that template file existing/being tracked in the repo.
    GENERATED_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env << EOF
MONGO_URL="mongodb://localhost:27017"
DB_NAME="momentumx"
CORS_ORIGINS="http://localhost:4000,http://127.0.0.1:4000"
JWT_SECRET="${GENERATED_JWT_SECRET}"
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
ALPACA_API_KEY=""
ALPACA_SECRET_KEY=""
ALPACA_BASE_URL="https://paper-api.alpaca.markets"
ALPACA_PAPER="true"
ALPACA_DATA_API_KEY=""
ALPACA_DATA_SECRET_KEY=""
SMA_SHORT="20"
SMA_LONG="50"
EOF
    echo "  Created backend/.env (generated a random JWT_SECRET for you)."

    if [ -t 0 ]; then
        echo ""
        echo "  Set your login email + password for this app (used for the login screen):"
        read -rp "    Login email: " ADMIN_EMAIL_INPUT
        read -rp "    Login password: " ADMIN_PASSWORD_INPUT
        if [ -n "$ADMIN_EMAIL_INPUT" ]; then
            sed -i "s|^ADMIN_EMAIL=\"\"|ADMIN_EMAIL=\"${ADMIN_EMAIL_INPUT}\"|" .env
        fi
        if [ -n "$ADMIN_PASSWORD_INPUT" ]; then
            sed -i "s|^ADMIN_PASSWORD=\"\"|ADMIN_PASSWORD=\"${ADMIN_PASSWORD_INPUT}\"|" .env
        fi
        echo ""
        echo "  Enter your Alpaca PAPER trading keys (from alpaca.markets) - or press"
        echo "  Enter to skip and fill them into backend/.env manually later:"
        read -rp "    ALPACA_API_KEY (paper, used for orders): " ALPACA_KEY_INPUT
        read -rp "    ALPACA_SECRET_KEY (paper, used for orders): " ALPACA_SECRET_INPUT
        if [ -n "$ALPACA_KEY_INPUT" ]; then
            sed -i "s|^ALPACA_API_KEY=\"\"|ALPACA_API_KEY=\"${ALPACA_KEY_INPUT}\"|" .env
        fi
        if [ -n "$ALPACA_SECRET_INPUT" ]; then
            sed -i "s|^ALPACA_SECRET_KEY=\"\"|ALPACA_SECRET_KEY=\"${ALPACA_SECRET_INPUT}\"|" .env
        fi
        echo ""
        echo "  Optional: a SEPARATE Alpaca key pair used only for market data/news"
        echo "  (can be a live account - never used for trading). Press Enter to skip"
        echo "  and fall back to using your paper keys above for data too:"
        read -rp "    ALPACA_DATA_API_KEY (optional, data/news only): " ALPACA_DATA_KEY_INPUT
        read -rp "    ALPACA_DATA_SECRET_KEY (optional, data/news only): " ALPACA_DATA_SECRET_INPUT
        if [ -n "$ALPACA_DATA_KEY_INPUT" ]; then
            sed -i "s|^ALPACA_DATA_API_KEY=\"\"|ALPACA_DATA_API_KEY=\"${ALPACA_DATA_KEY_INPUT}\"|" .env
        fi
        if [ -n "$ALPACA_DATA_SECRET_INPUT" ]; then
            sed -i "s|^ALPACA_DATA_SECRET_KEY=\"\"|ALPACA_DATA_SECRET_KEY=\"${ALPACA_DATA_SECRET_INPUT}\"|" .env
        fi
    fi
fi

python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
deactivate
echo "  Backend dependencies installed."

# ============================================================
# [6/7] Frontend setup (unconditional install + build)
# ============================================================
echo ""
echo "[6/7] Setting up frontend..."
cd "$ROOT_DIR/frontend"
if [ ! -f ".env" ]; then
    # Written directly here for the same reason as backend/.env above -
    # never depends on frontend/.env.example existing in the repo.
    cat > .env << 'EOF'
REACT_APP_BACKEND_URL="http://127.0.0.1:9001"
WDS_SOCKET_PORT=443
EOF
fi
yarn install
yarn build
echo "  Frontend built."

# ============================================================
# [7/7] Service user + systemd units (unconditional install/start)
# ============================================================
echo ""
echo "[7/7] Installing systemd services..."
useradd --system --no-create-home --shell /usr/sbin/nologin momentumx 2>/dev/null || true
chown -R momentumx:momentumx "$ROOT_DIR"
echo "  Repo ownership set to momentumx:momentumx so the service user can read it."

cp "$SCRIPT_DIR/momentumx-backend.service" /etc/systemd/system/
cp "$SCRIPT_DIR/momentumx-frontend.service" /etc/systemd/system/
# The checked-in .service files hardcode /opt/momentumx as a readable
# default/example path. Substitute in the REAL detected repo location so
# this works no matter what the repo folder is actually named/cloned to
# (e.g. /opt/Internal-trader) - only rewrite if it actually differs, so
# this stays a no-op on the common case.
if [ "$ROOT_DIR" != "/opt/momentumx" ]; then
    sed -i "s|/opt/momentumx|$ROOT_DIR|g" /etc/systemd/system/momentumx-backend.service
    sed -i "s|/opt/momentumx|$ROOT_DIR|g" /etc/systemd/system/momentumx-frontend.service
    echo "  Repo is at $ROOT_DIR (not /opt/momentumx) - patched systemd unit paths to match."
fi
systemctl daemon-reload
systemctl enable momentumx-backend.service momentumx-frontend.service
systemctl restart momentumx-backend.service
systemctl restart momentumx-frontend.service
sleep 2

echo ""
echo "============================================================"
systemctl status momentumx-backend --no-pager -l | head -5
echo "------------------------------------------------------------"
systemctl status momentumx-frontend --no-pager -l | head -5
echo "============================================================"
if grep -qE '^ADMIN_EMAIL=""$' "$ROOT_DIR/backend/.env" 2>/dev/null; then
    echo "REMINDER: backend/.env still has an empty ADMIN_EMAIL/ADMIN_PASSWORD - the"
    echo "  login screen won't work until you set these, then run: sudo systemctl restart momentumx-backend"
fi
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
