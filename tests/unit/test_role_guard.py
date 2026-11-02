from apps.core.db.guard import role_violations


def test_restricted_role_has_no_violations():
    assert role_violations((False, False, False, False, False, False, False)) == []


def test_each_unsafe_fact_is_reported():
    assert role_violations((True, False, False, False, False, False, False)) == ["superuser"]
    assert role_violations((False, True, False, False, True, False, False)) == [
        "bypassrls",
        "owns relations",
    ]
    assert role_violations((False, False, False, False, False, False, True)) == ["owns database"]
