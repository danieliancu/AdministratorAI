from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "web"]

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {"host": env("MAIL_HOST", "mailpit"), "port": 1025},
    },
}

AAI_ALLOW_DEV_SEED = True

AAI_ALLOW_FAKE_AI = True
