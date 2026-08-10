# VPS & Linux Deployment Guide

Deploy the School Management System on Ubuntu/Debian VPS (DigitalOcean, Linode, Hetzner, AWS EC2, etc.) or any Linux server.

## Architecture

```
Internet → Nginx (port 80/443) → Gunicorn (127.0.0.1:8000) → Flask app → SQLite/PostgreSQL
                ↓
         /static/ served directly (fast)
```

## Requirements

- Ubuntu 22.04+ or Debian 11+
- 1 GB RAM minimum (2 GB recommended)
- Python 3.10+
- Domain pointed to your server IP (for HTTPS)

## Database on cloud server (fresh start)

**Your local database is never uploaded to GitHub or the server automatically.**

- `instance/` and `*.db` are in `.gitignore` — only application code is pushed.
- On first VPS install, `deploy/init-fresh-database.sh` removes any old SQLite files and creates **empty tables**.
- Set `ADMIN_PASSWORD` in `/etc/school-management/env` before install (or run `python create.py` after).

```bash
# In /etc/school-management/env
FRESH_DATABASE=1
ADMIN_EMAIL=admin@school.com
ADMIN_NAME=School Administrator
ADMIN_PASSWORD=your_secure_password
```

Re-deploys (`git pull` + restart) **keep** the server database. To reset the server DB manually:

```bash
cd /var/www/school-management
sudo FRESH_DATABASE=1 bash deploy/init-fresh-database.sh
sudo systemctl restart school-management
```

### Optional: copy your local database to the server

Only if you intentionally want dev data on production:

```bash
# From your Windows/Mac machine (replace user and server IP)
scp instance/keeptrack_full.db user@your-server:/var/www/school-management/instance/
ssh user@your-server "sudo chown www-data:www-data /var/www/school-management/instance/keeptrack_full.db"
ssh user@your-server "sudo systemctl restart school-management"
```

## Quick install (automated)

1. Copy the project to your server:

```bash
sudo mkdir -p /var/www/school-management
sudo chown $USER:$USER /var/www/school-management
git clone <your-repo-url> /var/www/school-management
# or: rsync/scp your project files
```

2. Run the installer:

```bash
cd /var/www/school-management
sudo bash deploy/install-linux.sh
```

3. Edit environment and domain:

```bash
sudo nano /etc/school-management/env
sudo nano /etc/nginx/sites-available/school-management
# Replace your-domain.com with your real domain
sudo nginx -t && sudo systemctl reload nginx
```

4. Enable HTTPS:

```bash
sudo certbot --nginx -d your-domain.com
```

Uncomment the HTTPS `server { }` block in the nginx config if you prefer manual SSL setup.

## Manual install

### 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx
```

### 2. Application setup

```bash
cd /var/www/school-management
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p instance static/uploads
cp .env.example .env
# Edit .env — set SECRET_KEY, FLASK_ENV=production, PRODUCTION=1
```

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Run with Gunicorn (production)

```bash
source .venv/bin/activate
export FLASK_ENV=production PRODUCTION=1
gunicorn -c gunicorn.conf.py wsgi:application
```

Or use the helper script:

```bash
bash deploy/start-gunicorn.sh
```

### 4. Systemd service (always on)

```bash
sudo mkdir -p /etc/school-management
sudo cp deploy/env.production.example /etc/school-management/env
sudo nano /etc/school-management/env

sudo cp deploy/systemd/school-management.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now school-management
sudo systemctl status school-management
```

Logs: `journalctl -u school-management -f`

### 5. Nginx reverse proxy

```bash
sudo cp deploy/nginx/school-management.conf /etc/nginx/sites-available/school-management
sudo ln -s /etc/nginx/sites-available/school-management /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## Performance settings

| Variable | Default | Notes |
|----------|---------|-------|
| `WEB_CONCURRENCY` | `1` with SQLite | Use **1 worker** for SQLite. Increase only with PostgreSQL. |
| `GUNICORN_THREADS` | `8` | Threads per worker — good for I/O-bound Flask routes |
| `GUNICORN_TIMEOUT` | `120` | PDF/report generation may need this |
| `GUNICORN_PRELOAD` | `true` | Loads app once before forking workers |
| `MAX_UPLOAD_MB` | `16` | Student assignment uploads |

SQLite optimizations (automatic in production):

- WAL journal mode
- `busy_timeout=5000` for concurrent reads
- Nginx serves `/static/` directly

### Scaling to PostgreSQL (recommended for 100+ concurrent users)

```bash
sudo apt install postgresql postgresql-contrib
sudo -u postgres createuser schooluser -P
sudo -u postgres createdb school_db -O schooluser
pip install psycopg2-binary
```

In `/etc/school-management/env`:

```
DATABASE_URL=postgresql+psycopg2://schooluser:YOUR_PASSWORD@127.0.0.1:5432/school_db
WEB_CONCURRENCY=4
```

## Environment variables

See `.env.example` and `deploy/env.production.example`.

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Random 64-char hex string |
| `FLASK_ENV` | Yes | `production` on VPS |
| `PRODUCTION` | Yes | `1` enables secure cookies + proxy fix |
| `DATABASE_URL` | No | Defaults to SQLite in `instance/` |
| `FRESH_DATABASE` | No | `1` = wipe SQLite on install and create empty tables |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | First install | Creates master admin via `create.py` |
| `GUNICORN_BIND` | No | `127.0.0.1:8000` behind Nginx |
| `SESSION_COOKIE_SECURE` | No | `true` when using HTTPS |

## Updates / redeploy

```bash
cd /var/www/school-management
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart school-management
```

## Windows dev vs Linux production

| | Development (Windows) | Production (Linux VPS) |
|--|----------------------|------------------------|
| Server | `python app.py` (Waitress) | Gunicorn + Nginx |
| Port | 3000 | 80/443 (Nginx) → 8000 |
| Config | `.env` | `/etc/school-management/env` |

## Troubleshooting

**502 Bad Gateway** — Gunicorn not running:

```bash
sudo systemctl status school-management
journalctl -u school-management -n 50
```

**Permission denied on uploads/database**:

```bash
sudo chown -R www-data:www-data /var/www/school-management/instance
sudo chown -R www-data:www-data /var/www/school-management/static/uploads
```

**CSRF errors behind HTTPS** — ensure Nginx sends `X-Forwarded-Proto https` and `PRODUCTION=1` is set.

**SQLite database locked** — keep `WEB_CONCURRENCY=1` or migrate to PostgreSQL.

## Security checklist

- [ ] Change `SECRET_KEY` from default
- [ ] Enable HTTPS with Certbot
- [ ] Set `SESSION_COOKIE_SECURE=true`
- [ ] Firewall: `sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable`
- [ ] Restrict `/etc/school-management/env` to root (`chmod 600`)
- [ ] Regular backups of `instance/keeptrack_full.db`
