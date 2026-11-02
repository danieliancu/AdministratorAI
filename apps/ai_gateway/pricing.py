from decimal import ROUND_CEILING, Decimal

MILLION = Decimal(1_000_000)
STEP = Decimal("0.00000001")


def _quantize(value):
    # Rounded up: a fraction of a unit must never escape the budget.
    return value.quantize(STEP, rounding=ROUND_CEILING)


def actual_cost(pricing, *, input_tokens, cached, write_30m, write_12h, output_tokens):
    """Cached reads and cache writes are parts of input_tokens, each with its own rate."""
    ordinary = input_tokens - cached - write_30m - write_12h
    if ordinary < 0:
        raise ValueError("Cache tokens exceed input tokens")
    total = (
        Decimal(ordinary) * pricing.input_per_mtok
        + Decimal(cached) * pricing.cached_read_per_mtok
        + Decimal(write_30m) * pricing.cache_write_30m_per_mtok
        + Decimal(write_12h) * pricing.cache_write_12h_per_mtok
        + Decimal(output_tokens) * pricing.output_per_mtok
    )
    return _quantize(total / MILLION)


def maximum_cost(pricing, *, input_bytes, max_output_tokens):
    """Upper bound before the call: one token per UTF-8 byte, at the dearest input rate."""
    dearest_input = max(
        pricing.input_per_mtok,
        pricing.cache_write_30m_per_mtok,
        pricing.cache_write_12h_per_mtok,
    )
    total = Decimal(input_bytes) * dearest_input + Decimal(max_output_tokens) * (
        pricing.output_per_mtok
    )
    return _quantize(total / MILLION)
