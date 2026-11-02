"""Hybrid retrieval that only offers text applicable on the date asked about.

It returns evidence and limitations, and writes no answer. Retrieved text is untrusted data:
whoever builds a prompt from it must treat it as content, never as instructions.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import connections
from django.utils import timezone

from .models import Authority, LegalActVersion, LegalSource
from .parsing import fold_for_search

CANDIDATES = 40
RRF_K = 60
AUTHORITY_WEIGHT = {
    Authority.LEGISLATION: 1.0,
    Authority.CONSOLIDATED: 1.0,
    Authority.PROCEDURE: 0.85,
    Authority.GUIDANCE: 0.7,
    Authority.INTERPRETATION: 0.5,
}
MIN_TERM_LENGTH = 3

_BASE = """
    FROM legal_knowledge_legalchunk c
    JOIN legal_knowledge_legalprovisionversion pv ON pv.id = c.provision_version_id
    JOIN legal_knowledge_legalprovision p ON p.id = pv.provision_id
    JOIN legal_knowledge_legalactversion v ON v.id = pv.act_version_id
    JOIN legal_knowledge_legalact a ON a.id = v.act_id
    JOIN legal_knowledge_legaldocument d ON d.id = v.document_id
    JOIN legal_knowledge_legalapplicability ap ON ap.version_id = v.id
    WHERE ap.valid_from <= %(on_date)s
      AND (ap.valid_to IS NULL OR ap.valid_to > %(on_date)s)
      AND ap.recorded_at <= %(known_at)s
      AND (ap.retired_at IS NULL OR ap.retired_at > %(known_at)s)
      AND v.recorded_at <= %(known_at)s
      AND v.review_status <> 'rejected'
      AND a.authority <> 'draft'
"""

_COLUMNS = """
    c.id AS chunk_id, c.text, c.paragraph_label, c.checksum, p.label AS article,
    pv.structure_path, a.act_type, a.number, a.year, a.title, a.authority, a.official_url,
    v.id AS version_id, v.text_form, v.consolidated_as_of, v.review_status,
    ap.valid_from, ap.valid_to, d.retrieved_at, d.source_id
"""


@dataclass(frozen=True)
class Evidence:
    text: str
    citation: str
    article: str
    paragraph: str
    act_title: str
    authority: str
    authority_label: str
    official_url: str
    valid_from: date
    valid_to: date | None
    text_form: str
    review_status: str
    last_retrieved_at: datetime
    source_key: str
    version_id: object
    warnings: tuple = ()
    score: float = 0.0


@dataclass(frozen=True)
class RetrievalResult:
    on_date: date
    known_at: datetime
    evidence: list = field(default_factory=list)
    limitations: list = field(default_factory=list)

    @property
    def has_evidence(self):
        return bool(self.evidence)


def _or_query(question):
    terms = re.findall(r"[a-z0-9]+", fold_for_search(question))
    unique = list(dict.fromkeys(t for t in terms if len(t) >= MIN_TERM_LENGTH))
    return " | ".join(unique)


def _text_candidates(cursor, params):
    query = _or_query(params["question"])
    if not query:
        return []
    cursor.execute(
        f"""SELECT {_COLUMNS},
                   ts_rank_cd(c.search_vector, to_tsquery('romanian', %(query)s)) AS rank
            {_BASE}
            AND c.search_vector @@ to_tsquery('romanian', %(query)s)
            ORDER BY rank DESC LIMIT {CANDIDATES}""",  # noqa: S608
        {**params, "query": query},
    )
    return _rows(cursor)


def _vector_candidates(cursor, params, query_vector, model_key):
    cursor.execute(
        f"""SELECT {_COLUMNS}, e.embedding <=> %(vector)s::vector AS distance
            {_BASE.replace("JOIN legal_knowledge_legalprovisionversion pv",
                           "JOIN legal_knowledge_legalembedding e ON e.checksum = c.checksum "
                           "AND e.model_key = %(model)s "
                           "JOIN legal_knowledge_legalprovisionversion pv")}
            ORDER BY distance LIMIT {CANDIDATES}""",  # noqa: S608
        {**params, "vector": str(list(query_vector)), "model": model_key},
    )
    return _rows(cursor)


def _rows(cursor):
    columns = [column.name for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _fuse(*rankings):
    """Reciprocal rank fusion, then source authority: binding law outranks commentary."""
    merged = {}
    for ranking in rankings:
        for position, row in enumerate(ranking):
            entry = merged.setdefault(row["chunk_id"], {"row": row, "score": 0.0})
            entry["score"] += 1.0 / (RRF_K + position + 1)
    for entry in merged.values():
        entry["score"] *= AUTHORITY_WEIGHT.get(entry["row"]["authority"], 0.5)
    return sorted(merged.values(), key=lambda entry: entry["score"], reverse=True)


def _evidence(entry):
    row = entry["row"]
    warnings = []
    if row["text_form"] == LegalActVersion.TextForm.ORIGINAL:
        warnings.append(
            "Text în forma publicată inițial: modificările ulterioare pot lipsi."
        )
    elif row["text_form"] == LegalActVersion.TextForm.UNKNOWN:
        warnings.append("Nu se știe dacă textul include modificările ulterioare.")
    if row["review_status"] != LegalActVersion.Review.REVIEWED:
        warnings.append("Text neverificat de un specialist.")
    if row["authority"] in (Authority.GUIDANCE, Authority.INTERPRETATION):
        warnings.append("Nu este un text de lege.")
    return Evidence(
        text=row["text"],
        citation=f"{row['act_type']} nr. {row['number']}/{row['year']}",
        article=row["article"],
        paragraph=row["paragraph_label"],
        act_title=row["title"],
        authority=row["authority"],
        authority_label=Authority(row["authority"]).label,
        official_url=row["official_url"],
        valid_from=row["valid_from"],
        valid_to=row["valid_to"],
        text_form=row["text_form"],
        review_status=row["review_status"],
        last_retrieved_at=row["retrieved_at"],
        source_key=row["source_id"],
        version_id=row["version_id"],
        warnings=tuple(warnings),
        score=entry["score"],
    )


def _freshness_limitations(sources_used, now, using):
    limitations = []
    sources = LegalSource.objects.using(using).filter(pk__in=sources_used)
    for source in sources:
        if source.connector == LegalSource.Connector.MANUAL:
            continue
        limit = timedelta(hours=source.freshness_hours)
        if source.last_success_at is None or now - source.last_success_at > limit:
            limitations.append(
                f"Sursa „{source.name}” nu a fost sincronizată recent: "
                "pot exista modificări neincluse."
            )
    return limitations


def retrieve(
    question,
    *,
    on_date,
    known_at=None,
    limit=8,
    query_vector=None,
    embedding_model=None,
    using="default",
):
    """`on_date` is when the law must apply. `known_at` reconstructs an earlier state of
    knowledge, for auditing what the application could have used at that moment."""
    now = timezone.now()
    known_at = known_at or now
    params = {"on_date": on_date, "known_at": known_at, "question": question}
    limitations = []
    with connections[using].cursor() as cursor:
        text_rows = _text_candidates(cursor, params)
        vector_rows = []
        if query_vector is not None and embedding_model:
            vector_rows = _vector_candidates(cursor, params, query_vector, embedding_model)
        else:
            limitations.append("Căutare doar după cuvinte: căutarea semantică nu este disponibilă.")
    fused = _fuse(text_rows, vector_rows)
    evidence = [_evidence(entry) for entry in fused[:limit]]
    if evidence:
        sources_used = {item.source_key for item in evidence}
        limitations.extend(_freshness_limitations(sources_used, now, using))
    else:
        limitations.append(
            "Nu există în baza de cunoștințe text aplicabil la această dată pentru întrebare."
        )
    return RetrievalResult(
        on_date=on_date, known_at=known_at, evidence=evidence, limitations=limitations
    )
