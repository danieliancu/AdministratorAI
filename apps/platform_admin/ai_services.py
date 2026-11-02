import json

from .services import _rows


def tenant_usage():
    return _rows(
        """SELECT u.*, a.highest_threshold
           FROM platform.ai_tenant_usage u
           LEFT JOIN platform.ai_alerts a ON a.tenant_id = u.tenant_id
           ORDER BY u.spent DESC, u.tenant_name"""
    )


def tenant_usage_one(tenant_id):
    rows = _rows("SELECT * FROM platform.ai_tenant_usage WHERE tenant_id = %s", [tenant_id])
    return rows[0] if rows else None


def usd_ron_rate():
    rows = _rows("SELECT * FROM platform.ai_usd_ron_rate")
    return rows[0] if rows else None


def cost_breakdown():
    return _rows(
        "SELECT * FROM platform.ai_cost_breakdown ORDER BY month DESC, cost DESC LIMIT 500"
    )


def uncertain_reservations():
    return _rows("SELECT * FROM platform.ai_uncertain_reservations ORDER BY created_at")


def reconciliations():
    return _rows("SELECT * FROM platform.ai_reconciliations ORDER BY period_start DESC LIMIT 50")


def catalog():
    rows = _rows("SELECT kind, key FROM platform.ai_catalog ORDER BY key")
    return {
        "models": [r["key"] for r in rows if r["kind"] == "model"],
        "operations": [r["key"] for r in rows if r["kind"] == "operation"],
    }


def set_policy(actor_id, tenant_id, *, reason, **fields):
    _rows(
        "SELECT platform.set_ai_policy(%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s::jsonb, %s::jsonb, %s) AS done",
        [
            actor_id,
            tenant_id,
            fields["monthly_limit"],
            fields["overage_authorised"],
            fields["overage_limit"],
            fields["max_cost_per_request"],
            fields["max_output_tokens"],
            fields["user_daily_limit"],
            fields["user_monthly_limit"],
            fields["requests_per_minute"],
            fields["billing_anchor_day"],
            json.dumps(fields["allowed_models"]),
            json.dumps(fields["allowed_operations"]),
            reason,
        ],
    )


def resolve_reservation(actor_id, reservation_id, actual, reason):
    _rows(
        "SELECT platform.resolve_ai_reservation(%s::uuid, %s::uuid, %s, %s) AS done",
        [actor_id, reservation_id, actual, reason],
    )


def record_reconciliation(actor_id, *, provider, start, end, reported, currency, note):
    return _rows(
        "SELECT platform.record_ai_reconciliation(%s::uuid, %s, %s, %s, %s, %s, %s) AS calculated",
        [actor_id, provider, start, end, reported, currency, note],
    )[0]["calculated"]
