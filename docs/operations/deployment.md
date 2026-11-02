# Deployment

**No production deployment exists, and none is permitted yet.** Milestone 8 sets the release gates: security review, backup testing, monitoring, legal data access review and fiscal specialist validation.

## Verified so far

- `gunicorn` starts with `config.settings.prod`, and `/healthz/` and `/readyz/` answer.
- `check --deploy` reports only `SECURE_HSTS_PRELOAD`, which is left off deliberately.

## Requirements already known

- Roles come from `ops/db/roles.sql`. Set `AAI_OWNER_CREATEDB` to false in production.
- Run migrations from a one-shot job holding owner credentials. `web` and `worker` must never receive them, and they refuse to start with them.
- Only `web` gets `AAI_PLATFORM_DB_PASSWORD`.
- Run `collectstatic` at build time: Compose development does not.
- Never run `seed_dev`. It refuses without development settings.
- Required settings: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `MAIL_HOST`, and the database and Redis variables.
- The proxy must set `X-Forwarded-Proto`, and clients must not be able to set it themselves.

## Operational checks

`tenants.record_context_probe` writes a `diagnostic.worker_context` event in a chosen tenant, which confirms a worker receives tenant context.
