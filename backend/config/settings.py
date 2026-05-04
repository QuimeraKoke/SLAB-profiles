"""Django settings for SLAB backend."""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR.parent / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "core",
    "exams",
    "dashboards",
    "events",
    "goals",
    "attachments",
    "api",
    "storages",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="slab"),
        "USER": env("POSTGRES_USER", default="slab"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="slab"),
        "HOST": env("POSTGRES_HOST", default="postgres"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# 25 MB cap per upload.
FILE_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

# --- S3 / MinIO storage ---
# `django-storages[s3]` routes Django's default file storage to S3-compatible
# endpoints.
#
# **Local dev** (docker-compose): `.env` sets AWS_S3_ENDPOINT_URL to
# http://minio:9000 + AWS_S3_PUBLIC_ENDPOINT_URL to http://localhost:9000
# + AWS_S3_ADDRESSING_STYLE=path so signed URLs reach the host's MinIO.
#
# **Real AWS S3** (Railway, prod): leave AWS_S3_ENDPOINT_URL,
# AWS_S3_PUBLIC_ENDPOINT_URL, and AWS_S3_ADDRESSING_STYLE unset (or empty).
# The defaults below coerce empty strings to None so boto3 picks the
# canonical AWS endpoint + virtual-host addressing automatically.
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="slab-attachments")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-east-1")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="") or None
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
# `auto` lets boto3 pick virtual-host (real AWS) or path (MinIO/R2) per
# endpoint. Override to "path" only when targeting an S3-compatible service
# that requires it.
AWS_S3_ADDRESSING_STYLE = env("AWS_S3_ADDRESSING_STYLE", default="auto")
AWS_S3_CUSTOM_DOMAIN = None
# Real AWS uses HTTPS; MinIO over HTTP only matters for local dev which
# overrides this in `.env`.
AWS_S3_URL_PROTOCOL = env("AWS_S3_URL_PROTOCOL", default="https:")
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_DEFAULT_ACL = None  # don't ACL public — bucket policy is private
AWS_QUERYSTRING_AUTH = True
AWS_QUERYSTRING_EXPIRE = 300  # signed URLs valid for 5 min
AWS_S3_FILE_OVERWRITE = False

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Public endpoint used when generating signed download URLs so the browser
# can reach the storage backend (not the Docker internal hostname). Real
# AWS / R2 / etc. don't need this — `_public_signed_get_url` falls back to
# the canonical endpoint when it's None.
AWS_S3_PUBLIC_ENDPOINT_URL = env(
    "AWS_S3_PUBLIC_ENDPOINT_URL", default=""
) or None

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:3000", "http://127.0.0.1:3000"],
)
CORS_ALLOW_CREDENTIALS = True

# --- JWT ---
JWT_SECRET = env("JWT_SECRET", default=SECRET_KEY)
JWT_ALGORITHM = env("JWT_ALGORITHM", default="HS256")
JWT_LIFETIME_HOURS = env.int("JWT_LIFETIME_HOURS", default=12)

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://redis:6379/0")
CELERY_TIMEZONE = env("CELERY_TIMEZONE", default="UTC")
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# --- Email ---
# Default in dev: print emails to stdout. Set EMAIL_BACKEND to
# 'django.core.mail.backends.smtp.EmailBackend' (or AWS SES, SendGrid, etc.)
# in production via env vars.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="alerts@s-lab.cl",
)

# Frontend origin used to build "open in app" links in alert emails.
FRONTEND_BASE_URL = env(
    "FRONTEND_BASE_URL", default="http://localhost:3000",
)
