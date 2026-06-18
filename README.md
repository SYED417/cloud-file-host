# Cloud File Host

A full-stack cloud file-hosting application with a Flask REST API backend deployed on **AWS EC2**, file storage on **Amazon S3**, and a static frontend hosted on **Vercel**.

Built as a portfolio project to demonstrate cloud deployment, backend API design, authentication, and frontend integration across two separate hosting environments.

---

## Live Demo

| Layer | URL |
|-------|-----|
| Frontend (Vercel) | _Deploy to Vercel and add URL here_ |
| Backend API (EC2) | _Started on demand — see "Running the Backend" below_ |

> The EC2 instance is stopped when not in use to stay within the AWS Free Tier.
> Start it and update `frontend/config.json` with the current backend URL to see the live app.

---

## Architecture

```
Browser ──HTTPS──> Vercel (static HTML/JS frontend)
                      │
                      │  REST API  (Bearer token auth)
                      ▼
              Cloudflare Tunnel  (stable HTTPS endpoint)
                      │
                      ▼
            AWS EC2 – Amazon Linux  (Flask app, systemd)
                      │
                      ▼
                Amazon S3  (file storage, eu-north-1)
                      │
                      ▼
                  SQLite  (user accounts, stored on EC2)
```

### Key design decisions

- **Separate frontend and backend** — Vercel for the static UI, EC2 for the API. This mirrors real-world SaaS architecture.
- **Token-based auth over cookies** — avoids cross-origin cookie restrictions between Vercel and EC2. The backend issues a signed bearer token; the frontend stores it in `localStorage`.
- **Two UIs, one backend** — the EC2 Flask app serves its own server-rendered HTML UI (for direct access) *and* a JSON API for the Vercel frontend. No code was removed; auth was layered on top.
- **Runtime config, not build-time env vars** — the frontend reads the backend URL from `frontend/config.json` at page load, so changing the backend URL requires editing one file and redeploying — no rebuild needed.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend language | Python 3.9 |
| Backend framework | Flask 3 |
| Authentication | Flask-Login (HTML UI) + itsdangerous tokens (JSON API) |
| Database | SQLite via Flask-SQLAlchemy |
| File storage | Amazon S3 (boto3) |
| Server | AWS EC2 (Amazon Linux), systemd service |
| CORS | Flask-Cors |
| Frontend | Vanilla HTML5 / CSS / JavaScript |
| Frontend hosting | Vercel |
| Styling | Bootstrap 5 + Bootstrap Icons (CDN) |

---

## Features

- **File upload** — drag-and-drop style upload form; validates extension and enforces a 20 MB per-file limit server-side.
- **File listing** — responsive table showing filename, size, last-modified date, and download/delete actions.
- **Authentication** — email + hashed-password login. Sessions for the HTML UI; bearer tokens for the JSON API.
- **User limit** — maximum 3 non-admin users can register. Admin account is created via a CLI command and does not count toward the limit.
- **Dual interface** — the same Flask app serves server-rendered Jinja2 templates and a CORS-enabled JSON API on `/api/*`.
- **Backend status indicator** — the Vercel frontend pings `/api/health` on load and shows "Backend online / offline" in real time.
- **Offline message** — if EC2 is stopped, the frontend shows "Backend currently offline. Demo available on request." instead of an error.

---

## Project Structure

```
.
├── app.py                  # Flask application (routes, models, API, auth)
├── requirements.txt        # Python dependencies
├── .env.example            # Template for environment variables
│
├── templates/
│   ├── base.html           # Shared layout (navbar, flash messages)
│   ├── index.html          # Dashboard (upload + file list)
│   ├── login.html          # Login page
│   └── register.html       # Registration page
│
├── static/
│   └── styles.css          # Custom styles (drop-zone, card tweaks)
│
└── frontend/               # Vercel static site (separate deployable unit)
    ├── index.html          # Single-page app (landing + login + dashboard)
    ├── app.js              # All fetch/API logic
    ├── config.json         # Backend URL — edit this when the IP changes
    ├── styles.css          # Minimal overrides on top of Bootstrap
    └── README.md           # Frontend-specific setup instructions
```

---

## Local Development

### Prerequisites

- Python 3.9+
- An AWS account with an S3 bucket and IAM credentials
- Git

### 1. Clone and set up the backend

```bash
git clone https://github.com/SYED417/cloud-file-host.git
cd cloud-file-host

python -m venv venv
# Windows:
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your real values:

```env
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=eu-north-1
S3_BUCKET_NAME=your-bucket-name
FLASK_SECRET_KEY=a-long-random-string
FRONTEND_ORIGINS=http://localhost:8000
```

### 3. Create your admin account

```bash
flask --app app create-admin you@example.com YourStrongPassword
```

This is a one-time command. It creates (or updates) a user with `is_admin=True`.
Re-run with a new password to change it.

### 4. Run the backend

```bash
python app.py
```

Backend available at **http://localhost:5000**

- HTML UI: http://localhost:5000/login
- Health check: http://localhost:5000/api/health

### 5. Run the frontend

```bash
cd frontend
python -m http.server 8000
```

Frontend available at **http://localhost:8000**

Log in with the admin credentials you created in step 3.

---

## API Reference

All `/api/*` routes require the header `Authorization: Bearer <token>` (except `/api/health` and `/api/login`).

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/health` | None | Returns `{"status":"ok"}` |
| `POST` | `/api/login` | None | Body: `{"email","password"}` → returns `{token, email, is_admin}` |
| `GET` | `/api/me` | Token | Returns the current user's info |
| `GET` | `/api/files` | Token | Returns all S3 objects as a JSON array |
| `POST` | `/api/upload` | Token | `multipart/form-data` with field `file` |
| `POST` | `/api/delete` | Token | Body: `{"key":"<s3-key>"}` |

---

## Deployment

### Backend — AWS EC2

```bash
# On Amazon Linux EC2:
sudo yum install -y python3 python3-venv git
git clone https://github.com/SYED417/cloud-file-host.git ~/cloudapp
cd ~/cloudapp
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # fill in real values
flask --app app create-admin you@example.com YourPassword
```

Create `/etc/systemd/system/cloudfilehost.service`:

```ini
[Unit]
Description=Cloud File Host Flask App
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/cloudapp
ExecStart=/home/ec2-user/cloudapp/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cloudfilehost
```

> **Security group:** inbound TCP port 5000 from your IP (for direct access) or from Cloudflare IPs only (when using a tunnel).

> **HTTPS requirement:** Vercel serves the frontend over HTTPS. Browsers block HTTPS pages from calling plain HTTP, so the backend needs a stable HTTPS URL. Use a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (free tier) to expose the Flask app as `https://...` without opening extra ports or managing certificates.

### Frontend — Vercel

1. Push this repo to GitHub.
2. In Vercel: **New Project → Import repo → Root Directory: `frontend` → Framework: Other → Deploy**.
3. No build step, no environment variables needed — the backend URL lives in `frontend/config.json`.
4. After deploying, update `FRONTEND_ORIGINS` in your EC2 `.env` to the Vercel URL and restart the service.

### Updating the backend URL

When your EC2 IP changes after a stop/start:

1. Edit `frontend/config.json`:
   ```json
   { "apiBaseUrl": "https://your-new-backend-url" }
   ```
2. Commit and push — Vercel redeploys automatically.

---

## Security Notes

- Passwords are stored as **salted hashes** (Werkzeug's `generate_password_hash`). Plain-text passwords are never stored or logged.
- API tokens are signed with `itsdangerous.URLSafeTimedSerializer` using the app secret key. Tokens expire after 12 hours.
- The `FLASK_SECRET_KEY` and all AWS credentials are loaded from `.env` (excluded from git via `.gitignore`).
- CORS is restricted to the `/api/*` prefix. In production, set `FRONTEND_ORIGINS` to your exact Vercel domain.
- This app runs Flask's development server. For production, replace it with **Gunicorn** behind **nginx**.

---

## Future Improvements

- [ ] Add Gunicorn + nginx for production-grade serving
- [ ] Attach an Elastic IP to EC2 to keep a fixed address
- [ ] Add file preview for images in the browser
- [ ] Add per-user file isolation (each user sees only their uploads)
- [ ] Add admin dashboard to manage users

---

## Author

Built by **Syed Sulaiman** as a portfolio project demonstrating AWS, Flask, and cloud deployment skills.

- GitHub: [@sulaimansyed417](https://github.com/sulaimansyed417)
- Email: sulaimansyed417@gmail.com
