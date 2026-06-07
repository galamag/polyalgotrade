from decimal import Decimal

from pat.core.types import Category
from pat.costs.polymarket import MAKER_REBATE_RATE, polymarket_maker_fee, polymarket_taker_fee


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


def test_min_fee_floor_for_tiny_nonzero():
    f = polymarket_taker_fee(Category.SPORTS, Decimal("0.001"), Decimal("1"))
    assert f >= Decimal("0.00001")


def test_geopolitics_rebate_rate_is_zero():
    assert MAKER_REBATE_RATE[Category.GEOPOLITICS] == Decimal("0")
    assert MAKER_REBATE_RATE[Category.POLITICS] == Decimal("0.25")
    assert MAKER_REBATE_RATE[Category.CRYPTO] == Decimal("0.20")
