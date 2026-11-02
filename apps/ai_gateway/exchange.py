"""Official exchange rates from the National Bank of Romania. A rate is never assumed."""

from datetime import date
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree

BNR_URL = "https://curs.bnr.ro/nbrfxrates.xml"


class RateUnavailable(Exception):
    pass


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_bnr(content, currency):
    """Return (date, lei for one unit). Matched by local name: BNR has changed its namespace."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise RateUnavailable("The response is not valid XML") from exc
    for cube in root.iter():
        if _local(cube.tag) != "Cube":
            continue
        for rate in cube:
            if _local(rate.tag) == "Rate" and rate.get("currency") == currency:
                try:
                    day = date.fromisoformat(cube.get("date", ""))
                    value = Decimal(rate.text or "") / Decimal(rate.get("multiplier", "1"))
                except (ValueError, InvalidOperation) as exc:
                    raise RateUnavailable("The rate could not be read") from exc
                if value <= 0:
                    raise RateUnavailable("The rate is not positive")
                return day, value
    raise RateUnavailable(f"No rate for {currency}")
