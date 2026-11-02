# Administrator AI

Multi-tenant SaaS for Romanian small and medium businesses, built as a Django modular monolith with server-rendered templates, HTMX and Alpine.js on PostgreSQL.

**Status:** Milestones 1, 2, 3 and 5: SaaS foundation, AI gateway, legal knowledge infrastructure, financial application. No real AI provider has been called, and the fiscal corpus has no consolidated text yet. Tax rules, the fiscal calendar, the assistant and billing are not built. See [docs/implementation-progress.md](docs/implementation-progress.md). The application is not production ready.

## Run it locally

Requires Docker Desktop and Git.

```powershell
Copy-Item .env.example .env   # then replace every change-me value with a long random string
docker compose up -d --wait
docker compose exec web python manage.py seed_dev
docker compose run --rm migrate python manage.py grant_platform_role superadmin superadmin --reason "dev seed"
docker compose run --rm migrate python manage.py seed_ai_dev   # fake AI provider, invented prices
```

| Address | What it is |
|---|---|
| http://localhost:8000/ | Public landing page |
| http://localhost:8000/autentificare/ | Login, shared by everyone |
| http://localhost:8000/t/&lt;uuid&gt;/ | A tenant's dashboard |
| http://localhost:8000/platform/ | Platform administration |
| http://localhost:8025/ | Mailpit: emails sent in development |

`seed_dev` creates two development accounts, both with the password `1234`. It refuses to run outside the development settings. `docker compose exec web python manage.py seed_finance_dev` adds fictional invoices, expenses and products to the demo firm, under the same restriction.

| Login | Access |
|---|---|
| `admin` | Owner of the fictional tenant "Firmă Demo SRL (fictivă)" |
| `superadmin` | Platform superadmin, member of no tenant |

## Tests

```powershell
docker compose run --rm test pytest                        # runs as the restricted aai_app role
docker compose --profile pooling run --rm pgbouncer-smoke  # RLS through PgBouncer, needs seed_dev
docker compose --profile e2e run --rm e2e                  # real browser, needs seed and platform grant
docker compose run --rm --no-deps test ruff check .
```

The browser test adds its own fictional users and firms to the development database, and suspends one firm per run.

## Local Python

The full stack runs in Docker because Celery does not support Windows. For local commands, with the containers running:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements.lock
. .\scripts\dev-env.ps1
python manage.py check
```

## Documentation

- [Architecture overview](docs/architecture/overview.md), [decisions](docs/architecture/decisions.md), [data model](docs/architecture/data-model.md)
- [Tenant isolation](docs/security/tenant-isolation.md), [AI cost accounting](docs/ai/cost-accounting.md)
- [Legal sources](docs/legal/source-registry.md), [legal versioning](docs/legal/versioning.md)
- [Deployment](docs/operations/deployment.md), [backup and restore](docs/operations/backup-restore.md)
- [Implementation progress](docs/implementation-progress.md)

The tax rule and ANAF documents record requirements for later milestones and describe no working code.
