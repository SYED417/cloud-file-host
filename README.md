# Cloud File Host

A production-grade, full-stack cloud file-hosting application built with **Python / Flask**, deployed on **Render**, and backed by **Amazon S3** for storage and **PostgreSQL** for persistence.

Built as a portfolio project to demonstrate end-to-end cloud architecture, secure file handling, authentication, and infrastructure decision-making.

> **Live app:** _Add your Render URL here after deploying_

---

## Architecture

```
Browser ──HTTPS──> Render (Flask app — serves UI + API on one domain)
                      │
                      ├──> Amazon S3  (file storage, eu-north-1)
                      │       └── pre-signed URLs  (private bucket, no public access)
                      │
                      └──> Render PostgreSQL  (persistent user accounts)
```

**Why monolithic on Render?**
A single-domain deployment eliminates CORS entirely. The browser sends the session cookie automatically with every request because the UI and API share the same origin — no token management, no preflight overhead.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Language | Python 3.10 | — |
| Framework | Flask 3 | Lightweight, production-proven |
| Auth | Flask-Login + Werkzeug password hashing | Session-based, CSRF-safe via SameSite cookie |
| Database | PostgreSQL (Render) / SQLite (local) | Persistent accounts that survive redeploys |
| ORM | Flask-SQLAlchemy | Clean model layer, easy migrations |
| File storage | Amazon S3 via boto3 | Durable, cheap, scales to any file size |
| Download security | S3 pre-signed URLs (60 s TTL) | Bucket stays private; links expire automatically |
| Web server | Gunicorn | Production WSGI, handles concurrent requests |
| Hosting | Render | Zero-config deploy from GitHub, free PostgreSQL |
| Styling | Bootstrap 5 + Bootstrap Icons | Fast, accessible, responsive out of the box |

---

## Features

- **Secure file upload** — drag-and-drop form with server-side extension whitelist (`txt pdf png jpg jpeg zip`) and a hard 20 MB cap. Files stream directly into S3 — nothing touches disk.
- **Private downloads via pre-signed URLs** — the S3 bucket has no public access. Clicking Download hits `/download/<key>`, which generates a 60-second signed URL and redirects. Expired links are dead and cannot be forwarded.
- **Authentication** — email + bcrypt-hashed password login. Session cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` on Render (HTTPS only).
- **User limit enforcement** — maximum 3 non-admin registrations. Admin account is auto-seeded from environment variables on first deploy.
- **Persistent accounts** — PostgreSQL on Render keeps user data across every restart and redeploy. Falls back to SQLite for local development automatically.
- **Fail-fast startup** — the app refuses to start if any required environment variable is missing, preventing silent misconfigurations in production.

---

## Security Design

| Concern | Mitigation |
|---------|-----------|
| Hardcoded secrets | None. Every credential is loaded from environment variables. App exits at startup if any are missing. |
| S3 bucket exposure | Bucket is **fully private**. No bucket policy grants public read. All downloads go through 60-second pre-signed URLs generated server-side. |
| Session hijacking | Cookie is `HttpOnly` (no JS access), `SameSite=Lax` (CSRF mitigation), `Secure` (HTTPS only on Render). |
| Oversized uploads | Flask rejects payloads above 20 MB at the WSGI layer before S3 is touched. |
| Plaintext passwords | Passwords are stored as salted bcrypt hashes via Werkzeug. Never logged or stored in plain text. |
| Filename injection | `werkzeug.utils.secure_filename` sanitises all filenames. A UUID prefix prevents collisions and path traversal. |
| SQL injection | All DB queries go through SQLAlchemy ORM with parameterised bindings. No raw SQL. |

---

## Project Structure

```
.
├── app.py                  # Flask app — routes, models, auth, S3 logic
├── requirements.txt        # Pinned Python dependencies
├── Procfile                # Render / Gunicorn start command
├── .env.example            # Documents every required environment variable
│
├── templates/
│   ├── base.html           # Shared layout (navbar, flash messages)
│   ├── index.html          # Dashboard — upload form + file table
│   ├── login.html          # Login page
│   └── register.html       # Registration page
│
└── static/
    ├── script.js           # Upload fetch logic (same-origin, relative path)
    └── styles.css          # Indigo/navy theme, drop-zone styling
```

---

## Local Development

### Prerequisites
- Python 3.10+
- An AWS account with an S3 bucket and an IAM user that has `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` permissions

### Setup

```bash
git clone https://github.com/SYED417/cloud-file-host.git
cd cloud-file-host

python -m venv venv
# Windows
.\venv\Scripts\Activate.ps1
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and fill in your AWS credentials, bucket name, and secret key.
# Leave DATABASE_URL blank to use the local SQLite fallback.

python app.py
# → http://localhost:5000
```

The admin account is auto-created from `ADMIN_EMAIL` + `ADMIN_PASSWORD` in `.env` on the first run.

Alternatively, create it with the CLI:

```bash
flask --app app create-admin you@example.com YourStrongPassword
```

---

## Render Deployment

### 1. Create a PostgreSQL instance on Render
Render dashboard → **New → PostgreSQL** → copy the **Internal Database URL**.

### 2. Create a Web Service
Render dashboard → **New → Web Service** → connect this GitHub repo.

| Setting | Value |
|---------|-------|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | _(from Procfile — auto-detected)_ |

### 3. Set environment variables

| Variable | Description |
|----------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM access key |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key |
| `AWS_DEFAULT_REGION` | e.g. `eu-north-1` |
| `S3_BUCKET_NAME` | Your bucket name |
| `FLASK_SECRET_KEY` | Any long random string (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `ADMIN_EMAIL` | Login email for the admin account |
| `ADMIN_PASSWORD` | Login password for the admin account |
| `DATABASE_URL` | Internal Database URL from step 1 |

### 4. Deploy
Push to `main` → Render builds and deploys automatically on every push.

---

## Environment Variables Reference

See `.env.example` for the full annotated template.

---

## Future Improvements

- [ ] Per-user file isolation (each user sees only their own uploads)
- [ ] Admin dashboard to view and manage all users
- [ ] File preview for images directly in the browser
- [ ] Virus/malware scanning on upload (AWS Lambda + ClamAV)
- [ ] Audit log — record who uploaded/deleted what and when

---

## Author

**Syed Sulaiman Usman**
Portfolio project demonstrating AWS S3, Flask, PostgreSQL, secure authentication, and cloud deployment on Render.

- GitHub: [@SYED417](https://github.com/SYED417)
- Email: sulaimansyed417@gmail.com
