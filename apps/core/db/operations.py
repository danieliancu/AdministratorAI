from django.db import migrations

RUNTIME_ROLES = "aai_app, aai_owner"
CURRENT_TENANT = "(SELECT app.current_tenant_id())"


class EnableRLS(migrations.RunSQL):
    """Turn on enforced RLS. The caller supplies the policies."""

    def __init__(self, table):
        self.table = table
        super().__init__(
            sql=f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"
            f" ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
            reverse_sql=f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;"
            f" ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
        )

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.table], {})


class EnableTenantRLS(migrations.RunSQL):
    """Standard tenant table: one policy per command, with full DML for aai_app."""

    def __init__(self, table, tenant_column="tenant_id"):
        self.table = table
        self.tenant_column = tenant_column
        match = f"{tenant_column} = {CURRENT_TENANT}"
        super().__init__(
            sql=f"""
                ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
                CREATE POLICY {table}_sel ON {table} FOR SELECT TO {RUNTIME_ROLES}
                    USING ({match});
                CREATE POLICY {table}_ins ON {table} FOR INSERT TO {RUNTIME_ROLES}
                    WITH CHECK ({match});
                CREATE POLICY {table}_upd ON {table} FOR UPDATE TO {RUNTIME_ROLES}
                    USING ({match}) WITH CHECK ({match});
                CREATE POLICY {table}_del ON {table} FOR DELETE TO {RUNTIME_ROLES}
                    USING ({match});
                GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO aai_app;
            """,
            reverse_sql=f"""
                REVOKE ALL ON {table} FROM aai_app;
                DROP POLICY {table}_del ON {table};
                DROP POLICY {table}_upd ON {table};
                DROP POLICY {table}_ins ON {table};
                DROP POLICY {table}_sel ON {table};
                ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
            """,
        )

    def deconstruct(self):
        return (
            self.__class__.__qualname__,
            [self.table],
            {"tenant_column": self.tenant_column},
        )


class GrantGlobal(migrations.RunSQL):
    """Grant the runtime role access to a table that holds no tenant data."""

    def __init__(self, table, privileges):
        self.table = table
        self.privileges = privileges
        super().__init__(
            sql=f"GRANT {privileges} ON {table} TO aai_app;",
            reverse_sql=f"REVOKE {privileges} ON {table} FROM aai_app;",
        )

    def deconstruct(self):
        return (self.__class__.__qualname__, [self.table, self.privileges], {})
