"""Analytics metrics — EV/Sharpe verdict gate (CLAUDE.md §6).

Produces a ``Result`` dataclass from a list of fill dicts, then lets
``Verdict.from_metrics`` apply the three gating conditions:

  1. n_trades >= 1000   (minimum sample for statistical confidence)
  2. net_pnl > 0        (positive expected value, net-of-fee)
  3. sharpe > 1.0       (risk-adjusted return threshold)

Gates are checked in that order; the first failure determines the reason string.

HONESTY RULE (fee audit H4):
  net_pnl = gross_pnl - fee_drag
  No maker-rebate income is included.  Rebates are a daily-batch credit with a
  $1/day gate, to be modelled separately in a later phase.  Including them here
  would make backtests lie about net EV.

Money representation:
  All monetary fields use ``decimal.Decimal``.
  ``sharpe`` is ``float`` — it is a dimensionless statistical ratio and the
  standard library ``statistics`` module works on floats; rounding artefacts
  from Decimal are irrelevant here.

Definitions
-----------
gross_pnl
    Σ(price * size) for sells − Σ(price * size) for buys.
    This is the cash-flow P&L before fees.

fee_drag
    Σ fees across all fills.

net_pnl
    gross_pnl − fee_drag.  This is the number that matters.

win_rate
    Fraction of fills with a positive *per-fill net contribution*.
    Per-fill contribution = (price * size) if sell, −(price * size) if buy,
    then subtract the fill's own fee.
    A buy contribution is negative at fill time (capital outflow), so win_rate
    counts fills where the net contribution is strictly > 0, divided by n_trades.
    Note: on a simple buy→sell round-trip the sell fill will be positive and
    the buy fill negative; win_rate is a fill-level statistic, not a round-trip
    statistic.  This is documented here so callers are not surprised.

max_drawdown
    Maximum peak-to-trough decline in the running cumulative net-PnL series
    (sum of per-fill net contributions in order of appearance).  Always >= 0.

sharpe
    mean(per_fill_net_contributions) / stdev(per_fill_net_contributions).
    Returns 0.0 if there are fewer than 2 fills or the stdev is zero.
    Computed in float (Decimal series converted at the end).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    """Aggregated metrics for a set of fills.

    All monetary fields are Decimal; sharpe is float.
    """

    gross_pnl: Decimal
    fee_drag: Decimal
    net_pnl: Decimal
    win_rate: Decimal       # fraction in [0, 1]
    max_drawdown: Decimal   # peak-to-trough, always >= 0
    n_trades: int
    sharpe: float


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def summarize(fills: list[dict[str, Any]]) -> Result:
    """Compute aggregate metrics from a list of fill dicts.

    Each fill dict must have:
      - ``side``:  "buy" or "sell"
      - ``price``: string or Decimal, in [0, 1]
      - ``size``:  string or Decimal, > 0
      - ``fee``:   string or Decimal, >= 0

    Args:
        fills: Ordered list of fill records (e.g. from the trade journal).

    Returns:
        A frozen ``Result`` dataclass.

    Raises:
        ValueError: If a fill has an unknown side value.
    """
    if not fills:
        return Result(
            gross_pnl=Decimal("0"),
            fee_drag=Decimal("0"),
            net_pnl=Decimal("0"),
            win_rate=Decimal("0"),
            max_drawdown=Decimal("0"),
            n_trades=0,
            sharpe=0.0,
        )

    gross_pnl = Decimal("0")
    fee_drag = Decimal("0")
    per_fill_net: list[Decimal] = []

    for fill in fills:
        side = fill["side"]
        price = Decimal(str(fill["price"]))
        size = Decimal(str(fill["size"]))
        fee = Decimal(str(fill["fee"]))

        notional = price * size

        if side == "buy":
            cash_flow = -notional   # capital outflow
        elif side == "sell":
            cash_flow = notional    # cash inflow
        else:
            msg = f"Unknown side: {side!r}; expected 'buy' or 'sell'"
            raise ValueError(msg)

        gross_pnl += cash_flow
        fee_drag += fee

        # Per-fill net contribution: cash flow minus this fill's own fee
        per_fill_net.append(cash_flow - fee)

    net_pnl = gross_pnl - fee_drag

    # win_rate: fraction of fills with strictly positive net contribution
    n_positive = sum(1 for c in per_fill_net if c > Decimal("0"))
    n_trades = len(fills)
    win_rate = Decimal(n_positive) / Decimal(n_trades)

    # max_drawdown: max peak-to-trough of running cumulative net-PnL series
    max_drawdown = _compute_max_drawdown(per_fill_net)

    # sharpe: mean / stdev of per-fill net contributions (float)
    sharpe = _compute_sharpe(per_fill_net)

    return Result(
        gross_pnl=gross_pnl,
        fee_drag=fee_drag,
        net_pnl=net_pnl,
        win_rate=win_rate,
        max_drawdown=max_drawdown,
        n_trades=n_trades,
        sharpe=sharpe,
    )


# ---------------------------------------------------------------------------
# Verdict dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """Strategy advancement verdict.

    Attributes:
        advance: True iff ALL three gates are met.
        reason:  Human-readable explanation.  Empty string when advance=True.
    """

    advance: bool
    reason: str

    @classmethod
    def from_metrics(
        cls,
        sharpe: float,
        net_pnl: Decimal,
        n_trades: int,
    ) -> Verdict:
        """Apply the three gating conditions and return a Verdict.

        Gates (checked in order — first failure wins):
          1. n_trades >= 1000  → reason contains "sample"
          2. net_pnl > 0       → reason contains "ev" and "negative"
          3. sharpe > 1.0      → reason contains "sharpe"

        Args:
            sharpe:   Sharpe ratio (float).
            net_pnl:  Net PnL after fees (Decimal).
            n_trades: Total number of fills.

        Returns:
            A frozen ``Verdict`` dataclass.
        """
        if n_trades < 1000:
            return cls(
                advance=False,
                reason=(
                    f"Insufficient sample: {n_trades} trades < 1000 minimum required "
                    "for statistical confidence."
                ),
            )

        if net_pnl <= Decimal("0"):
            return cls(
                advance=False,
                reason=(
                    f"Negative or zero EV: net_pnl={net_pnl} <= 0 after fees. "
                    "Strategy does not have positive expected value."
                ),
            )

        if sharpe <= 1.0:
            return cls(
                advance=False,
                reason=(
                    f"Sharpe ratio {sharpe:.4f} <= 1.0. "
                    "Risk-adjusted return is below the minimum threshold."
                ),
            )

        return cls(
            advance=True,
            reason="All gates met: sample >= 1000, net EV > 0, Sharpe > 1.0.",
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_max_drawdown(per_fill_net: list[Decimal]) -> Decimal:
    """Compute max peak-to-trough drawdown of the running cumulative series.

    Args:
        per_fill_net: Ordered list of per-fill net contributions.

    Returns:
        Maximum drawdown as a non-negative Decimal.  Returns 0 if the series
        never declines from its peak.
    """
    if not per_fill_net:
        return Decimal("0")

    peak = Decimal("0")
    running = Decimal("0")
    max_dd = Decimal("0")

    for contribution in per_fill_net:
        running += contribution
        if running > peak:
            peak = running
        drawdown = peak - running
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd


def _compute_sharpe(per_fill_net: list[Decimal]) -> float:
    """Compute the Sharpe ratio of per-fill net contributions.

    mean / stdev of the series, computed in float.
    Returns 0.0 if fewer than 2 observations or stdev == 0.

    Args:
        per_fill_net: Ordered list of per-fill net contributions (Decimal).

    Returns:
        Sharpe ratio as float, or 0.0 when undefined.
    """
    if len(per_fill_net) < 2:
        return 0.0

    floats = [float(c) for c in per_fill_net]
    stdev = statistics.stdev(floats)

    if stdev == 0.0:
        return 0.0

    return statistics.mean(floats) / stdev
