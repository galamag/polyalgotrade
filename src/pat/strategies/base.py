"""Strategy plugin interface — one strategy, three brokers (CLAUDE.md principle 8).

A Strategy reacts to trade events and emits OrderActions (post/cancel).  It owns
no execution: the broker matches and fills.  The same code runs against
BacktestBroker, PaperBroker, and LiveBroker.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pat.core.types import Fill, Order


@dataclass(frozen=True)
class PostOrder:
    """Intent to rest a new limit order."""

    order: Order


@dataclass(frozen=True)
class CancelOrder:
    """Intent to cancel a resting order by its client_id."""

    client_id: str


OrderAction = PostOrder | CancelOrder


@runtime_checkable
class Strategy(Protocol):
    """Pure decision logic. Stateful across calls; emits intents, never fills."""

    def on_trade(self, price: Decimal, size: Decimal) -> list[OrderAction]:
        """React to an observed trade; return quote post/cancel intents."""
        ...

    def on_fills(self, fills: list[Fill]) -> None:
        """Receive fills produced by the broker so the strategy can update state."""
        ...
