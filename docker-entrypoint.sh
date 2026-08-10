#!/usr/bin/env bash
# Container startup: persistent dirs, optional fresh DB, then exec Gunicorn.
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p instance static/uploads/uploads static/uploads/activities \
  static/uploads/submissions static/uploads/school_media

FRESH_DATABASE="${FRESH_DATABASE:-0}"
if [[ "${FRESH_DATABASE}" == "1" ]]; then
  echo "==> FRESH_DATABASE=1 — removing existing SQLite files in instance/"
  rm -f instance/*.db instance/*.db-wal instance/*.db-shm instance/*.db-journal 2>/dev/null || true
fi

if [[ ! -f instance/keeptrack_full.db ]] || [[ "${FRESH_DATABASE}" == "1" ]]; then
  echo "==> Initializing database schema..."
  python init_db.py
fi

if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
  echo "==> Ensuring master administrator account..."
  python create.py
fi

echo "==> Starting: $*"
exec "$@"