from django.db import connections


def _rows(sql, params=None):
    with connections["platform"].cursor() as cursor:
        cursor.execute(sql, params or [])
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def counts():
    return _rows("SELECT * FROM platform.counts")[0]


def tenants(search=""):
    return _rows(
        "SELECT * FROM platform.tenant_overview WHERE name ILIKE %s ORDER BY created_at DESC",
        [f"%{search}%"],
    )


def users():
    return _rows("SELECT * FROM platform.user_overview ORDER BY created_at DESC")


def audit_log():
    return _rows("SELECT * FROM platform.audit_log ORDER BY occurred_at DESC LIMIT 500")


def create_tenant(actor_id, *, name, owner_login, reason):
    return _rows(
        "SELECT platform.create_tenant(%s::uuid, %s, %s, %s) AS id",
        [actor_id, name, owner_login, reason],
    )[0]["id"]


def set_tenant_status(actor_id, tenant_id, status, reason):
    _rows(
        "SELECT platform.set_tenant_status(%s::uuid, %s::uuid, %s, %s) AS done",
        [actor_id, tenant_id, status, reason],
    )
