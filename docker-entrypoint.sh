#!/usr/bin/env bash
# Container startup: persistent dirs, optional fresh DB, then exec Gunicorn.
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p instance static/uploads/uploads static/uploads/activities \
  static/uploads/submissions static/uploads/school_media

FRESH_DATABASE="${FRESH_DATABASE:-0}"
DATABASE_URL="${DATABASE_URL:-}"
if [[ "${FRESH_DATABASE}" == "1" && "${FLASK_ENV:-}" == "production" ]]; then
  echo "ERROR: FRESH_DATABASE=1 is blocked in production to protect existing data."
  echo "Set FRESH_DATABASE=0 for normal deployments."
  exit 1
fi
if [[ "${FRESH_DATABASE}" == "1" ]]; then
  echo "==> FRESH_DATABASE=1 — removing existing SQLite files in instance/"
  rm -f instance/*.db instance/*.db-wal instance/*.db-shm instance/*.db-journal 2>/dev/null || true
fi

if [[ -z "${DATABASE_URL}" && ! -f instance/future_leaders_full.db ]] || [[ "${FRESH_DATABASE}" == "1" ]]; then
  echo "==> Initializing database schema..."
  python init_db.py
fi

if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
  echo "==> Ensuring master administrator account..."
  python create.py
fi

echo "==> Starting: $*"
exec "$@"