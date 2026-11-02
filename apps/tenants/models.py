import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.db.constraints import TenantFK

from .roles import Role


class Tenant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Activ"
        SUSPENDED = "suspended", "Suspendat"

    AAI_TENANT_OWNED = False

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "idempotency_key"], name="tenant_creator_idempotency_uniq"
            ),
        ]

    def __str__(self):
        return self.name


class TenantOwnedModel(models.Model):
    AAI_TENANT_OWNED = True

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True
        constraints = [
            # Target of the composite foreign keys declared with TenantFK.
            models.UniqueConstraint(
                fields=["tenant", "id"], name="%(app_label)s_%(class)s_tenant_id_uniq"
            ),
        ]


class TenantMembership(TenantOwnedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(fields=["tenant", "user"], name="membership_tenant_user_uniq"),
        ]
        indexes = [models.Index(fields=["user"], name="membership_user_idx")]

    def __str__(self):
        return f"{self.user_id} / {self.role}"


class TenantSettings(TenantOwnedModel):
    locale = models.CharField(max_length=10, default="ro")
    timezone = models.CharField(max_length=64, default="Europe/Bucharest")

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(fields=["tenant"], name="settings_one_per_tenant"),
        ]

    def __str__(self):
        return f"Setări {self.tenant_id}"


class CompanyFiscalProfile(TenantOwnedModel):
    class VatStatus(models.TextChoices):
        UNKNOWN = "unknown", "Neconfirmat"
        PAYER = "payer", "Plătitor de TVA"
        NON_PAYER = "non_payer", "Neplătitor de TVA"

    class Provenance(models.TextChoices):
        NONE = "none", "Necompletat"
        USER_DECLARED = "user_declared", "Declarat de utilizator"

    company_name = models.CharField(max_length=200, blank=True)
    # No global unique on CUI: constraints bypass RLS, so one would reveal other tenants' firms.
    cui = models.CharField("CUI", max_length=20, blank=True)
    registration_number = models.CharField("Nr. Registrul Comerțului", max_length=40, blank=True)
    caen_codes = models.CharField("Coduri CAEN", max_length=200, blank=True)
    fiscal_regime = models.CharField("Regim fiscal", max_length=60, blank=True)
    vat_status = models.CharField(
        "Statut TVA", max_length=20, choices=VatStatus.choices, default=VatStatus.UNKNOWN
    )
    provenance = models.CharField(
        max_length=20, choices=Provenance.choices, default=Provenance.NONE
    )
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(fields=["tenant"], name="fiscal_profile_one_per_tenant"),
        ]

    def __str__(self):
        return self.company_name or f"Profil fiscal {self.tenant_id}"


class TenantInvitation(TenantOwnedModel):
    email = models.CharField(max_length=254)
    role = models.CharField(max_length=20, choices=Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        TenantMembership, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            TenantFK(
                column="invited_by_id",
                to_table="tenants_tenantmembership",
                name="invitation_invited_by_tenant_fk",
            ),
        ]

    def __str__(self):
        return f"Invitație {self.pk}"
