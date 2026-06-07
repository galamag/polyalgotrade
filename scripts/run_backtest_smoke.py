"""Phase-1 end-to-end backtest smoke — pipeline gate (≥1000 trades, net-of-fee).

Goal
----
Prove that the fee model, trade journal, and analytics/verdict pipeline work
together correctly before any real market data arrives.  This script is the
Phase-1 gate: it must produce a Result with n_trades >= 1000, fee_drag > 0, and
net_pnl == gross_pnl - fee_drag.

Design note — why TAKER fills, not BacktestBroker fills
-------------------------------------------------------
BacktestBroker simulates resting (MAKER) limit orders that are traded through.
Polymarket maker fee is always 0, so BacktestBroker fills carry fee = 0 and
would make fee_drag == 0 — proving nothing about the fee pipeline.

This smoke bypasses the broker and calls polymarket_taker_fee() directly to
generate synthetic TAKER fills (the fee-bearing case).  The BacktestBroker's
maker fill model is exercised by its dedicated unit tests in
tests/execution/test_backtest.py.  Here we prove:

  polymarket_taker_fee()  →  TradeJournal  →  summarize()  →  Verdict

Usage
-----
  uv run python -m scripts.run_backtest_smoke          # prints Result + Verdict
  uv run pytest tests/test_pipeline_smoke.py -q        # gate test
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from pat.analytics.metrics import Result, Verdict, summarize
from pat.core.types import Category
from pat.costs.polymarket import polymarket_taker_fee
from pat.logging import TradeJournal


def run(n: int = 1000, journal_dir: Path | None = None) -> Result:
    """Generate n synthetic taker fills, journal them, and return the aggregated Result.

    All variation is deterministic (index-based, no randomness) so the smoke is
    reproducible and the test can assert on exact structure.

    Args:
        n:           Number of fills to generate (default 1000).
        journal_dir: If provided, a JSONL trade journal is written to this directory.
                     Useful for inspecting the log output; not required for the gate.

    Returns:
        A frozen Result dataclass from pat.analytics.metrics.summarize().
    """
    journal: TradeJournal | None = None
    if journal_dir is not None:
        journal = TradeJournal(
            path=Path(journal_dir) / "smoke_journal.jsonl",
            mode="backtest",
            corr_id=str(uuid.uuid4()),
        )

    category = Category.POLITICS  # taker rate = 0.04 — nonzero fee at prices near 0.5

    size = Decimal("10")  # constant share size per fill
    fills: list[dict[str, Any]] = []

    for i in range(n):
        # Deterministic price in (0, 1): cycles through 11 values from 0.45 to 0.55
        raw_price = Decimal("0.45") + Decimal(str(i % 11)) * Decimal("0.01")
        # Clamp strictly into (0, 1) — formula is safe here but guard against edge
        price = max(Decimal("0.01"), min(Decimal("0.99"), raw_price))

        side = "buy" if i % 2 == 0 else "sell"

        fee = polymarket_taker_fee(category, price, size)

        fill: dict[str, Any] = {
            "side": side,
            "price": price,
            "size": size,
            "fee": fee,
        }
        fills.append(fill)

        if journal is not None:
            journal.record(
                event="fill",
                side=side,
                price=str(price),
                size=str(size),
                fee=str(fee),
                reason="smoke",
                category=category,
            )

    result = summarize(fills)

    # Build the Verdict so it is available when __main__ runs the script
    _verdict = Verdict.from_metrics(
        sharpe=result.sharpe,
        net_pnl=result.net_pnl,
        n_trades=result.n_trades,
    )

    return result


if __name__ == "__main__":
    import sys

    journal_path = Path("logs")
    result = run(journal_dir=journal_path)

    verdict = Verdict.from_metrics(
        sharpe=result.sharpe,
        net_pnl=result.net_pnl,
        n_trades=result.n_trades,
    )

    print("=== Phase-1 Backtest Smoke Result ===")
    print(f"  n_trades    : {result.n_trades}")
    print(f"  gross_pnl   : {result.gross_pnl}")
    print(f"  fee_drag    : {result.fee_drag}")
    print(f"  net_pnl     : {result.net_pnl}")
    print(f"  win_rate    : {result.win_rate}")
    print(f"  max_drawdown: {result.max_drawdown}")
    print(f"  sharpe      : {result.sharpe:.6f}")
    print()
    print("=== Verdict ===")
    print(f"  advance     : {verdict.advance}")
    print(f"  reason      : {verdict.reason}")

    sys.exit(0)
