# Every table in the public schema must be classified here. A catalog test fails on
# anything unlisted, so a new table cannot appear without deciding how it is protected.
TENANT = {
    "tenants_companyfiscalprofile",
    "tenants_tenantinvitation",
    "tenants_tenantmembership",
    "tenants_tenantsettings",
}
TENANT_ROOT = {"tenants_tenant"}
IDENTITY = {"accounts_user"}
SYSTEM = {
    "auth_group",
    "auth_group_permissions",
    "auth_permission",
    "django_content_type",
    "django_migrations",
    "django_session",
}
ALL_TABLES = TENANT | TENANT_ROOT | IDENTITY | SYSTEM
RLS_TABLES = TENANT | TENANT_ROOT | IDENTITY

# Unique constraints on protected tables that may omit tenant_id. Constraints bypass
# RLS, so each entry here is a potential side channel and needs a reason.
UNIQUE_WITHOUT_TENANT = {
    "accounts_user": {"email"},  # registration answers identically either way
    "tenants_tenant": {"created_by_id,idempotency_key"},  # collides only with your own rows
    "tenants_tenantinvitation": {"token_hash"},  # random 256-bit value
}
