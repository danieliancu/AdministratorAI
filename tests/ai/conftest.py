import json
import uuid
from decimal import Decimal

import psycopg
import pytest

from apps.ai_gateway.providers.base import ProviderAdapter, ProviderResult
from apps.tenants.models import TenantMembership
from apps.tenants.roles import Role
from tests.conftest import _owner_dsn
from tests.factories import make_tenant, make_user

MODEL = "test:small"
OP = "test.op"
SCHEMA_OP = "test.schema"
CACHED_OP = "test.cached"
UNPRICED_OP = "test.unpriced"
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


@pytest.fixture(scope="session")
def ai_catalog(django_db_setup):
    """The global catalog is written with owner credentials, as in production."""
    with psycopg.connect(**_owner_dsn()) as conn:
        conn.execute(
            "INSERT INTO ai_gateway_aiprovider (key, name, is_active) VALUES ('test', 'Test', true)"
        )
        for key, provider_name in ((MODEL, "small"), ("test:unpriced", "unpriced")):
            conn.execute(
                "INSERT INTO ai_gateway_aimodel (key, provider_id, provider_model_name, is_active)"
                " VALUES (%s, 'test', %s, true)",
                [key, provider_name],
            )
        conn.execute(
            """INSERT INTO ai_gateway_aimodelpricing
               (id, model_id, effective_from, currency, input_per_mtok, cached_read_per_mtok,
                cache_write_30m_per_mtok, cache_write_12h_per_mtok, output_per_mtok,
                source_url, created_at)
               VALUES (gen_random_uuid(), %s, now() - interval '1 year', 'USD',
                       1, 0.1, 1.25, 2.5, 4, 'test', now())""",
            [MODEL],
        )
        operations = [
            (OP, MODEL, None, False, 0),
            (SCHEMA_OP, MODEL, json.dumps(SCHEMA), False, 0),
            (CACHED_OP, MODEL, None, True, 3600),
            (UNPRICED_OP, "test:unpriced", None, False, 0),
        ]
        for key, model, schema, cacheable, ttl in operations:
            conn.execute(
                """INSERT INTO ai_gateway_aioperation
                   (key, name, default_model_id, capability, allowed_variables, max_input_bytes,
                    max_output_tokens, output_schema, cacheable, cache_ttl_seconds, is_active)
                   VALUES (%s, %s, %s, 'use_ai', '["note"]', 2000, 100, %s, %s, %s, true)""",
                [key, key, model, schema, cacheable, ttl],
            )
            conn.execute(
                """INSERT INTO ai_gateway_prompttemplateversion
                   (id, operation_id, version, system_template, user_template, is_active,
                    created_at)
                   VALUES (gen_random_uuid(), %s, 1, 'SYSTEM', 'Date: $note', true, now())""",
                [key],
            )


@pytest.fixture
def set_policy(owner_connection):
    """Writes a policy directly as the owner, in that tenant's context."""

    def write(tenant, **overrides):
        values = {
            "monthly_limit": Decimal("1"),
            "overage_authorised": False,
            "overage_limit": Decimal("0"),
            "max_cost_per_request": Decimal("1"),
            "max_output_tokens": 100,
            "user_daily_limit": None,
            "user_monthly_limit": None,
            "requests_per_minute": 100000,
            "billing_anchor_day": 1,
            "allowed_models": [MODEL, "test:unpriced"],
            "allowed_operations": [OP, SCHEMA_OP, CACHED_OP, UNPRICED_OP],
        }
        values.update(overrides)
        conn = owner_connection
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant.pk)])
        conn.execute(
            """INSERT INTO ai_gateway_aibudgetpolicy
               (id, tenant_id, currency, monthly_limit, overage_authorised, overage_limit,
                max_cost_per_request, max_output_tokens, user_daily_limit, user_monthly_limit,
                requests_per_minute, billing_anchor_day, allowed_models, allowed_operations,
                updated_at)
               VALUES (gen_random_uuid(), %s, 'USD', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       now())""",
            [
                tenant.pk,
                values["monthly_limit"],
                values["overage_authorised"],
                values["overage_limit"],
                values["max_cost_per_request"],
                values["max_output_tokens"],
                values["user_daily_limit"],
                values["user_monthly_limit"],
                values["requests_per_minute"],
                values["billing_anchor_day"],
                json.dumps(values["allowed_models"]),
                json.dumps(values["allowed_operations"]),
            ],
        )
        conn.commit()

    return write


@pytest.fixture
def firm(committed_db, ai_catalog, set_policy):
    user = make_user()
    tenant = make_tenant(user)
    set_policy(tenant)
    return tenant, user


def add_member(tenant, owner, role):
    from apps.core.db.scope import db_scope

    member = make_user()
    with db_scope(tenant_id=tenant.pk, user_id=owner.pk):
        TenantMembership.objects.create(tenant=tenant, user=member, role=role)
    return member


def request_for(firm_tuple, operation=OP, key=None, note="salut"):
    from apps.ai_gateway.gateway import AIRequest

    tenant, user = firm_tuple
    return AIRequest(
        tenant_id=tenant.pk,
        user_id=user.pk,
        operation=operation,
        idempotency_key=key or str(uuid.uuid4()),
        variables={"note": note},
    )


class ScriptedAdapter(ProviderAdapter):
    """Plays back results or exceptions, and records every call."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def usage_result(text="răspuns", input_tokens=100, output_tokens=50, **extra):
    return ProviderResult(
        output_text=text,
        status=extra.pop("status", "completed"),
        usage_known=extra.pop("usage_known", True),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        raw_usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
        request_id="req_test",
        **extra,
    )


__all__ = ["add_member", "request_for", "ScriptedAdapter", "usage_result", "Role"]
