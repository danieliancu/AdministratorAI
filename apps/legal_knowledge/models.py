"""Shared legal corpus. Holds no tenant data, and is never copied per tenant.

Facts are never overwritten. Two separate time lines exist: when a text applied in law
(`valid_from` and `valid_to`), and when this system knew that (`recorded_at` and `retired_at`).
"""

import uuid

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils import timezone
from pgvector.django import VectorField

EMBEDDING_DIMENSIONS = 1536


class Authority(models.TextChoices):
    LEGISLATION = "legislation", "Legislație oficială"
    CONSOLIDATED = "consolidated", "Text legislativ consolidat"
    GUIDANCE = "guidance", "Îndrumare ANAF"
    PROCEDURE = "procedure", "Procedură administrativă"
    INTERPRETATION = "interpretation", "Interpretare fără caracter obligatoriu"
    DRAFT = "draft", "Proiect, nu este lege în vigoare"


class LegalSource(models.Model):
    class Connector(models.TextChoices):
        SOAP = "soap", "SOAP"
        RSS = "rss", "RSS"
        MANUAL = "manual", "Import manual"
        NONE = "none", "Neimplementat"

    class Licence(models.TextChoices):
        UNKNOWN = "unknown", "Necunoscut"
        PERMITTED = "permitted", "Permis"
        RESTRICTED = "restricted", "Restricționat"

    key = models.CharField(primary_key=True, max_length=40)
    name = models.CharField(max_length=200)
    official_url = models.CharField(max_length=500)
    connector = models.CharField(max_length=10, choices=Connector.choices)
    access_restrictions = models.TextField(blank=True)
    licence_status = models.CharField(
        max_length=12, choices=Licence.choices, default=Licence.UNKNOWN
    )
    rate_limit_note = models.CharField(max_length=300, blank=True)
    # Off by default: reuse terms are unverified, so a person must decide to start it.
    is_enabled = models.BooleanField(default=False)
    schedule_minutes = models.PositiveIntegerField(default=1440)
    freshness_hours = models.PositiveIntegerField(default=168)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_document_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    circuit_open_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.key


class LegalSyncJob(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "În curs"
        SUCCEEDED = "succeeded", "Reușit"
        FAILED = "failed", "Eșuat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(LegalSource, on_delete=models.PROTECT, related_name="jobs")
    trigger = models.CharField(max_length=20, default="schedule")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    discovered = models.PositiveIntegerField(default=0)
    new_documents = models.PositiveIntegerField(default=0)
    unchanged = models.PositiveIntegerField(default=0)
    failed_items = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"{self.source_id} {self.started_at:%Y-%m-%d %H:%M}"


class LegalDocument(models.Model):
    """One retrieved official original, exactly as received. Immutable."""

    class TextStatus(models.TextChoices):
        COMPLETE = "complete", "Complet"
        # The source returned a title or stub without the body: never used as evidence.
        INCOMPLETE = "incomplete", "Incomplet"
        NOT_EXTRACTED = "not_extracted", "Neextras"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(LegalSource, on_delete=models.PROTECT, related_name="documents")
    external_id = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=1000)
    title = models.CharField(max_length=1000)
    authority = models.CharField(max_length=20, choices=Authority.choices)
    content_type = models.CharField(max_length=100)
    checksum = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=200)
    byte_size = models.PositiveBigIntegerField()
    extracted_text = models.TextField(blank=True)
    text_status = models.CharField(max_length=15, choices=TextStatus.choices)
    published_on = models.DateField(null=True, blank=True)
    retrieved_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "checksum"], name="legal_document_source_checksum_uniq"
            ),
        ]

    def __str__(self):
        return self.title[:80]


class LegalAct(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    act_type = models.CharField(max_length=60)
    number = models.CharField(max_length=30)
    year = models.PositiveSmallIntegerField()
    issuer = models.CharField(max_length=200, blank=True)
    # The source's own document id. Type, number, year and issuer are not unique: Portal
    # Legislativ really returned two separate rectifications with identical values, and
    # treating them as versions of one act would invent a period of application.
    source_document_id = models.CharField(max_length=300, blank=True)
    title = models.CharField(max_length=1000)
    publication = models.CharField(max_length=300, blank=True)
    official_url = models.CharField(max_length=1000)
    authority = models.CharField(max_length=20, choices=Authority.choices)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["act_type", "number", "year", "issuer", "source_document_id"],
                name="legal_act_identity_uniq",
            ),
        ]

    def __str__(self):
        return self.citation

    @property
    def citation(self):
        return f"{self.act_type} nr. {self.number}/{self.year}"


class LegalActVersion(models.Model):
    class TextForm(models.TextChoices):
        # As first published: later amendments are not reflected in this text.
        ORIGINAL = "original", "Forma publicată inițial"
        CONSOLIDATED = "consolidated", "Formă consolidată"
        UNKNOWN = "unknown", "Formă necunoscută"

    class Review(models.TextChoices):
        UNREVIEWED = "unreviewed", "Neverificat de un specialist"
        REVIEWED = "reviewed", "Verificat de un specialist"
        REJECTED = "rejected", "Respins"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    act = models.ForeignKey(LegalAct, on_delete=models.PROTECT, related_name="versions")
    document = models.ForeignKey(LegalDocument, on_delete=models.PROTECT, related_name="versions")
    checksum = models.CharField(max_length=64)
    text_form = models.CharField(max_length=15, choices=TextForm.choices)
    consolidated_as_of = models.DateField(null=True, blank=True)
    # Only this column ever changes, and only through an audited review.
    review_status = models.CharField(
        max_length=12, choices=Review.choices, default=Review.UNREVIEWED
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["act", "checksum"], name="legal_version_checksum_uniq"),
        ]

    def __str__(self):
        return f"{self.act_id} {self.checksum[:8]}"


class LegalApplicability(models.Model):
    """When a version applied in law, as this system understood it at a given moment.

    A correction retires the row and adds a new one, so an audit can reconstruct what
    the application knew when an earlier answer was given.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(
        LegalActVersion, on_delete=models.PROTECT, related_name="applicability"
    )
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    basis = models.CharField(max_length=200)
    recorded_at = models.DateTimeField(default=timezone.now)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="legal_applicability_order",
            ),
        ]
        indexes = [
            models.Index(fields=["valid_from", "valid_to"], name="legal_applicability_dates_idx"),
        ]

    def __str__(self):
        return f"{self.valid_from} – {self.valid_to or '…'}"


class LegalProvision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    act = models.ForeignKey(LegalAct, on_delete=models.PROTECT, related_name="provisions")
    label = models.CharField(max_length=60)
    ordinal = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["act", "label"], name="legal_provision_label_uniq"),
        ]

    def __str__(self):
        return self.label


class LegalProvisionVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provision = models.ForeignKey(LegalProvision, on_delete=models.PROTECT, related_name="versions")
    act_version = models.ForeignKey(
        LegalActVersion, on_delete=models.PROTECT, related_name="provision_versions"
    )
    structure_path = models.CharField(max_length=300, blank=True)
    text = models.TextField()

    def __str__(self):
        return f"{self.provision_id} @ {self.act_version_id}"


class LegalChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provision_version = models.ForeignKey(
        LegalProvisionVersion, on_delete=models.PROTECT, related_name="chunks"
    )
    ordinal = models.PositiveIntegerField()
    paragraph_label = models.CharField(max_length=40, blank=True)
    text = models.TextField()
    normalized_text = models.TextField()
    # Filled by a database trigger from normalized_text.
    search_vector = SearchVectorField(null=True, editable=False)
    checksum = models.CharField(max_length=64)

    class Meta:
        indexes = [
            GinIndex(fields=["search_vector"], name="legal_chunk_search_idx"),
            models.Index(fields=["checksum"], name="legal_chunk_checksum_idx"),
        ]

    def __str__(self):
        return f"{self.provision_version_id} #{self.ordinal}"


class LegalEmbedding(models.Model):
    """Keyed by text checksum and model, so unchanged text is never embedded twice."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checksum = models.CharField(max_length=64)
    model_key = models.CharField(max_length=100)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)
    is_synthetic = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["checksum", "model_key"], name="legal_embedding_checksum_model_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.model_key} {self.checksum[:8]}"


class LegalRelationship(models.Model):
    class Kind(models.TextChoices):
        REFERS_TO = "refers_to", "Face referire la"
        AMENDS = "amends", "Modifică"
        REPEALS = "repeals", "Abrogă"
        REPLACES = "replaces", "Înlocuiește"
        SUPPLEMENTS = "supplements", "Completează"
        IMPLEMENTS = "implements", "Aplică"
        TRANSITIONAL = "transitional", "Afectează aplicarea tranzitorie"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    from_version = models.ForeignKey(
        LegalActVersion, on_delete=models.PROTECT, related_name="relationships"
    )
    to_reference = models.CharField(max_length=120)
    to_act = models.ForeignKey(
        LegalAct, null=True, blank=True, on_delete=models.PROTECT, related_name="referenced_by"
    )
    kind = models.CharField(max_length=15, choices=Kind.choices)
    # Text matching can suggest a reference. It never establishes a legal effect.
    extracted_automatically = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return f"{self.kind} {self.to_reference}"


class LegalChangeEvent(models.Model):
    class Kind(models.TextChoices):
        NEW_VERSION = "new_version", "Versiune nouă"
        NEW_ACT = "new_act", "Act nou"
        INCOMPLETE_TEXT = "incomplete_text", "Text incomplet la sursă"
        NEEDS_DATE = "needs_date", "Lipsește data de aplicare"
        DISCOVERED = "discovered", "Document descoperit"

    class Status(models.TextChoices):
        PENDING = "pending", "În așteptare"
        APPROVED = "approved", "Aprobat"
        REJECTED = "rejected", "Respins"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(LegalSource, on_delete=models.PROTECT, related_name="changes")
    document = models.ForeignKey(
        LegalDocument, null=True, on_delete=models.PROTECT, related_name="changes"
    )
    version = models.ForeignKey(
        LegalActVersion, null=True, on_delete=models.PROTECT, related_name="changes"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    summary = models.CharField(max_length=500)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by_id = models.UUIDField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return f"{self.kind} {self.created_at:%Y-%m-%d}"
