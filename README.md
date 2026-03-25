# Planforge

A portfolio-grade Django SaaS project — project management for focused teams.

## Tech Stack

| Layer       | Technology                        |
|-------------|-----------------------------------|
| Backend     | Django 6                          |
| Database    | PostgreSQL                        |
| Frontend    | Django Templates + Tailwind CSS   |
| Auth        | Custom — email verification flow  |
| Rate limiting | Django cache (in-memory / DB)   |

## Features

- **Authentication** — register, email verification, login, logout, password reset, email change, account deletion
- **Organizations** — create, rename, delete, switch between orgs
- **Memberships** — invite members by username, assign roles (owner / admin / member), remove members
- **Projects** — create, view, edit, delete projects within an organization
- **Role-based access** — decorators enforce permissions at the view level
- **Session-based org context** — active organization persists across pages

## Architecture
```
Request → View → Form (validation) → DTO → Service → Model → DB
```

- **Views** read the request and return a response — no business logic
- **Forms** validate the shape of input data
- **DTOs** (`schemas.py`) clean and type data before it reaches services
- **Services** contain all business logic — never touch `request`
- **Decorators** enforce org-level access control

## Project Structure
```
planforge/
├── core/               # Shared utilities: rate limiter, email, helpers
├── accounts/           # Auth: register, login, profile, password reset
├── organizations/      # Orgs, memberships, role checks, org switching
├── projects/           # Project CRUD
├── templates/          # Project-level templates
└── planforge/
    └── settings/
        ├── base.py     # Shared settings
        ├── dev.py      # Development
        └── prod.py     # Production
```

## Local Setup
```bash
git clone <repo>
cd planforge
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:
```ini
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
DB_NAME=planforge_db
DB_USER=planforge_user
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
DEFAULT_FROM_EMAIL=noreply@planforge.dev
```
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## What's next

- AI-powered project planning features
- Blueprint / chat interface
- Advanced dashboards
- Deployment (Render / Railway)
```

---

# Final Checkpoint — test everything
```
1.  /                         → landing page renders with features + CTA
2.  /accounts/register/       → register a new user
3.  /accounts/verify/         → verify with code from terminal
4.  /accounts/login/          → form-based, rate limited
5.  /dashboard/               → redirects to org create if no org
6.  Create org                → redirects to org settings
7.  /dashboard/               → shows org name, projects, member count
8.  /accounts/password/reset/ → full flow works end to end
9.  /accounts/profile/        → change password page is styled
10. /accounts/account/delete/ → styled danger page, works
11. Org switcher in navbar     → hover dropdown, switch works
12. python manage.py check    → 0 errors, 0 warnings
```

---

## Final project structure
```
planforge/
│
├── core/
│   ├── ratelimit.py
│   ├── utils.py
│   ├── urls.py
│   └── views.py            ← home + dashboard
│
├── accounts/
│   ├── templates/accounts/ ← all auth templates styled
│   ├── models.py
│   ├── schemas.py
│   ├── services.py
│   ├── forms.py
│   ├── views.py
│   └── urls.py
│
├── organizations/
│   ├── models.py
│   ├── schemas.py
│   ├── services.py
│   ├── decorators.py
│   ├── context_processors.py
│   ├── forms.py
│   ├── views.py
│   └── urls.py
│
├── projects/
│   ├── models.py
│   ├── forms.py
│   ├── views.py
│   └── urls.py
│
├── templates/
│   ├── base.html
│   ├── home.html           ← NEW
│   ├── dashboard.html
│   ├── organizations/
│   └── projects/
│
├── planforge/
│   ├── settings/           ← NEW
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── .env
├── .gitignore
├── requirements.txt
└── README.md               ← NEW