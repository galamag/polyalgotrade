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


def test_quote_band_stands_aside_near_resolution() -> None:
    # fv within quote_band of a boundary → no quotes posted (near-resolved binary).
    mm = _mm(quote_band=Decimal("0.10"))
    high = mm.on_trade(Decimal("0.97"), Decimal("10"))   # first trade seeds fv=0.97 > 0.90
    assert [a for a in high if isinstance(a, PostOrder)] == []
    low = _mm(quote_band=Decimal("0.10")).on_trade(Decimal("0.03"), Decimal("10"))  # fv=0.03 < 0.10
    assert [a for a in low if isinstance(a, PostOrder)] == []


def test_quote_band_quotes_normally_at_mid_price() -> None:
    mm = _mm(quote_band=Decimal("0.10"))
    actions = mm.on_trade(Decimal("0.50"), Decimal("10"))  # mid → two-sided as usual
    assert len([a for a in actions if isinstance(a, PostOrder)]) == 2


def test_quote_band_default_zero_keeps_legacy_quoting_at_extremes() -> None:
    # default quote_band=0 → guard disabled, still posts (and clamps) near the boundary
    mm = _mm(half_spread=Decimal("0.05"))
    actions = mm.on_trade(Decimal("0.99"), Decimal("10"))
    assert len([a for a in actions if isinstance(a, PostOrder)]) == 2


def _quotes(actions: list) -> dict:
    return {a.order.side: a.order.price for a in actions if isinstance(a, PostOrder)}


def _set_long(mm: MarketMaker, shares: str) -> None:
    """Seed fv=0.50 + post quotes, then fill the bid to push inventory long by `shares`."""
    mm.on_trade(Decimal("0.50"), Decimal("10"))
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"),
                      size=Decimal(shares), fee=Decimal("0"),
                      liquidity=Liquidity.MAKER, mode="backtest", ts=1)])


def test_gamma_long_lowers_both_quotes() -> None:
    base = _mm(inventory_cap=Decimal("100"), gamma=Decimal("0"))
    skew = _mm(inventory_cap=Decimal("100"), gamma=Decimal("0.10"))
    _set_long(base, "50")   # inv_frac = 0.5
    _set_long(skew, "50")
    b = _quotes(base.on_trade(Decimal("0.50"), Decimal("10")))
    s = _quotes(skew.on_trade(Decimal("0.50"), Decimal("10")))
    assert s[Side.BUY] < b[Side.BUY]
    assert s[Side.SELL] < b[Side.SELL]


def test_skew_delta_long_deepens_bid_only() -> None:
    base = _mm(inventory_cap=Decimal("100"), skew_delta=Decimal("0"))
    skew = _mm(inventory_cap=Decimal("100"), skew_delta=Decimal("0.10"))
    _set_long(base, "50")
    _set_long(skew, "50")
    b = _quotes(base.on_trade(Decimal("0.50"), Decimal("10")))
    s = _quotes(skew.on_trade(Decimal("0.50"), Decimal("10")))
    assert s[Side.BUY] < b[Side.BUY]       # bid deeper
    assert s[Side.SELL] == b[Side.SELL]    # ask unchanged


def test_skew_zero_identical_to_v1() -> None:
    plain = _mm(inventory_cap=Decimal("100"))
    skew = _mm(inventory_cap=Decimal("100"), gamma=Decimal("0"), skew_delta=Decimal("0"))
    _set_long(plain, "50")
    _set_long(skew, "50")
    assert _quotes(plain.on_trade(Decimal("0.50"), Decimal("10"))) == \
           _quotes(skew.on_trade(Decimal("0.50"), Decimal("10")))


def test_inv_frac_clamped_bounds_shift() -> None:
    mm = _mm(inventory_cap=Decimal("10"), gamma=Decimal("0.10"))
    mm.on_trade(Decimal("0.50"), Decimal("10"))
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    # inv=+20 > cap=10 -> frac clamped to 1
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"),
                      size=Decimal("20"), fee=Decimal("0"),
                      liquidity=Liquidity.MAKER, mode="backtest", ts=1)])
    q = _quotes(mm.on_trade(Decimal("0.50"), Decimal("10")))
    assert Side.BUY not in q                       # over cap -> only ask posts
    assert q[Side.SELL] == Decimal("0.42")         # fv_eff=0.50-0.10*1=0.40, ask=0.40+0.02=0.42


def test_no_cross_invariant_across_grid() -> None:
    grid = [Decimal("0"), Decimal("0.05"), Decimal("0.10")]
    for gamma in grid:
        for delta in grid:
            for fv in (Decimal("0.02"), Decimal("0.50"), Decimal("0.98")):
                for inv in (Decimal("-99"), Decimal("0"), Decimal("99")):
                    mm = _mm(inventory_cap=Decimal("100"), half_spread=Decimal("0.05"),
                             quote_band=Decimal("0"), gamma=gamma, skew_delta=delta)
                    mm.fv = fv
                    mm.inventory = inv
                    q = _quotes(mm.on_trade(fv, Decimal("10")))
                    if Side.BUY in q and Side.SELL in q:
                        assert q[Side.SELL] - q[Side.BUY] >= mm.tick
