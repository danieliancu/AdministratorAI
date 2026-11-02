# Implementation progress

Status reflects what has actually been run. Anything not listed as run is untested.

## Milestone 1: SaaS foundation (in progress)

### Increment 0: scaffolding (written, not yet run)

Written: Compose stack, Dockerfile, split settings, database role setup, runtime role guard, health endpoints.

Tests executed: **none**. Python and Docker were not runnable when these files were written, because WSL was waiting for a Windows restart. No file has been parsed, linted or started.

To verify once Docker runs:

- The stack starts within its memory limits on the 8 GB development machine.
- `web` refuses to start with `aai_owner` credentials.
- `pytest-django` 4.14 works with Django 6.1. It declares support for Django 5.2 and 6.0 only.
- `redis:8-alpine` and `axllent/mailpit:v1.27` tags resolve. These two tags were not checked; `pgvector/pgvector:0.8.6-pg18` was.
- Dependency versions are locked. `requirements*.txt` currently use ranges.

Known limitations:

- Git commits have not been made because no commit identity is configured.
