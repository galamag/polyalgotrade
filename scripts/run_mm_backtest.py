"""Phase-2 MM backtest — parameter sweep over half_spread, net-of-fee with inventory MtM.

Pure-function core (run_sweep) is deterministic and unit-tested offline.  The
__main__ block runs it on a saved per-token trade stream (Task 8 supplies real
geopolitics data).  Backtest fidelity is a conservative lower bound (no order
book); the real verdict is paper (ADR 0014).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pat.analytics.metrics import Result, Verdict, summarize
from pat.core.types import Market
from pat.execution.backtest import BacktestBroker
from pat.execution.replay import run_replay
from pat.strategies.market_maker import MarketMaker

Stream = list[tuple[Decimal, Decimal]]


def run_sweep(
    streams: dict[str, Stream],
    market: Market,
    half_spreads: list[Decimal],
    size: Decimal,
    inventory_cap: Decimal,
    alpha: Decimal,
) -> list[dict[str, Any]]:
    """Run the MM over every token stream for each half_spread; return frontier rows.

    Each row: {"half_spread", "result": Result, "verdict": Verdict}.
    Residual inventory is marked at last trade price minus a half_spread haircut.
    """
    rows: list[dict[str, Any]] = []
    for hs in half_spreads:
        fill_dicts: list[dict[str, Any]] = []
        marks: dict[str, Decimal] = {}
        for token_id, trades in streams.items():
            broker = BacktestBroker(market=market)
            mm = MarketMaker(token_id=token_id, half_spread=hs, size=size,
                             inventory_cap=inventory_cap, alpha=alpha, tick=market.tick_size)
            fills = run_replay(mm, broker, trades)
            for f in fills:
                side = mm.side_of(f.order_id)
                if side is None:
                    continue
                fill_dicts.append({"side": side.value, "price": f.price,
                                   "size": f.size, "fee": f.fee, "token_id": f.token_id})
            if trades:
                marks[token_id] = trades[-1][0]  # last trade price = mark
        result: Result = summarize(fill_dicts, marks=marks, inventory_haircut=hs)
        verdict: Verdict = Verdict.from_metrics(result.sharpe, result.net_pnl, result.n_trades)
        rows.append({"half_spread": hs, "result": result, "verdict": verdict})
    return rows


def print_frontier(rows: list[dict[str, Any]]) -> None:
    print("half_spread | n_trades | net_pnl | inv_value | sharpe | advance")  # noqa: T201
    for r in rows:
        res, v = r["result"], r["verdict"]
        print(  # noqa: T201
            f"  {r['half_spread']!s:>9} | {res.n_trades:>8} | {res.net_pnl:>7} | "
            f"{res.inventory_value:>9} | {res.sharpe:>6.3f} | {v.advance}"
        )
