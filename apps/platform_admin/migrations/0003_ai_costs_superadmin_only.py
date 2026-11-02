from django.db import migrations

ROLE = "aai_platform_definer"
ATTRS = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

# AI consumption and limits belong to platform staff only, so these actions no longer write
# a tenant-visible mirror event. Alerts move here from the tenant's page.
OBJECTS = f"""
    GRANT SELECT ON ai_gateway_aibudgetalert TO {ROLE};
    CREATE POLICY aialert_sel_platform ON ai_gateway_aibudgetalert FOR SELECT TO {ROLE}
        USING (true);

    SET LOCAL ROLE {ROLE};

    CREATE VIEW platform.ai_alerts WITH (security_barrier) AS
        SELECT a.tenant_id, b.period_start, max(a.threshold) AS highest_threshold
        FROM public.ai_gateway_aibudgetalert a
        JOIN public.ai_gateway_aibudget b ON b.id = a.budget_id
        WHERE now() >= b.period_start AND now() < b.period_end
        GROUP BY 1, 2;
    GRANT SELECT ON platform.ai_alerts TO aai_platform;

    CREATE OR REPLACE FUNCTION platform.set_ai_policy(
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
        UPDATE public.ai_gateway_aibudget
            SET limit_amount = new_monthly_limit,
                overage_limit = CASE WHEN new_overage_authorised THEN new_overage_limit ELSE 0 END
            WHERE tenant_id = tenant AND now() >= period_start AND now() < period_end;
        PERFORM platform.record_event(actor, 'ai.policy.updated', tenant, reason,
            jsonb_build_object('monthly_limit', new_monthly_limit,
                               'overage_authorised', new_overage_authorised));
    END $$;

    CREATE OR REPLACE FUNCTION platform.resolve_ai_reservation(
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
    END $$;

    RESET ROLE;
"""


class Migration(migrations.Migration):
    dependencies = [("platform_admin", "0002_ai_costs")]

    operations = [migrations.RunSQL(OBJECTS, migrations.RunSQL.noop)]
