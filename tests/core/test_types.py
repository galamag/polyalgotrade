from decimal import Decimal

import pytest
from pydantic import ValidationError

from pat.core.types import Category, Fill, Liquidity, Market, Order, Side, Venue


def test_price_must_be_in_unit_interval():
    with pytest.raises(ValidationError):
        Order(
            client_id="a",
            token_id="t",  # noqa: S106
            side=Side.BUY,
            price=Decimal("1.5"),
            size=Decimal("10"),
            mode="backtest",
            reason="x",
        )


def test_order_roundtrips_decimal():
    o = Order(
        client_id="a",
        token_id="t",  # noqa: S106
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        mode="backtest",
        reason="quote",
    )
    assert o.price == Decimal("0.40") and o.notional == Decimal("4.00")


def test_market_category_normalizes():
    m = Market(
        id="m1",
        venue=Venue.POLYMARKET,
        question="Q?",
        category=Category.GEOPOLITICS,
        tick_size=Decimal("0.01"),
    )
    assert m.category is Category.GEOPOLITICS


def test_fill_carries_fee_and_liquidity():
    f = Fill(
        order_id="a",
        token_id="t",  # noqa: S106
        price=Decimal("0.40"),
        size=Decimal("10"),
        fee=Decimal("0.0"),
        liquidity=Liquidity.MAKER,
        mode="backtest",
        ts=1,
    )
    assert f.liquidity is Liquidity.MAKER and f.fee == Decimal("0")
