# Production settings.
# All secrets must come from environment variables — never hardcode them here.

from .base import *

# SECURITY WARNING: don't run with debug turned on in production!

DEBUG = False

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")

# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST"),
        "PORT": os.getenv("DB_PORT", "5432"),
        # Connection pooling
        # Without CONN_MAX_AGE, Django opens a fresh PostgreSQL connection on
        # every single request (default = 0). Each connection costs ~5 ms setup
        # time and ~5 MB RAM on the Postgres server. At 10k users Postgres hits
        # max_connections (default: 100) and starts refusing connections entirely.
        #
        # CONN_MAX_AGE=60 keeps each Gunicorn worker's connection alive for 60
        # seconds of inactivity, reusing it across requests instead of tearing
        # it down. Effective connection count = workers × DB replicas, not RPS.
        #
        # CONN_HEALTH_CHECKS=True pings the connection before reuse so stale
        # connections (killed by Postgres idle timeout or a network blip) are
        # detected and replaced rather than causing a 500 error.
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}

CACHES = {
    "default": {
        "BACKEND":  "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/1"),
        "OPTIONS": {
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        },
    }
}

# Sessions → Redis
# Django's default session backend writes every logged-in page request to the
# django_session DB table. At 10k concurrent users this creates punishing write
# contention on a table that grows unbounded without manual clearsessions runs.
#
# Switching to the cache backend stores sessions in Redis instead:
#   - Zero DB writes for session reads/writes on normal page loads
#   - Automatic expiry (no manual clearsessions needed)
#   - Sessions share the Redis instance already used for rate limiting & cache
#
# CONN_MAX_AGE on the DB config (see below) handles the remaining DB connections.
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"


# Email via Resend
# Render blocks outbound SMTP (port 587/465), so we use Resend's HTTP API
# instead. No SMTP connection needed — just an HTTPS POST to api.resend.com.
#
# Setup:
#   1. Create a free account at https://resend.com
#   2. Add + verify your sending domain under Domains
#   3. Generate an API key under API Keys (send-only scope is fine)
#   4. Set RESEND_API_KEY and RESEND_FROM_EMAIL as env vars on Render
#
# core/utils.py detects RESEND_API_KEY and calls the Resend API directly,
# bypassing Django's email backend entirely for all production sends.
RESEND_API_KEY = os.getenv('RESEND_API_KEY', '')
DEFAULT_FROM_EMAIL = os.getenv('RESEND_FROM_EMAIL', 'noreply@yourdomain.com')

# Safe fallback — never used in prod as long as RESEND_API_KEY is set,
# but keeps Django from raising ImproperlyConfigured if the key is missing.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Security headers — enable when you have HTTPS
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True  # allows submission to browser HSTS preload lists

# Trusted proxy (rate limiting)
#
# Uncomment the block below ONLY after confirming ALL of the following:
#   1. Django sits behind a reverse proxy (Nginx, Cloudflare, AWS ALB, etc.)
#   2. The proxy ALWAYS sets/overwrites X-Forwarded-For before it reaches Django.
#   3. The proxy ALWAYS sets/overwrites X-Forwarded-Proto before it reaches Django.
#
# Without condition 2 and 3, clients can spoof these headers and:
#   - bypass IP-based rate limits (by forging X-Forwarded-For)
#   - bypass SECURE_SSL_REDIRECT (by forging X-Forwarded-Proto)
#
# Set NUM_PROXIES to the number of trusted proxy hops in your chain
# (usually 1 for a single Nginx/ALB in front of Gunicorn).
#
# UNCOMMENT TO ACTIVATE:
# USE_X_FORWARDED_HOST    = True
# SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# NUM_PROXIES             = 1

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {message}",
            "style":  "{",
        },
    },
    "handlers": {
        "console": {
            "class":     "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level":    "INFO",
    },
    "loggers": {
        "django": {
            "handlers":  ["console"],
            "level":     "WARNING",
            "propagate": False,
        },
        "django.security": {
            "handlers":  ["console"],
            "level":     "ERROR",
            "propagate": False,
        },
    },
}