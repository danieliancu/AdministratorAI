# Tenant isolation

## What protects what

| Threat | Protection |
|---|---|
| A view forgets to filter by tenant | RLS, in the database |
| A view forgets to open a scope | Middleware opens it from the URL, and the query guard raises on unscoped queries |
| Missing context | Policies compare to NULL: no rows returned, inserts refused |
| The table owner reads through RLS | `FORCE ROW LEVEL SECURITY` |
| Context leaks between pooled connections | Only transaction-local settings; verified through PgBouncer |
| A row points at another tenant's row | Composite foreign keys |
| Probing whether a foreign ID exists | Composite keys make foreign and missing IDs fail alike; non-members and missing tenants get the same 404 |
| A bug adds someone as Owner | Membership insert trigger |
| A new table is left unprotected | No default privileges, plus catalog tests |
| Staff browse private data | Staff role has masked views only, with no table access |

## What it does not protect

- **Injected SQL.** It could set any tenant context. Parameterised queries and role grants carry that risk.
- **The owner role.** It can disable RLS, so its credentials are kept out of `web` and `worker`.
- **A wrong tenant ID passed to `db_scope` by application code.** The database cannot tell. Requests have a single entry point, and the membership trigger limits the worst case.
- **Non-PostgreSQL stores.** Redis holds throttle counters only today. File storage, logs and future caches need their own rules.

## How the proof works

Tests create the database as the owner, then demote every connection to `aai_app`, so they cannot pass on owner privileges.

- `tests/isolation/test_harness.py`: confirms the role, and a negative control shows RLS is what hides the rows.
- `tests/isolation/test_catalog.py`: reads the PostgreSQL catalog for missing RLS, policies and unsafe grants.
- `tests/isolation/test_matrix.py`: read, modify, export and discover on every tenant table, plus concurrency.
- `tests/isolation/test_http.py`, `test_platform.py`, `test_celery.py`: the same guarantees through HTTP, platform pages and tasks.

Deliberately weakening a policy or `db_scope` makes the suite fail. See the mutation results in the progress document.

## Rules for new code

1. A tenant table inherits `TenantOwnedModel`, gets `EnableTenantRLS` in a migration, and is added to the manifest.
2. Backfills use one tenant scope at a time, because under forced RLS a bare `RunPython` silently sees zero rows.
3. A tenant view declares `@requires(capability)`.
4. Slow work goes to Celery through `enqueue()`, because a request holds a transaction while rendering.
5. Streaming responses are refused inside a tenant scope.
