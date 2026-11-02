"""Decide, without any model, what a question is about and which period it covers."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from apps.legal_knowledge.parsing import fold_for_search
from apps.reports.figures import add_months, first_of_month

_MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}
_SECTION_WORDS = {
    "expenses": ("cheltuiel", "cost", "furnizor", "platit", "plati"),
    "receivables": ("factur", "neincasat", "restan", "scaden", "creant", "client", "incasa"),
    "sales": ("venit", "vanz", "vand", "client", "cifra de afaceri"),
    "inventory": ("stoc", "produs", "marf", "aprovizion"),
}
_ALL_SECTIONS = ("expenses", "receivables", "sales", "inventory")
_RISK_WORDS = ("risc", "problem", "ingrijor", "verific", "atentie")
_LEGAL_WORDS = (
    "lege",
    "legal",
    "legisl",
    "cod fiscal",
    "codul fiscal",
    "tva",
    "impozit",
    "anaf",
    "ordonant",
    "oug",
    "articol",
    "contributi",
    "declarati",
    "obligati",
    "fiscal",
    "termen",
)
_TAX_CALCULATION = re.compile(
    r"(\bcat\b|\bcate\b|calcul|\bce suma\b).{0,40}"
    r"(impozit|tva|contributi|taxa|taxe|dividend|de plata la|de plata catre)"
)


@dataclass(frozen=True)
class Understanding:
    category: str
    sections: tuple
    wants_legal: bool
    start: date
    end: date
    period_label: str
    period_assumed: bool


def _month_range(month):
    return month, add_months(month, 1) - timedelta(days=1)


def _label(start, end):
    return f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"


def _period(text, today):
    """Return (start, end, assumed). An unstated period falls back to the current month."""
    current = first_of_month(today)
    if re.search(r"\bluna (aceasta|asta|curenta)\b", text):
        return (*_month_range(current), False)
    if re.search(r"\bluna (trecuta|precedenta|anterioara)\b", text):
        return (*_month_range(add_months(current, -1)), False)
    if re.search(r"\banul (acesta|asta|curent)\b", text):
        return date(today.year, 1, 1), date(today.year, 12, 31), False
    if re.search(r"\banul (trecut|precedent|anterior)\b", text):
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), False
    recent = re.search(r"\bultimele (\d{1,2}) luni\b", text)
    if recent and 1 <= int(recent.group(1)) <= 36:
        first = add_months(current, 1 - int(recent.group(1)))
        return first, _month_range(current)[1], False
    year = re.search(r"\b(20\d{2})\b", text)
    for name, number in _MONTHS.items():
        if re.search(rf"\b{name}\b", text):
            if year:
                return (*_month_range(date(int(year.group(1)), number, 1)), False)
            # Without a year, the latest such month that has already started.
            chosen = date(today.year, number, 1)
            if chosen > today:
                chosen = date(today.year - 1, number, 1)
            return (*_month_range(chosen), False)
    if year:
        return date(int(year.group(1)), 1, 1), date(int(year.group(1)), 12, 31), False
    return (*_month_range(current), True)


def understand(question, today):
    text = fold_for_search(question)
    start, end, assumed = _period(text, today)
    wants_legal = any(word in text for word in _LEGAL_WORDS)
    if any(word in text for word in _RISK_WORDS):
        sections = _ALL_SECTIONS
    else:
        sections = tuple(
            section
            for section, words in _SECTION_WORDS.items()
            if any(word in text for word in words)
        )
    if _TAX_CALCULATION.search(text):
        category = "tax_calculation"
    elif wants_legal and not sections:
        category = "legal"
    elif wants_legal:
        category = "mixed"
    else:
        category = "financial"
    return Understanding(
        category=category,
        sections=sections,
        wants_legal=wants_legal,
        start=start,
        end=end,
        period_label=_label(start, end),
        period_assumed=assumed,
    )
