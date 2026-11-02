# Data model

Covers tables that exist today. `apps/core/db/manifest.py` is the authoritative classification, and a catalog test fails on any table it does not list.

| Table | Class | Key points |
|---|---|---|
| `accounts_user` | identity | UUID key. Visible to itself, to a caller naming its email, and to members of the current tenant |
| `accounts_platformgrant` | identity | One row per staff user. Runtime role reads its own row only |
| `tenants_tenant` | tenant root | `status` cannot be changed by `aai_app`. No delete |
| `tenants_tenantmembership` | tenant | Unique per tenant and user. An insert trigger checks who may add members |
| `tenants_tenantsettings` | tenant | One per tenant |
| `tenants_companyfiscalprofile` | tenant | One per tenant. Declared by the user, unverified. CUI is deliberately not globally unique |
| `tenants_tenantinvitation` | tenant | Stores only a token hash. Composite foreign key to the inviter's membership |
| `audit_tenantevent` | audit | Tenant-scoped, append-only |
| `audit_securityevent` | audit | `aai_app` can insert, not read. Stores a hash of the login identifier |
| `audit_platformevent` | audit | Reachable only through the `platform` schema |
| `ai_gateway_aibudgetpolicy` | tenant | One per tenant. The application only reads it; platform staff write it |
| `ai_gateway_aibudget` | tenant | One per billing period. Its row lock serialises reservations. Limits come from the policy through a trigger |
| `ai_gateway_aibudgetalert` | tenant | One per budget and threshold |
| `ai_gateway_aiusagereservation` | tenant | Unique per tenant and idempotency key. `unknown` keeps money held |
| `ai_gateway_aiusageevent` | tenant | Immutable. No prompt or answer |
| `ai_gateway_aistoredresponse` | tenant | Answers for replay and caching, with an expiry. Not updatable |
| `ai_gateway_aiprovider`, `aimodel`, `aioperation` | global catalog | Application reads; owner credentials write |
| `ai_gateway_aimodelpricing` | global catalog | Immutable, per model and effective date |
| `ai_gateway_prompttemplateversion` | global catalog | Text immutable; only activation can change |
| `ai_gateway_aiproviderreconciliation`, `aiexchangerate` | platform only | No application grant. Exchange rates are not used yet |
| `django_session`, `django_content_type`, `auth_permission`, `django_migrations` | system | No tenant data. Explicit minimal grants |
| `auth_group`, `auth_group_permissions` | system | Unused, no grants |

## Schemas

- `app`: context functions and trigger functions.
- `platform`: masked views and `SECURITY DEFINER` functions, owned by `aai_platform_definer`.

## Relationships between tenant tables

Tenant-owned models inherit `TenantOwnedModel`, with a unique `(tenant_id, id)`. A relation between two tenant tables uses `ForeignKey(db_constraint=False)` plus a composite `TenantFK`, and a system check rejects anything else.
