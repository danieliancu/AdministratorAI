from django.db import migrations

from apps.core.db.operations import EnableTenantRLS, GrantGlobal

BUDGET_FROM_POLICY = """
    -- The application only asks for a budget row: the limits always come from the policy,
    -- which it cannot write, so no bug can grant itself more money.
    CREATE FUNCTION app.ai_budget_from_policy() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        policy record;
    BEGIN
        SELECT monthly_limit, overage_authorised, overage_limit, currency INTO policy
            FROM ai_gateway_aibudgetpolicy WHERE tenant_id = NEW.tenant_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'no AI policy for this tenant' USING ERRCODE = '42501';
        END IF;
        NEW.limit_amount := policy.monthly_limit;
        NEW.overage_limit := CASE WHEN policy.overage_authorised
                                  THEN policy.overage_limit ELSE 0 END;
        NEW.currency := policy.currency;
        NEW.spent := 0;
        NEW.reserved := 0;
        RETURN NEW;
    END $$;
    CREATE TRIGGER ai_budget_limits BEFORE INSERT ON ai_gateway_aibudget
        FOR EACH ROW EXECUTE FUNCTION app.ai_budget_from_policy();
"""

IMMUTABLE = """
    CREATE FUNCTION app.immutable_row() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME USING ERRCODE = '42501';
    END $$;
    CREATE TRIGGER ai_pricing_immutable BEFORE UPDATE OR DELETE ON ai_gateway_aimodelpricing
        FOR EACH ROW EXECUTE FUNCTION app.immutable_row();
    CREATE TRIGGER ai_event_immutable BEFORE UPDATE OR DELETE ON ai_gateway_aiusageevent
        FOR EACH ROW EXECUTE FUNCTION app.immutable_row();

    CREATE FUNCTION app.prompt_text_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' OR NEW.system_template IS DISTINCT FROM OLD.system_template
           OR NEW.user_template IS DISTINCT FROM OLD.user_template
           OR NEW.version IS DISTINCT FROM OLD.version
           OR NEW.operation_id IS DISTINCT FROM OLD.operation_id THEN
            RAISE EXCEPTION 'prompt versions are immutable' USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER ai_prompt_immutable BEFORE UPDATE OR DELETE
        ON ai_gateway_prompttemplateversion
        FOR EACH ROW EXECUTE FUNCTION app.prompt_text_immutable();
"""

# Standard policies come from EnableTenantRLS. These narrow what the application may do.
NARROW_GRANTS = """
    REVOKE INSERT, UPDATE, DELETE ON ai_gateway_aibudgetpolicy FROM aai_app;
    REVOKE UPDATE, DELETE ON ai_gateway_aibudget FROM aai_app;
    GRANT UPDATE (spent, reserved) ON ai_gateway_aibudget TO aai_app;
    REVOKE UPDATE, DELETE ON ai_gateway_aibudgetalert FROM aai_app;
    REVOKE UPDATE, DELETE ON ai_gateway_aiusagereservation FROM aai_app;
    GRANT UPDATE (status, failure_reason, resolved_at) ON ai_gateway_aiusagereservation TO aai_app;
    REVOKE UPDATE, DELETE ON ai_gateway_aiusageevent FROM aai_app;
    REVOKE UPDATE ON ai_gateway_aistoredresponse FROM aai_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_app_schema"),
        ("ai_gateway", "0001_initial"),
    ]

    operations = [
        EnableTenantRLS("ai_gateway_aibudgetpolicy"),
        EnableTenantRLS("ai_gateway_aibudget"),
        EnableTenantRLS("ai_gateway_aibudgetalert"),
        EnableTenantRLS("ai_gateway_aiusagereservation"),
        EnableTenantRLS("ai_gateway_aiusageevent"),
        EnableTenantRLS("ai_gateway_aistoredresponse"),
        migrations.RunSQL(NARROW_GRANTS, migrations.RunSQL.noop),
        migrations.RunSQL(BUDGET_FROM_POLICY, migrations.RunSQL.noop),
        migrations.RunSQL(IMMUTABLE, migrations.RunSQL.noop),
        GrantGlobal("ai_gateway_aiprovider", "SELECT"),
        GrantGlobal("ai_gateway_aimodel", "SELECT"),
        GrantGlobal("ai_gateway_aimodelpricing", "SELECT"),
        GrantGlobal("ai_gateway_aioperation", "SELECT"),
        GrantGlobal("ai_gateway_prompttemplateversion", "SELECT"),
    ]
