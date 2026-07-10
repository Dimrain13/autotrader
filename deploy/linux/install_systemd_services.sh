#!/bin/bash
# MomentumX - TRUE one-shot setup for a bare Linux VPS (Ubuntu/Debian).
# Assumes NOTHING is pre-installed except a base OS + apt. Installs every
# system dependency needed (compiler toolchain, Python, a modern Node.js via
# NodeSource, MongoDB via its official repo, yarn/serve), sets up backend +
# frontend .env files, installs app dependencies, builds the frontend, then
# installs + starts both apps as persistent systemd services.
#
# Run with sudo. Safe to re-run (idempotent - skips steps already done).
# Assumes the repo lives at /opt/momentumx (adjust paths in the .service
# files if you placed it elsewhere).
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root/sudo: sudo ./install_systemd_services.sh"
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "ERROR: this script targets Debian/Ubuntu (apt-get not found)."
    echo "On another distro, install the equivalent packages manually: a C"
    echo "compiler toolchain, Python 3.10+, Node.js 20+, MongoDB, yarn, serve."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
echo "Repo root: $ROOT_DIR"
export DEBIAN_FRONTEND=noninteractive

# ============================================================
# [1/7] Base system packages (compiler toolchain + basics)
# ============================================================
echo ""
echo "[1/7] Installing base system packages..."
apt-get update -qq
apt-get install -y \
    curl gnupg ca-certificates \
    build-essential pkg-config \
    libssl-dev libffi-dev

# ============================================================
# [2/7] Python 3 (use whatever's on the system, or install 3.11)
# ============================================================
echo ""
echo "[2/7] Setting up Python 3..."
PYTHON_BIN=""
for candidate in python3.11 python3.12 python3.13 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "  No python3 found - installing python3.11..."
    apt-get install -y python3.11 python3.11-venv python3-pip
    PYTHON_BIN="python3.11"
else
    echo "  Using $($PYTHON_BIN --version) at $(command -v $PYTHON_BIN)"
fi
# Make sure the venv module actually works for whichever python we picked
# (some distros split it into a separate "pythonX.Y-venv" package).
if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
    PY_VER_SUFFIX=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo "  Installing python${PY_VER_SUFFIX}-venv..."
    apt-get install -y "python${PY_VER_SUFFIX}-venv" || apt-get install -y python3-venv
fi

# ============================================================
# [3/7] Node.js 20 LTS via NodeSource (distro-default apt packages are
# often years out of date and too old to build this React 19 frontend)
# ============================================================
echo ""
echo "[3/7] Setting up Node.js..."
NODE_MAJOR_OK=false
if command -v node >/dev/null 2>&1; then
    NODE_MAJOR=$(node -v | sed 's/^v//' | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        NODE_MAJOR_OK=true
        echo "  Node $(node -v) already installed and new enough."
    fi
fi
if [ "$NODE_MAJOR_OK" = false ]; then
    echo "  Installing Node.js 20 LTS via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
    echo "  Installed $(node -v)."
fi

# ============================================================
# [4/7] MongoDB via its official apt repo
# ============================================================
echo ""
echo "[4/7] Setting up MongoDB..."
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

# ============================================================
# [5/7] yarn + serve (npm globals)
# ============================================================
echo ""
echo "[5/7] Installing yarn + serve..."
if ! command -v yarn >/dev/null 2>&1 || ! command -v serve >/dev/null 2>&1; then
    npm install -g yarn serve
else
    echo "  yarn/serve already present."
fi

# ============================================================
# [6/7] Backend + frontend setup (.env, deps, build)
# ============================================================
echo ""
echo "[6/7] Setting up backend..."
cd "$ROOT_DIR/backend"

if [ ! -f ".env" ]; then
    cp .env.example .env
    GENERATED_TOKEN=$("$PYTHON_BIN" -c "import secrets; print(secrets.token_urlsafe(48))")
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
    "$PYTHON_BIN" -m venv venv
fi
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
deactivate
echo "  Backend dependencies installed."

echo ""
echo "  Setting up frontend..."
cd "$ROOT_DIR/frontend"
[ -f ".env" ] || cp .env.example .env
yarn install --silent
yarn build
echo "  Frontend built."

# ============================================================
# [7/7] Dedicated service user + systemd units
# ============================================================
echo ""
echo "[7/7] Installing systemd services..."
if ! id -u momentumx >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin momentumx
    echo "  Created 'momentumx' system user."
else
    echo "  'momentumx' system user already exists."
fi

cp "$SCRIPT_DIR/momentumx-backend.service" /etc/systemd/system/
cp "$SCRIPT_DIR/momentumx-frontend.service" /etc/systemd/system/
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
