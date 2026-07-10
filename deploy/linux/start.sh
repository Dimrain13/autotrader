#!/bin/bash
# MomentumX - one-touch manual startup (no systemd, quick test run).
# Starts MongoDB (if not already a running service) + backend + frontend,
# all bound to 127.0.0.1 - access via an SSH tunnel (see README.md).
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "Repo root: $ROOT_DIR"

echo ""
echo "[1/3] Ensuring MongoDB is running..."
if systemctl is-active --quiet mongod 2>/dev/null; then
    echo "  mongod service already running."
elif command -v mongod >/dev/null 2>&1; then
    sudo systemctl start mongod 2>/dev/null || (mongod --dbpath "$ROOT_DIR/mongodb-data" --fork --logpath "$ROOT_DIR/mongodb-data/mongod.log" || true)
else
    echo "  WARNING: mongod not found - install MongoDB Community first."
fi

echo ""
echo "[2/3] Starting backend (127.0.0.1:9001)..."
cd "$ROOT_DIR/backend"
source venv/bin/activate
nohup uvicorn server:app --host 127.0.0.1 --port 9001 > backend.log 2>&1 &
echo "  Backend PID: $!  (logs: backend/backend.log)"
deactivate

echo ""
echo "[3/3] Building + serving frontend (127.0.0.1:4000)..."
cd "$ROOT_DIR/frontend"
if [ ! -d "build" ]; then
    yarn build
fi
nohup npx serve -s build -l tcp://127.0.0.1:4000 > frontend.log 2>&1 &
echo "  Frontend PID: $!  (logs: frontend/frontend.log)"

echo ""
echo "============================================================"
echo "MomentumX is running, bound to 127.0.0.1 only."
echo "From your LOCAL machine, tunnel in over SSH:"
echo "  ssh -L 4000:127.0.0.1:4000 -L 9001:127.0.0.1:9001 user@your-vps-ip"
echo "Then open http://localhost:4000 in your local browser."
echo "Stop with: pkill -f 'uvicorn server:app' && pkill -f 'serve -s build'"
echo "============================================================"
