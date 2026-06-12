# Cloud File Host — Frontend

A static (HTML + vanilla JS) frontend for the Cloud File Host project, deployed on
Vercel. It talks to a Flask backend running on AWS EC2, which stores files in
Amazon S3.

## Architecture

```
Browser ──HTTPS──> Vercel (this static site)
                      │  fetch() + Bearer token
                      ▼
              Stable HTTPS URL (Cloudflare Tunnel)
                      ▼
                 Flask API on EC2  ──>  Amazon S3
```

- **Auth:** the frontend logs in at `POST /api/login`, receives a signed token,
  and sends it as `Authorization: Bearer <token>` on every request.
- **Backend URL:** stored in `config.json` and read at runtime. To point the
  frontend at a new backend URL, edit `config.json` and redeploy.

## Configure the backend URL

Edit `config.json`:

```json
{ "apiBaseUrl": "https://your-stable-backend-url" }
```

- For local testing against a local backend: `http://localhost:5000`
- For production: your backend's **HTTPS** URL (see note below).

> A deployed Vercel site is served over HTTPS, and browsers block HTTPS pages
> from calling plain HTTP. The backend must therefore be reachable over HTTPS.
> The easiest way is a Cloudflare Tunnel, which also gives a stable URL that
> survives EC2 restarts.

## Run locally

```powershell
# From this folder, start any static server, e.g. Python's:
python -m http.server 8000
```

Open http://localhost:8000

## Start the EC2 backend

```bash
# On the EC2 instance:
sudo systemctl start cloudfilehost
sudo systemctl status cloudfilehost
```

## Deploy to Vercel

1. Push this folder to a GitHub repo.
2. In Vercel: **New Project → Import** the repo.
3. Framework preset: **Other** (it's a static site, no build step).
4. Deploy. Update `config.json` with your backend URL and push to redeploy.
