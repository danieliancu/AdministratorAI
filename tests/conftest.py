import psycopg
import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test.utils import setup_databases, teardown_databases

from apps.core.db import manifest


def _owner_dsn():
    db = settings.DATABASES["default"]
    return {
        "host": db["HOST"],
        "port": db["PORT"],
        "dbname": db["NAME"],
        "user": _owner_credentials["user"],
        "password": _owner_credentials["password"],
    }


_owner_credentials = {}


@pytest.fixture(scope="session")
def django_db_setup(django_test_environment, django_db_blocker):
    """Create the database as the owner, then run every test as the restricted role.

    Without this demotion the isolation tests would pass even with RLS broken,
    because a table owner or superuser can see everything.
    """
    db = settings.DATABASES["default"]
    _owner_credentials.update(user=db["USER"], password=db["PASSWORD"])
    with django_db_blocker.unblock():
        old_config = setup_databases(verbosity=0, interactive=False)
        connection.close()
        for settings_dict in (db, connection.settings_dict):
            settings_dict["USER"] = settings.AAI_TEST_APP_USER
            settings_dict["PASSWORD"] = settings.AAI_TEST_APP_PASSWORD
        settings.AAI_DB_ROLE_GUARD = True
    yield
    with django_db_blocker.unblock():
        connection.close()
        settings.AAI_DB_ROLE_GUARD = False
        for settings_dict in (db, connection.settings_dict):
            settings_dict["USER"] = _owner_credentials["user"]
            settings_dict["PASSWORD"] = _owner_credentials["password"]
        teardown_databases(old_config, verbosity=0)


@pytest.fixture
def owner_connection(django_db_setup):
    """Separate owner connection, for catalog checks and for proving what RLS hides."""
    conn = psycopg.connect(**_owner_dsn())
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def committed_db(django_db_setup, django_db_blocker):
    """Real commits and autocommit, for what TestCase's wrapping transaction would hide."""
    with django_db_blocker.unblock():
        yield
        connection.close()
    with psycopg.connect(**_owner_dsn()) as conn:
        tables = ", ".join(sorted(manifest.RLS_TABLES))
        conn.execute(f"TRUNCATE {tables} CASCADE")


@pytest.fixture(autouse=True)
def _clear_throttles():
    cache.clear()
    yield
