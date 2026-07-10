#!/bin/bash
# MomentumX - install persistent systemd services (survive reboot/logout).
# Run with sudo. Assumes the repo lives at /opt/momentumx (adjust paths in
# the .service files below first if you placed it elsewhere).
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root/sudo: sudo ./install_systemd_services.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create a dedicated low-privilege user to run the services, if it doesn't exist
if ! id -u momentumx >/dev/null 2>&1; then
    echo "Creating service user 'momentumx'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin momentumx
fi

echo "Installing systemd unit files..."
cp "$SCRIPT_DIR/momentumx-backend.service" /etc/systemd/system/
cp "$SCRIPT_DIR/momentumx-frontend.service" /etc/systemd/system/

echo "Reloading systemd and enabling services..."
systemctl daemon-reload
systemctl enable momentumx-backend.service
systemctl enable momentumx-frontend.service

echo "Starting services..."
systemctl restart momentumx-backend.service
systemctl restart momentumx-frontend.service

echo ""
echo "============================================================"
echo "Done. Check status with:"
echo "  systemctl status momentumx-backend"
echo "  systemctl status momentumx-frontend"
echo "  journalctl -u momentumx-backend -f    (live logs)"
echo "============================================================"
