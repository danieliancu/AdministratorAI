from datetime import timedelta
from decimal import Decimal as D

import psycopg
import pytest
from django.core.management import CommandError, call_command
from django.db import DatabaseError
from django.utils import timezone

from apps.core.db.scope import db_scope
from tests.conftest import _owner_dsn

pytestmark = pytest.mark.django_db


def _command(**options):
    with db_scope():
        call_command("set_ai_operation_model", **options)


def test_unknown_model_is_refused():
    with pytest.raises(CommandError, match="No active model"):
        _command(operation="diagnostic.echo", model="openai:does-not-exist")


def _add_model(key, effective_from):
    with psycopg.connect(**_owner_dsn()) as conn:
        conn.execute(
            "INSERT INTO ai_gateway_aiprovider (key, name, is_active)"
            " VALUES ('cmdtest', 'test', true)"
            " ON CONFLICT DO NOTHING"
        )
        conn.execute(
            "INSERT INTO ai_gateway_aimodel (key, provider_id, provider_model_name, is_active)"
            " VALUES (%s, 'cmdtest', %s, true) ON CONFLICT DO NOTHING",
            [key, key],
        )
        if effective_from is not None:
            conn.execute(
                "INSERT INTO ai_gateway_aimodelpricing (id, model_id, effective_from, currency,"
                " input_per_mtok, cached_read_per_mtok, cache_write_30m_per_mtok,"
                " cache_write_12h_per_mtok, output_per_mtok, source_url, created_at)"
                " VALUES (gen_random_uuid(), %s, %s, 'USD', %s, 0, 0, 0, %s, 'test', now())",
                [key, effective_from, D("1"), D("1")],
            )


def test_model_without_a_price_in_force_is_refused():
    _add_model("cmdtest:no-price", None)
    _add_model("cmdtest:future-price", timezone.now() + timedelta(days=30))
    with pytest.raises(CommandError, match="no price in force"):
        _command(operation="diagnostic.echo", model="cmdtest:no-price")
    with pytest.raises(CommandError, match="no price in force"):
        _command(operation="diagnostic.echo", model="cmdtest:future-price")


def test_the_application_role_cannot_assign_a_model():
    _add_model("cmdtest:priced", timezone.now() - timedelta(days=1))
    # Tests run as aai_app, which has no write access to the catalog: only the owner can.
    with pytest.raises(DatabaseError):
        _command(operation="diagnostic.echo", model="cmdtest:priced")
