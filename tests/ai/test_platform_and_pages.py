from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, ProgrammingError, connections
from django.urls import reverse
from django.utils import timezone

from apps.ai_gateway import tasks
from apps.ai_gateway.gateway import AIGateway, AIOutcomeUnknown
from apps.ai_gateway.models import AIBudget, AIBudgetPolicy, AIUsageReservation
from apps.ai_gateway.providers.base import ProviderOutcomeUnknown
from apps.ai_gateway.providers.fake import SYNTHETIC_TEXT, FakeAdapter
from apps.audit.models import TenantEvent
from apps.core.db.scope import db_scope
from apps.platform_admin import ai_services
from apps.tenants.roles import Role
from tests.factories import make_tenant, make_user

from .conftest import MODEL, OP, ScriptedAdapter, add_member, request_for, usage_result

PASSWORD = "correct-horse-battery"


def grant(owner_connection, user, role="superadmin"):
    owner_connection.execute(
        "INSERT INTO accounts_platformgrant (id, user_id, role, created_at)"
        " VALUES (gen_random_uuid(), %s, %s, now())",
        [user.pk, role],
    )
    owner_connection.commit()


def sign_in(client, user):
    assert (
        client.post(
            reverse("public:login"), {"identifier": user.email, "password": PASSWORD}
        ).status_code
        == 302
    )


def policy_fields(**overrides):
    return {
        "monthly_limit": Decimal("5"),
        "overage_authorised": False,
        "overage_limit": Decimal("0"),
        "max_cost_per_request": Decimal("1"),
        "max_output_tokens": 100,
        "user_daily_limit": None,
        "user_monthly_limit": None,
        "requests_per_minute": 1000,
        "billing_anchor_day": 1,
        "allowed_models": [MODEL],
        "allowed_operations": [OP],
        **overrides,
    }


def uncertain_reservation(firm):
    with pytest.raises(AIOutcomeUnknown):
        AIGateway(
            sleep=lambda s: None, adapter=ScriptedAdapter(ProviderOutcomeUnknown("timeout"))
        ).execute(request_for(firm))
    tenant, user = firm
    with db_scope(tenant_id=tenant.pk, user_id=user.pk):
        return AIUsageReservation.objects.get()


class TestPolicyManagement:
    def test_superadmin_sets_a_policy_audited_and_visible_to_the_firm(
        self, committed_db, ai_catalog, owner_connection
    ):
        staff, owner = make_user(), make_user()
        tenant = make_tenant(owner)
        grant(owner_connection, staff)
        ai_services.set_policy(staff.pk, tenant.pk, reason="plan Start", **policy_fields())
        with db_scope(tenant_id=tenant.pk, user_id=owner.pk):
            assert AIBudgetPolicy.objects.get().monthly_limit == Decimal("5")
            mirror = TenantEvent.objects.get(action="platform.ai.policy.updated")
        assert mirror.metadata["reason"] == "plan Start"
        logged = [
            r for r in ai_services.tenant_usage() if r["tenant_id"] == tenant.pk
        ]
        assert logged[0]["monthly_limit"] == Decimal("5")

    def test_a_change_applies_to_the_running_period(
        self, firm, owner_connection
    ):
        staff = make_user()
        grant(owner_connection, staff)
        AIGateway(sleep=lambda s: None, adapter=ScriptedAdapter(usage_result())).execute(
            request_for(firm)
        )
        tenant, user = firm
        ai_services.set_policy(
            staff.pk, tenant.pk, reason="majorare", **policy_fields(monthly_limit=Decimal("9"))
        )
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            assert AIBudget.objects.get().limit_amount == Decimal("9")

    def test_support_cannot_change_a_policy(self, committed_db, ai_catalog, owner_connection):
        staff, owner = make_user(), make_user()
        tenant = make_tenant(owner)
        grant(owner_connection, staff, "support")
        with pytest.raises(ProgrammingError, match="superadmin required"):
            ai_services.set_policy(staff.pk, tenant.pk, reason="x", **policy_fields())

    def test_a_reason_is_required(self, committed_db, ai_catalog, owner_connection):
        staff, owner = make_user(), make_user()
        tenant = make_tenant(owner)
        grant(owner_connection, staff)
        with pytest.raises(DatabaseError, match="reason"):
            ai_services.set_policy(staff.pk, tenant.pk, reason=" ", **policy_fields())

    def test_invalid_period_day_is_refused(self, committed_db, ai_catalog, owner_connection):
        staff, owner = make_user(), make_user()
        tenant = make_tenant(owner)
        grant(owner_connection, staff)
        with pytest.raises(DatabaseError, match="invalid"):
            ai_services.set_policy(
                staff.pk, tenant.pk, reason="x", **policy_fields(billing_anchor_day=31)
            )


class TestUncertainReservations:
    def test_listed_for_staff_with_no_prompt_data(self, firm, owner_connection):
        reservation = uncertain_reservation(firm)
        rows = ai_services.uncertain_reservations()
        row = next(r for r in rows if r["id"] == reservation.pk)
        assert row["status"] == "unknown"
        assert row["max_cost"] == reservation.max_cost
        assert not {"variables", "prompt", "output_text"} & set(row)

    def test_release_after_provider_confirms_no_charge(self, firm, owner_connection):
        staff = make_user()
        grant(owner_connection, staff)
        reservation = uncertain_reservation(firm)
        ai_services.resolve_reservation(staff.pk, reservation.pk, None, "verificat, netaxat")
        tenant, user = firm
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            budget = AIBudget.objects.get()
            assert AIUsageReservation.objects.get().status == "released"
        assert budget.reserved == 0
        assert budget.spent == 0

    def test_charge_after_provider_confirms_a_cost(self, firm, owner_connection):
        staff = make_user()
        grant(owner_connection, staff)
        reservation = uncertain_reservation(firm)
        ai_services.resolve_reservation(
            staff.pk, reservation.pk, Decimal("0.0002"), "taxat conform facturii"
        )
        tenant, user = firm
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            budget = AIBudget.objects.get()
            assert AIUsageReservation.objects.get().status == "committed"
            assert TenantEvent.objects.filter(
                action="platform.ai.reservation.resolved"
            ).exists()
        assert budget.reserved == 0
        assert budget.spent == Decimal("0.0002")

    def test_resolving_twice_is_refused(self, firm, owner_connection):
        staff = make_user()
        grant(owner_connection, staff)
        reservation = uncertain_reservation(firm)
        ai_services.resolve_reservation(staff.pk, reservation.pk, None, "motiv")
        with pytest.raises(DatabaseError, match="not uncertain"):
            ai_services.resolve_reservation(staff.pk, reservation.pk, None, "motiv")

    def test_a_fresh_running_reservation_cannot_be_released(self, firm, owner_connection):
        staff = make_user()
        grant(owner_connection, staff)
        running = {}

        class Peek(ScriptedAdapter):
            def complete(self, request):
                tenant, user = firm
                with db_scope(tenant_id=tenant.pk, user_id=user.pk):
                    running["id"] = AIUsageReservation.objects.get().pk
                with pytest.raises(DatabaseError, match="not uncertain"):
                    ai_services.resolve_reservation(staff.pk, running["id"], None, "motiv")
                return usage_result()

        AIGateway(sleep=lambda s: None, adapter=Peek()).execute(request_for(firm))
        assert running["id"]


class TestReconciliation:
    def test_difference_against_our_calculation(self, firm, owner_connection):
        staff = make_user()
        grant(owner_connection, staff)
        result = AIGateway(sleep=lambda s: None, adapter=ScriptedAdapter(usage_result())).execute(
            request_for(firm)
        )
        now = timezone.now()
        calculated = ai_services.record_reconciliation(
            staff.pk,
            provider="test",
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
            reported=Decimal("0.001"),
            currency="USD",
            note="factura test",
        )
        assert calculated >= result.cost
        row = ai_services.reconciliations()[0]
        assert row["difference"] == row["reported_cost"] - row["calculated_cost"]


class TestPages:
    def test_tenant_page_shows_consumption(self, firm, client):
        AIGateway(sleep=lambda s: None, adapter=ScriptedAdapter(usage_result())).execute(
            request_for(firm)
        )
        sign_in(client, firm[1])
        response = client.get(reverse("tenant:ai-usage", args=[firm[0].pk]))
        assert response.status_code == 200
        content = response.content.decode()
        assert "Consum AI" in content
        assert "Ultimele cereri" in content

    def test_a_firm_without_ai_says_so(self, committed_db, ai_catalog, client):
        user = make_user()
        tenant = make_tenant(user)
        sign_in(client, user)
        content = client.get(reverse("tenant:ai-usage", args=[tenant.pk])).content.decode()
        assert "nu este activat" in content

    def test_a_member_cannot_see_the_costs(self, firm, client):
        tenant, owner = firm
        member = add_member(tenant, owner, Role.MEMBER)
        sign_in(client, member)
        assert client.get(reverse("tenant:ai-usage", args=[tenant.pk])).status_code == 403

    def test_another_tenants_page_is_not_found(self, firm, client):
        stranger = make_user()
        make_tenant(stranger)
        sign_in(client, stranger)
        assert client.get(reverse("tenant:ai-usage", args=[firm[0].pk])).status_code == 404

    def test_synthetic_answers_are_labelled(self, firm, client, settings):
        settings.AAI_ALLOW_FAKE_AI = True
        AIGateway(sleep=lambda s: None, adapter=FakeAdapter()).execute(request_for(firm))
        sign_in(client, firm[1])
        content = client.get(reverse("tenant:ai-usage", args=[firm[0].pk])).content.decode()
        assert SYNTHETIC_TEXT in content
        assert "sintetic" in content

    def test_platform_pages_work_and_hide_answers(self, firm, owner_connection, client):
        staff = make_user()
        grant(owner_connection, staff)
        AIGateway(
            sleep=lambda s: None, adapter=ScriptedAdapter(usage_result(text="raspuns-privat"))
        ).execute(request_for(firm))
        sign_in(client, staff)
        for name in ("platform:ai-usage", "platform:ai-costs"):
            response = client.get(reverse(name))
            assert response.status_code == 200
            assert "raspuns-privat" not in response.content.decode()
        form = client.get(reverse("platform:ai-policy", args=[firm[0].pk]))
        assert form.status_code == 200

    def test_superadmin_sets_a_policy_over_http(
        self, committed_db, ai_catalog, owner_connection, client
    ):
        staff, owner = make_user(), make_user()
        tenant = make_tenant(owner)
        grant(owner_connection, staff)
        sign_in(client, staff)
        response = client.post(
            reverse("platform:ai-policy", args=[tenant.pk]),
            {
                "monthly_limit": "3",
                "overage_limit": "0",
                "max_cost_per_request": "1",
                "max_output_tokens": "100",
                "requests_per_minute": "10",
                "billing_anchor_day": "1",
                "allowed_models": [MODEL],
                "allowed_operations": [OP],
                "reason": "activare",
            },
        )
        assert response.status_code == 302
        with db_scope(tenant_id=tenant.pk, user_id=owner.pk):
            assert AIBudgetPolicy.objects.get().monthly_limit == Decimal("3")

    def test_support_cannot_open_the_policy_form(
        self, committed_db, ai_catalog, owner_connection, client
    ):
        staff, owner = make_user(), make_user()
        tenant = make_tenant(owner)
        grant(owner_connection, staff, "support")
        sign_in(client, staff)
        assert client.get(reverse("platform:ai-policy", args=[tenant.pk])).status_code == 403
        assert client.get(reverse("platform:ai-usage")).status_code == 200


class TestProviderSelection:
    def test_the_fake_provider_refuses_outside_development(self, firm, settings):
        settings.AAI_ALLOW_FAKE_AI = False
        from apps.ai_gateway.gateway import AIProviderFailed

        with pytest.raises(AIProviderFailed, match="ProviderNotConfigured"):
            AIGateway(sleep=lambda s: None, adapter=FakeAdapter()).execute(request_for(firm))
        tenant, user = firm
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            assert AIBudget.objects.get().reserved == 0

    def test_diagnostic_task_runs_without_a_surrounding_transaction(self, firm, monkeypatch):
        tenant, user = firm
        seen = {}

        def fake_execute(request):
            seen["tenant"] = request.tenant_id
            seen["in_transaction"] = connections["default"].in_atomic_block
            return None

        monkeypatch.setattr(tasks, "execute", fake_execute)
        outcome = tasks.run_diagnostic(
            _tenant_id=str(tenant.pk),
            _actor_id=str(user.pk),
            idempotency_key="k",
            note="n",
        )
        assert outcome == "ok"
        assert seen == {"tenant": str(tenant.pk), "in_transaction": False}
