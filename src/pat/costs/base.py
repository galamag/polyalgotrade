"""Shared rounding utilities for the cost layer."""

from decimal import ROUND_CEILING, Decimal


def ceil_to(x: Decimal, tick: Decimal) -> Decimal:
    """Round x up to the nearest multiple of tick."""
    return (x / tick).to_integral_value(rounding=ROUND_CEILING) * tick
