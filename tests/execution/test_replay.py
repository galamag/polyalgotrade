from decimal import Decimal

from pat.core.types import Category, Market, Venue
from pat.execution.backtest import BacktestBroker
from pat.execution.replay import run_replay
from pat.strategies.market_maker import MarketMaker


def _mkt() -> Market:
    return Market(id="m", venue=Venue.POLYMARKET, question="q", category=Category.GEOPOLITICS)


def test_first_trade_produces_no_fill_but_posts_quotes() -> None:
    """No look-ahead: the first trade can't fill (no resting quotes yet)."""
    broker = BacktestBroker(market=_mkt())
    mm = MarketMaker(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                     inventory_cap=Decimal("50"))
    fills = run_replay(mm, broker, [(Decimal("0.50"), Decimal("10"))])
    assert fills == []
    assert mm.fv == Decimal("0.50")  # strategy did observe the trade and quote


def test_bid_fills_on_adverse_down_move() -> None:
    """Quote at 0.50, then price trades through the 0.48 bid → we buy into a fall."""
    broker = BacktestBroker(market=_mkt())
    mm = MarketMaker(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                     inventory_cap=Decimal("50"))
    fills = run_replay(mm, broker, [
        (Decimal("0.50"), Decimal("10")),   # posts bid 0.48 / ask 0.52
        (Decimal("0.47"), Decimal("10")),   # 0.47 < 0.48 → bid fills (adverse)
    ])
    assert len(fills) == 1
    assert fills[0].price == Decimal("0.48")
    assert mm.inventory == Decimal("10")  # we are now long into a falling market


def test_returns_all_broker_fills() -> None:
    broker = BacktestBroker(market=_mkt())
    mm = MarketMaker(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                     inventory_cap=Decimal("50"))
    fills = run_replay(mm, broker, [
        (Decimal("0.50"), Decimal("10")),
        (Decimal("0.47"), Decimal("10")),
        (Decimal("0.55"), Decimal("10")),
    ])
    assert fills is broker.fills
