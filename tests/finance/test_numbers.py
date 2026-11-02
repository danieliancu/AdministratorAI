from datetime import date
from decimal import Decimal as D

import pytest

from apps.core.exports import safe_cell
from apps.core.numbers import BadValue, parse_date, parse_decimal
from apps.core.templatetags.money import lei, quantity


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1234", "1234.00"),
        ("1234,5", "1234.50"),
        ("1234.56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1.234.567", "1234567.00"),
        ("1 234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("0,125", None),
        ("-12,50", "-12.50"),
        (1234.5, "1234.50"),
        (100, "100.00"),
        (0.1 + 0.2, "0.30"),
    ],
)
def test_money_parsing(text, expected):
    if expected is None:
        with pytest.raises(BadValue):
            parse_decimal(text, places=2)
    else:
        assert parse_decimal(text, places=2) == D(expected)


@pytest.mark.parametrize("text", ["1.234", "1,234", "-1.234", "123.456", "12,345"])
def test_a_number_that_could_be_read_two_ways_is_refused(text):
    with pytest.raises(BadValue, match="ambiguu"):
        parse_decimal(text, places=2)
    with pytest.raises(BadValue, match="ambiguu"):
        parse_decimal(text, places=3)


@pytest.mark.parametrize(
    "text", ["", "abc", "12a", "NaN", "Infinity", "1e5", "1,2,3", "12.34.5", "--5", "(5)", "5 lei"]
)
def test_garbage_is_refused(text):
    with pytest.raises(BadValue):
        parse_decimal(text, places=2)


def test_true_is_not_a_number_and_huge_values_are_refused():
    with pytest.raises(BadValue):
        parse_decimal(True, places=2)
    with pytest.raises(BadValue):
        parse_decimal("999999999999", places=2)
    with pytest.raises(BadValue):
        parse_decimal(float("nan"), places=2)


def test_too_many_decimals_is_an_error_not_a_rounding():
    with pytest.raises(BadValue, match="zecimale"):
        parse_decimal("10,1234", places=2)
    assert parse_decimal("0,125", places=3) == D("0.125")


@pytest.mark.parametrize("text", ["31.03.2026", "2026-03-31", "31/03/2026", "31-03-2026"])
def test_dates(text):
    assert parse_date(text) == date(2026, 3, 31)


def test_impossible_dates_are_refused():
    with pytest.raises(BadValue):
        parse_date("31.02.2026")
    with pytest.raises(BadValue):
        parse_date("03/31/2026")


def test_display_uses_romanian_notation():
    assert lei(D("1234567.5")) == "1.234.567,50 lei"
    assert lei(None) == "—"
    assert quantity(D("1234.500")) == "1.234,5"
    assert quantity(D("10.000")) == "10"


@pytest.mark.parametrize("cell", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_exported_text_cannot_run_as_a_formula(cell):
    assert safe_cell(cell) == f"'{cell}"


def test_exported_numbers_keep_their_sign():
    assert safe_cell(D("-12.50")) == "-12,50"
    assert safe_cell(None) == ""
