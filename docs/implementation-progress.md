# Implementation progress

Status reflects what has actually been run. Anything not listed as run is untested.

## Milestone 1: SaaS foundation (in progress, not accepted)

| Increment | State |
|---|---|
| 0 Compose, settings, role guard | Done, run |
| 1 User model, `app` schema, grants | Done, run |
| 2 Test harness as `aai_app`, negative control | Done, run |
| 3 `db_scope`, query guard | Done, run |
| 4 Tenant models, RLS, catalog tests | Done, run |
| 5 `TenantFK`, system check | Done, run |
| 6 Scope middleware, dashboard, base template | Done, run |
| 7 Registration, verification, login, reset, throttling | Done, run. Password reset has no end-to-end test yet |
| 8 Tenant creation, settings, fiscal profile, invitations | Done, run. Concurrency races not yet tested |
| 9 Audit tables and triggers | Not started |
| 10 Celery context API | Not started. Email is still sent inside the request |
| 11 `/platform/` | Not started |
| 12 Design system, landing page | Partial: tokens and app shell exist; landing page is a placeholder; HTMX, Alpine and Chart.js not yet added |
| 13 Full isolation matrix, PgBouncer, E2E, docs | Not started |

### Verified by running

- `docker compose up -d --wait`: all services healthy; about 230 MiB in use at idle.
- `pytest` in the `test` service as `aai_app`: see the last run below.
- Real HTTP against `runserver`: login as the seed account, dashboard, fiscal profile, members and settings answer 200; a wrong password stays on the form; an unknown tenant answers 404; anonymous access redirects to login.
- `web` refuses the owner role at connection time.
- The local `.venv` runs `manage.py check` and connects as `aai_app`.
- `pytest-django` 4.14 works with Django 6.1.2 for everything in this suite, although it does not declare 6.1.

### Defects found by running

- `runserver` failed at startup: its migration check was blocked by the query guard, and `aai_app` could not read `django_migrations`. Fixed, with a regression test in `tests/isolation/test_runtime_startup.py`.
- The negative control test first passed nothing useful because it ran inside the suite's wrapping transaction. It now uses committed data.

### Development seed

`docker compose exec web python manage.py seed_dev` creates the fictional tenant "Firmă Demo SRL (fictivă)" and the account `admin` / `1234` with the Owner role. It runs as `aai_app` through the normal services. It refuses to run unless `DEBUG` and `AAI_ALLOW_DEV_SEED` are both on, which only `config.settings.dev` sets. The account deliberately skips the password policy and must never exist outside local development.

### Known limitations

- `requirements*.txt` use version ranges; there is no lock file yet.
- Marketing claims from the design reference are not on the placeholder landing page yet.
- No audit trail exists yet, so nothing is logged for security review.
- `web` runs the development server in Compose. Gunicorn is the Dockerfile default and has not been run.
- CI is not written.
