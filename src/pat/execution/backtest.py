"""BacktestBroker — deterministic, conservative limit-order fill engine.

Fill rule (conservative / back-of-queue):
  - Resting BUY  fills when trade_price <  order.price  (trade through the bid)
  - Resting SELL fills when trade_price >  order.price  (trade through the ask)
  - Equality → NO fill (back-of-queue assumption: at-price trades are front-runners)

Fill price = the resting order's quoted limit price (standard limit-order semantics).
Fill classification = MAKER (we were resting, not aggressing).
Fee = polymarket_maker_fee(...) — always 0 on Polymarket, but routed through the
cost model so any future change to the model is automatically picked up.

Partial fills:
  A single on_trade() call distributes its size across all eligible resting orders
  in insertion order (FIFO).  Each order consumes min(remaining_order, remaining_trade).
  Fully-filled orders are removed from the book.

positions() reconstructs net BUY-minus-SELL per token from the fill list, using a
side registry (client_id -> Side) that is populated at submit() time.

This module is intentionally small and single-purpose.  Taker fills, slippage
beyond the through-price, and adverse-selection modelling are Phase-2 refinements.

See docs/architecture/execution-brokers.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pat.core.types import Fill, Liquidity, Market, Order, Position, Side
from pat.costs.polymarket import polymarket_maker_fee

if TYPE_CHECKING:
    from pat.logging import TradeJournal


@dataclass
class _RestingOrder:
    """Internal representation of a resting limit order on the simulated book."""

    order: Order
    remaining: Decimal  # shares not yet filled


class BacktestBroker:
    """Deterministic backtest broker with a conservative through-trade fill model.

    Usage::

        broker = BacktestBroker(market=mkt)
        broker.submit(order)
        broker.on_trade(price=Decimal("0.39"), size=Decimal("50"))
        for fill in broker.fills:
            ...

    Args:
        market:  The market being simulated.  Determines the fee-rate category.
        journal: Optional append-only trade journal (logging-observability.md).
                 If supplied, every order submission and fill is recorded with
                 ``event``, ``reason``, ``fee``, ``corr_id``.
    """

    def __init__(self, market: Market, journal: TradeJournal | None = None) -> None:
        self._market = market
        self._journal = journal
        self._book: list[_RestingOrder] = []          # resting orders, insertion order
        self._ts: int = 0                              # monotonically increasing fill counter
        # side registry: client_id -> Side, so positions() knows direction per fill
        self._side_registry: dict[str, Side] = {}
        self.fills: list[Fill] = []

    # ------------------------------------------------------------------
    # Public interface (implements Broker protocol)
    # ------------------------------------------------------------------

    def submit(self, order: Order) -> None:
        """Record a resting limit order on the simulated book.

        Pre-trade risk checks are the caller's responsibility (risk/ layer).
        The order is accepted unconditionally here to keep this module
        single-purpose.

        Args:
            order: Limit order to rest.
        """
        self._book.append(_RestingOrder(order=order, remaining=order.size))
        self._side_registry[order.client_id] = order.side

        if self._journal is not None:
            self._journal.record(
                event="order",
                client_id=order.client_id,
                token_id=order.token_id,
                side=order.side,
                price=str(order.price),
                size=str(order.size),
                reason=order.reason,
                mode=order.mode,
            )

    def on_trade(self, price: Decimal, size: Decimal) -> None:
        """Feed a trade event and match against resting orders.

        Conservative through-trade rule:
          BUY  resting: fills iff trade_price <  order.price
          SELL resting: fills iff trade_price >  order.price

        Trade size is distributed in insertion order (FIFO).  Each eligible
        resting order consumes min(order.remaining, trade_size_remaining).

        Args:
            price: The price at which the observed market trade executed.
            size:  The number of shares that traded.
        """
        trade_remaining = size
        fully_filled_indices: list[int] = []

        for idx, resting in enumerate(self._book):
            if trade_remaining <= Decimal("0"):
                break

            if not self._through_trade(price, resting.order):
                continue

            qty = min(resting.remaining, trade_remaining)
            fill_price = resting.order.price
            fee = polymarket_maker_fee(
                category=self._market.category,
                price=fill_price,
                shares=qty,
            )

            self._ts += 1
            fill = Fill(
                order_id=resting.order.client_id,
                token_id=resting.order.token_id,
                price=fill_price,
                size=qty,
                fee=fee,
                liquidity=Liquidity.MAKER,
                mode="backtest",
                ts=self._ts,
            )
            self.fills.append(fill)

            if self._journal is not None:
                self._journal.record(
                    event="fill",
                    order_id=fill.order_id,
                    token_id=fill.token_id,
                    price=str(fill.price),
                    size=str(fill.size),
                    fee=str(fill.fee),
                    liquidity=fill.liquidity,
                    reason=resting.order.reason,
                    ts=fill.ts,
                )

            resting.remaining -= qty
            trade_remaining -= qty

            if resting.remaining <= Decimal("0"):
                fully_filled_indices.append(idx)

        # Remove fully-filled orders in reverse index order to keep earlier indices valid.
        for idx in reversed(fully_filled_indices):
            del self._book[idx]

    def positions(self) -> list[Position]:
        """Aggregate net positions per token_id from all fills.

        BUY fills contribute +size; SELL fills contribute -size.
        Returns one Position per token_id that has at least one fill.

        Returns:
            List of Position objects.  Empty if no fills have occurred.
        """
        net: dict[str, Decimal] = {}
        for fill in self.fills:
            side = self._side_registry.get(fill.order_id)
            if side is None:
                # Should never happen; belt-and-suspenders guard.
                continue
            delta = fill.size if side is Side.BUY else -fill.size
            net[fill.token_id] = net.get(fill.token_id, Decimal("0")) + delta

        return [
            Position(token_id=token_id, net_size=net_size)
            for token_id, net_size in net.items()
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _through_trade(self, trade_price: Decimal, order: Order) -> bool:
        """Return True iff trade_price trades *through* order's limit price.

        Conservative (back-of-queue): equality does NOT produce a fill.

        Args:
            trade_price: Price of the observed market trade.
            order:       The resting limit order to check.

        Returns:
            True if the order should fill.
        """
        if order.side is Side.BUY:
            return trade_price < order.price
        # Side.SELL
        return trade_price > order.price
