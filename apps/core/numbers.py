"""Strict reading of numbers and dates typed by people or found in imported files."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_PLAIN = re.compile(r"^-?\d+(?:[.,]\d+)?$")
# A group of thousands never starts with zero, so 0,125 is a fraction and not 125.
_DOT_GROUPS = re.compile(r"^-?[1-9]\d{0,2}(?:\.\d{3})+(?:,\d+)?$")
_COMMA_GROUPS = re.compile(r"^-?[1-9]\d{0,2}(?:,\d{3})+(?:\.\d+)?$")
_AMBIGUOUS = re.compile(r"^-?[1-9]\d{0,2}[.,]\d{3}$")
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y")
MAX_MAGNITUDE = Decimal(10) ** 11


class BadValue(ValueError):
    pass


def parse_decimal(value, *, places):
    """Return a Decimal, refusing anything that could be misread instead of guessing.

    "1.234" is one thousand in Romanian notation and one point two elsewhere, so it is
    an error here: a wrong guess would change a financial figure a thousandfold.
    """
    if isinstance(value, bool):
        raise BadValue("Valoarea nu este un număr.")
    if isinstance(value, int | float):
        # A number cell in a spreadsheet: its value is known, only binary noise is removed.
        number = Decimal(str(round(value, 6) if isinstance(value, float) else value))
    else:
        text = re.sub(r"[\s ]", "", str(value))
        if _AMBIGUOUS.match(text):
            raise BadValue(
                f"„{text}” este ambiguu: scrie valoarea fără separator de mii sau cu altă "
                "precizie (de exemplu 1234 sau 1,2340)."
            )
        if _DOT_GROUPS.match(text):
            text = text.replace(".", "").replace(",", ".")
        elif _COMMA_GROUPS.match(text):
            text = text.replace(",", "")
        elif _PLAIN.match(text):
            text = text.replace(",", ".")
        else:
            raise BadValue(f"„{text}” nu este un număr valid.")
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise BadValue(f"„{text}” nu este un număr valid.") from exc
    if not number.is_finite():
        raise BadValue("Valoarea nu este un număr.")
    if abs(number) >= MAX_MAGNITUDE:
        raise BadValue("Valoarea este prea mare.")
    if -number.normalize().as_tuple().exponent > places:
        raise BadValue(f"Sunt permise cel mult {places} zecimale.")
    return number.quantize(Decimal(1).scaleb(-places))


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in _DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise BadValue(f"„{text}” nu este o dată validă. Folosește formatul ZZ.LL.AAAA.")
