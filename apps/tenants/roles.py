from django.db import models


class Role(models.TextChoices):
    OWNER = "owner", "Proprietar"
    ADMINISTRATOR = "administrator", "Administrator"
    ACCOUNTANT = "accountant", "Contabil"
    MEMBER = "member", "Membru"
    READ_ONLY = "read_only", "Doar citire"


VIEW_DASHBOARD = "view_dashboard"
VIEW_FISCAL_PROFILE = "view_fiscal_profile"
EDIT_FISCAL_PROFILE = "edit_fiscal_profile"
MANAGE_MEMBERS = "manage_members"
MANAGE_SETTINGS = "manage_settings"
USE_AI = "use_ai"
VIEW_FINANCE = "view_finance"
EDIT_FINANCE = "edit_finance"
IMPORT_FINANCE = "import_finance"

_FINANCE_ALL = {VIEW_FINANCE, EDIT_FINANCE, IMPORT_FINANCE}

CAPABILITIES = {
    Role.OWNER: {
        VIEW_DASHBOARD,
        VIEW_FISCAL_PROFILE,
        EDIT_FISCAL_PROFILE,
        MANAGE_MEMBERS,
        MANAGE_SETTINGS,
        USE_AI,
        *_FINANCE_ALL,
    },
    Role.ADMINISTRATOR: {
        VIEW_DASHBOARD,
        VIEW_FISCAL_PROFILE,
        EDIT_FISCAL_PROFILE,
        MANAGE_MEMBERS,
        MANAGE_SETTINGS,
        USE_AI,
        *_FINANCE_ALL,
    },
    Role.ACCOUNTANT: {
        VIEW_DASHBOARD,
        VIEW_FISCAL_PROFILE,
        EDIT_FISCAL_PROFILE,
        USE_AI,
        *_FINANCE_ALL,
    },
    Role.MEMBER: {VIEW_DASHBOARD, VIEW_FISCAL_PROFILE, USE_AI, VIEW_FINANCE, EDIT_FINANCE},
    Role.READ_ONLY: {VIEW_DASHBOARD, VIEW_FINANCE},
}


def requires(capability):
    """Declare what a tenant view needs. DbScopeMiddleware refuses views without it."""

    def decorator(view):
        view.required_capability = capability
        return view

    return decorator
