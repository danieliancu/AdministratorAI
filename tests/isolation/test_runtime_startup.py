from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def test_runtime_role_can_compare_migrations_without_a_scope(committed_db):
    """runserver does this at startup, as the restricted role and outside any scope."""
    executor = MigrationExecutor(connection)
    assert executor.migration_plan(executor.loader.graph.leaf_nodes()) == []
