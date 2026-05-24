# PlanForge

A production-ready Django SaaS — project management for small teams.

**Live demo:** [planforge.coreapp.name.ng](https://planforge.coreapp.name.ng) *(Render Free — first load may take ~10 s after inactivity)*

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6, Python 3.12 |
| Database | PostgreSQL (Supabase) |
| Cache / Sessions | Redis (Upstash) |
| Frontend | Django Templates, DM Sans + Lora, PWA |
| Auth | Custom email verification + Google OAuth |
| File storage | Cloudinary |
| Email | Resend HTTP API |
| Rate limiting | Redis-backed atomic counter |
| Hosting | Render |

---

## Architecture

```
Request → View → DTO (schemas.py) → Service → Model → DB
```

- **Views** — thin. Read the request, call a service, return a response. No business logic.
- **DTOs** (`schemas.py`) — validate and type-annotate data before it reaches services.
- **Services** — all business logic lives here. Never touch `request`. Fully unit-testable.
- **Decorators** — enforce org-level and project-level permissions before the view runs.
- **Context processors** — inject active org + unread count into every template (cached 30 s per user).

---

## Features

**Auth**
- Register with email verification (6-digit code, 10-minute expiry, 5-attempt lockout)
- Login with rate limiting (10 attempts/min per IP + username)
- Google OAuth — full redirect flow, CSRF state token, open redirect protection
- Password reset (customised to use Resend instead of SMTP)
- Email change with re-verification
- Account deletion

**Organizations (multi-tenancy)**
- Create and switch between multiple organizations
- Session-based active org context — every view scopes to the active org automatically
- Invite members by username (direct invite) or shareable link (approval required)
- Roles: Owner / Admin / Member — enforced at decorator and service level
- Transfer ownership

**Projects**
- Full CRUD with status tracking (Active / On Hold / Completed / Archived)
- Cover image upload via Cloudinary
- Budget tracking with multi-currency support

**Tasks**
- Create, edit, delete, status toggle (inline checkbox)
- Priority levels, due dates, assignee
- File attachments (Cloudinary, 10 MB limit, type whitelist)
- Comments
- AI task generation via Groq (optional)

**Other**
- Activity feed (org-wide and per-project)
- Analytics dashboard (Chart.js)
- Email digests (daily urgent / weekly summary) via cron-job.org
- PWA — installable, offline fallback page, service worker asset caching
- Guest access — invite external collaborators to a single project without org membership

---

## Project Structure

```
planforge/
├── core/                    # Rate limiter, email utils, dashboard view
├── accounts/                # Auth: register, login, Google OAuth, profile
├── organizations/           # Orgs, memberships, RBAC, notifications
├── projects/                # Projects, tasks, attachments, comments, activity
├── tests/                   # 68 smoke + functional tests (Django TestClient)
├── templates/               # All HTML templates
├── static/                  # CSS, JS, PWA manifest + service worker
└── planforge/
    └── settings/
        ├── base.py          # Shared settings
        ├── dev.py           # Local development
        └── prod.py          # Production (Render)
```

---

## Local Setup

```bash
git clone <https://github.com/israel-omotayo/Planforge.git>
cd planforge
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` in the project root:

```ini
SECRET_KEY=any-random-string-for-dev
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# PostgreSQL
DB_NAME=planforge_db
DB_USER=planforge_user
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432

# Leave these empty in dev — emails print to terminal, files won't upload
RESEND_API_KEY=
RESEND_FROM_EMAIL=
CLOUDINARY_URL=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GROQ_API_KEY=
CRON_SECRET=
```

```bash
python manage.py migrate --settings=planforge.settings.dev
python manage.py createsuperuser --settings=planforge.settings.dev
python manage.py runserver --settings=planforge.settings.dev
```

---

## Running Tests

```bash
# All 68 tests
python manage.py test tests --settings=planforge.settings.dev

# Single class
python manage.py test tests.test_smoke.TaskTest --settings=planforge.settings.dev

# Verbose
python manage.py test tests -v 2 --settings=planforge.settings.dev
```

---

## Deploying to Render

### Prerequisites

| Service | Purpose |
|---|---|
| [Supabase](https://supabase.com) | PostgreSQL database |
| [Upstash](https://upstash.com) | Redis (sessions, cache, rate limiting) |
| [Resend](https://resend.com) | Transactional email |
| [Cloudinary](https://cloudinary.com) | File storage |
| [Google Cloud Console](https://console.cloud.google.com) | OAuth credentials |
| [Groq](https://console.groq.com) | AI task generation |
---

### Step 1 — Database (Supabase)

1. Create a project at [supabase.com](https://supabase.com).
2. Go to **Settings → Database → Connection string** tab.
3. Select **Session pooler** (not Transaction pooler — that mode breaks Django's prepared statements).
4. Note these values for later:
   - `DB_HOST` — `aws-0-<region>.pooler.supabase.com`
   - `DB_USER` — `postgres.<project-ref>`
   - `DB_PASSWORD` — your database password
   - `DB_PORT` — always `5432`

### Step 2 — Redis (Upstash)

1. Create an account at [upstash.com](https://upstash.com).
2. Create a Redis database — pick the region closest to Render's server.
3. Copy the **Redis URL** (starts with `rediss://`).

### Step 3 — Email (Resend)

1. Create an account at [resend.com](https://resend.com).
2. Add and verify your sending domain under **Domains**.
3. Generate an API key under **API Keys** (send-only scope is fine).

> **Note:** Render blocks outbound SMTP (ports 587/465). PlanForge calls the Resend HTTP API directly from `core/utils.py`, bypassing this entirely.

### Step 4 — File Storage (Cloudinary)

1. Create an account at [cloudinary.com](https://cloudinary.com).
2. Copy your **Cloudinary URL** from the dashboard: `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`.

### Step 5 — Deploy the Web Service

1. Render → **New Web Service** → connect your GitHub repo.
2. **Runtime:** Python
3. **Build Command:**
   ```
   pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
   ```
4. **Start Command:**
   ```
   gunicorn planforge.wsgi:application --workers 1 --timeout 120 --bind 0.0.0.0:$PORT
   ```
   > Keep workers at **1** on the free tier (512 MB RAM). More workers will OOM-kill the dyno.

5. Set all environment variables (see Step 6).

---

### Step 6 — Environment Variables

| Variable | Value |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `planforge.settings.prod` |
| `SECRET_KEY` | Strong random string |
| `ALLOWED_HOSTS` | `yourapp.onrender.com` (add custom domain if you have one) |
| `RENDER_EXTERNAL_HOSTNAME` | `yourapp.onrender.com` |
| `BASE_FRONTEND_URL` | `yourapp.onrender.com` (or custom domain) |
| `DB_HOST` | Supabase Session Pooler host |
| `DB_PORT` | `5432` |
| `DB_NAME` | `postgres` |
| `DB_USER` | Supabase Session Pooler user |
| `DB_PASSWORD` | Your Supabase database password |
| `REDIS_URL` | From Upstash (starts with `rediss://`) |
| `RESEND_API_KEY` | From Resend |
| `RESEND_FROM_EMAIL` | e.g. `noreply@yourdomain.com` |
| `CLOUDINARY_URL` | `cloudinary://key:secret@cloudname` |
| `CRON_SECRET` | A long random string — used to authenticate cron-job.org requests |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console *(optional)* |
| `GOOGLE_CLIENT_SECRET` | From Google Cloud Console *(optional)* |
| `GROQ_API_KEY` | From [console.groq.com](https://console.groq.com) *(optional)* |

---

### Step 7 — Scheduled Jobs (cron-job.org)

PlanForge uses [cron-job.org](https://cron-job.org) to trigger scheduled tasks via HTTP. Each job hits a protected endpoint on your app — no separate worker process needed.

Create an account, then add four jobs. For each one:
- **Method:** POST
- **Header:** `X-Cron-Secret: <your CRON_SECRET value>`

| Job | URL | Schedule |
|---|---|---|
| Cleanup activity | `https://yourapp.onrender.com/cron/cleanup-activity/` | `0 5 * * *` |
| Cleanup invites | `https://yourapp.onrender.com/cron/cleanup-invites/` | `0 6 * * *` |
| Daily digest | `https://yourapp.onrender.com/cron/daily-digest/` | `0 7 * * *` |
| Weekly digest | `https://yourapp.onrender.com/cron/weekly-digest/` | `0 8 * * 1` |

All times are UTC.

---

### Step 8 — Google OAuth (optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services → Credentials**.
2. Create an **OAuth 2.0 Client ID** (Web application).
3. Add your Render URL as an **Authorised redirect URI**: `https://yourapp.onrender.com/accounts/google/callback/`
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in your Render environment.

---

## Performance Notes

- **Sessions in Redis** — zero DB writes per page load for authenticated users.
- **`CONN_MAX_AGE=60`** — persistent DB connections; avoids ~5 ms setup cost per request.
- **Notification count cached 30 s per user** — removes one DB query from every authenticated page load.
- **WhiteNoise + `CompressedManifestStaticFilesStorage`** — static files served directly from Gunicorn with gzip + cache-busting hashes; no Nginx needed.
- **ActivityLog composite indexes** on `(organization, -created_at)` and `(project, -created_at)` — the two hottest query patterns.
- **Rate limiting** uses atomic Redis `SETNX + INCR` — correct under concurrent load, no double-counting.
- **`CONN_HEALTH_CHECKS=True`** — stale connections are detected and replaced instead of causing a 500 error.