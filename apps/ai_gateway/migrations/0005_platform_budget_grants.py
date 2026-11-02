from django.db import migrations

GRANTS = """
    GRANT SELECT ON ai_gateway_aiprovider, ai_gateway_aimodel, ai_gateway_aimodelpricing
        TO aai_legal;
    GRANT SELECT, INSERT ON ai_gateway_aiplatformbudget, ai_gateway_aiplatformusage TO aai_legal;
    GRANT UPDATE (spent, reserved) ON ai_gateway_aiplatformbudget TO aai_legal;
    GRANT UPDATE (status, actual_cost, input_tokens, is_synthetic, latency_ms)
        ON ai_gateway_aiplatformusage TO aai_legal;
"""


class Migration(migrations.Migration):
    dependencies = [("ai_gateway", "0004_aiplatformbudget_aiplatformusage")]

    operations = [migrations.RunSQL(GRANTS, migrations.RunSQL.noop)]
