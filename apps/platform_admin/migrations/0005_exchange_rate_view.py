from django.db import migrations

ROLE = "aai_platform_definer"

OBJECTS = f"""
    GRANT SELECT ON ai_gateway_aiexchangerate TO {ROLE};
    SET ROLE {ROLE};

    CREATE VIEW platform.ai_usd_ron_rate WITH (security_barrier) AS
        SELECT rate, effective_date, source_url
        FROM public.ai_gateway_aiexchangerate
        WHERE base_currency = 'USD' AND quote_currency = 'RON'
        ORDER BY effective_date DESC
        LIMIT 1;

    GRANT SELECT ON platform.ai_usd_ron_rate TO aai_platform;

    RESET ROLE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("platform_admin", "0004_legal_sources"),
        ("ai_gateway", "0006_assistant_operation"),
    ]

    operations = [migrations.RunSQL(OBJECTS, migrations.RunSQL.noop)]
