# Deploy on PythonAnywhere

Host the School Management System at `https://YOUR_USERNAME.pythonanywhere.com`.

**Repository:** https://github.com/FRANCIS72351/SCHOOL_MANAGEMENT.git

The database starts **fresh** on PythonAnywhere (your local `instance/*.db` is not in git).

---

## 1. Open PythonAnywhere

1. Sign in at [pythonanywhere.com](https://www.pythonanywhere.com)
2. Open the **Dashboard**

---

## 2. Clone and install (Bash console)

Open a **Bash** console and run:

```bash
cd ~
git clone https://github.com/FRANCIS72351/SCHOOL_MANAGEMENT.git
cd SCHOOL_MANAGEMENT
bash deploy/pythonanywhere/setup.sh
```

Edit `.env` and set a strong admin password:

```bash
nano ~/SCHOOL_MANAGEMENT/.env
```

Set at minimum:

```
ADMIN_PASSWORD=your_secure_password_here
```

Re-run database + admin setup if you changed the password after first run:

```bash
cd ~/SCHOOL_MANAGEMENT
workon schoolmgmt
bash deploy/pythonanywhere/init-database.sh
```

---

## 3. Create the Web app

Go to the **Web** tab → **Add a new web app**:

| Setting | Value |
|---------|--------|
| Framework | Manual configuration |
| Python | 3.10 (or 3.11) |

Then configure:

| Field | Value |
|-------|--------|
| **Source code** | `/home/YOUR_USERNAME/SCHOOL_MANAGEMENT` |
| **Working directory** | `/home/YOUR_USERNAME/SCHOOL_MANAGEMENT` |
| **Virtualenv** | `/home/YOUR_USERNAME/.virtualenvs/schoolmgmt` |

Replace `YOUR_USERNAME` with your PythonAnywhere username.

---

## 4. WSGI configuration

Click the WSGI configuration file link and replace its contents with
`deploy/pythonanywhere/wsgi.py` from the project, changing:

```python
USERNAME = "YOUR_USERNAME"
```

to your real username, e.g.:

```python
USERNAME = "francis72351"
```

Save the file.

---

## 5. Static files

On the **Web** tab, under **Static files**, add:

| URL | Directory |
|-----|-----------|
| `/static/` | `/home/YOUR_USERNAME/SCHOOL_MANAGEMENT/static/` |

---

## 6. Go live

Click the green **Reload** button on the Web tab.

Visit: `https://YOUR_USERNAME.pythonanywhere.com`

Log in with the admin email/password from `.env` (default email: `admin@school.com`).

---

## Updates (after you push to GitHub)

```bash
cd ~/SCHOOL_MANAGEMENT
git pull origin main
workon schoolmgmt
pip install -r requirements.txt
```

Then **Reload** the web app on the Web tab.

This keeps your PythonAnywhere database; it does not wipe it.

---

## Optional: copy your local database to PythonAnywhere

Only if you want your Windows dev data on PythonAnywhere:

```bash
# From your Windows machine (Git Bash or PowerShell with scp)
scp instance/keeptrack_full.db YOUR_USERNAME@ssh.pythonanywhere.com:/home/YOUR_USERNAME/SCHOOL_MANAGEMENT/instance/
```

Then reload the web app.

---

## Troubleshooting

**502 / import error**

- Check **Error log** on the Web tab
- Confirm virtualenv path and `workon schoolmgmt` has all packages: `pip install -r requirements.txt`

**SECRET_KEY error**

- Ensure `.env` exists with `SECRET_KEY` and `PRODUCTION=1`
- WSGI file must `load_dotenv` (see `deploy/pythonanywhere/wsgi.py`)

**CSRF / login issues**

- PythonAnywhere uses HTTPS; keep `SESSION_COOKIE_SECURE=true` in `.env`

**Database permission errors**

```bash
chmod 775 ~/SCHOOL_MANAGEMENT/instance
```

**OCR grading (pytesseract)**

- Optional feature; may not work on PythonAnywhere free tier (no Tesseract). Other features work normally.

---

## PythonAnywhere vs VPS

| | PythonAnywhere | Linux VPS |
|--|----------------|-----------|
| Server | Managed WSGI | Gunicorn + Nginx |
| Setup | `deploy/pythonanywhere/setup.sh` | `deploy/install-linux.sh` |
| Domain | `username.pythonanywhere.com` | Your own domain |
| Database | Fresh SQLite in `instance/` | Fresh SQLite in `instance/` |
