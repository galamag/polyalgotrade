from decimal import Decimal

import pytest

from pat.core.types import Category
from pat.costs.polymarket import (
    MAKER_REBATE_RATE,
    MARKET_HALF_SPREAD,
    POLYGON_TX_GAS_USDC,
    depth_vwap,
    gas_cost,
    liquidation_haircut,
    polymarket_maker_fee,
    polymarket_taker_fee,
)


def test_crypto_peak_is_1_75pct_at_half():
    assert polymarket_taker_fee(Category.CRYPTO, Decimal("0.5"), Decimal("1")) == Decimal("0.01750")


def test_geopolitics_is_zero():
    fee = polymarket_taker_fee(Category.GEOPOLITICS, Decimal("0.5"), Decimal("100"))
    assert fee == Decimal("0")


def test_politics_rate_is_4pct():
    fee = polymarket_taker_fee(Category.POLITICS, Decimal("0.5"), Decimal("1"))
    assert fee == Decimal("0.01000")


def test_maker_is_always_free():
    assert polymarket_maker_fee(Category.CRYPTO, Decimal("0.5"), Decimal("100")) == Decimal("0")


def test_tiny_fee_truncates_to_zero():
    # 0.03 * 0.0001 * 0.9999 ≈ 0.0000029997 -> rounds to 0.00000
    assert polymarket_taker_fee(Category.SPORTS, Decimal("0.0001"), Decimal("1")) == Decimal("0")


def test_out_of_range_price_raises():
    with pytest.raises(ValueError):
        polymarket_taker_fee(Category.CRYPTO, Decimal("-0.1"), Decimal("100"))
    with pytest.raises(ValueError):
        polymarket_taker_fee(Category.CRYPTO, Decimal("1.1"), Decimal("100"))


def test_negative_shares_raises():
    with pytest.raises(ValueError):
        polymarket_taker_fee(Category.CRYPTO, Decimal("0.5"), Decimal("-100"))


def test_price_at_bounds_is_zero():
    assert polymarket_taker_fee(Category.CRYPTO, Decimal("0"), Decimal("100")) == Decimal("0")
    assert polymarket_taker_fee(Category.CRYPTO, Decimal("1"), Decimal("100")) == Decimal("0")


def test_economics_rate_is_5pct():
    fee = polymarket_taker_fee(Category.ECONOMICS, Decimal("0.5"), Decimal("1"))
    assert fee == Decimal("0.01250")


def test_crypto_100_share_peak_is_1_75():
    fee = polymarket_taker_fee(Category.CRYPTO, Decimal("0.5"), Decimal("100"))
    assert fee == Decimal("1.75000")


def test_geopolitics_rebate_rate_is_zero():
    assert MAKER_REBATE_RATE[Category.GEOPOLITICS] == Decimal("0")
    assert MAKER_REBATE_RATE[Category.POLITICS] == Decimal("0.25")
    assert MAKER_REBATE_RATE[Category.CRYPTO] == Decimal("0.20")


def test_liquidation_haircut_scales_with_abs_shares_and_market_half_spread():
    assert MARKET_HALF_SPREAD > Decimal("0")
    assert liquidation_haircut(Decimal("100")) == Decimal("100") * MARKET_HALF_SPREAD
    assert liquidation_haircut(Decimal("-50")) == Decimal("50") * MARKET_HALF_SPREAD  # abs(short)
    assert liquidation_haircut(Decimal("0")) == Decimal("0")


def test_gas_cost_is_per_tx():
    assert gas_cost(1) == POLYGON_TX_GAS_USDC
    assert gas_cost(3) == POLYGON_TX_GAS_USDC * 3
    assert gas_cost(0) == Decimal("0")


def test_gas_cost_rejects_negative():
    with pytest.raises(ValueError):
        gas_cost(-1)


def test_depth_vwap_walks_levels_best_first():
    levels = [(Decimal("0.40"), Decimal("5")), (Decimal("0.50"), Decimal("5"))]
    assert depth_vwap(levels, Decimal("5")) == Decimal("0.40")
    assert depth_vwap(levels, Decimal("10")) == Decimal("0.45")  # (2 + 2.5) / 10


def test_depth_vwap_partial_second_level():
    levels = [(Decimal("0.40"), Decimal("5")), (Decimal("0.50"), Decimal("10"))]
    # 5 @ 0.40 + 3 @ 0.50 = 3.5 / 8 = 0.4375
    assert depth_vwap(levels, Decimal("8")) == Decimal("0.4375")


def test_depth_vwap_insufficient_depth_is_none():
    levels = [(Decimal("0.40"), Decimal("5"))]
    assert depth_vwap(levels, Decimal("6")) is None
    assert depth_vwap([], Decimal("1")) is None


def test_depth_vwap_size_exactly_total_depth():
    levels = [(Decimal("0.40"), Decimal("5")), (Decimal("0.50"), Decimal("5"))]
    assert depth_vwap(levels, Decimal("10")) == Decimal("0.45")
