# AWS Deployment Guide — School Management System

Deploy the Flask app on AWS using **EC2 + Docker** (recommended default). Alternatives: **Elastic Beanstalk (Docker)** and **App Runner** are documented below.

## Recommended architecture (default)

```
Internet
   │
   ▼
Route 53 (optional DNS)
   │
   ▼
Application Load Balancer (HTTPS, ACM certificate)
   │
   ▼
EC2 (t3.small, 2 GB RAM) — Docker container
   ├── Gunicorn :8000
   ├── /health probe
   ├── EBS volume → /app/instance (SQLite) + /app/static/uploads
   └── (optional) Amazon RDS PostgreSQL
```

| Component | Choice | Why |
|-----------|--------|-----|
| Compute | **EC2 + Docker** | Full control, persistent EBS, matches existing Gunicorn/Linux setup |
| Database (small school) | **SQLite on EBS** | Simple, no extra cost; single instance only |
| Database (production) | **RDS PostgreSQL** | Backups, multi-AZ, multiple app instances |
| HTTPS | **ALB + ACM** | Free TLS certs, health checks on `/health` |
| Static files | **App serves `/static`** | Optional later: S3 + CloudFront for CDN |
| Secrets | **SSM Parameter Store** or `.env` on EBS | Never commit `.env` to git |

### Why not SQLite on ephemeral storage?

AWS container/instance **local disk is ephemeral** unless you attach storage:

- **ECS Fargate / App Runner**: container filesystem is lost on redeploy.
- **EC2 without EBS mount**: instance store or root volume may be replaced.

**Always mount persistent storage** for SQLite and uploads:

- **EBS volume** mounted at `/data`, bind to `/app/instance` and `/app/static/uploads`.
- Or **Amazon EFS** if you need shared storage across multiple containers (SQLite still needs a **single writer** — use PostgreSQL for multiple app servers).

### PostgreSQL migration path

1. Create RDS PostgreSQL 16 (db.t4g.micro is fine to start).
2. Security group: allow port 5432 from the EC2/ECS security group only.
3. Set in production env:

   ```bash
   DATABASE_URL=postgresql+psycopg2://schooluser:PASSWORD@endpoint.region.rds.amazonaws.com:5432/school_db
   WEB_CONCURRENCY=2
   ```

4. Run `flask db upgrade` or `python init_db.py` once against the new database.
5. Migrate data from SQLite with `pgloader` or a one-off export script if you have existing data.

---

## Prerequisites

- AWS account
- Domain name (optional but required for HTTPS and `SITE_URL` QR codes)
- Git clone of this repository on your machine

---

## Step 1 — Test locally with Docker

```bash
cd SCHOOL_MANAGEMENT
cp .env.production.example .env
# Edit .env: SECRET_KEY, ADMIN_PASSWORD, SITE_URL=http://localhost:8000 (for local test)

docker compose up --build
```

Open http://localhost:8000 and http://localhost:8000/health

After first login works, set `FRESH_DATABASE=0` in `.env` for subsequent starts.

### Test with PostgreSQL locally

```bash
# In .env:
# DATABASE_URL=postgresql+psycopg2://schooluser:change_me_in_production@db:5432/school_db
# POSTGRES_PASSWORD=change_me_in_production

docker compose --profile postgres up --build
```

---

## Step 2 — Build and push image (optional ECR)

On your workstation or EC2:

```bash
aws ecr create-repository --repository-name school-management
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ACCOUNT.dkr.ecr.us-east-1.amazonaws.com

docker build -t school-management .
docker tag school-management:latest ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/school-management:latest
docker push ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/school-management:latest
```

You can also `git pull` on EC2 and `docker build` there without ECR.

---

## Step 3 — EC2 + Docker (recommended)

### 3.1 Launch EC2

- AMI: **Ubuntu 22.04 LTS**
- Instance: **t3.small** (2 GB RAM)
- Storage: **gp3 30 GB** root volume
- Security group:
  - SSH (22) from your IP
  - HTTP (80) from 0.0.0.0/0 (ALB) or temporarily for testing
  - Custom TCP **8000** only if not using ALB yet

### 3.2 Attach EBS for persistent data (SQLite + uploads)

1. Create a **gp3 EBS volume** (20–50 GB) in the same AZ as the instance.
2. Attach to `/dev/xvdf` (example).
3. On EC2:

```bash
sudo mkfs.ext4 /dev/xvdf   # first time only
sudo mkdir -p /data/school-management
echo '/dev/xvdf /data/school-management ext4 defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a
sudo mkdir -p /data/school-management/instance /data/school-management/uploads
```

### 3.3 Install Docker

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
# log out and back in
```

### 3.4 Deploy application

```bash
sudo git clone <your-repo-url> /opt/school-management
cd /opt/school-management
sudo cp .env.production.example .env
sudo nano .env   # SECRET_KEY, SITE_URL, ADMIN_PASSWORD, FRESH_DATABASE=1 once
```

Create `docker-compose.prod.yml` override on the server:

```yaml
services:
  web:
    build: .
    ports:
      - "127.0.0.1:8000:8000"
    env_file: .env
    volumes:
      - /data/school-management/instance:/app/instance
      - /data/school-management/uploads:/app/static/uploads
    restart: always
```

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
curl -s http://127.0.0.1:8000/health
```

Set `FRESH_DATABASE=0` in `.env` after successful first boot.

### 3.5 HTTPS with Application Load Balancer

1. Request an **ACM certificate** for `school.example.com`.
2. Create an **ALB** (internet-facing) with HTTPS listener → target group.
3. Target group: EC2 instance port **8000**, health check path **`/health`**, success codes **200**.
4. Point Route 53 A/alias record to the ALB.
5. Ensure `.env` has:

   ```bash
   SITE_URL=https://school.example.com
   SESSION_COOKIE_SECURE=true
   PROXY_FIX_HOPS=1
   ```

6. Restrict EC2 security group so **only the ALB** can reach port 8000.

### 3.6 Backups

- **SQLite**: snapshot the EBS volume or cron-copy `instance/keeptrack_full.db` to S3.
- **RDS**: enable automated backups and retention.
- **Uploads**: sync `/data/school-management/uploads` to S3 (e.g. `aws s3 sync` nightly).

---

## Alternative A — Elastic Beanstalk (Docker)

1. Install EB CLI: `pip install awsebcli`
2. From project root:

```bash
eb init -p docker school-management --region us-east-1
eb create school-management-prod --elb-type application
```

3. Set environment properties in the EB console (or `eb setenv`):

   - `SECRET_KEY`, `PRODUCTION=1`, `FLASK_ENV=production`, `DOCKER=1`
   - `SITE_URL`, `DATABASE_URL` (RDS endpoint if used)
   - `GUNICORN_BIND=0.0.0.0:8000`

4. Configure load balancer health check: path **`/health`**, port **80** (EB maps to container).

5. For SQLite on EB: attach **EFS** and mount to `/app/instance` and `/app/static/uploads` in a `.ebextensions` volume config, or use **RDS PostgreSQL** (strongly preferred on EB).

`Procfile` in the repo root is used if you deploy without the Dockerfile platform.

---

## Alternative B — AWS App Runner

App Runner works with a container image in ECR. **Do not use SQLite** on App Runner without external storage — use **RDS PostgreSQL** and store uploads on **S3** (would require app changes for S3 uploads; EC2+EBS is simpler today).

High level:

1. Push image to ECR.
2. Create App Runner service from ECR image, port **8000**.
3. Configure health check: **`/health`**.
4. Set env vars from `.env.production.example`.
5. Attach custom domain + ACM in App Runner console.

---

## Static files and CDN (optional)

The app serves files from `static/` and `static/uploads/` via Flask/Werkzeug. For a single-school deployment this is sufficient behind ALB.

To add **S3 + CloudFront** later:

1. Upload versioned assets (`static/css`, `static/js`, images) to an S3 bucket.
2. Create a CloudFront distribution with the S3 origin.
3. Keep **user uploads** on EBS/EFS or move to a private S3 bucket with presigned URLs (requires code changes).
4. Set `SITE_URL` to your CloudFront or ALB HTTPS URL.

---

## Security checklist

| Item | Production setting |
|------|-------------------|
| `SECRET_KEY` | Unique 64-char hex; store in SSM/Secrets Manager |
| `SITE_URL` | `https://your-domain.com` |
| `SESSION_COOKIE_SECURE` | `true` |
| `PROXY_FIX_HOPS` | `1` behind one ALB/Nginx hop |
| `FRESH_DATABASE` | `1` only on first install |
| `.env` | chmod 600, never in git |
| SSH | Key-only, restrict source IP |
| RDS | Not publicly accessible; security group to app only |

---

## Operations

```bash
# Logs
docker compose logs -f web

# Restart after env change
docker compose up -d --build

# Shell into container
docker compose exec web bash

# Reset admin password on server
docker compose exec web python create.py
```

Health endpoint (for ALB/ECS/Beanstalk):

```text
GET /health
200 {"status":"ok","service":"school-management","database":"connected"}
503 if database unreachable
```

---

## Related docs

- [DEPLOYMENT.md](DEPLOYMENT.md) — bare-metal VPS with Gunicorn + Nginx + systemd
- [.env.production.example](.env.production.example) — full production variable list
- [.env.example](.env.example) — local development template
