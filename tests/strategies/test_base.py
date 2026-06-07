from decimal import Decimal

from pat.core.types import Fill, Order, Side
from pat.strategies.base import CancelOrder, PostOrder, Strategy


def _order() -> Order:
    return Order(client_id="c1", token_id="t", side=Side.BUY,
                 price=Decimal("0.40"), size=Decimal("10"), reason="q", mode="backtest")


def test_post_and_cancel_actions_carry_payload() -> None:
    p = PostOrder(order=_order())
    c = CancelOrder(client_id="c1")
    assert p.order.client_id == "c1"
    assert c.client_id == "c1"


def test_actions_are_frozen() -> None:
    import dataclasses

    import pytest

    c = CancelOrder(client_id="c1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.client_id = "c2"  # type: ignore[misc]


def test_a_minimal_strategy_satisfies_the_protocol() -> None:
    class Noop:
        def on_trade(self, price: Decimal, size: Decimal) -> list:
            return []

        def on_fills(self, fills: list[Fill]) -> None:
            return None

    assert isinstance(Noop(), Strategy)
