# Architecture decisions

## No `ATOMIC_REQUESTS`

It wraps only the view callable, so `TemplateResponse` rendering would run outside the transaction and lose the tenant context. `db_scope` is opened by middleware and covers rendering. A system check keeps it off.

## Tenant in the URL

`/t/<uuid>/`, not in the session or a subdomain. With a session-selected tenant, an accountant with two tabs open could post into the wrong firm. Subdomains need wildcard TLS and expose tenant names.

## No auto-filtering tenant manager

It would hide broken RLS, because tests would pass on the ORM filter alone. RLS is the only row filter.

## A separate role for platform pages, not a setting

A session flag could be set by any injected SQL. `aai_platform` has no table access at all, only masked views and audited functions.

## Three audit tables

A shared table with a nullable tenant would mix access rules. Tenant events follow RLS, security events are insert-only for the application, and platform events are unreachable for it.

## Audit: no `db_default`

It adds `RETURNING` to inserts, which needs `SELECT` and would break insert-only tables.

## Repository stays on the Windows filesystem

Moving it into WSL would be faster, but this path is what the development session and editor use. Django's polling reloader works here. Revisit if it becomes slow.

## Password hash on the user row

Inside a tenant scope, the ORM can read colleagues' password hashes, because `accounts_user` is visible to members of the same tenant. Templates never show them. A separate credentials table would close this and is cleaner, and should be revisited before production.

## The seed account holds a non-email identifier

`admin` was requested as the development login. Registration validates real emails, so only the seed account can hold a value without `@`, and password reset ignores it.

## Runtime grants for platform access

`accounts_platformgrant` can be written only with owner credentials, through `grant_platform_role`. No application bug can promote a user to staff.

## Versions

- Django 6.1, moving to the 6.2 LTS after its planned April 2027 release.
- Python 3.13.
- HTMX 2.0.4 rather than the newer 4.0 major version, chosen as the conservative option and not evaluated against 4.0.
- `pytest-django` 4.14 does not declare Django 6.1 support, but this suite runs on it.

## `SECURE_HSTS_PRELOAD` off

Joining browser preload lists is hard to undo, so it should be decided on the final domain.

## AI consumption is visible to the superadmin only

A product decision: firms do not see their own AI consumption, costs, limits or alerts, and neither does the Support role. Platform actions on AI policy therefore write no tenant-visible audit event, unlike tenant suspension. `aai_app` must still read budget and usage tables to enforce limits, so this is enforced by routes and capabilities, not by the database. When the assistant is built in Milestone 6, its refusal messages must not reveal amounts or limits.
