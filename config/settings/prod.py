from .base import *  # noqa: F403
from .base import env

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS").split(",")

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": env("MAIL_HOST"),
            "port": int(env("MAIL_PORT", "587")),
            "username": env("MAIL_USERNAME", ""),
            "password": env("MAIL_PASSWORD", ""),
            "use_tls": True,
        },
    },
}
