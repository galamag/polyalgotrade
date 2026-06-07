from decimal import Decimal

from pat.core.types import Category, Market, Venue
from scripts.run_mm_backtest import run_sweep


def _mkt() -> Market:
    return Market(id="m", venue=Venue.POLYMARKET, question="q", category=Category.GEOPOLITICS)


def _oscillating_stream(n: int) -> list[tuple[Decimal, Decimal]]:
    """Deterministic saw-tooth around 0.50 that repeatedly trades through ±2-5c quotes."""
    out: list[tuple[Decimal, Decimal]] = []
    for i in range(n):
        # cycle 0.46, 0.50, 0.54, 0.50, ... to fill both bid and ask repeatedly
        step = [Decimal("0.46"), Decimal("0.50"), Decimal("0.54"), Decimal("0.50")][i % 4]
        out.append((step, Decimal("10")))
    return out


def test_sweep_returns_a_row_per_half_spread() -> None:
    streams = {"t": _oscillating_stream(40)}
    hs = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")]
    rows = run_sweep(streams, market=_mkt(),
                     half_spreads=hs,
                     size=Decimal("10"), inventory_cap=Decimal("100"), alpha=Decimal("0.5"))
    assert [r["half_spread"] for r in rows] == hs
    assert all("result" in r and "verdict" in r for r in rows)


def test_sweep_aggregates_fills_across_streams() -> None:
    streams = {"a": _oscillating_stream(40), "b": _oscillating_stream(40)}
    rows = run_sweep(streams, market=_mkt(), half_spreads=[Decimal("0.02")],
                     size=Decimal("10"), inventory_cap=Decimal("100"), alpha=Decimal("0.5"))
    assert rows[0]["result"].n_trades > 0


def test_sweep_marks_open_inventory() -> None:
    # a one-sided down-drift leaves the MM long → inventory_value must be non-zero
    streams = {"t": [(Decimal("0.50"), Decimal("10"))] + [(Decimal("0.40"), Decimal("10"))] * 10}
    rows = run_sweep(streams, market=_mkt(), half_spreads=[Decimal("0.02")],
                     size=Decimal("10"), inventory_cap=Decimal("1000"), alpha=Decimal("0.5"))
    assert rows[0]["result"].inventory_value != Decimal("0")


def test_pipeline_reaches_1000_fills_and_produces_verdict() -> None:
    """End-to-end offline gate analog: ≥1000 MM fills, a Verdict object is produced.

    The saw-tooth stream fills ~50% of trades (2 per 4-trade cycle), so
    5 tokens × 600 trades = 3000 trades → ~1500 fills (comfortable margin over 1000).
    """
    streams = {f"t{k}": _oscillating_stream(600) for k in range(5)}
    rows = run_sweep(streams, market=_mkt(), half_spreads=[Decimal("0.02")],
                     size=Decimal("10"), inventory_cap=Decimal("100000"), alpha=Decimal("0.5"))
    r = rows[0]
    assert r["result"].n_trades >= 1000  # ~1500 expected
    assert r["verdict"].reason  # non-empty verdict string (advance True/False both fine)


def test_streams_from_fills_groups_orders_and_filters() -> None:
    from pat.core.types import Fill, Liquidity
    from scripts.run_mm_backtest import streams_from_fills

    fills = [
        Fill(order_id="o1", token_id="a", price=Decimal("0.5"), size=Decimal("3"),
             fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=2),
        Fill(order_id="o2", token_id="a", price=Decimal("0.4"), size=Decimal("1"),
             fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=1),
        Fill(order_id="o3", token_id="b", price=Decimal("0.6"), size=Decimal("2"),
             fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=3),
    ]
    streams = streams_from_fills(fills, token_ids={"a"})
    assert set(streams) == {"a"}                       # 'b' filtered out
    assert streams["a"] == [(Decimal("0.4"), Decimal("1")),
                            (Decimal("0.5"), Decimal("3"))]   # ts-ordered
