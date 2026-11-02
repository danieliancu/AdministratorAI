from datetime import date
from decimal import Decimal as D

import pytest

from apps.ai_gateway.exchange import RateUnavailable, parse_bnr
from apps.core.templatetags.money import ron

SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="https://www.bnr.ro/xsd"><Header><PublishingDate>2026-11-02</PublishingDate></Header>
<Body><OrigCurrency>RON</OrigCurrency><Cube date="2026-11-02">
<Rate currency="EUR">5.3403</Rate><Rate currency="USD">4.6012</Rate>
<Rate currency="HUF" multiplier="100">1.4645</Rate></Cube></Body></DataSet>"""


def test_official_rate_is_read_with_its_date():
    assert parse_bnr(SAMPLE, "USD") == (date(2026, 11, 2), D("4.6012"))


def test_a_multiplier_is_applied():
    assert parse_bnr(SAMPLE, "HUF")[1] == D("0.014645")


def test_old_namespace_still_reads():
    assert parse_bnr(SAMPLE.replace(b"https://www.bnr.ro/xsd", b"http://www.bnr.ro/xsd"), "USD")


@pytest.mark.parametrize(
    "content",
    [
        b"<html>pagina principala</html>",
        b"nu este xml",
        b'<Cube date="x"><Rate currency="USD">1</Rate></Cube>',
    ],
)
def test_anything_unexpected_stores_no_rate(content):
    with pytest.raises(RateUnavailable):
        parse_bnr(content, "USD")


def test_entity_expansion_is_refused():
    bomb = (
        b'<!DOCTYPE x [<!ENTITY a "1">]>'
        b'<Cube date="2026-11-02"><Rate currency="USD">&a;</Rate></Cube>'
    )
    with pytest.raises(Exception):  # noqa: B017
        parse_bnr(bomb, "USD")


def test_display_is_in_lei_with_two_decimals():
    assert ron(D("0.05000000"), "USD", D("4.6012")) == "0,23 lei"
    assert ron(D("1234.5678"), "USD", D("1")) == "1.234,57 lei"
    assert ron(D("12"), "RON", None) == "12,00 lei"


def test_a_missing_rate_is_not_guessed():
    assert ron(D("0.5"), "USD", None) == "0,50 USD"
    assert ron(None, "USD", D("4")) == "—"
