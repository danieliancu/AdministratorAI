"""Runs source synchronisation with bounded effort and a circuit breaker."""

import logging
from datetime import timedelta
from io import BytesIO

from django.db import transaction
from django.utils import timezone

from .connectors import anaf_rss
from .connectors.http import SourceError, fetch
from .connectors.portal_legislativ import PortalAct, PortalLegislativClient
from .ingestion import LEGAL, ActIdentity, IncomingDocument, ingest_act, record_discovered
from .models import Authority, LegalActVersion, LegalDocument, LegalSource, LegalSyncJob

logger = logging.getLogger(__name__)

CIRCUIT_AFTER_FAILURES = 5
CIRCUIT_OPEN_HOURS = 6
# The API cannot filter by date or relevance, so discovery is narrow and capped.
FISCAL_TITLE_TERMS = ("Codul fiscal", "impozit", "taxa pe valoarea adăugată", "fiscal")
PAGE_SIZE = 10
MAX_PAGES_PER_TERM = 1
MAX_FEED_DOCUMENTS = 10


def ingest_portal_act(act: PortalAct, source_key="portal_legislativ"):
    incoming = IncomingDocument(
        source_key=source_key,
        url=act.link or "http://legislatie.just.ro/",
        title=act.title,
        authority=Authority.LEGISLATION,
        content=act.raw,
        content_type="application/xml",
        text=act.text,
        external_id=act.link,
        published_on=act.valid_from,
    )
    identity = ActIdentity(
        act_type=act.act_type,
        number=act.number,
        year=act.year or (act.valid_from.year if act.valid_from else 0),
        issuer=act.issuer,
        publication=act.publication,
        source_document_id=act.link,
    )
    return ingest_act(
        incoming,
        identity,
        valid_from=act.valid_from,
        basis="DataVigoare din Portal Legislativ",
        # The service offers no consolidated form or history. Assume the safer reading.
        text_form=LegalActVersion.TextForm.ORIGINAL,
    )


def _sync_portal(job, source):
    client = PortalLegislativClient(max_attempts=source.max_attempts)
    year = timezone.now().year
    seen = set()
    for term in FISCAL_TITLE_TERMS:
        for page in range(MAX_PAGES_PER_TERM):
            for act in client.search(page=page, page_size=PAGE_SIZE, year=year, title=term):
                if act.link in seen:
                    continue
                seen.add(act.link)
                job.discovered += 1
                _count(job, ingest_portal_act(act))


def extract_pdf_text(content):
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", type(exc).__name__)
        return ""


def _sync_anaf(job, source):
    for item in anaf_rss.fetch_feed(max_attempts=source.max_attempts)[:MAX_FEED_DOCUMENTS]:
        job.discovered += 1
        content, content_type = fetch(item.link, max_attempts=source.max_attempts)
        text = extract_pdf_text(content) if "pdf" in content_type.lower() else ""
        result = record_discovered(
            IncomingDocument(
                source_key=source.pk,
                url=item.link,
                title=item.title,
                authority=Authority.GUIDANCE,
                content=content,
                content_type=content_type[:100],
                text=text,
                external_id=item.link,
                published_on=item.published_on,
            )
        )
        _count(job, result)


def _count(job, result):
    if result.created:
        job.new_documents += 1
    else:
        job.unchanged += 1


CONNECTORS = {"portal_legislativ": _sync_portal, "anaf": _sync_anaf}


def is_due(source, now):
    if not source.is_enabled or source.pk not in CONNECTORS:
        return False
    if source.circuit_open_until and source.circuit_open_until > now:
        return False
    if source.last_attempt_at is None:
        return True
    return now - source.last_attempt_at >= timedelta(minutes=source.schedule_minutes)


def run_source(source_key, *, trigger="schedule", connector=None):
    """Records every attempt. A failure opens the circuit eventually, and is never hidden."""
    run = connector or CONNECTORS.get(source_key)
    if run is None:
        raise SourceError(f"No connector for {source_key}")
    source = LegalSource.objects.using(LEGAL).get(pk=source_key)
    job = LegalSyncJob.objects.using(LEGAL).create(source=source, trigger=trigger)
    now = timezone.now()
    source.last_attempt_at = now
    try:
        run(job, source)
    except Exception as exc:
        logger.warning("Legal source %s failed: %s", source_key, type(exc).__name__)
        job.status = LegalSyncJob.Status.FAILED
        job.error = f"{type(exc).__name__}: {exc}"[:300]
        source.last_error = job.error
        source.consecutive_failures += 1
        if source.consecutive_failures >= CIRCUIT_AFTER_FAILURES:
            source.circuit_open_until = now + timedelta(hours=CIRCUIT_OPEN_HOURS)
    else:
        job.status = LegalSyncJob.Status.SUCCEEDED
        source.last_success_at = timezone.now()
        source.last_error = ""
        source.consecutive_failures = 0
        source.circuit_open_until = None
        if job.new_documents:
            source.last_document_at = timezone.now()
    job.finished_at = timezone.now()
    with transaction.atomic(using=LEGAL):
        job.save(using=LEGAL)
        # Status columns only: this role cannot switch a source on or off.
        source.save(
            using=LEGAL,
            update_fields=[
                "last_attempt_at",
                "last_success_at",
                "last_document_at",
                "last_error",
                "consecutive_failures",
                "circuit_open_until",
            ],
        )
    return job


def run_due_sources():
    now = timezone.now()
    jobs = []
    for source in LegalSource.objects.using(LEGAL).all():
        if is_due(source, now):
            jobs.append(run_source(source.pk))
    return jobs


__all__ = ["LegalDocument", "ingest_portal_act", "is_due", "run_due_sources", "run_source"]
