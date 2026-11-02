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
| `ai_gateway_aiproviderreconciliation`, `aiexchangerate` | platform only | No application grant. The latest USD to RON rate is used for display on platform pages |
| `ai_gateway_aiplatformbudget`, `aiplatformusage` | platform only | The platform's own AI spending, such as indexing. `aai_legal` updates status columns |
| `legal_knowledge_legalsource` | global | Registry and health. `aai_legal` writes status columns, and only a superadmin can enable a source |
| `legal_knowledge_legaldocument`, `legalact`, `legalprovision`, `legalprovisionversion`, `legalchunk`, `legalembedding`, `legalrelationship` | global | Immutable. Written by `aai_legal`, read by `aai_app` |
| `legal_knowledge_legalactversion` | global | Immutable except the review columns, which only a superadmin's decision changes |
| `legal_knowledge_legalapplicability` | global | Append-only history of when a version applied in law. See [versioning](../legal/versioning.md) |
| `legal_knowledge_legalsyncjob`, `legalchangeevent` | platform only | Sync history and the review queue |
| `sales_customer`, `sales_salescategory` | tenant | CUI unique per firm when present. Customers cannot be deleted |
| `sales_invoice` | tenant | Number unique per firm, kept after cancelling. Total must equal net plus VAT. No delete |
| `sales_payment` | tenant | Cash received, separate from the invoice. Voided, never deleted |
| `sales_saletransaction` | tenant | Sale without an invoice, paid on the spot. No delete |
| `expenses_expensecategory`, `expenses_recurringexpense` | tenant | A template records nothing until generated |
| `expenses_expense` | tenant | One per template and month. No delete |
| `expenses_expensedocument` | tenant | Metadata of an uploaded file. No update or delete |
| `inventory_product` | tenant | SKU unique per firm. Stock is derived, never stored. No delete |
| `inventory_stockmovement` | tenant | Append-only. The sign must match the kind |
| `financial_imports_importbatch` | tenant | One live batch per firm, kind and file checksum. No delete |
| `financial_imports_importrow` | tenant | Original cells cannot be changed; only outcome columns can |
| `reports_openingcash` | tenant | One per firm. Declared by the user, unverified |
| `assistant_assistantmessage` | tenant | Row-level security also limits it to the person who asked |
| `django_session`, `django_content_type`, `auth_permission`, `django_migrations` | system | No tenant data. Explicit minimal grants |
| `auth_group`, `auth_group_permissions` | system | Unused, no grants |

## Schemas

- `app`: context functions and trigger functions.
- `platform`: masked views and `SECURITY DEFINER` functions, owned by `aai_platform_definer`.

## Relationships between tenant tables

Tenant-owned models inherit `TenantOwnedModel`, with a unique `(tenant_id, id)`. A relation between two tenant tables uses `ForeignKey(db_constraint=False)` plus a composite `TenantFK`, and a system check rejects anything else.
