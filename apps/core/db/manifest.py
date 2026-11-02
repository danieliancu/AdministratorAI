# Every table in the public schema must be classified here. A catalog test fails on
# anything unlisted, so a new table cannot appear without deciding how it is protected.
TENANT = {
    "tenants_companyfiscalprofile",
    "tenants_tenantinvitation",
    "tenants_tenantmembership",
    "tenants_tenantsettings",
    "ai_gateway_aibudgetpolicy",
    "ai_gateway_aibudget",
    "ai_gateway_aibudgetalert",
    "ai_gateway_aiusagereservation",
    "ai_gateway_aiusageevent",
    "ai_gateway_aistoredresponse",
}
TENANT_ROOT = {"tenants_tenant"}
IDENTITY = {"accounts_user", "accounts_platformgrant"}
AUDIT = {"audit_tenantevent", "audit_securityevent", "audit_platformevent"}
# Shared catalog with no tenant data: readable by the application, written with owner credentials.
GLOBAL_REF = {
    "ai_gateway_aiprovider",
    "ai_gateway_aimodel",
    "ai_gateway_aimodelpricing",
    "ai_gateway_aioperation",
    "ai_gateway_prompttemplateversion",
}
# The application has no grant here at all.
PLATFORM_ONLY = {"ai_gateway_aiproviderreconciliation", "ai_gateway_aiexchangerate"}
SYSTEM = {
    "auth_group",
    "auth_group_permissions",
    "auth_permission",
    "django_content_type",
    "django_migrations",
    "django_session",
}
RLS_TABLES = TENANT | TENANT_ROOT | IDENTITY
ALL_TABLES = RLS_TABLES | AUDIT | GLOBAL_REF | PLATFORM_ONLY | SYSTEM

# Unique constraints on protected tables that may omit tenant_id. Constraints bypass
# RLS, so each entry here is a potential side channel and needs a reason.
UNIQUE_WITHOUT_TENANT = {
    "accounts_user": {"email"},  # registration answers identically either way
    "accounts_platformgrant": {"user_id"},  # the runtime role cannot insert here
    "tenants_tenant": {"created_by_id,idempotency_key"},  # collides only with your own rows
    "tenants_tenantinvitation": {"token_hash"},  # random 256-bit value
}
