# Planforge

A production-ready Django SaaS — project management for small teams.

Built to demonstrate real backend architecture: service layer pattern, multi-tenancy, RBAC, and a deployment setup that holds up past the first 100 users.

**Live demo:** [planforge.onrender.com](https://planforge.onrender.com) *(Render Free — first load may take ~10s)*

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6, Python 3.12 |
| Database | PostgreSQL (Supabase) |
| Cache / Sessions | Redis (Upstash free tier) |
| Frontend | Django Templates, DM Sans + Lora, PWA |
| Auth | Custom email verification + Google OAuth |
| File storage | Cloudinary |
| Email | Resend HTTP API |
| Rate limiting | Redis-backed atomic counter |
| Hosting | Render Free (web) + Render Cron Jobs |

---

## Architecture

```
Request → View → DTO (schemas.py) → Service → Model → DB
```

- **Views** — thin. Read the request, call a service, return a response. No business logic.
- **DTOs** (`schemas.py`) — validate and type-annotate data before it reaches services.
- **Services** — all business logic lives here. Never touch `request`. Fully unit-testable.
- **Decorators** — enforce org-level and project-level permissions before the view runs.
- **Context processors** — inject active org + unread count into every template (cached 30s per user).

This pattern was chosen deliberately. Django's default is to put everything in views — that works at tutorial scale but creates untestable spaghetti as the app grows. The service layer means every mutation (create org, invite member, change role) can be tested without spinning up HTTP.

---

## Features

**Auth**
- Register with email verification (6-digit code, 10-minute expiry, 5-attempt lockout)
- Login with rate limiting (10 attempts/min per IP + username)
- Google OAuth — full redirect flow, CSRF state token, open redirect protection
- Password reset (Django built-in, customised to use Resend instead of SMTP)
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
- File attachments (Cloudinary, 10MB limit, type whitelist)
- Comments
- AI task generation (Groq)

**Other**
- Activity feed (org-wide and per-project)
- Analytics dashboard (Chart.js)
- Email digests (daily urgent / weekly summary) via Render Cron Jobs
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
git clone <repo>
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

### Prerequisites (all free tier)

| Service | Purpose | Time to set up |
|---|---|---|
| [Render](https://render.com) | Web hosting + Cron Jobs + PostgreSQL | — |
| [Upstash](https://upstash.com) | Redis (sessions, cache, rate limiting) | 5 min |
| [Resend](https://resend.com) | Transactional email | 10 min |
| [Cloudinary](https://cloudinary.com) | File storage | 5 min |
| [Google Cloud Console](https://console.cloud.google.com) | OAuth credentials | 15 min (optional) |

### Step 1 — Redis (Upstash)

1. Create a free account at upstash.com
2. Create a Redis database → select the region closest to Render's US East servers
3. Copy the **Redis URL** (starts with `rediss://`)

### Step 2 — Email (Resend)

1. Create a free account at resend.com
2. Add and verify your sending domain under **Domains**
3. Generate an API key under **API Keys** (send-only scope)
4. Note your `from` address, e.g. `noreply@yourdomain.com`

### Step 3 — File storage (Cloudinary)

1. Create a free account at cloudinary.com
2. From the dashboard copy your **Cloudinary URL**: `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`

### Step 4 — Deploy to Render

**Option A — Blueprint (one click):**

Push this repo to GitHub. In Render, click **New → Blueprint** and point it at the repo. Render reads `render.yaml` and creates the web service, PostgreSQL database, and all four Cron Jobs automatically.

**Option B — Manual:**

1. Render → **New Web Service** → connect your GitHub repo
2. Set **Build Command**: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
3. Set **Start Command**: `gunicorn planforge.wsgi:application --workers 3 --timeout 120`
4. Set **Environment Variables** (see table below)

### Step 5 — Environment Variables

Set these in Render → your service → **Environment**:

| Variable | Value |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `planforge.settings.prod` |
| `SECRET_KEY` | Generate a strong random string |
| `ALLOWED_HOSTS` | `yourapp.onrender.com` (your Render URL) |
| `RENDER_EXTERNAL_HOSTNAME` | `yourapp.onrender.com` |
| `REDIS_URL` | From Upstash |
| `RESEND_API_KEY` | From Resend |
| `RESEND_FROM_EMAIL` | e.g. `noreply@yourdomain.com` |
| `CLOUDINARY_URL` | From Cloudinary |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console (optional) |
| `GOOGLE_CLIENT_SECRET` | From Google Cloud Console (optional) |
| `GROQ_API_KEY` | From Groq (optional — AI task generation) |

### Step 6 — UptimeRobot (keep the free tier awake)

Render Free sleeps after 15 minutes of inactivity. Add a free monitor at [uptimerobot.com](https://uptimerobot.com):

- Monitor type: **HTTP(s)**
- URL: `https://yourapp.onrender.com/` 
- Interval: **5 minutes**

### Step 7 — Cron Jobs (if using manual deploy)

In Render → your project → **New Cron Job**, add these four:

| Name | Schedule | Command |
|---|---|---|
| Cleanup activity | `0 5 * * *` | `python manage.py cleanup_activity --days=30` |
| Cleanup invites | `0 6 * * *` | `python manage.py cleanup_invites` |
| Daily digest | `0 7 * * *` | `python manage.py send_digest --frequency=daily` |
| Weekly digest | `0 8 * * 1` | `python manage.py send_digest --frequency=weekly` |

---

## Performance Notes (5k users)

- **Sessions in Redis** — zero DB writes per page load for authenticated users
- **CONN_MAX_AGE=60** — persistent DB connections, avoids ~5ms setup cost per request
- **Notification count cached 30s per user** — removes one DB query from every authenticated page load
- **WhiteNoise with CompressedManifestStaticFilesStorage** — static files served directly from Gunicorn with gzip + cache-busting hashes, no Nginx needed
- **ActivityLog composite indexes** on `(organization, -created_at)` and `(project, -created_at)` — the two hottest query patterns
- **Rate limiting** uses atomic Redis SETNX + INCR — correct under concurrent load, no double-counting
-