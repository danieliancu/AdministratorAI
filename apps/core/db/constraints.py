from django.db.models import BaseConstraint


class TenantFK(BaseConstraint):
    """Composite foreign key (tenant_id, field) -> to_table (tenant_id, id).

    Pair it with a ForeignKey(db_constraint=False). A single-column key would let one
    tenant reference another tenant's row, and its check bypasses RLS, so it would also
    reveal whether a foreign id exists.
    """

    def __init__(self, *, column, to_table, name):
        self.column = column
        self.to_table = to_table
        super().__init__(name=name)

    def _definition(self):
        return (
            f"FOREIGN KEY (tenant_id, {self.column}) REFERENCES {self.to_table} (tenant_id, id)"
            " DEFERRABLE INITIALLY DEFERRED"
        )

    def constraint_sql(self, model, schema_editor):
        return f"CONSTRAINT {self.name} {self._definition()}"

    def create_sql(self, model, schema_editor):
        table = model._meta.db_table
        return f"ALTER TABLE {table} ADD CONSTRAINT {self.name} {self._definition()}"

    def remove_sql(self, model, schema_editor):
        return f"ALTER TABLE {model._meta.db_table} DROP CONSTRAINT {self.name}"

    def validate(self, model, instance, exclude=None, using=None):
        return None

    def deconstruct(self):
        path = f"{self.__class__.__module__}.{self.__class__.__name__}"
        return path, [], {"column": self.column, "to_table": self.to_table, "name": self.name}

    def __eq__(self, other):
        return isinstance(other, TenantFK) and self.deconstruct() == other.deconstruct()

    __hash__ = None
