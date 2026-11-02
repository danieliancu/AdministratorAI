# Architecture overview

Administrator AI is a Django modular monolith. Pages are server-rendered, with HTMX for partial updates and Alpine.js for small interactions. There is no JavaScript application.

## Implemented apps

| App | Responsibility |
|---|---|
| `apps.core` | `db_scope`, database guards, migration operations, middleware, throttling, task base classes |
| `apps.accounts` | User model, authentication, registration, password reset, platform grants |
| `apps.tenants` | Tenants, memberships, roles and capabilities, invitations, settings, fiscal profile |
| `apps.audit` | Append-only event tables and the recording API |
| `apps.platform_admin` | The `/platform/` area, on its own database role |

## Request flow

The first URL namespace decides the database scope, in `DbScopeMiddleware`:

| Namespace | Path | Database scope |
|---|---|---|
| `public` | `/`, `/autentificare/` | None. Services open narrow scopes |
| `account` | `/cont/` | The signed-in user, no tenant |
| `tenant` | `/t/<uuid>/` | The tenant and the user, after checking membership and capability |
| `platform` | `/platform/` | The `platform` connection for data; the user's scope only to read the grant |

A route in no namespace raises an error. Views render inside the scope, so lazy template queries still have their context.

## Services

| Service | Role | Purpose |
|---|---|---|
| `db` | superuser | PostgreSQL 18 with pgvector |
| `dbinit` | superuser | Idempotent role setup, on every start |
| `migrate` | `aai_owner` | One-shot migrations, the only runtime holder of owner credentials |
| `web` | `aai_app`, `aai_platform` | Requests |
| `worker`, `beat` | `aai_app` | Background tasks |
| `redis` | | Celery broker and throttle counters |
| `mailpit` | | Development email |
