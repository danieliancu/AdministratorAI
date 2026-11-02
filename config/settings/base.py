import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name, default=None):
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Missing environment variable {name}")
    return value


SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.accounts",
    "apps.tenants",
    "apps.audit",
    "apps.platform_admin",
]

# DbScopeMiddleware must stay last: it answers from process_view, which skips
# any process_view hook after it. A system check enforces this.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.DbScopeMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env("DB_HOST", "db"),
        "PORT": env("DB_PORT", "5432"),
        "NAME": env("DB_NAME", "administrator_ai"),
        "USER": env("DB_USER", "aai_app"),
        "PASSWORD": env("DB_PASSWORD"),
        # Tenant context is opened by an explicit scope, not around the view callable:
        # ATOMIC_REQUESTS would leave TemplateResponse rendering outside the transaction.
        "ATOMIC_REQUESTS": False,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,
        # Server-side cursors do not survive PgBouncer transaction pooling.
        "DISABLE_SERVER_SIDE_CURSORS": True,
        "OPTIONS": {"prepare_threshold": None},
    },
}

# Refuse to serve through a role that could bypass row-level security, and
# refuse queries that run outside a db_scope.
AAI_DB_ROLE_GUARD = True

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.ScopedBackend"]
LOGIN_URL = "public:login"
LOGIN_REDIRECT_URL = "account:tenant-list"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_REDIS_URL", "redis://redis:6379/1"),
    },
}

LANGUAGE_CODE = "ro"
TIME_ZONE = "Europe/Bucharest"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAILERS = {
    "default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"},
}
DEFAULT_FROM_EMAIL = "Administrator AI <no-reply@administrator-ai.local>"

CELERY_BROKER_URL = env("REDIS_URL", "redis://redis:6379/0")
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# Only config.settings.dev may enable the seed command with its weak known password.
AAI_ALLOW_DEV_SEED = False

# Platform staff pages use this role only: masked views and audited functions, no tables.
DATABASES["platform"] = {
    **DATABASES["default"],
    "USER": "aai_platform",
    "PASSWORD": env("AAI_PLATFORM_DB_PASSWORD", ""),
}
DATABASE_ROUTERS = ["apps.core.db.router.PlatformRouter"]

CELERY_BEAT_SCHEDULE = {
    "clear-expired-sessions": {
        "task": "accounts.clear_expired_sessions",
        "schedule": 24 * 60 * 60,
    },
}
