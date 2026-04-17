# Development settings — never use in production.

from .base import *

DEBUG = True

ALLOWED_HOSTS = ["127.0.0.1", "localhost", ".ngrok.app", ".ngrok-free.dev",]

CSRF_TRUSTED_ORIGINS = ["https://*.ngrok.app", "https://*.ngrok-free.dev",]

# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# Emails print to terminal in dev — no SMTP setup needed
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Django debug toolbar can be added here later if needed