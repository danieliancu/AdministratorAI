from django.apps import apps
from django.conf import settings
from django.core.checks import Error, register
from django.db import models

from .constraints import TenantFK


@register()
def check_database_settings(app_configs, **kwargs):
    errors = []
    if settings.DATABASES["default"].get("ATOMIC_REQUESTS"):
        errors.append(
            Error("ATOMIC_REQUESTS must stay off: use db_scope.", id="aai.E001")
        )
    if settings.MIDDLEWARE[-1] != "apps.core.middleware.DbScopeMiddleware":
        errors.append(Error("DbScopeMiddleware must be the last middleware.", id="aai.E002"))
    return errors


@register()
def check_tenant_relations(app_configs, **kwargs):
    errors = []
    for model in apps.get_models():
        if not getattr(model, "AAI_TENANT_OWNED", False):
            continue
        composite = {c.column for c in model._meta.constraints if isinstance(c, TenantFK)}
        for field in model._meta.local_fields:
            if not isinstance(field, models.ForeignKey):
                continue
            if not getattr(field.related_model, "AAI_TENANT_OWNED", False):
                continue
            if field.db_constraint or field.column not in composite:
                errors.append(
                    Error(
                        f"{model.__name__}.{field.name} needs db_constraint=False and a TenantFK.",
                        id="aai.E003",
                    )
                )
        for field in model._meta.local_many_to_many:
            errors.append(
                Error(
                    f"{model.__name__}.{field.name}: use an explicit tenant-owned through model.",
                    id="aai.E004",
                )
            )
    return errors
