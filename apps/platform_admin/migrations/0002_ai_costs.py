from django.db import migrations

ROLE = "aai_platform_definer"
ATTRS = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

DEFINER_ACCESS = f"""
    GRANT SELECT ON ai_gateway_aiprovider, ai_gateway_aimodel, ai_gateway_aimodelpricing,
        ai_gateway_aioperation TO {ROLE};

    GRANT SELECT, INSERT, UPDATE ON ai_gateway_aibudgetpolicy TO {ROLE};
    CREATE POLICY aipolicy_sel_platform ON ai_gateway_aibudgetpolicy FOR SELECT TO {ROLE}
        USING (true);
    CREATE POLICY aipolicy_ins_platform ON ai_gateway_aibudgetpolicy FOR INSERT TO {ROLE}
        WITH CHECK (true);
    CREATE POLICY aipolicy_upd_platform ON ai_gateway_aibudgetpolicy FOR UPDATE TO {ROLE}
        USING (true) WITH CHECK (true);

    GRANT SELECT ON ai_gateway_aibudget TO {ROLE};
    GRANT UPDATE (spent, reserved, limit_amount, overage_limit) ON ai_gateway_aibudget TO {ROLE};
    CREATE POLICY aibudget_sel_platform ON ai_gateway_aibudget FOR SELECT TO {ROLE} USING (true);
    CREATE POLICY aibudget_upd_platform ON ai_gateway_aibudget FOR UPDATE TO {ROLE}
        USING (true) WITH CHECK (true);

    GRANT SELECT ON ai_gateway_aiusagereservation TO {ROLE};
    GRANT UPDATE (status, failure_reason, resolved_at) ON ai_gateway_aiusagereservation TO {ROLE};
    CREATE POLICY aireservation_sel_platform ON ai_gateway_aiusagereservation FOR SELECT
        TO {ROLE} USING (true);
    CREATE POLICY aireservation_upd_platform ON ai_gateway_aiusagereservation FOR UPDATE
        TO {ROLE} USING (true) WITH CHECK (true);

    GRANT SELECT, INSERT ON ai_gateway_aiusageevent TO {ROLE};
    CREATE POLICY aievent_sel_platform ON ai_gateway_aiusageevent FOR SELECT TO {ROLE}
        USING (true);
    CREATE POLICY aievent_ins_platform ON ai_gateway_aiusageevent FOR INSERT TO {ROLE}
        WITH CHECK (true);

    GRANT SELECT, INSERT ON ai_gateway_aiproviderreconciliation TO {ROLE};
"""

PLATFORM_OBJECTS = f"""
    SET LOCAL ROLE {ROLE};

    -- Numbers and identifiers only: no prompt or answer ever reaches these views.
    CREATE VIEW platform.ai_tenant_usage WITH (security_barrier) AS
        SELECT t.id AS tenant_id, t.name AS tenant_name, p.currency,
               p.monthly_limit, p.overage_authorised, p.overage_limit,
               b.period_start, b.period_end,
               coalesce(b.spent, 0) AS spent, coalesce(b.reserved, 0) AS reserved,
               (SELECT count(*) FROM public.ai_gateway_aiusageevent e
                WHERE e.tenant_id = t.id AND b.id IS NOT NULL
                  AND e.created_at >= b.period_start AND e.created_at < b.period_end) AS requests,
               p.allowed_models, p.allowed_operations, p.max_cost_per_request,
               p.max_output_tokens, p.user_daily_limit, p.user_monthly_limit,
               p.requests_per_minute, p.billing_anchor_day
        FROM public.tenants_tenant t
        JOIN public.ai_gateway_aibudgetpolicy p ON p.tenant_id = t.id
        LEFT JOIN public.ai_gateway_aibudget b
            ON b.tenant_id = t.id AND now() >= b.period_start AND now() < b.period_end;

    CREATE VIEW platform.ai_cost_breakdown WITH (security_barrier) AS
        SELECT e.operation_id, e.model_id, m.provider_id, e.currency, e.is_synthetic,
               date_trunc('month', e.created_at) AS month,
               count(*) AS requests,
               sum(e.input_tokens) AS input_tokens,
               sum(e.cached_tokens) AS cached_tokens,
               sum(e.output_tokens) AS output_tokens,
               sum(e.actual_cost) AS cost
        FROM public.ai_gateway_aiusageevent e
        JOIN public.ai_gateway_aimodel m ON m.key = e.model_id
        GROUP BY 1, 2, 3, 4, 5, 6;

    CREATE VIEW platform.ai_uncertain_reservations WITH (security_barrier) AS
        SELECT r.id, r.tenant_id, t.name AS tenant_name, r.operation_id, r.model_id,
               r.max_cost, r.currency, r.status, r.failure_reason, r.created_at
        FROM public.ai_gateway_aiusagereservation r
        JOIN public.tenants_tenant t ON t.id = r.tenant_id
        WHERE r.status = 'unknown'
           OR (r.status = 'reserved' AND r.created_at < now() - interval '1 hour');

    CREATE VIEW platform.ai_reconciliations WITH (security_barrier) AS
        SELECT id, provider_id, period_start, period_end, currency, reported_cost,
               calculated_cost, reported_cost - calculated_cost AS difference, note, recorded_at
        FROM public.ai_gateway_aiproviderreconciliation;

    CREATE VIEW platform.ai_catalog WITH (security_barrier) AS
        SELECT 'model' AS kind, key FROM public.ai_gateway_aimodel WHERE is_active
        UNION ALL
        SELECT 'operation', key FROM public.ai_gateway_aioperation WHERE is_active;

    CREATE FUNCTION platform.set_ai_policy(
        actor uuid, tenant uuid, new_monthly_limit numeric, new_overage_authorised boolean,
        new_overage_limit numeric, new_max_cost_per_request numeric, new_max_output_tokens integer,
        new_user_daily_limit numeric, new_user_monthly_limit numeric,
        new_requests_per_minute integer, new_billing_anchor_day integer,
        new_allowed_models jsonb, new_allowed_operations jsonb, reason text
    ) RETURNS void {ATTRS} AS $$
    BEGIN
        PERFORM platform.require_superadmin(actor);
        PERFORM platform.require_reason(reason);
        IF new_monthly_limit < 0 OR new_overage_limit < 0 OR new_max_cost_per_request < 0
           OR new_billing_anchor_day NOT BETWEEN 1 AND 28 THEN
            RAISE EXCEPTION 'invalid AI policy' USING ERRCODE = '22023';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.tenants_tenant WHERE id = tenant) THEN
            RAISE EXCEPTION 'tenant not found' USING ERRCODE = 'P0002';
        END IF;
        INSERT INTO public.ai_gateway_aibudgetpolicy (
            id, tenant_id, currency, monthly_limit, overage_authorised, overage_limit,
            max_cost_per_request, max_output_tokens, user_daily_limit, user_monthly_limit,
            requests_per_minute, billing_anchor_day, allowed_models, allowed_operations, updated_at
        ) VALUES (
            gen_random_uuid(), tenant, 'USD', new_monthly_limit, new_overage_authorised,
            new_overage_limit, new_max_cost_per_request, new_max_output_tokens,
            new_user_daily_limit, new_user_monthly_limit, new_requests_per_minute,
            new_billing_anchor_day, new_allowed_models, new_allowed_operations, now()
        )
        ON CONFLICT (tenant_id) DO UPDATE SET
            monthly_limit = EXCLUDED.monthly_limit,
            overage_authorised = EXCLUDED.overage_authorised,
            overage_limit = EXCLUDED.overage_limit,
            max_cost_per_request = EXCLUDED.max_cost_per_request,
            max_output_tokens = EXCLUDED.max_output_tokens,
            user_daily_limit = EXCLUDED.user_daily_limit,
            user_monthly_limit = EXCLUDED.user_monthly_limit,
            requests_per_minute = EXCLUDED.requests_per_minute,
            billing_anchor_day = EXCLUDED.billing_anchor_day,
            allowed_models = EXCLUDED.allowed_models,
            allowed_operations = EXCLUDED.allowed_operations,
            updated_at = now();
        -- A change applies to the running period too.
        UPDATE public.ai_gateway_aibudget
            SET limit_amount = new_monthly_limit,
                overage_limit = CASE WHEN new_overage_authorised THEN new_overage_limit ELSE 0 END
            WHERE tenant_id = tenant AND now() >= period_start AND now() < period_end;
        PERFORM platform.record_event(actor, 'ai.policy.updated', tenant, reason,
            jsonb_build_object('monthly_limit', new_monthly_limit,
                               'overage_authorised', new_overage_authorised));
        PERFORM platform.record_tenant_mirror(tenant, actor, 'platform.ai.policy.updated', reason);
    END $$;

    CREATE FUNCTION platform.resolve_ai_reservation(
        actor uuid, reservation uuid, actual numeric, reason text
    ) RETURNS void {ATTRS} AS $$
    -- actual NULL: staff confirmed with the provider that nothing was charged.
    DECLARE
        held record;
    BEGIN
        PERFORM platform.require_superadmin(actor);
        PERFORM platform.require_reason(reason);
        IF actual < 0 THEN
            RAISE EXCEPTION 'invalid amount' USING ERRCODE = '22023';
        END IF;
        SELECT * INTO held FROM public.ai_gateway_aiusagereservation
            WHERE id = reservation FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'reservation not found' USING ERRCODE = 'P0002';
        END IF;
        IF NOT (held.status = 'unknown'
                OR (held.status = 'reserved' AND held.created_at < now() - interval '1 hour')) THEN
            RAISE EXCEPTION 'reservation is not uncertain' USING ERRCODE = '22023';
        END IF;
        PERFORM 1 FROM public.ai_gateway_aibudget WHERE id = held.budget_id FOR UPDATE;
        UPDATE public.ai_gateway_aibudget
            SET reserved = reserved - held.max_cost, spent = spent + coalesce(actual, 0)
            WHERE id = held.budget_id;
        UPDATE public.ai_gateway_aiusagereservation
            SET status = CASE WHEN actual IS NULL THEN 'released' ELSE 'committed' END,
                resolved_at = now()
            WHERE id = reservation;
        IF actual IS NOT NULL THEN
            INSERT INTO public.ai_gateway_aiusageevent (
                id, tenant_id, reservation_id, user_id, operation_id, model_id, pricing_id,
                prompt_id, status, input_tokens, cached_tokens, cache_write_30m_tokens,
                cache_write_12h_tokens, output_tokens, provider_usage, provider_request_id,
                estimated_cost, actual_cost, currency, latency_ms, retry_count, is_synthetic,
                created_at
            ) VALUES (
                gen_random_uuid(), held.tenant_id, held.id, held.user_id, held.operation_id,
                held.model_id, held.pricing_id, held.prompt_id, 'usage_missing',
                0, 0, 0, 0, 0, '{{}}'::jsonb, '', held.max_cost, actual, held.currency,
                0, 0, false, now()
            );
        END IF;
        PERFORM platform.record_event(actor, 'ai.reservation.resolved', held.tenant_id, reason,
            jsonb_build_object('reservation', held.id, 'actual', actual));
        PERFORM platform.record_tenant_mirror(
            held.tenant_id, actor, 'platform.ai.reservation.resolved', reason);
    END $$;

    CREATE FUNCTION platform.record_ai_reconciliation(
        actor uuid, provider text, starts timestamptz, ends timestamptz, reported numeric,
        reported_currency text, note text
    ) RETURNS numeric {ATTRS} AS $$
    DECLARE
        calculated numeric;
    BEGIN
        PERFORM platform.require_superadmin(actor);
        IF ends <= starts OR reported < 0 THEN
            RAISE EXCEPTION 'invalid reconciliation' USING ERRCODE = '22023';
        END IF;
        SELECT coalesce(sum(e.actual_cost), 0) INTO calculated
            FROM public.ai_gateway_aiusageevent e
            JOIN public.ai_gateway_aimodel m ON m.key = e.model_id
            WHERE m.provider_id = provider AND e.currency = reported_currency
              AND e.created_at >= starts AND e.created_at < ends;
        INSERT INTO public.ai_gateway_aiproviderreconciliation (
            id, provider_id, period_start, period_end, currency, reported_cost,
            calculated_cost, note, recorded_by_id, recorded_at
        ) VALUES (
            gen_random_uuid(), provider, starts, ends, reported_currency, reported,
            calculated, coalesce(note, ''), actor, now()
        );
        PERFORM platform.record_event(actor, 'ai.reconciliation.recorded', NULL, note,
            jsonb_build_object('provider', provider, 'reported', reported,
                               'calculated', calculated));
        RETURN calculated;
    END $$;

    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA platform FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION platform.mask_email(text) TO aai_platform;
    GRANT EXECUTE ON FUNCTION
        platform.record_event(uuid, text, uuid, text, jsonb),
        platform.set_tenant_status(uuid, uuid, text, text),
        platform.create_tenant(uuid, text, text, text),
        platform.set_ai_policy(uuid, uuid, numeric, boolean, numeric, numeric, integer, numeric,
                               numeric, integer, integer, jsonb, jsonb, text),
        platform.resolve_ai_reservation(uuid, uuid, numeric, text),
        platform.record_ai_reconciliation(uuid, text, timestamptz, timestamptz, numeric, text, text)
        TO aai_platform;
    GRANT EXECUTE ON FUNCTION platform.record_event(uuid, text, uuid, text, jsonb) TO aai_owner;
    GRANT SELECT ON platform.ai_tenant_usage, platform.ai_cost_breakdown,
        platform.ai_uncertain_reservations, platform.ai_reconciliations, platform.ai_catalog
        TO aai_platform;

    RESET ROLE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("platform_admin", "0001_platform_schema"),
        ("ai_gateway", "0002_row_level_security"),
    ]

    operations = [
        migrations.RunSQL(DEFINER_ACCESS, migrations.RunSQL.noop),
        migrations.RunSQL(PLATFORM_OBJECTS, migrations.RunSQL.noop),
    ]
