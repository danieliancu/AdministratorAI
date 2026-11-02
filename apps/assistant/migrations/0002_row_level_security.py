from django.db import migrations

from apps.core.db.operations import CURRENT_TENANT, RUNTIME_ROLES, EnableRLS

CURRENT_USER = "(SELECT app.current_user_id())"
TABLE = "assistant_assistantmessage"
MINE = f"tenant_id = {CURRENT_TENANT} AND user_id = {CURRENT_USER}"


class Migration(migrations.Migration):
    dependencies = [("assistant", "0001_initial")]

    operations = [
        EnableRLS(TABLE),
        # A question is private: colleagues in the same firm cannot read it.
        migrations.RunSQL(
            f"""
            CREATE POLICY assistant_sel ON {TABLE} FOR SELECT TO {RUNTIME_ROLES} USING ({MINE});
            CREATE POLICY assistant_ins ON {TABLE} FOR INSERT TO {RUNTIME_ROLES}
                WITH CHECK ({MINE});
            CREATE POLICY assistant_upd ON {TABLE} FOR UPDATE TO {RUNTIME_ROLES}
                USING ({MINE}) WITH CHECK ({MINE});
            CREATE POLICY assistant_del ON {TABLE} FOR DELETE TO {RUNTIME_ROLES} USING ({MINE});
            GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO aai_app;
            """,
            reverse_sql=f"""
            REVOKE ALL ON {TABLE} FROM aai_app;
            DROP POLICY assistant_del ON {TABLE};
            DROP POLICY assistant_upd ON {TABLE};
            DROP POLICY assistant_ins ON {TABLE};
            DROP POLICY assistant_sel ON {TABLE};
            """,
        ),
    ]
