"""Turns a retrieved official document into immutable, versioned, attributable records."""

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from . import parsing
from .models import (
    Authority,
    LegalAct,
    LegalActVersion,
    LegalApplicability,
    LegalChangeEvent,
    LegalChunk,
    LegalDocument,
    LegalProvision,
    LegalProvisionVersion,
    LegalRelationship,
    LegalSource,
)
from .storage import get_store

LEGAL = "legal"


@dataclass(frozen=True)
class IncomingDocument:
    source_key: str
    url: str
    title: str
    authority: str
    content: bytes
    content_type: str
    text: str
    external_id: str = ""
    published_on: date | None = None


@dataclass(frozen=True)
class ActIdentity:
    act_type: str
    number: str
    year: int
    issuer: str = ""
    publication: str = ""
    # Empty only when an operator declares that documents are versions of one act.
    source_document_id: str = ""


@dataclass(frozen=True)
class IngestResult:
    document: LegalDocument
    created: bool
    version: LegalActVersion | None = None


def _store_document(incoming):
    key, checksum = get_store().put(incoming.content)
    source = LegalSource.objects.using(LEGAL).get(pk=incoming.source_key)
    existing = LegalDocument.objects.using(LEGAL).filter(source=source, checksum=checksum).first()
    if existing is not None:
        return existing, False
    parsed = parsing.parse_legal_text(incoming.text) if incoming.text else None
    status = LegalDocument.TextStatus.NOT_EXTRACTED
    if parsed is not None:
        status = (
            LegalDocument.TextStatus.COMPLETE
            if parsed.is_complete
            else LegalDocument.TextStatus.INCOMPLETE
        )
    document = LegalDocument.objects.using(LEGAL).create(
        source=source,
        external_id=incoming.external_id,
        url=incoming.url,
        title=incoming.title[:1000],
        authority=incoming.authority,
        content_type=incoming.content_type,
        checksum=checksum,
        storage_key=key,
        byte_size=len(incoming.content),
        extracted_text=incoming.text,
        text_status=status,
        published_on=incoming.published_on,
    )
    return document, True


def _write_provisions(act, version, parsed):
    for ordinal, item in enumerate(parsed.provisions):
        provision, _ = LegalProvision.objects.using(LEGAL).get_or_create(
            act=act, label=item.label[:60], defaults={"ordinal": ordinal}
        )
        provision_version = LegalProvisionVersion.objects.using(LEGAL).create(
            provision=provision,
            act_version=version,
            structure_path=item.structure_path,
            text=item.text,
        )
        LegalChunk.objects.using(LEGAL).bulk_create(
            LegalChunk(
                provision_version=provision_version,
                ordinal=index,
                paragraph_label=chunk.paragraph_label,
                text=chunk.text,
                normalized_text=parsing.fold_for_search(chunk.text),
                checksum=chunk.checksum,
            )
            for index, chunk in enumerate(item.chunks)
        )


def _set_applicability(act, version, valid_from, basis):
    """Re-derives the time line of the act. Older understandings are retired, never edited."""
    now = timezone.now()
    current = list(
        LegalApplicability.objects.using(LEGAL)
        .select_for_update(of=("self",))
        .filter(version__act=act, retired_at__isnull=True)
    )
    entries = [(row.valid_from, row.version_id, row.basis) for row in current]
    entries.append((valid_from, version.pk, basis))
    entries.sort(key=lambda entry: entry[0])

    desired = {}
    for index, (start, version_id, entry_basis) in enumerate(entries):
        end = entries[index + 1][0] if index + 1 < len(entries) else None
        if end == start:
            end = None
        desired[version_id] = (start, end, entry_basis)

    for row in current:
        start, end, _ = desired[row.version_id]
        if (row.valid_from, row.valid_to) == (start, end):
            desired.pop(row.version_id)
        else:
            row.retired_at = now
            row.save(using=LEGAL, update_fields=["retired_at"])
    for version_id, (start, end, entry_basis) in desired.items():
        LegalApplicability.objects.using(LEGAL).create(
            version_id=version_id,
            valid_from=start,
            valid_to=end,
            basis=entry_basis,
            recorded_at=now,
        )


def ingest_act(
    incoming: IncomingDocument,
    identity: ActIdentity,
    *,
    valid_from: date | None,
    basis: str,
    text_form: str,
    consolidated_as_of: date | None = None,
) -> IngestResult:
    """Idempotent: the same bytes change nothing. Each new text becomes a new version."""
    with transaction.atomic(using=LEGAL):
        document, created = _store_document(incoming)
        if not created:
            return IngestResult(document=document, created=False)
        act, new_act = LegalAct.objects.using(LEGAL).get_or_create(
            act_type=identity.act_type,
            number=identity.number,
            year=identity.year,
            issuer=identity.issuer,
            source_document_id=identity.source_document_id,
            defaults={
                "title": incoming.title[:1000],
                "publication": identity.publication,
                "official_url": incoming.url,
                "authority": incoming.authority,
            },
        )
        if document.text_status != LegalDocument.TextStatus.COMPLETE:
            # Stored for provenance. No provisions, so it can never be cited as evidence.
            LegalChangeEvent.objects.using(LEGAL).create(
                source=document.source,
                document=document,
                kind=LegalChangeEvent.Kind.INCOMPLETE_TEXT,
                summary=f"{act.citation}: sursa nu a furnizat textul complet.",
            )
            return IngestResult(document=document, created=True)

        checksum = parsing.text_checksum(incoming.text)
        existing = LegalActVersion.objects.using(LEGAL).filter(act=act, checksum=checksum).first()
        if existing is not None:
            return IngestResult(document=document, created=True, version=existing)

        version = LegalActVersion.objects.using(LEGAL).create(
            act=act,
            document=document,
            checksum=checksum,
            text_form=text_form,
            consolidated_as_of=consolidated_as_of,
        )
        _write_provisions(act, version, parsing.parse_legal_text(incoming.text))
        for reference in parsing.find_references(incoming.text):
            LegalRelationship.objects.using(LEGAL).create(
                from_version=version,
                to_reference=reference[:120],
                kind=LegalRelationship.Kind.REFERS_TO,
            )
        if valid_from is None:
            # Without a date the text cannot answer "what applied then?", so it stays unused.
            kind = LegalChangeEvent.Kind.NEEDS_DATE
            summary = f"{act.citation}: lipsește data de aplicare."
        else:
            _set_applicability(act, version, valid_from, basis)
            kind = (
                LegalChangeEvent.Kind.NEW_ACT if new_act else LegalChangeEvent.Kind.NEW_VERSION
            )
            summary = f"{act.citation}: {'act nou' if new_act else 'versiune nouă'}."
        LegalChangeEvent.objects.using(LEGAL).create(
            source=document.source,
            document=document,
            version=version,
            kind=kind,
            summary=summary,
        )
    return IngestResult(document=document, created=True, version=version)


def record_discovered(incoming: IncomingDocument) -> IngestResult:
    """A document that is not an act, such as an ANAF press release. Used as guidance only."""
    with transaction.atomic(using=LEGAL):
        document, created = _store_document(incoming)
        if created:
            LegalChangeEvent.objects.using(LEGAL).create(
                source=document.source,
                document=document,
                kind=LegalChangeEvent.Kind.DISCOVERED,
                summary=incoming.title[:500],
            )
    return IngestResult(document=document, created=created)


__all__ = [
    "ActIdentity",
    "Authority",
    "IncomingDocument",
    "IngestResult",
    "ingest_act",
    "record_discovered",
]
