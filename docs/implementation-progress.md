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
| `pytest` as `aai_app` | 125 passed |
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
- CI first ran after the repository reached GitHub on 2 November 2026. See Milestone 5.
- `mypy` is not configured.
- Docker Desktop lists Windows 10 22H2 only while it is within Microsoft's servicing timeline, so this machine may stop receiving updates.

### Remaining dependencies

None for local development. Production needs hosting, a mail provider and the Milestone 8 gates.

### Next: Milestone 2, AI gateway and cost control

Buildable and testable with a fake provider. Real calls need an OpenAI API key.

## Milestone 2: AI gateway and cost control

**State: acceptance criteria met with a fake provider. No real provider has been called.** Every AI request through the gateway is tenant-scoped, cost-accounted and subject to enforced limits. See [cost accounting](ai/cost-accounting.md).

### Implemented

- Central gateway with provider adapters: OpenAI, and a fake one refused outside development.
- Versioned model prices with five rates, immutable prompt versions, and an operation catalog.
- Atomic budget reservations, firm and per-user limits, per-request caps, rate limits, overage only when authorised, and alerts at 70, 90 and 100 percent.
- Idempotent requests, tenant-isolated exact-match caching, and bounded retries.
- Conservative handling of uncertain outcomes, with audited resolution by staff.
- Superadmin-only pages for usage, costs, alerts, policies, uncertain reservations and reconciliation. Firms and Support see no AI consumption, by product decision.

### Migrations

`ai_gateway` 0001–0003, `platform_admin` 0002. Applied to the development database.

### Tests executed on 2 November 2026

| Check | Result |
|---|---|
| `pytest` as `aai_app` | 232 passed |
| Concurrency tests, 5 repeated runs | 4 passed each time |
| Mutation: no row lock on the budget | 3 of 4 concurrency tests failed in each of 3 runs; reverted |
| Cost formula | Matches the worked example in the OpenAI prompt caching guide |
| OpenAI adapter | Simulated HTTP only |
| Browser, page to Redis to real worker to gateway to fake provider | Passed; a 54 + 20 token request cost $0.000134 in the database, as calculated by hand |
| `pip-audit` on `requirements.lock` | No known vulnerabilities |

### Defects found by running

- `TenantFK` could run before the unique constraint it targets, within one migration. It worked for earlier tables only because of operation order. It now runs at the end of the migration.

### Known limitations

See "Not built yet" in the [cost accounting](ai/cost-accounting.md) document. Also:

- A prompt template change needs a data migration; there is no management page.
- Denied requests are written to the tenant's audit log even when the caller is not a member, so a signed-in non-member calling code directly could add noise there. No page lets them do so today.

### Remaining dependencies

- An OpenAI API key, and the current official prices, for the first real call.

### Next: Milestone 3, legal knowledge infrastructure

Needs a legal review of reuse terms before commercial use. Portal Legislativ's terms are undocumented.

## Milestone 3: legal knowledge infrastructure

**State: infrastructure built and tested. The acceptance criterion is met for permitted material and representative questions, but the fiscal corpus is not usable yet.** The Fiscal Code cannot be obtained from the official service, and no consolidated text exists. See [source registry](legal/source-registry.md) and [versioning](legal/versioning.md).

### Implemented

- Source registry with health, freshness, schedules and a circuit breaker. All sources start disabled.
- Portal Legislativ SOAP connector and ANAF RSS discovery, both run against the real services.
- Manual import of official documents with declared provenance.
- Content-addressed storage of originals, behind a replaceable adapter.
- Parsing along articles and paragraphs, with Romanian full-text search that tolerates missing or old diacritics.
- Bitemporal versioning, immutable history, incremental embedding, and hybrid retrieval with warnings.
- Superadmin pages for sources and the review queue, with audited decisions.

### Migrations

`legal_knowledge` 0001–0003, `ai_gateway` 0004–0005, `platform_admin` 0004. Applied to the development database. `.env` needs the new `AAI_LEGAL_PASSWORD`.

### Tests executed on 2 November 2026

| Check | Result |
|---|---|
| `pytest` | 313 passed |
| Mutation: date filter removed | 4 tests failed; reverted |
| Mutation: `known_at` ignored | 1 test failed; reverted |
| Real Portal Legislativ | Legea 296/2023 imported with 137 provisions; 2 rectifications kept as separate acts |
| Real date check | The law is found for 2024, and nothing is found for 2020, before it applied |
| Real Fiscal Code request | Rejected as incomplete, stored for provenance only |
| Real ANAF feed | 5 press releases stored with extracted text, as guidance |
| Browser, superadmin legal pages | Passed |
| `pip-audit` on `requirements.lock` | No known vulnerabilities |

Real data in the development database: 4 acts, of which 3 are usable, and 9 documents, of which 5 are ANAF press releases. No large corpus was downloaded, and every source remains disabled.

### Defects found by running

- **Invented period of application.** Two rectifications sharing type, number, year and issuer became versions of one act, with a false end date. Found only with real data. Acts from Portal Legislativ now include the source document id, with a regression test.
- A locking query needed a privilege the legal role rightly lacks. The lock now covers only its own table.

### Known limitations

- **No consolidated text, so the corpus cannot answer what applies today.** This is the main gap.
- ANAF documents are stored and listed but not searchable, because they have no act identity.
- Amending laws quote other laws, so article citations can name the wrong act.
- Semantic search ran only with the fake generator, so its quality is unknown.
- Monitorul Oficial, Ministry of Finance, ONRC and EUR-Lex connectors are not built.
- Change notifications to firms are not built.

### Remaining dependencies

- A decision on where consolidated texts come from, and a legal review of reuse terms.
- A fiscal specialist for review and the 200-question regression set.
- An OpenAI key for real embeddings.

### Next: Milestone 4, tax rules engine

Needs a fiscal specialist before any rule can become active.

## Milestone 5: financial application

Built before Milestone 4, which needs a fiscal specialist before any rule can become active.

**State: acceptance criteria met on test data. No real accounting export has been imported.** Users can manage company data and read clearly labelled figures, with no AI involved. See [financial figures](financial/figures.md).

### Implemented

- Sales: customers, invoices with separate payments, sales without an invoice, categories.
- Expenses: records, categories, supporting documents, recurring templates generated on request.
- Inventory: products, append-only movements, derived stock levels, low-stock alerts.
- CSV and Excel imports for 7 kinds of data, with preview, duplicate detection, original rows kept, and a file of rejected rows to correct.
- Dashboard with labelled figures, alerts, a 12-month chart and the same numbers as a table.
- Reports: summary with period comparison, sales, expenses, receivables by age, inventory, each with CSV export.
- Roles: all can read; Member records; Accountant, Administrator and Owner also import.
- Friendlier page for an expired form, after a report of a technical 403 on sign-out.

### Migrations

`financial_imports` 0001–0002, `sales` 0001–0002, `expenses` 0001–0003, `inventory` 0001–0002, `reports` 0001–0002. Applied to the development database. New dependency: `openpyxl`, so rebuild the images. Chart.js 4.4.9 is vendored in `static/vendor`.

### Tests executed on 2 November 2026

| Check | Result |
|---|---|
| `pytest` as `aai_app` | 533 passed |
| Isolation matrix | Extended to all 14 new tables |
| Mutation: no row lock on the invoice when paying | Concurrency test failed; reverted |
| Mutation: no row lock on the product when issuing | Concurrency test failed; reverted |
| Browser flow in Chromium | Passed: customer, invoice, payment, real CSV upload, preview, commit, dashboard, chart values, no sideways scroll at 400 px on 6 pages |
| Chart palette validator | All checks pass in light mode |
| `ruff check` | Clean |
| `makemigrations --check` | No changes |
| `pip-audit` on `requirements.lock` | No known vulnerabilities |
| GitHub Actions | All steps passed on `master` |

### Defects found by running

- **`0,125` was read as 125.** The thousands pattern accepted a leading zero. A financial misread caught by a unit test before any use.
- **The receivables report counted later payments.** It disagreed with the unpaid total at a past date. Caught by a test requiring the two to match.
- **Two uploads of one file at the same moment collided** on a shared temporary file. The legal document store had the same pattern, and both are fixed.
- **Original columns appeared sorted.** `jsonb` reorders keys, so the preview now follows the file's header order.

### CI

The first runs on GitHub failed at the lint step, with exit code 2. Reproduced locally: the container user cannot write to a checkout owned by the runner's user, so `ruff` cannot create its cache. The workflow now opens the permissions first, and every step has since passed on GitHub: lint, tests, migrations, `pip-audit` and `gitleaks`.

### Security considerations

- Uploaded documents are identified by content, limited in size, and always downloaded as attachments, so they cannot run in the application's origin.
- Exported text cannot run as a spreadsheet formula.
- Excel files are checked for decompression bombs before parsing.
- Files are stored under the firm's folder, and reads check that prefix as well as the row's visibility. Row-level security does not cover the disk, so this check is what protects it.

### Known limitations

See [financial figures](financial/figures.md). The main ones: invoices have no lines, so sales do not reduce stock; credit notes are refused; RON only; a whole import cannot be undone; no real accounting export format has been tested.

### Remaining dependencies

- Sample exports from the accounting systems firms really use.
- A fiscal specialist's view on VAT in the estimated result.

### Next: Milestone 4, tax rules engine

Needs a fiscal specialist before any rule can become active. Milestone 6, the assistant, needs an OpenAI key and can use these figures.

## First real AI provider call

On 2 November 2026 one `diagnostic.echo` request went through the whole path, page aside: command, Redis, worker, gateway, OpenAI.

| Check | Result |
|---|---|
| Model | `gpt-6-luna`, at the official price checked that day |
| Answer | „Testul de diagnostic a reușit.”, marked as not synthetic |
| Usage | 71 input and 35 output tokens, of which 19 were reasoning |
| Held before the call | $0.0000885 |
| Actual cost | $0.0000246, matching the hand calculation |
| Key | In the worker only, not in `web` |

**Reasoning counts as output.** More than half of this answer's output tokens were reasoning, so an operation's `max_output_tokens` must allow for it, or an answer can stop short. Milestone 6 must set this per operation.

The demo firm's budget of $0.05 also holds $0.00027 from earlier fake-provider tests, because synthetic usage is charged to the same budget. This affects only the development database.

Not done: real embeddings for the legal corpus, reconciliation against OpenAI's own usage figures, and any operation other than the diagnostic.

## Milestone 6: AI assistant

**State: built and run against the real provider on fictional data. Open: tax rule integration, because Milestone 4 does not exist, and specialist validation.** See [assistant](ai/assistant.md).

### Implemented

- Assistant page with search, filters, suggested questions by source, and answers in sections with icons.
- Figures from the application only, with checks in code on numbers, citations and sources.
- Tax calculations refused before any model call.
- Legal retrieval by date, with amending acts cited without an article number.
- Private history per person, with deletion.
- Superadmin AI amounts in lei with two decimals, at the official BNR rate.

### Migrations

`assistant` 0001–0002, `ai_gateway` 0006–0007, `platform_admin` 0005. Applied to the development database.

### Tests executed on 2 November 2026

| Check | Result |
|---|---|
| `pytest` as `aai_app` | 601 passed |
| Real provider, 11 questions on the final prompt | No invented figures; manipulation refused; off-topic question not answered |
| Browser, real worker and real provider | Passed: suggestion, question, polling, answer, off-topic refusal, search, no sideways scroll at 400 px |
| Full browser flow | Passed |
| `ruff check` | Clean |
| `makemigrations --check` | No changes |
| `pip-audit` on `requirements.lock` | No known vulnerabilities |
| Real BNR rate | 1 USD = 4.7658 RON on 2 November 2026 |
| Real AI spending while testing | 29 real requests, 0.08 lei in total |

The checks in code did not withhold any answer in the real run, so against the real model they are proven only by simulated answers in the tests.

### Defects found by running

- **The real model answered "Paris" to an off-topic question** from general knowledge. The prompt now forbids it, and an answer with no source is not shown, whatever the model does.
- **The question box did not return after an answer** without a manual reload. Found only in the browser.
- BNR's documented address redirects to its home page, with a success status. The parser refuses anything that holds no rate.

### Known limitations

See [assistant](ai/assistant.md). Mainly: legal answers are limited by the corpus; retrieval is by keyword; each question stands alone; no regression set exists; the exchange rate is updated by hand.

### Security considerations

- Company figures, and names when relevant, go to OpenAI. A legal review is needed before real use.
- The repository is public, including the development accounts and their password, which work only in development.

### Remaining dependencies

- A fiscal specialist, for the 200-question set and for Milestone 4.
- Consolidated legal texts.
- Legal review of data sent to the provider.

### Next: Milestone 4, tax rules engine

Rules stay inactive until a specialist approves them.
