# Implementation progress

Status reflects what has actually been run. Anything not listed as run is untested.

## Milestone 1: SaaS foundation

**State: acceptance criteria met in local development. Not a production release.**

A user can register, verify their email, create a firm or join one by invitation, and use the tenant dashboard. Cross-tenant isolation tests pass.

### Implemented

- Compose stack: PostgreSQL 18 with pgvector, Redis, web, Celery worker and Beat, Mailpit, plus PgBouncer and browser test profiles.
- Database roles `aai_owner`, `aai_app`, `aai_platform`, `aai_platform_definer`, with a guard that refuses unsafe runtime roles.
- `aai_maint` from the plan is not created: nothing uses it until backups exist in Milestone 8.
- Forced row-level security on all tenant, identity and audit tables, opened through `db_scope` from the URL namespace.
- Registration, email verification, login, logout, password reset, throttling.
- Tenants, memberships, roles and capabilities, invitations, settings, fiscal profile (user-declared, unverified).
- Append-only audit tables.
- Celery tasks that must declare a scope, with tenant context carried explicitly.
- `/platform/`: overview, tenants (search, create, suspend, reactivate), users, audit log. Data is masked at source. There is no impersonation.
- Landing page and application shell in Romanian, following the design reference.

### Migrations

`core` 0001–0003, `accounts` 0001–0002, `tenants` 0001–0002, `audit` 0001–0002, `platform_admin` 0001. Applied to the development database.

### Tests executed on 2 November 2026

| Check | Result |
|---|---|
| `pytest` as `aai_app` | 125 passed (see the note on the last run below) |
| Mutation: permissive tenant SELECT policy | Suite failed, 14 tests |
| Mutation: identity mode sees every tenant | Suite failed, 4 tests |
| Mutation: `db_scope` stops restoring context | Suite failed, 1 test |
| PgBouncer smoke, transaction mode, one backend | 150 alternating transactions, no context carried over |
| Real Celery worker through Redis | Task received the tenant context and wrote to the right tenant |
| Browser flow in Chromium | Passed: register, verify, firm, invite, join, 403 by role, 404 for an outsider, HTMX search, suspend, audit log |
| Landing page at 400 px | No horizontal scroll |
| `ruff check` | Clean |
| `makemigrations --check` | No changes |
| `pip-audit` on `requirements.lock` | No known vulnerabilities |
| Secret check | The generated `.env` application password appears nowhere in git history |
| `gunicorn` with production settings | `/healthz/` and `/readyz/` answered |
| `check --deploy` | Only `SECURE_HSTS_PRELOAD`, left off deliberately: see decisions |

The mutations were reverted after each run.

### Defects found by running

Each of these passed the unit tests at the time, and a regression test now covers the first two.

- `runserver` failed at startup: the query guard blocked its migration check, and `aai_app` could not read `django_migrations`.
- `enqueue()` failed on Celery's real send path: Celery validated the context kwargs against the task signature. The earlier test had patched `apply_async`.
- `aai_platform` needed `EXECUTE` on `mask_email`: functions inside a view are checked against the querying role.
- Production settings sent email to the console. Found by `check --deploy`.

### Security considerations

- RLS protects against application bugs. Injected SQL could set any tenant context, so that risk rests on parameterised queries and on role grants, which are separate from RLS.
- The table owner can always disable RLS, so `aai_owner` credentials exist only in the migrate and test containers.
- Colleagues' password hashes are readable at ORM level inside a tenant scope. See decisions.
- The development accounts use the password `1234`. `seed_dev` refuses to run outside development settings.

### Known limitations

- Emails are sent inside the request, not through Celery, so a mail server outage fails or slows the request.
- MFA, data export and deletion, and retention settings are not built.
- No Content-Security-Policy header. The Alpine build needs `unsafe-eval`, so this needs a decision.
- The admin cannot yet change member roles or remove members; only invitations exist.
- Platform "Create tenant" requires the owner to already have an account.
- The landing page has no photographs: the ones in the design reference are not usable assets.
- The price on the landing page is provisional text from the design reference.
- CI is written but has never run, because there is no remote.
- `mypy` is not configured.
- Docker Desktop lists Windows 10 22H2 only while it is within Microsoft's servicing timeline, so this machine may stop receiving updates.

### Remaining dependencies

None for local development. Production needs hosting, a mail provider and the Milestone 8 gates.

### Next: Milestone 2, AI gateway and cost control

Buildable and testable with a fake provider. Real calls need an OpenAI API key.
