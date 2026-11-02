"""All act text in these tests is invented, and labelled so. It is not Romanian law."""

from datetime import date

import psycopg
import pytest

from apps.legal_knowledge.ingestion import ActIdentity, IncomingDocument, ingest_act
from apps.legal_knowledge.models import Authority, LegalActVersion
from tests.conftest import _owner_dsn

LEGAL_TABLES = (
    "legal_knowledge_legalchangeevent",
    "legal_knowledge_legalrelationship",
    "legal_knowledge_legalapplicability",
    "legal_knowledge_legalchunk",
    "legal_knowledge_legalprovisionversion",
    "legal_knowledge_legalprovision",
    "legal_knowledge_legalactversion",
    "legal_knowledge_legalact",
    "legal_knowledge_legaldocument",
    "legal_knowledge_legalembedding",
    "legal_knowledge_legalsyncjob",
    "ai_gateway_aiplatformusage",
    "ai_gateway_aiplatformbudget",
)


@pytest.fixture
def legal_db(committed_db, tmp_path, settings):
    settings.LEGAL_OBJECT_ROOT = str(tmp_path / "objects")
    yield
    with psycopg.connect(**_owner_dsn()) as conn:
        conn.execute(f"TRUNCATE {', '.join(LEGAL_TABLES)} CASCADE")
        conn.execute(
            """UPDATE legal_knowledge_legalsource
               SET is_enabled = false, last_attempt_at = NULL, last_success_at = NULL,
                   last_document_at = NULL, last_error = '', consecutive_failures = 0,
                   circuit_open_until = NULL"""
        )


def act_text(rate, *, extra=""):
    return f"""ACT DE TEST nr. 1 din 2 ianuarie 2020 (text inventat pentru teste)
Articolul 1
(1) Prezentul act de test stabilește impozitul pe venit fictiv, cu cota de {rate}%.
(2) Cota se aplică veniturilor realizate de microîntreprinderi fictive.
Articolul 2
Termenul de plată a impozitului fictiv este data de 25 a lunii următoare.
Articolul 3
Dispozițiile art. 1 se completează cu Legea nr. 227/2015. {extra}
"""


def ingest_test_act(
    *,
    rate="10",
    valid_from=date(2020, 1, 1),
    form=LegalActVersion.TextForm.CONSOLIDATED,
    authority=Authority.LEGISLATION,
    number="1",
    year=2020,
    text=None,
    source="manual_official",
):
    body = text if text is not None else act_text(rate)
    return ingest_act(
        IncomingDocument(
            source_key=source,
            url=f"https://example.test/act/{number}/{rate}",
            title=f"Act de test nr. {number}/{year}",
            authority=authority,
            content=body.encode(),
            content_type="text/plain",
            text=body,
        ),
        ActIdentity(act_type="ACT DE TEST", number=number, year=year, issuer="Emitent de test"),
        valid_from=valid_from,
        basis="fixture de test",
        text_form=form,
    )
