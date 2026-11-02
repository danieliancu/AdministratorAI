from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.ai_gateway.gateway import billing_period
from apps.ai_gateway.pricing import actual_cost, maximum_cost

ONE_DOLLAR = SimpleNamespace(
    input_per_mtok=Decimal("1"),
    cached_read_per_mtok=Decimal("0.1"),
    cache_write_30m_per_mtok=Decimal("1.25"),
    cache_write_12h_per_mtok=Decimal("2.5"),
    output_per_mtok=Decimal("0"),
)


def test_cost_matches_the_worked_example_in_the_provider_documentation():
    # OpenAI prompt caching guide: 12000 input, 4000 cached, 3000 + 4000 written, $1 per million.
    cost = actual_cost(
        ONE_DOLLAR, input_tokens=12000, cached=4000, write_30m=3000, write_12h=4000, output_tokens=0
    )
    assert cost == Decimal("0.01515")


def test_cost_uses_decimal_and_never_rounds_down():
    pricing = SimpleNamespace(**{**vars(ONE_DOLLAR), "output_per_mtok": Decimal("4")})
    cost = actual_cost(
        pricing, input_tokens=1, cached=0, write_30m=0, write_12h=0, output_tokens=1
    )
    assert isinstance(cost, Decimal)
    assert cost == Decimal("0.00000500")
    tiny = actual_cost(
        ONE_DOLLAR, input_tokens=1, cached=1, write_30m=0, write_12h=0, output_tokens=0
    )
    assert tiny == Decimal("0.00000010")
    smallest = SimpleNamespace(**{**vars(ONE_DOLLAR), "cached_read_per_mtok": Decimal("0.001")})
    assert actual_cost(
        smallest, input_tokens=1, cached=1, write_30m=0, write_12h=0, output_tokens=0
    ) == Decimal("0.00000001")


def test_impossible_usage_is_refused_rather_than_billed_wrongly():
    with pytest.raises(ValueError):
        actual_cost(ONE_DOLLAR, input_tokens=10, cached=20, write_30m=0, write_12h=0,
                    output_tokens=0)


def test_maximum_uses_the_dearest_input_rate():
    pricing = SimpleNamespace(**{**vars(ONE_DOLLAR), "output_per_mtok": Decimal("4")})
    assert maximum_cost(pricing, input_bytes=1000, max_output_tokens=100) == Decimal("0.00290000")


def test_maximum_always_covers_any_real_outcome():
    pricing = SimpleNamespace(**{**vars(ONE_DOLLAR), "output_per_mtok": Decimal("4")})
    bound = maximum_cost(pricing, input_bytes=500, max_output_tokens=100)
    for cached, w30, w12 in ((500, 0, 0), (0, 500, 0), (0, 0, 500), (100, 200, 200), (0, 0, 0)):
        real = actual_cost(
            pricing, input_tokens=500, cached=cached, write_30m=w30, write_12h=w12,
            output_tokens=100,
        )
        assert real <= bound


@pytest.mark.parametrize(
    "now,anchor,start,end",
    [
        (datetime(2026, 3, 15, tzinfo=UTC), 1, datetime(2026, 3, 1, tzinfo=UTC),
         datetime(2026, 4, 1, tzinfo=UTC)),
        (datetime(2026, 3, 15, tzinfo=UTC), 20, datetime(2026, 2, 20, tzinfo=UTC),
         datetime(2026, 3, 20, tzinfo=UTC)),
        (datetime(2026, 1, 5, tzinfo=UTC), 20, datetime(2025, 12, 20, tzinfo=UTC),
         datetime(2026, 1, 20, tzinfo=UTC)),
        (datetime(2026, 12, 25, tzinfo=UTC), 20, datetime(2026, 12, 20, tzinfo=UTC),
         datetime(2027, 1, 20, tzinfo=UTC)),
    ],
)
def test_billing_periods(now, anchor, start, end):
    assert billing_period(now, anchor) == (start, end)
