#!/usr/bin/env bash
# Install School Management System on Ubuntu/Debian VPS
# Usage: sudo bash deploy/install-linux.sh /var/www/school-management
set -euo pipefail

APP_DIR="${1:-/var/www/school-management}"
APP_USER="${APP_USER:-www-data}"
ENV_FILE="/etc/school-management/env"

echo "==> Installing to ${APP_DIR}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash deploy/install-linux.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

mkdir -p "${APP_DIR}" /etc/school-management
mkdir -p "${APP_DIR}/instance" "${APP_DIR}/static/uploads"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${APP_DIR}/.env.example" "${ENV_FILE}" 2>/dev/null || cp "${APP_DIR}/deploy/env.production.example" "${ENV_FILE}"
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s/change_this_to_a_long_random_string/${SECRET}/" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  echo "Created ${ENV_FILE} — review before going live."
fi

cd "${APP_DIR}"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Initializing fresh database on server (local dev DB is not deployed via git)"
FRESH_DATABASE="${FRESH_DATABASE:-1}" ENV_FILE="${ENV_FILE}" bash deploy/init-fresh-database.sh "${APP_DIR}"

chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/instance" "${APP_DIR}/static/uploads"
chmod -R 775 "${APP_DIR}/instance" "${APP_DIR}/static/uploads"

cp deploy/systemd/school-management.service /etc/systemd/system/school-management.service
sed -i "s|/var/www/school-management|${APP_DIR}|g" /etc/systemd/system/school-management.service

cp deploy/nginx/school-management.conf /etc/nginx/sites-available/school-management
ln -sf /etc/nginx/sites-available/school-management /etc/nginx/sites-enabled/school-management
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable school-management
systemctl restart school-management
nginx -t && systemctl reload nginx

echo ""
echo "==> Deployment complete"
echo "    App:  systemctl status school-management"
echo "    Logs: journalctl -u school-management -f"
echo "    Edit: ${ENV_FILE}"
echo "    Set your domain in /etc/nginx/sites-available/school-management"
echo "    HTTPS: certbot --nginx -d your-domain.com"
