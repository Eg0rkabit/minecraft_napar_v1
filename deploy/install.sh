#!/bin/bash
set -euo pipefail
cd /opt/napar
test "$(id -u)" = 0
test -f .env
test -x .venv/bin/python
# Validate without printing any values (including secrets on validation errors).
./.venv/bin/python -c 'from napar.config import Settings; Settings(); print("Settings valid")' 2>/dev/null
if ! id napar >/dev/null 2>&1; then
    useradd --system --home /opt/napar --shell /usr/sbin/nologin napar
fi
install -d -o napar -g napar -m 0750 /opt/napar/data
chown napar:napar .env
chmod 600 .env
# Code stays root-owned. Only the database directory is writable to the service.
install -m 0644 deploy/napar.service /etc/systemd/system/napar.service
systemctl daemon-reload
systemctl enable napar
systemctl restart napar
for attempt in 1 2 3 4 5; do
    if curl --fail --silent http://127.0.0.1:8000/health; then
        printf '\n'
        systemctl is-active napar
        exit 0
    fi
    sleep 1
done
echo 'Health check failed; inspect journalctl -u napar -n 30'
exit 1
