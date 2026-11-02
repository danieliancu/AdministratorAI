from .base import *  # noqa: F403

ALLOWED_HOSTS = ["testserver"]

# The owner creates and migrates the test database. Increment 2 demotes the
# connection to aai_app and turns this guard back on for the test run.
AAI_DB_ROLE_GUARD = False
