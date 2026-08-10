#!/usr/bin/env bash
# Create a fresh SQLite database on the server (never copy dev machine DB via git).
# Usage: bash deploy/init-fresh-database.sh [/var/www/school-management]
set -euo pipefail

APP_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="${ENV_FILE:-/etc/school-management/env}"

cd "${APP_DIR}"

if [[ ! -d .venv ]]; then
  echo "Virtualenv not found. Run install-linux.sh or create .venv first."
  exit 1
fi

PYTHON="${APP_DIR}/.venv/bin/python"
FRESH_DATABASE="${FRESH_DATABASE:-1}"

mkdir -p "${APP_DIR}/instance"

if [[ "${FRESH_DATABASE}" == "1" ]]; then
  echo "==> Fresh database: removing any existing SQLite files in instance/"
  rm -f "${APP_DIR}/instance/"*.db \
        "${APP_DIR}/instance/"*.db-wal \
        "${APP_DIR}/instance/"*.db-shm \
        "${APP_DIR}/instance/"*.db-journal 2>/dev/null || true
else
  echo "==> FRESH_DATABASE=0 — keeping existing database files if present"
fi

echo "==> Creating tables and applying schema patches..."
"${PYTHON}" init_db.py

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
elif [[ -f "${APP_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${APP_DIR}/.env"
  set +a
fi

if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
  echo "==> Creating master administrator from ADMIN_PASSWORD in env..."
  "${PYTHON}" create.py
else
  echo "==> No ADMIN_PASSWORD set. After install, run:"
  echo "    cd ${APP_DIR} && .venv/bin/python create.py"
fi

echo "==> Fresh database ready at instance/keeptrack_full.db"
