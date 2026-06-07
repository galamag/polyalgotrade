"""No-look-ahead replay loop: drive a Strategy against a Broker over a trade stream.

Per trade, in order:
  1. broker matches the trade against EXISTING resting quotes -> new fills
  2. strategy.on_fills(new_fills)        -> update inventory
  3. strategy.on_trade(price, size)      -> requote intents for the FUTURE
  4. apply intents (cancel / submit)

Step 1 precedes step 3 so a trade can never fill a quote that was posted because
of that same trade.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from pat.core.types import Fill
from pat.execution.broker import Broker
from pat.strategies.base import CancelOrder, PostOrder, Strategy


def run_replay(
    strategy: Strategy,
    broker: Broker,
    trades: Iterable[tuple[Decimal, Decimal]],
) -> list[Fill]:
    """Replay (price, size) trades; return all fills the broker produced."""
    for price, size in trades:
        new_fills = broker.on_trade(price, size)
        strategy.on_fills(new_fills)
        for action in strategy.on_trade(price, size):
            if isinstance(action, CancelOrder):
                broker.cancel(action.client_id)
            elif isinstance(action, PostOrder):
                broker.submit(action.order)
    return broker.fills
