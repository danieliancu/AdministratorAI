import threading
import uuid
from decimal import Decimal

import psycopg
import pytest
from django.db import ProgrammingError, connection, connections, transaction

from apps.ai_gateway.gateway import (
    AIDenied,
    AIGateway,
    AIInvalidOutput,
    AIOutcomeUnknown,
    AIProviderFailed,
    AIRequest,
    AIRequestInProgress,
    GatewayMisuse,
)
from apps.ai_gateway.models import (
    AIBudget,
    AIBudgetAlert,
    AIBudgetPolicy,
    AIModelPricing,
    AIStoredResponse,
    AIUsageEvent,
    AIUsageReservation,
    PromptTemplateVersion,
)
from apps.ai_gateway.providers.base import (
    ProviderOutcomeUnknown,
    ProviderRejected,
    ProviderRetryable,
)
from apps.audit.models import TenantEvent
from apps.core.db.scope import db_scope
from apps.tenants.roles import Role
from tests.factories import make_tenant, make_user

from .conftest import (
    CACHED_OP,
    SCHEMA_OP,
    UNPRICED_OP,
    ScriptedAdapter,
    add_member,
    request_for,
    usage_result,
)

Status = AIUsageReservation.Status


def gateway(adapter):
    return AIGateway(sleep=lambda seconds: None, adapter=adapter)


def budget_of(firm):
    tenant, user = firm
    with db_scope(tenant_id=tenant.pk, user_id=user.pk):
        return AIBudget.objects.get()


def reservations_of(firm):
    tenant, user = firm
    with db_scope(tenant_id=tenant.pk, user_id=user.pk):
        return list(AIUsageReservation.objects.all())


def events_of(firm):
    tenant, user = firm
    with db_scope(tenant_id=tenant.pk, user_id=user.pk):
        return list(AIUsageEvent.objects.all())


class TestAccounting:
    def test_success_records_cost_and_releases_the_unused_amount(self, firm):
        result = gateway(ScriptedAdapter(usage_result())).execute(request_for(firm))
        assert result.output_text == "răspuns"
        # 100 input at $1 + 50 output at $4, per million.
        assert result.cost == Decimal("0.00030000")
        budget = budget_of(firm)
        assert budget.spent == Decimal("0.00030000")
        assert budget.reserved == 0
        [reservation] = reservations_of(firm)
        assert reservation.status == Status.COMMITTED
        [event] = events_of(firm)
        assert event.actual_cost == Decimal("0.00030000")
        assert event.estimated_cost == reservation.max_cost
        assert event.estimated_cost >= event.actual_cost
        assert event.input_tokens == 100
        assert event.output_tokens == 50
        assert event.currency == "USD"
        assert event.user_id == firm[1].pk
        assert event.pricing_id == reservation.pricing_id
        assert event.provider_request_id == "req_test"

    def test_the_prompt_never_lands_in_usage_records(self, firm):
        secret = "cifra-confidentiala-a-firmei"
        gateway(ScriptedAdapter(usage_result())).execute(request_for(firm, note=secret))
        [event] = events_of(firm)
        for value in (event.provider_usage, event.status, event.provider_request_id):
            assert secret not in str(value)

    def test_history_keeps_the_price_in_force_at_the_time(
        self, committed_db, ai_catalog, set_policy, owner_connection
    ):
        # Its own model and operation: prices are immutable, so a new one would stay in
        # force for every later test.
        suffix = uuid.uuid4().hex[:8]
        model, operation = f"test:history-{suffix}", f"test.history-{suffix}"
        conn = owner_connection

        def add_price(age, input_rate, output_rate):
            conn.execute(
                """INSERT INTO ai_gateway_aimodelpricing
                   (id, model_id, effective_from, currency, input_per_mtok, cached_read_per_mtok,
                    cache_write_30m_per_mtok, cache_write_12h_per_mtok, output_per_mtok,
                    source_url, created_at)
                   VALUES (gen_random_uuid(), %s, now() - %s::interval, 'USD', %s, %s, %s, %s,
                           %s, 'test', now())""",
                [model, age, input_rate, input_rate, input_rate, input_rate, output_rate],
            )
            conn.commit()

        conn.execute(
            "INSERT INTO ai_gateway_aimodel (key, provider_id, provider_model_name, is_active)"
            " VALUES (%s, 'test', 'history', true)",
            [model],
        )
        conn.execute(
            """INSERT INTO ai_gateway_aioperation
               (key, name, default_model_id, capability, allowed_variables, max_input_bytes,
                max_output_tokens, output_schema, cacheable, cache_ttl_seconds, is_active)
               VALUES (%s, 'h', %s, 'use_ai', '["note"]', 2000, 100, NULL, false, 0, true)""",
            [operation, model],
        )
        conn.execute(
            """INSERT INTO ai_gateway_prompttemplateversion
               (id, operation_id, version, system_template, user_template, is_active, created_at)
               VALUES (gen_random_uuid(), %s, 1, 'S', '$note', true, now())""",
            [operation],
        )
        add_price("1 year", 1, 4)

        user = make_user()
        tenant = make_tenant(user)
        firm = (tenant, user)
        set_policy(tenant, allowed_models=[model], allowed_operations=[operation])

        gateway(ScriptedAdapter(usage_result())).execute(request_for(firm, operation=operation))
        first = events_of(firm)[0]
        add_price("1 second", 10, 40)
        result = gateway(ScriptedAdapter(usage_result())).execute(
            request_for(firm, operation=operation)
        )

        assert result.cost == Decimal("0.00300000")
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            old = AIUsageEvent.objects.get(pk=first.pk)
            assert AIUsageEvent.objects.exclude(pk=first.pk).get().pricing_id != first.pricing_id
        assert old.actual_cost == Decimal("0.00030000")
        assert old.pricing_id == first.pricing_id


class TestDenials:
    def test_no_policy_means_no_ai(self, committed_db, ai_catalog):
        user = make_user()
        tenant = make_tenant(user)
        adapter = ScriptedAdapter(usage_result())
        with pytest.raises(AIDenied, match="ai_not_enabled"):
            gateway(adapter).execute(request_for((tenant, user)))
        assert adapter.calls == []

    def test_a_denial_is_recorded(self, firm):
        tenant, user = firm
        outsider = make_user()
        adapter = ScriptedAdapter(usage_result())
        with pytest.raises(AIDenied, match="no_tenant_access"):
            gateway(adapter).execute(request_for((tenant, outsider)))
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            event = TenantEvent.objects.get(action="ai.denied")
        assert event.metadata["reason"] == "no_tenant_access"

    def test_a_non_member_cannot_spend_a_firms_budget(self, firm):
        tenant, _ = firm
        adapter = ScriptedAdapter(usage_result())
        with pytest.raises(AIDenied, match="no_tenant_access"):
            gateway(adapter).execute(request_for((tenant, make_user())))
        assert adapter.calls == []

    def test_a_role_without_the_capability_is_refused(self, firm):
        tenant, owner = firm
        reader = add_member(tenant, owner, Role.READ_ONLY)
        adapter = ScriptedAdapter(usage_result())
        with pytest.raises(AIDenied, match="not_permitted"):
            gateway(adapter).execute(request_for((tenant, reader)))
        assert adapter.calls == []

    def test_a_suspended_firm_is_refused(self, firm, owner_connection):
        tenant, _ = firm
        conn = owner_connection
        conn.execute("ALTER TABLE tenants_tenant NO FORCE ROW LEVEL SECURITY")
        conn.execute("UPDATE tenants_tenant SET status = 'suspended' WHERE id = %s", [tenant.pk])
        conn.execute("ALTER TABLE tenants_tenant FORCE ROW LEVEL SECURITY")
        conn.commit()
        with pytest.raises(AIDenied, match="no_tenant_access"):
            gateway(ScriptedAdapter(usage_result())).execute(request_for(firm))

    def test_operation_outside_the_plan(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(tenant, allowed_operations=[])
        with pytest.raises(AIDenied, match="operation_not_in_plan"):
            gateway(ScriptedAdapter(usage_result())).execute(request_for((tenant, user)))

    def test_model_outside_the_plan(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(tenant, allowed_models=[])
        with pytest.raises(AIDenied, match="model_not_in_plan"):
            gateway(ScriptedAdapter(usage_result())).execute(request_for((tenant, user)))

    def test_a_model_without_a_price_is_refused(self, firm):
        with pytest.raises(AIDenied, match="no_pricing"):
            gateway(ScriptedAdapter(usage_result())).execute(
                request_for(firm, operation=UNPRICED_OP)
            )

    def test_unknown_operation(self, firm):
        with pytest.raises(AIDenied, match="unknown_operation"):
            gateway(ScriptedAdapter(usage_result())).execute(
                request_for(firm, operation="nu.exista")
            )

    def test_undeclared_variables_never_reach_the_provider(self, firm):
        tenant, user = firm
        adapter = ScriptedAdapter(usage_result())
        request = AIRequest(
            tenant_id=tenant.pk,
            user_id=user.pk,
            operation="test.op",
            idempotency_key=str(uuid.uuid4()),
            variables={"note": "x", "cnp": "date personale"},
        )
        with pytest.raises(AIDenied, match="unexpected_variables"):
            gateway(adapter).execute(request)
        assert adapter.calls == []

    def test_oversized_input_is_refused(self, firm):
        with pytest.raises(AIDenied, match="input_too_large"):
            gateway(ScriptedAdapter(usage_result())).execute(request_for(firm, note="x" * 3000))

    def test_rate_limit(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(tenant, requests_per_minute=2)
        g = gateway(ScriptedAdapter(usage_result()))
        g.execute(request_for((tenant, user)))
        g.execute(request_for((tenant, user)))
        with pytest.raises(AIDenied, match="rate_limited"):
            g.execute(request_for((tenant, user)))

    def test_request_cost_cap(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(tenant, max_cost_per_request=Decimal("0.00000001"))
        with pytest.raises(AIDenied, match="request_too_expensive"):
            gateway(ScriptedAdapter(usage_result())).execute(request_for((tenant, user)))

    def test_output_tokens_are_capped_by_the_policy(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(tenant, max_output_tokens=7)
        adapter = ScriptedAdapter(usage_result())
        gateway(adapter).execute(request_for((tenant, user)))
        assert adapter.calls[0].max_output_tokens == 7


class TestBudgets:
    def test_budget_exhausted_stops_the_call(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(tenant, monthly_limit=Decimal("0.00000100"))
        adapter = ScriptedAdapter(usage_result())
        with pytest.raises(AIDenied, match="budget_exhausted"):
            gateway(adapter).execute(request_for((tenant, user)))
        assert adapter.calls == []

    def test_authorised_overage_extends_the_limit(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(
            tenant,
            monthly_limit=Decimal("0.00000100"),
            overage_authorised=True,
            overage_limit=Decimal("1"),
        )
        gateway(ScriptedAdapter(usage_result())).execute(request_for((tenant, user)))

    def test_overage_amount_without_authorisation_does_nothing(
        self, committed_db, ai_catalog, set_policy
    ):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(
            tenant,
            monthly_limit=Decimal("0.00000100"),
            overage_authorised=False,
            overage_limit=Decimal("1"),
        )
        with pytest.raises(AIDenied, match="budget_exhausted"):
            gateway(ScriptedAdapter(usage_result())).execute(request_for((tenant, user)))

    def test_user_daily_limit(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        colleague = add_member(tenant, user, Role.MEMBER)
        set_policy(tenant, user_daily_limit=Decimal("0.0008"))
        g = gateway(ScriptedAdapter(usage_result()))
        g.execute(request_for((tenant, user)))
        g.execute(request_for((tenant, user)))
        with pytest.raises(AIDenied, match="user_daily_limit"):
            g.execute(request_for((tenant, user)))
        # The limit is per person, not for the firm.
        g.execute(request_for((tenant, colleague)))

    def test_user_monthly_limit(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(tenant, user_monthly_limit=Decimal("0.0008"))
        g = gateway(ScriptedAdapter(usage_result()))
        g.execute(request_for((tenant, user)))
        g.execute(request_for((tenant, user)))
        with pytest.raises(AIDenied, match="user_monthly_limit"):
            g.execute(request_for((tenant, user)))

    def test_alerts_fire_once_per_threshold(self, committed_db, ai_catalog, set_policy):
        user = make_user()
        tenant = make_tenant(user)
        # 0.00004 per request, with a reservation of 0.00008 held during each one.
        set_policy(tenant, monthly_limit=Decimal("0.001"), max_output_tokens=10)
        g = gateway(ScriptedAdapter(usage_result(input_tokens=0, output_tokens=10)))
        seen = []
        for _ in range(40):
            try:
                g.execute(request_for((tenant, user)))
            except AIDenied as denied:
                assert denied.reason == "budget_exhausted"
                break
            with db_scope(tenant_id=tenant.pk, user_id=user.pk):
                seen = list(AIBudgetAlert.objects.values_list("threshold", flat=True))
        assert sorted(seen) == [70, 90]
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            # The hard stop acts before the limit, because a request could cost its maximum.
            assert AIBudget.objects.get().spent <= Decimal("0.001")

    def test_the_100_percent_alert_fires_when_overage_is_authorised(
        self, committed_db, ai_catalog, set_policy
    ):
        user = make_user()
        tenant = make_tenant(user)
        set_policy(
            tenant,
            monthly_limit=Decimal("0.0002"),
            overage_authorised=True,
            overage_limit=Decimal("1"),
            max_output_tokens=10,
        )
        g = gateway(ScriptedAdapter(usage_result(input_tokens=0, output_tokens=10)))
        for _ in range(8):
            g.execute(request_for((tenant, user)))
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            assert sorted(AIBudgetAlert.objects.values_list("threshold", flat=True)) == [
                70,
                90,
                100,
            ]
            assert AIBudget.objects.get().spent > AIBudget.objects.get().limit_amount


def _run_in_threads(count, function):
    barrier = threading.Barrier(count, timeout=30)
    outcomes = []
    lock = threading.Lock()

    def runner():
        try:
            barrier.wait()
            value = function()
            outcome = ("ok", value)
        except Exception as exc:
            outcome = ("error", exc)
        finally:
            connections.close_all()
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=runner) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(90)
    return outcomes


class TestConcurrency:
    def test_simultaneous_requests_cannot_exceed_the_budget(
        self, committed_db, ai_catalog, set_policy
    ):
        user = make_user()
        tenant = make_tenant(user)
        firm = (tenant, user)
        # One reservation is 0.000435 (14 bytes at 2.5, 100 output at 4). Four always fit at
        # once; a fifth can fit only after earlier ones settle below their maximum.
        set_policy(tenant, monthly_limit=Decimal("0.0021"))
        adapter = ScriptedAdapter(usage_result(input_tokens=16, output_tokens=100))

        def call():
            return AIGateway(sleep=lambda s: None, adapter=adapter).execute(
                request_for(firm, note="x" * 2)
            )

        outcomes = _run_in_threads(16, call)
        succeeded = [o for o in outcomes if o[0] == "ok"]
        denied = [o for o in outcomes if o[0] == "error"]
        assert len(outcomes) == 16
        assert all(isinstance(o[1], AIDenied) for o in denied), denied
        assert all(o[1].reason == "budget_exhausted" for o in denied)

        budget = budget_of(firm)
        assert budget.spent <= budget.limit_amount
        assert budget.reserved == 0
        assert len(adapter.calls) == len(succeeded)
        total = sum(e.actual_cost for e in events_of(firm))
        assert total == budget.spent
        assert len(succeeded) >= 4

    def test_in_flight_requests_all_count_against_the_budget(
        self, committed_db, ai_catalog, set_policy
    ):
        """Providers are slow: this holds every reservation open at once while others check."""
        user = make_user()
        tenant = make_tenant(user)
        firm = (tenant, user)
        set_policy(tenant, monthly_limit=Decimal("0.0021"))
        release = threading.Event()
        entered = []

        class SlowAdapter(ScriptedAdapter):
            def complete(self, request):
                entered.append(1)
                release.wait(20)
                return usage_result(input_tokens=16, output_tokens=100)

        adapter = SlowAdapter()

        def call():
            return AIGateway(sleep=lambda s: None, adapter=adapter).execute(
                request_for(firm, note="x" * 2)
            )

        results = []
        lock = threading.Lock()

        def runner():
            try:
                outcome = call()
            except Exception as exc:
                outcome = exc
            finally:
                connections.close_all()
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=runner) for _ in range(12)]
        for thread in threads:
            thread.start()
        for _ in range(200):
            with lock:
                done = len(results)
            if done == 12 - len(entered) and len(entered) >= 1:
                break
            threading.Event().wait(0.05)
        release.set()
        for thread in threads:
            thread.join(60)

        # Each reservation is 0.000435, so a limit of 0.0021 fits exactly 4 held at once.
        assert len(entered) == 4
        denied = [r for r in results if isinstance(r, AIDenied)]
        assert len(denied) == 8
        budget = budget_of(firm)
        assert budget.reserved == 0
        assert budget.spent == sum(e.actual_cost for e in events_of(firm))

    def test_same_idempotency_key_calls_the_provider_once(self, firm):
        adapter = ScriptedAdapter(usage_result())
        key = str(uuid.uuid4())

        def call():
            return AIGateway(sleep=lambda s: None, adapter=adapter).execute(
                request_for(firm, key=key)
            )

        outcomes = _run_in_threads(6, call)
        assert len(adapter.calls) == 1
        for kind, value in outcomes:
            if kind == "error":
                assert isinstance(value, AIRequestInProgress)
        budget = budget_of(firm)
        assert budget.spent == Decimal("0.00030000")
        assert len(events_of(firm)) == 1

    def test_counters_match_the_records_under_mixed_outcomes(self, firm):
        script = [
            usage_result(),
            ProviderRejected("400"),
            ProviderOutcomeUnknown("timeout"),
            usage_result(),
        ]
        lock = threading.Lock()

        class Mixed(ScriptedAdapter):
            def complete(self, request):
                with lock:
                    step = script.pop() if script else usage_result()
                if isinstance(step, Exception):
                    raise step
                return step

        def call():
            return AIGateway(sleep=lambda s: None, adapter=Mixed()).execute(request_for(firm))

        _run_in_threads(8, call)
        budget = budget_of(firm)
        reservations = reservations_of(firm)
        events = events_of(firm)
        held = sum(r.max_cost for r in reservations if r.status == Status.UNKNOWN)
        assert budget.reserved == held
        assert budget.spent == sum(e.actual_cost for e in events)
        assert any(r.status == Status.UNKNOWN for r in reservations)
        assert any(r.status == Status.RELEASED for r in reservations)


class TestFailures:
    def test_inside_a_transaction_is_refused(self, firm):
        with transaction.atomic(), pytest.raises(GatewayMisuse):
            gateway(ScriptedAdapter(usage_result())).execute(request_for(firm))

    def test_definite_rejection_releases_the_money(self, firm):
        with pytest.raises(AIProviderFailed):
            gateway(ScriptedAdapter(ProviderRejected("400"))).execute(request_for(firm))
        [reservation] = reservations_of(firm)
        assert reservation.status == Status.RELEASED
        budget = budget_of(firm)
        assert budget.reserved == 0
        assert budget.spent == 0
        assert events_of(firm) == []

    def test_timeout_keeps_the_money_held(self, firm):
        with pytest.raises(AIOutcomeUnknown):
            gateway(ScriptedAdapter(ProviderOutcomeUnknown("timeout"))).execute(request_for(firm))
        [reservation] = reservations_of(firm)
        assert reservation.status == Status.UNKNOWN
        assert budget_of(firm).reserved == reservation.max_cost

    def test_unexpected_exception_and_cancellation_are_treated_as_unknown(self, firm):
        class Cancelled(Exception):
            pass

        with pytest.raises(AIOutcomeUnknown):
            gateway(ScriptedAdapter(Cancelled())).execute(request_for(firm))
        [reservation] = reservations_of(firm)
        assert reservation.status == Status.UNKNOWN
        assert budget_of(firm).reserved == reservation.max_cost

    def test_retrying_the_same_key_after_unknown_does_not_call_again(self, firm):
        key = str(uuid.uuid4())
        adapter = ScriptedAdapter(ProviderOutcomeUnknown("timeout"))
        g = gateway(adapter)
        with pytest.raises(AIOutcomeUnknown):
            g.execute(request_for(firm, key=key))
        with pytest.raises(AIOutcomeUnknown):
            g.execute(request_for(firm, key=key))
        assert len(adapter.calls) == 1

    def test_retries_are_bounded(self, firm, settings):
        settings.AAI_AI_MAX_RETRIES = 2
        delays = []
        adapter = ScriptedAdapter(ProviderRetryable("429"))
        g = AIGateway(sleep=delays.append, adapter=adapter)
        with pytest.raises(AIProviderFailed):
            g.execute(request_for(firm))
        assert len(adapter.calls) == 3
        assert delays == [0.5, 1.0]
        assert reservations_of(firm)[0].status == Status.RELEASED

    def test_retry_count_is_recorded(self, firm):
        adapter = ScriptedAdapter(ProviderRetryable("429"), usage_result())
        gateway(adapter).execute(request_for(firm))
        assert events_of(firm)[0].retry_count == 1

    def test_missing_usage_charges_the_maximum(self, firm):
        result = gateway(ScriptedAdapter(usage_result(usage_known=False))).execute(
            request_for(firm)
        )
        [reservation] = reservations_of(firm)
        assert result.cost == reservation.max_cost
        assert budget_of(firm).spent == reservation.max_cost
        assert events_of(firm)[0].status == AIUsageEvent.Status.USAGE_MISSING

    @pytest.mark.parametrize(
        "kwargs,status",
        [
            ({"status": "refused"}, AIUsageEvent.Status.REFUSED),
            ({"status": "incomplete"}, AIUsageEvent.Status.INCOMPLETE),
        ],
    )
    def test_refused_and_incomplete_are_charged_and_not_returned(self, firm, kwargs, status):
        with pytest.raises(AIInvalidOutput):
            gateway(ScriptedAdapter(usage_result(**kwargs))).execute(request_for(firm))
        assert events_of(firm)[0].status == status
        assert budget_of(firm).spent > 0
        tenant, user = firm
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            assert AIStoredResponse.objects.count() == 0

    def test_structured_output_is_validated(self, firm):
        with pytest.raises(AIInvalidOutput):
            gateway(ScriptedAdapter(usage_result(text='{"wrong": 1}'))).execute(
                request_for(firm, operation=SCHEMA_OP)
            )
        assert events_of(firm)[0].status == AIUsageEvent.Status.INVALID_OUTPUT
        result = gateway(ScriptedAdapter(usage_result(text='{"answer": "da"}'))).execute(
            request_for(firm, operation=SCHEMA_OP)
        )
        assert result.output_text == '{"answer": "da"}'

    def test_not_json_is_invalid(self, firm):
        with pytest.raises(AIInvalidOutput):
            gateway(ScriptedAdapter(usage_result(text="nu e json"))).execute(
                request_for(firm, operation=SCHEMA_OP)
            )


class TestIdempotencyAndCache:
    def test_replay_does_not_charge_or_call_again(self, firm):
        key = str(uuid.uuid4())
        adapter = ScriptedAdapter(usage_result(text="original"))
        g = gateway(adapter)
        first = g.execute(request_for(firm, key=key))
        second = g.execute(request_for(firm, key=key))
        assert first.output_text == second.output_text == "original"
        assert second.replayed
        assert second.cost == 0
        assert len(adapter.calls) == 1
        assert budget_of(firm).spent == first.cost

    def test_a_cache_hit_costs_nothing_and_is_recorded(self, firm):
        adapter = ScriptedAdapter(usage_result(text="din provider"))
        g = gateway(adapter)
        first = g.execute(request_for(firm, operation=CACHED_OP))
        second = g.execute(request_for(firm, operation=CACHED_OP))
        assert second.from_cache
        assert second.output_text == "din provider"
        assert second.cost == 0
        assert len(adapter.calls) == 1
        assert budget_of(firm).spent == first.cost
        statuses = {e.status for e in events_of(firm)}
        assert AIUsageEvent.Status.CACHE_HIT in statuses

    def test_different_input_is_not_served_from_cache(self, firm):
        adapter = ScriptedAdapter(usage_result())
        g = gateway(adapter)
        g.execute(request_for(firm, operation=CACHED_OP, note="a"))
        g.execute(request_for(firm, operation=CACHED_OP, note="b"))
        assert len(adapter.calls) == 2

    def test_the_cache_is_never_shared_between_tenants(self, firm, set_policy):
        other_user = make_user()
        other_tenant = make_tenant(other_user)
        set_policy(other_tenant)
        adapter = ScriptedAdapter(usage_result(text="secretul firmei A"))
        gateway(adapter).execute(request_for(firm, operation=CACHED_OP, note="aceeași întrebare"))
        adapter_b = ScriptedAdapter(usage_result(text="răspunsul firmei B"))
        result = gateway(adapter_b).execute(
            request_for((other_tenant, other_user), operation=CACHED_OP, note="aceeași întrebare")
        )
        assert result.output_text == "răspunsul firmei B"
        assert len(adapter_b.calls) == 1


class TestDatabaseEnforcement:
    def test_the_application_cannot_raise_its_own_budget(self, firm):
        gateway(ScriptedAdapter(usage_result())).execute(request_for(firm))
        tenant, user = firm
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
            AIBudget.objects.update(limit_amount=Decimal("1000000"))
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
            AIBudgetPolicy.objects.update(monthly_limit=Decimal("1000000"))
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
            AIBudgetPolicy.objects.all().delete()

    def test_a_new_budget_row_always_takes_its_limits_from_the_policy(self, firm):
        tenant, user = firm
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            budget = AIBudget.objects.create(
                tenant=tenant,
                period_start="2020-01-01T00:00:00Z",
                period_end="2020-02-01T00:00:00Z",
                currency="XXX",
                limit_amount=Decimal("999999"),
                overage_limit=Decimal("999999"),
                spent=Decimal("-5"),
            )
            stored = AIBudget.objects.get(pk=budget.pk)
        assert stored.limit_amount == Decimal("1")
        assert stored.overage_limit == 0
        assert stored.spent == 0
        assert stored.currency == "USD"

    def test_no_policy_blocks_a_budget_row(self, committed_db, ai_catalog):
        user = make_user()
        tenant = make_tenant(user)
        with pytest.raises(ProgrammingError, match="no AI policy"):
            with db_scope(tenant_id=tenant.pk, user_id=user.pk):
                AIBudget.objects.create(
                    tenant=tenant,
                    period_start="2020-01-01T00:00:00Z",
                    period_end="2020-02-01T00:00:00Z",
                    currency="USD",
                )

    def test_usage_events_cannot_be_changed(self, firm):
        gateway(ScriptedAdapter(usage_result())).execute(request_for(firm))
        tenant, user = firm
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
            AIUsageEvent.objects.update(actual_cost=0)
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
            AIUsageEvent.objects.all().delete()

    def test_even_the_owner_cannot_change_events(self, firm, owner_connection):
        gateway(ScriptedAdapter(usage_result())).execute(request_for(firm))
        tenant, _ = firm
        owner_connection.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant.pk)])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owner_connection.execute("UPDATE ai_gateway_aiusageevent SET actual_cost = 0")

    def test_prices_are_immutable(self, firm, owner_connection):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owner_connection.execute("UPDATE ai_gateway_aimodelpricing SET input_per_mtok = 0")

    def test_prompt_text_is_immutable_but_activation_is_not(self, firm, owner_connection):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owner_connection.execute(
                "UPDATE ai_gateway_prompttemplateversion SET user_template = 'altceva'"
            )
        owner_connection.rollback()
        cursor = owner_connection.execute(
            "UPDATE ai_gateway_prompttemplateversion SET is_active = is_active"
        )
        assert cursor.rowcount >= 1
        owner_connection.rollback()

    def test_application_cannot_write_the_catalog(self, firm):
        tenant, user = firm
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
            AIModelPricing.objects.update(input_per_mtok=0)
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
            PromptTemplateVersion.objects.update(user_template="x")

    def test_usage_is_isolated_between_tenants(self, firm, set_policy):
        other_user = make_user()
        other_tenant = make_tenant(other_user)
        set_policy(other_tenant)
        gateway(ScriptedAdapter(usage_result())).execute(request_for(firm))
        with db_scope(tenant_id=other_tenant.pk, user_id=other_user.pk), connection.cursor() as c:
            for table in ("aiusageevent", "aiusagereservation", "aibudget", "aistoredresponse"):
                c.execute(f"SELECT count(*) FROM ai_gateway_{table}")
                assert c.fetchone()[0] == 0, table
