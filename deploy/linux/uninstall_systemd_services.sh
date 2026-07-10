#!/bin/bash
# Removes the MomentumX systemd services. Run with sudo.
set -e
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root/sudo: sudo ./uninstall_systemd_services.sh"
    exit 1
fi

systemctl stop momentumx-backend.service momentumx-frontend.service 2>/dev/null || true
systemctl disable momentumx-backend.service momentumx-frontend.service 2>/dev/null || true
rm -f /etc/systemd/system/momentumx-backend.service /etc/systemd/system/momentumx-frontend.service
systemctl daemon-reload

echo "MomentumX systemd services removed."
