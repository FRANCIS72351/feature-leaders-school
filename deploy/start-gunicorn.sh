#!/usr/bin/env bash
# Quick production start (no systemd) — useful for testing on VPS
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

export FLASK_ENV=production
export PRODUCTION=1
export GUNICORN_BIND="${GUNICORN_BIND:-127.0.0.1:8000}"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

exec gunicorn -c gunicorn.conf.py wsgi:application
