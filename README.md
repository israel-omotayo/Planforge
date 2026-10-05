# PlanForge

PlanForge is a Django project management app for small teams. It supports organizations, projects, tasks, file attachments, comments, activity feeds, email digests, and optional AI-assisted task generation.

Live demo: [planforge.coreapp.name.ng](https://planforge.coreapp.name.ng)

Render's free tier may take a few seconds to wake up after the app has been idle.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 6, Python 3.12 |
| Database | PostgreSQL on Supabase |
| Cache and sessions | Redis on Upstash |
| Frontend | Django templates, DM Sans, Lora, PWA |
| Auth | Email verification, Google OAuth |
| File storage | Cloudinary |
| Email | Resend HTTP API |
| Rate limiting | Redis |
| Hosting | Render |

## Architecture

The app keeps most request handling thin:

1. A view reads the request and calls a service.
2. DTOs in `schemas.py` validate and type the incoming data.
3. Service modules handle business rules.
4. Models handle persistence.
5. Decorators check organization, project, and role access before protected views run.
6. Context processors add the active organization and unread notification count to templates.

This keeps permission checks, validation, and database work out of templates and away from view functions where possible.

## Features

### Auth

- Email registration with a 6-digit verification code
- 10-minute verification expiry and 5-attempt lockout
- Login rate limiting by IP and username
- Google OAuth with CSRF state checking and open redirect protection
- Password reset through Resend
- Email change with re-verification
- Account deletion

### Organizations

- Multiple organizations per user
- Session-based active organization context
- Member invites by username
- Shareable invite links with approval
- Owner, admin, and member roles
- Ownership transfer

### Projects

- Create, read, update, and delete projects
- Project statuses: active, on hold, completed, archived
- Cover image uploads through Cloudinary
- Budget tracking with currency support

### Tasks

- Create, edit, delete, and toggle task status
- Priorities, due dates, and assignees
- File attachments through Cloudinary
- 10 MB attachment limit with a type whitelist
- Comments
- Optional task generation through Groq

### Other

- Organization and project activity feeds
- Analytics dashboard with Chart.js
- Daily urgent and weekly summary email digests
- Scheduled digest and cleanup jobs through cron-job.org
- Installable PWA with offline fallback
- Guest access for external project collaborators

## Project Structure

```text
planforge/
|-- core/                    # Rate limiting, email utilities, dashboard
|-- accounts/                # Registration, login, Google OAuth, profile
|-- organizations/           # Organizations, memberships, RBAC, notifications
|-- projects/                # Projects, tasks, attachments, comments, activity
|-- tests/                   # Smoke and functional tests
|-- templates/               # HTML templates
|-- static/                  # CSS, JavaScript, PWA assets
`-- planforge/
    `-- settings/
        |-- base.py          # Shared settings
        |-- dev.py           # Local development
        `-- prod.py          # Production settings
```

## Local Setup

Clone the repo and install the Python dependencies:

```bash
git clone https://github.com/israel-omotayo/Planforge.git
cd Planforge/planforge
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate the virtual environment with:

```powershell
.venv\Scripts\activate
```

Create a `.env` file in the project root:

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

# Optional in local development
RESEND_API_KEY=
RESEND_FROM_EMAIL=
CLOUDINARY_URL=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
CRON_SECRET=
```

Run the database migrations, create an admin user, and start the server:

```bash
python manage.py migrate --settings=planforge.settings.dev
python manage.py createsuperuser --settings=planforge.settings.dev
python manage.py runserver --settings=planforge.settings.dev
```

## Running Tests

Run the full test suite:

```bash
python manage.py test tests --settings=planforge.settings.dev
```

Run one test class:

```bash
python manage.py test tests.test_smoke.TaskTest --settings=planforge.settings.dev
```

Run with verbose output:

```bash
python manage.py test tests -v 2 --settings=planforge.settings.dev
```

## Deploying to Render

PlanForge uses Render for the web service, Supabase for PostgreSQL, Upstash for Redis, Resend for email, and Cloudinary for uploads.

### Required Services

| Service | Used for |
|---|---|
| [Supabase](https://supabase.com) | PostgreSQL database |
| [Upstash](https://upstash.com) | Redis sessions, cache, and rate limiting |
| [Resend](https://resend.com) | Transactional email |
| [Cloudinary](https://cloudinary.com) | File storage |
| [Google Cloud Console](https://console.cloud.google.com) | Optional Google OAuth credentials |
| [Groq](https://console.groq.com) | Optional task generation |

### Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. Open the database connection settings.
3. Use the Session Pooler connection string. Django can run into prepared statement issues with the Transaction Pooler.
4. Save these values:
   - `DB_HOST`: `aws-0-<region>.pooler.supabase.com`
   - `DB_USER`: `postgres.<project-ref>`
   - `DB_PASSWORD`: your database password
   - `DB_PORT`: `5432`

### Upstash

1. Create a Redis database at [upstash.com](https://upstash.com).
2. Pick a region close to your Render service.
3. Copy the Redis URL. It should start with `rediss://`.

### Resend

1. Create an account at [resend.com](https://resend.com).
2. Add and verify your sending domain.
3. Create an API key. A send-only key is enough.

Render blocks outbound SMTP ports on its free tier, so PlanForge sends mail through the Resend HTTP API in `core/utils.py`.

### Cloudinary

1. Create an account at [cloudinary.com](https://cloudinary.com).
2. Copy the Cloudinary URL from the dashboard.

The value should look like this:

```text
cloudinary://API_KEY:API_SECRET@CLOUD_NAME
```

### Render Web Service

1. Create a new web service in Render and connect the GitHub repo.
2. Set the runtime to Python.
3. Use this build command:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate
```

4. Use this start command:

```bash
gunicorn planforge.wsgi:application --workers 1 --timeout 120 --bind 0.0.0.0:$PORT
```

Keep the worker count at `1` on Render's free tier. The 512 MB memory limit is tight for multiple workers.

### Environment Variables

| Variable | Value |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `planforge.settings.prod` |
| `SECRET_KEY` | Strong random string |
| `ALLOWED_HOSTS` | `yourapp.onrender.com` plus any custom domain |
| `RENDER_EXTERNAL_HOSTNAME` | `yourapp.onrender.com` |
| `BASE_FRONTEND_URL` | `yourapp.onrender.com` or your custom domain |
| `DB_HOST` | Supabase Session Pooler host |
| `DB_PORT` | `5432` |
| `DB_NAME` | `postgres` |
| `DB_USER` | Supabase Session Pooler user |
| `DB_PASSWORD` | Supabase database password |
| `REDIS_URL` | Upstash Redis URL |
| `RESEND_API_KEY` | Resend API key |
| `RESEND_FROM_EMAIL` | For example, `noreply@yourdomain.com` |
| `CLOUDINARY_URL` | Cloudinary URL |
| `CRON_SECRET` | Long random string for scheduled job endpoints |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID, optional |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret, optional |
| `GROQ_API_KEY` | Groq API key, optional |
| `GROQ_MODEL` | Groq model name, defaults to `openai/gpt-oss-120b` |

### Scheduled Jobs

PlanForge uses [cron-job.org](https://cron-job.org) to call protected HTTP endpoints for cleanup and digest jobs. Each request must be a `POST` and include this header:

```text
X-Cron-Secret: <your CRON_SECRET value>
```

Create these jobs:

| Job | URL | Schedule |
|---|---|---|
| Deactivate old activity | `https://yourapp.onrender.com/cron/cleanup-activity/` | `0 5 * * *` |
| Cleanup invites | `https://yourapp.onrender.com/cron/cleanup-invites/` | `0 6 * * *` |
| Daily digest | `https://yourapp.onrender.com/cron/daily-digest/` | `0 7 * * *` |
| Weekly digest | `https://yourapp.onrender.com/cron/weekly-digest/` | `0 8 * * 1` |

Schedules are in UTC.

### Google OAuth

1. Open [Google Cloud Console](https://console.cloud.google.com).
2. Go to APIs and Services, then Credentials.
3. Create an OAuth 2.0 Client ID for a web application.
4. Add this authorized redirect URI:

```text
https://yourapp.onrender.com/accounts/google/callback/
```

5. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Render.

## Performance Notes

- Sessions are stored in Redis to avoid database writes on every authenticated page load.
- `CONN_MAX_AGE=60` keeps database connections open between requests.
- Notification counts are cached for 30 seconds per user.
- WhiteNoise serves static files through Gunicorn with gzip and cache-busting hashes.
- `ActivityLog` has composite indexes for organization and project activity pages.
- Rate limiting uses Redis atomic operations.
- `CONN_HEALTH_CHECKS=True` lets Django replace stale database connections before they cause request failures.
