#!/usr/bin/env bash
# Initialize fresh SQLite database on PythonAnywhere (uses active virtualenv).
set -euo pipefail

APP_DIR="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"
PYTHON="${PYTHON:-python}"

cd "${APP_DIR}"
mkdir -p instance static/uploads

FRESH_DATABASE="${FRESH_DATABASE:-1}"

if [[ "${FRESH_DATABASE}" == "1" ]]; then
  echo "==> Fresh database: removing existing SQLite files in instance/"
  rm -f instance/*.db instance/*.db-wal instance/*.db-shm instance/*.db-journal 2>/dev/null || true
fi

echo "==> Creating tables..."
"${PYTHON}" init_db.py

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
  echo "==> Creating administrator account..."
  "${PYTHON}" create.py
else
  echo "==> Set ADMIN_PASSWORD in .env then run: python create.py"
fi

echo "==> Database ready."
