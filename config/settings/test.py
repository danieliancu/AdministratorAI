from .base import *  # noqa: F403
from .base import env

ALLOWED_HOSTS = ["testserver"]

# The owner creates and migrates the test database. tests/conftest.py then demotes
# the connection to aai_app and turns this guard on for the test run.
AAI_DB_ROLE_GUARD = False
AAI_TEST_APP_USER = "aai_app"
AAI_TEST_APP_PASSWORD = env("AAI_APP_PASSWORD")

# A second connection to the same test database, as the restricted platform role.
DATABASES["platform"]["TEST"] = {"MIRROR": "default"}  # noqa: F405

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_REDIS_URL", "redis://redis:6379/2"),
    },
}

AAI_ALLOW_FAKE_AI = True
DATABASES["legal"]["TEST"] = {"MIRROR": "default"}  # noqa: F405
LEGAL_OBJECT_ROOT = "/tmp/test-legal-objects"  # noqa: S108
