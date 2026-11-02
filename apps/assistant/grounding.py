"""Check a generated answer against what the application actually gave the model."""

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_DATE = re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")


def _readings(token):
    """Every value a number as written could mean. A date is compared as written."""
    if _DATE.match(token):
        return {token}
    readings = set()
    for candidate in (
        token,
        token.replace(".", "").replace(",", "."),
        token.replace(",", ""),
        token.replace(",", "."),
    ):
        try:
            readings.add(Decimal(candidate).normalize())
        except InvalidOperation:
            continue
    return readings or {token}


def numbers_in(text):
    return [match.group(0) for match in _NUMBER.finditer(text)]


def known_values(texts):
    known = set()
    for text in texts:
        for token in numbers_in(text):
            known |= _readings(token)
    return known


def unknown_numbers(texts, known):
    """Numbers the model wrote that none of its inputs contained."""
    return [token for text in texts for token in numbers_in(text) if not (_readings(token) & known)]
