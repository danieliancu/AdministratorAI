"""Row-level security through PgBouncer in transaction mode, on one shared server backend.

Run by the `pgbouncer-smoke` Compose service against the development database. A session-level
setting would leak between these transactions, so this fails if scope state ever does.
"""

import os
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from django.db import connection  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.core.db.scope import db_scope  # noqa: E402
from apps.tenants.models import TenantMembership  # noqa: E402


def backend():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


def main():
    with db_scope(lookup_email="admin"):
        admin = User.objects.get(email="admin")
    with db_scope(user_id=admin.pk):
        tenant_id = TenantMembership.objects.values_list("tenant_id", flat=True).first()
    assert tenant_id, "Run seed_dev first"

    pids = set()
    for _ in range(50):
        with db_scope(tenant_id=tenant_id, user_id=admin.pk):
            pids.add(backend())
            assert TenantMembership.objects.count() == 1
        with db_scope():
            pids.add(backend())
            assert TenantMembership.objects.count() == 0
        with db_scope(tenant_id=uuid.uuid4()):
            pids.add(backend())
            assert TenantMembership.objects.count() == 0

    assert len(pids) == 1, f"Expected one shared backend, saw {pids}"
    print(f"OK: 150 alternating transactions on backend {pids.pop()}, no context carried over")


if __name__ == "__main__":
    main()
