"""Broker protocol — the single interface that every execution backend implements.

Strategies depend *only* on this protocol; the same strategy code runs unchanged
against BacktestBroker, PaperBroker, and LiveBroker.  This is what makes a
backtest verdict trustworthy as a prediction of live behaviour.

See docs/architecture/execution-brokers.md for the design rationale.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from pat.core.types import Fill, Order, Position


@runtime_checkable
class Broker(Protocol):
    """Minimal execution interface.

    All methods that interact with the market (submit, cancel, on_trade) are
    *synchronous* for the backtest engine; the async variants (PaperBroker,
    LiveBroker) will extend this via a separate AsyncBroker protocol at Phase 3.

    Every ``submit`` call must:
    - pass through ``risk/`` pre-trade checks (not enforced here — the broker
      implementation is responsible),
    - route the resulting fill's cost through ``costs/``.

    Fills are delivered via ``self.fills`` (backtest/paper) or pushed to the
    strategy via callbacks (live); the exact delivery mechanism is
    implementation-defined.
    """

    def submit(self, order: Order) -> None:
        """Accept and record a limit order.

        Args:
            order: The limit order to submit.  Must have a unique ``client_id``.
        """
        ...

    def on_trade(self, price: Decimal, size: Decimal) -> list[Fill]:
        """Feed a replayed/live trade event to the broker.

        The broker checks each resting order against the through-trade rule and
        produces fills accordingly.

        Args:
            price: Execution price of the observed trade (in [0, 1]).
            size:  Number of shares that traded.

        Returns:
            List of Fill objects produced by this trade event.
        """
        ...

    def cancel(self, client_id: str) -> None:
        """Remove a resting order by client_id. No-op if not present."""
        ...

    def positions(self) -> list[Position]:
        """Return the current net positions, one entry per token_id.

        Returns:
            A list of ``Position`` objects with ``net_size`` = BUY fills − SELL fills.
            Empty list if nothing has been filled yet.
        """
        ...
