#!/bin/bash
# One-command deploy: pulls the latest code from GitHub, updates dependencies,
# applies non-destructive schema changes, and restarts the service.
# The live database is never deleted or reset by this script.
set -euo pipefail

APP_DIR="/home/ubuntu/feature-leaders-school"
SERVICE_NAME="schoolapp"
HEALTH_URL="http://127.0.0.1:8000/health"
BACKUP_DIR="${APP_DIR}/instance/backups"

cd "${APP_DIR}" || { echo "ERROR: ${APP_DIR} not found."; exit 1; }

echo "==> Safety check: FRESH_DATABASE must not be 1 in production"
if [ -f ".env" ] && grep -Eq '^FRESH_DATABASE=1' .env; then
  echo "ERROR: .env has FRESH_DATABASE=1. This would wipe the database. Aborting."
  echo "       Set FRESH_DATABASE=0 in .env before deploying."
  exit 1
fi

echo "==> Backing up the current database (if present)..."
mkdir -p "${BACKUP_DIR}"
shopt -s nullglob
db_files=(instance/*.db)
if [ ${#db_files[@]} -gt 0 ]; then
  timestamp="$(date +%Y%m%d-%H%M%S)"
  for db_file in "${db_files[@]}"; do
    cp -p "${db_file}" "${BACKUP_DIR}/$(basename "${db_file}").${timestamp}.bak"
  done
  echo "    Backed up: ${db_files[*]}"
  # Keep the 14 most recent backups per database file; older ones are pruned.
  for db_file in "${db_files[@]}"; do
    name="$(basename "${db_file}")"
    ls -1t "${BACKUP_DIR}/${name}".*.bak 2>/dev/null | tail -n +15 | xargs -r rm -f
  done
else
  echo "    No local .db file found (likely using a remote/managed database)."
fi
shopt -u nullglob

echo "==> Recording current commit for rollback..."
previous_commit="$(git rev-parse HEAD)"

echo "==> Pulling latest changes from Git..."
git fetch origin
if ! git pull --ff-only origin main; then
  echo "ERROR: git pull was not a fast-forward (local commits or conflicts)."
  echo "       Resolve manually; deployment stopped to avoid data loss."
  exit 1
fi

echo "==> Activating virtual environment..."
source venv/bin/activate

echo "==> Installing updated dependencies..."
if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt --no-cache-dir
fi

echo "==> Applying non-destructive database schema updates..."
python init_db.py

echo "==> Restarting ${SERVICE_NAME} service..."
sudo systemctl restart "${SERVICE_NAME}"

echo "==> Waiting for the app to become healthy..."
healthy=0
for attempt in $(seq 1 10); do
  sleep 2
  if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  echo "    Attempt ${attempt}/10: not ready yet..."
done

if [ "${healthy}" -ne 1 ]; then
  echo "ERROR: Health check failed after deploy. Rolling back to ${previous_commit}."
  git reset --hard "${previous_commit}"
  source venv/bin/activate
  pip install -r requirements.txt --no-cache-dir
  sudo systemctl restart "${SERVICE_NAME}"
  echo "==> Rolled back. Database was not modified. Check logs:"
  echo "    journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  exit 1
fi

echo "==> Checking application status..."
sudo systemctl status "${SERVICE_NAME}" --no-pager -n 5

echo "==> Deployment complete! Database preserved; backup stored in ${BACKUP_DIR}."
