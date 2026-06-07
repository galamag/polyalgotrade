from decimal import Decimal

from pat.core.types import Fill, Liquidity, Side
from pat.strategies.base import CancelOrder, PostOrder
from pat.strategies.market_maker import MarketMaker


def _mm(**kw: object) -> MarketMaker:
    base = dict(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                inventory_cap=Decimal("50"), alpha=Decimal("0.5"), tick=Decimal("0.01"))
    base.update(kw)
    return MarketMaker(**base)  # type: ignore[arg-type]


def test_first_trade_initializes_fv_and_posts_two_quotes() -> None:
    mm = _mm()
    actions = mm.on_trade(Decimal("0.50"), Decimal("10"))
    posts = [a for a in actions if isinstance(a, PostOrder)]
    assert len(actions) == 2 and len(posts) == 2  # no cancels on first quote
    by_side = {p.order.side: p.order.price for p in posts}
    assert by_side[Side.BUY] == Decimal("0.48")
    assert by_side[Side.SELL] == Decimal("0.52")


def test_requote_cancels_previous_quotes() -> None:
    mm = _mm()
    first = mm.on_trade(Decimal("0.50"), Decimal("10"))
    first_ids = {p.order.client_id for p in first if isinstance(p, PostOrder)}
    second = mm.on_trade(Decimal("0.50"), Decimal("10"))
    cancel_ids = {c.client_id for c in second if isinstance(c, CancelOrder)}
    assert cancel_ids == first_ids


def test_ewma_updates_fair_value() -> None:
    mm = _mm(alpha=Decimal("0.5"))
    mm.on_trade(Decimal("0.50"), Decimal("10"))     # fv = 0.50
    actions = mm.on_trade(Decimal("0.60"), Decimal("10"))  # fv = 0.5*0.60 + 0.5*0.50 = 0.55
    posts = {a.order.side: a.order.price for a in actions if isinstance(a, PostOrder)}
    assert posts[Side.BUY] == Decimal("0.53") and posts[Side.SELL] == Decimal("0.57")


def test_inventory_cap_blocks_adding_side() -> None:
    mm = _mm(inventory_cap=Decimal("10"), size=Decimal("10"))
    mm.on_trade(Decimal("0.50"), Decimal("10"))                  # posts bid+ask
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"),
                      size=Decimal("10"), fee=Decimal("0"),
                      liquidity=Liquidity.MAKER, mode="backtest", ts=1)])
    assert mm.inventory == Decimal("10")  # at the long cap
    actions = mm.on_trade(Decimal("0.50"), Decimal("10"))
    posted_sides = {a.order.side for a in actions if isinstance(a, PostOrder)}
    assert Side.BUY not in posted_sides and Side.SELL in posted_sides


def test_on_fills_updates_inventory_both_directions() -> None:
    mm = _mm()
    mm.on_trade(Decimal("0.50"), Decimal("10"))
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    ask_id = next(c for c, s in mm._side.items() if s is Side.SELL)
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"), size=Decimal("4"),
                      fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=1)])
    mm.on_fills([Fill(order_id=ask_id, token_id="t", price=Decimal("0.52"), size=Decimal("1"),
                      fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=2)])
    assert mm.inventory == Decimal("3")  # +4 - 1


def test_quote_prices_clamped_into_range() -> None:
    mm = _mm(half_spread=Decimal("0.05"))
    actions = mm.on_trade(Decimal("0.99"), Decimal("10"))  # fv 0.99 → ask would be 1.04
    asks = [
        a.order.price for a in actions
        if isinstance(a, PostOrder) and a.order.side is Side.SELL
    ]
    assert asks and asks[0] == Decimal("0.99")  # clamped to 1 - tick
