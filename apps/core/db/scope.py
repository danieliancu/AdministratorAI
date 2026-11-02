from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.db import connections, transaction


class UnscopedQuery(Exception):
    pass


class ScopeViolation(Exception):
    pass


@dataclass(frozen=True)
class Scope:
    tenant_id: object = None
    user_id: object = None
    lookup_email: str | None = None
    invite_token_hash: str | None = None


EMPTY = Scope()
_scope: ContextVar[Scope | None] = ContextVar("aai_db_scope", default=None)


def current_scope():
    return _scope.get()


def _text(value):
    return "" if value is None else str(value)


def _apply(using, scope):
    connection = connections[using]
    if not connection.in_atomic_block:
        # A transaction-local setting would be lost at once, leaving the query context-free.
        raise ScopeViolation("Database scope can only be applied inside a transaction")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true),"
            " set_config('app.user_id', %s, true),"
            " set_config('app.lookup_email', %s, true),"
            " set_config('app.invite_token_hash', %s, true)",
            [
                _text(scope.tenant_id),
                _text(scope.user_id),
                _text(scope.lookup_email),
                _text(scope.invite_token_hash),
            ],
        )


@contextmanager
def db_scope(
    *, tenant_id=None, user_id=None, lookup_email=None, invite_token_hash=None, using="default"
):
    previous = _scope.get()
    if previous is not None and previous.tenant_id is not None:
        if str(previous.tenant_id) != _text(tenant_id):
            raise ScopeViolation("A tenant scope cannot be left or replaced while it is open")
    scope = Scope(tenant_id, user_id, lookup_email, invite_token_hash)
    with transaction.atomic(using=using):
        _apply(using, scope)
        token = _scope.set(scope)
        try:
            yield scope
        finally:
            _scope.reset(token)
    # Releasing a savepoint keeps transaction-local settings, so an enclosing
    # transaction must get its own context back. An exception skips this line:
    # rolling back to the savepoint has already reverted them.
    if connections[using].in_atomic_block:
        _apply(using, previous or EMPTY)
