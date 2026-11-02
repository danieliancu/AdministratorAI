from .services import _rows


def sources():
    return _rows("SELECT * FROM platform.legal_sources ORDER BY name")


def changes(status=None):
    if status:
        return _rows(
            "SELECT * FROM platform.legal_changes WHERE status = %s ORDER BY created_at DESC"
            " LIMIT 500",
            [status],
        )
    return _rows("SELECT * FROM platform.legal_changes ORDER BY created_at DESC LIMIT 500")


def corpus():
    return _rows("SELECT * FROM platform.legal_corpus")[0]


def platform_budget():
    return _rows("SELECT * FROM platform.ai_platform_budget ORDER BY period_start DESC LIMIT 1")


def set_source_enabled(actor_id, key, enabled, reason):
    _rows(
        "SELECT platform.set_legal_source_enabled(%s::uuid, %s, %s, %s) AS done",
        [actor_id, key, enabled, reason],
    )


def review_change(actor_id, change_id, decision, note):
    _rows(
        "SELECT platform.review_legal_change(%s::uuid, %s::uuid, %s, %s) AS done",
        [actor_id, change_id, decision, note],
    )
