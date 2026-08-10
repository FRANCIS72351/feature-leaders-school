# SOFTNETAFRICA — Full All-in-One Flask School Management System (Starter)

This expanded version of KeepTrack adds many modules from the project proposal:
students (with photo uploads), classes & schedules, assessments, grades, attendance,
announcements, payments, sponsors, discipline records, PDF transcript generation
(with QR code), Chart.js analytics, and a Zoom integration placeholder.

## Setup (local development)
1. Create a virtualenv and activate it:
   ```bash
   python -m venv venv
   source venv/bin/activate   # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
2. Create uploads folder:
   ```bash
   mkdir -p instance/uploads
   ```
3. Copy `.env.example` to `.env` and update any secrets (SECRET_KEY).
4. Seed sample data:
   ```bash
   python seed_data.py
   ```
5. Run the app:
   ```bash
   flask run --port=5000
   ```
6. Open http://127.0.0.1:5000

## Production (VPS / Linux)

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for full VPS setup with Gunicorn, Nginx, and systemd.

## Production (AWS)

See **[DEPLOY_AWS.md](DEPLOY_AWS.md)** for EC2 + Docker (recommended), Elastic Beanstalk, App Runner, RDS PostgreSQL, and EBS persistence notes.

Quick start on Linux:

```bash
cp .env.example .env   # set SECRET_KEY and FLASK_ENV=production
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash deploy/start-gunicorn.sh
```

## Notes
- Zoom integration is a placeholder: you must supply your Zoom API credentials and implement the API calls.
- For production, use a proper RDBMS and WSGI server (Gunicorn), secure SECRET_KEY, and serve static files via CDN.
