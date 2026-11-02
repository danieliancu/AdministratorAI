"""Legal evidence for an answer. Only what is returned here can ever be cited."""

import re

from apps.legal_knowledge.parsing import fold_for_search
from apps.legal_knowledge.retrieval import retrieve

MAX_EVIDENCE = 4
MAX_EVIDENCE_CHARS = 1500
_STOP_WORDS = {
    "care", "este", "sunt", "pentru", "cum", "cat", "cate", "cati", "unde", "cand", "firma",
    "firmei", "mea", "meu", "mele", "mei", "din", "dintre", "despre", "ale", "ala", "asta",
    "acest", "aceasta", "aceste", "trebuie", "pot", "poate", "putem", "fac", "face", "are",
    "am", "ai", "sau", "dar", "daca", "mai", "lege", "legea", "legii", "aplica", "aplicabil",
    "luna", "anul", "ceea", "ce", "ca", "cu", "la", "de", "pe", "in", "si",
}  # fmt: skip
_AMENDING = re.compile(r"\b(modificarea|completarea|abrogarea|rectificare|rectificarea)\b")


def _terms(question):
    words = re.findall(r"[a-z0-9]+", fold_for_search(question))
    return list(dict.fromkeys(w for w in words if len(w) >= 3 and w not in _STOP_WORDS))


def _is_relevant(item, terms):
    """Full-text search is a wide net here: require more than one shared word."""
    if not terms:
        return False
    text = fold_for_search(f"{item.act_title} {item.text}")
    # A short prefix tolerates Romanian endings: impozit, impozitul, impozitele.
    matched = sum(1 for term in terms if term[:6] in text)
    return matched >= min(2, len(terms))


def _is_amending_act(item):
    return bool(_AMENDING.search(fold_for_search(item.act_title)))


def _citation(item, index):
    amending = _is_amending_act(item)
    warnings = list(item.warnings)
    if amending:
        # Such an act quotes articles of the act it changes, so the article label misleads.
        warnings.append(
            "Act de modificare: articolul numerotat aici poate aparține actului modificat, "
            "de aceea nu este indicat."
        )
    return {
        "id": f"E{index}",
        "citation": item.citation,
        "title": item.act_title,
        "article": "" if amending else item.article,
        "paragraph": "" if amending else item.paragraph,
        "authority": item.authority_label,
        "official_url": item.official_url if item.official_url.startswith("http") else "",
        "valid_from": item.valid_from.strftime("%d.%m.%Y"),
        "valid_to": item.valid_to.strftime("%d.%m.%Y") if item.valid_to else "",
        "retrieved_at": item.last_retrieved_at.strftime("%d.%m.%Y"),
        "warnings": warnings,
        "text": item.text[:MAX_EVIDENCE_CHARS],
    }


def gather(question, on_date):
    """Return (citations, limitations), keeping only evidence that applied on the date."""
    result = retrieve(question, on_date=on_date, limit=12)
    terms = _terms(question)
    relevant = [item for item in result.evidence if _is_relevant(item, terms)][:MAX_EVIDENCE]
    citations = [_citation(item, index) for index, item in enumerate(relevant, start=1)]
    limitations = list(result.limitations)
    if result.evidence and not relevant:
        limitations.append("Nu am găsit în baza legislativă un text relevant pentru întrebare.")
    return citations, limitations
