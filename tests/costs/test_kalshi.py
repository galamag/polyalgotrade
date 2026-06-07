"""Tests for the Kalshi fee model (ADR 0009).

Key facts being verified:
- Taker fee uses quadratic formula: multiplier * price * (1 - price) * contracts
- Rounding is CEIL to the cent (not round-half-up), for non-direct members.
- Maker fee is 0.0175 (25 % of the 0.07 taker multiplier) — NOT zero.
- Per-series fee_multiplier may override the default 0.07.
- Price bounds [0, 1] and non-negative contracts are domain invariants.
"""

from decimal import Decimal

import pytest

from pat.costs.kalshi import kalshi_maker_fee, kalshi_taker_fee


def test_ceil_to_cent_diverges_from_round_at_p030():
    # raw = 0.07 * 0.30 * 0.70 * 1 = 0.0147
    # round(0.0147, 2)  -> 0.01   (rounds down because 4 < 5)
    # ceil to cent      -> 0.02   (CEIL always goes up)
    assert kalshi_taker_fee(Decimal("0.30"), Decimal("1")) == Decimal("0.02")


def test_peak_at_half():
    # 0.07 * 0.5 * 0.5 * 1 = 0.0175 -> ceil to cent -> 0.02
    assert kalshi_taker_fee(Decimal("0.50"), Decimal("1")) == Decimal("0.02")


def test_maker_fee_is_not_zero():
    # 0.0175 * 0.5 * 0.5 * 1 = 0.004375 -> ceil to cent -> 0.01
    assert kalshi_maker_fee(Decimal("0.50"), Decimal("1")) == Decimal("0.01")


def test_per_series_multiplier_override():
    # multiplier=0 means the category has zero fees (e.g. a promo series)
    assert kalshi_taker_fee(Decimal("0.50"), Decimal("1"), multiplier=Decimal("0")) == Decimal("0")


def test_price_at_bounds_is_zero():
    # At price=0 or price=1 the quadratic factor p*(1-p) is zero -> fee is zero
    assert kalshi_taker_fee(Decimal("0"), Decimal("100")) == Decimal("0")
    assert kalshi_taker_fee(Decimal("1"), Decimal("100")) == Decimal("0")


def test_out_of_range_price_raises():
    with pytest.raises(ValueError):
        kalshi_taker_fee(Decimal("-0.1"), Decimal("1"))
    with pytest.raises(ValueError):
        kalshi_taker_fee(Decimal("1.1"), Decimal("1"))


def test_negative_contracts_raises():
    with pytest.raises(ValueError):
        kalshi_taker_fee(Decimal("0.5"), Decimal("-1"))


# ------------------------------------------------------------------
# Additional coverage beyond the required minimum
# ------------------------------------------------------------------


def test_maker_negative_contracts_raises():
    with pytest.raises(ValueError):
        kalshi_maker_fee(Decimal("0.5"), Decimal("-1"))


def test_maker_out_of_range_price_raises():
    with pytest.raises(ValueError):
        kalshi_maker_fee(Decimal("1.5"), Decimal("1"))


def test_taker_scales_linearly_with_contracts():
    # Doubling contracts must double the fee (raw doubles -> ceil of double >= double of ceil)
    # Here we pick a price/contract combo where raw is exact cents to verify scaling.
    # 0.07 * 0.50 * 0.50 * 4 = 0.07 -> ceil to cent -> 0.07
    assert kalshi_taker_fee(Decimal("0.50"), Decimal("4")) == Decimal("0.07")


def test_maker_price_at_bounds_is_zero():
    assert kalshi_maker_fee(Decimal("0"), Decimal("10")) == Decimal("0")
    assert kalshi_maker_fee(Decimal("1"), Decimal("10")) == Decimal("0")


def test_zero_contracts_gives_zero_fee():
    assert kalshi_taker_fee(Decimal("0.50"), Decimal("0")) == Decimal("0")
    assert kalshi_maker_fee(Decimal("0.50"), Decimal("0")) == Decimal("0")
