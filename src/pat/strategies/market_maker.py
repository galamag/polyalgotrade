"""MarketMaker v1 — simple fixed-spread quoting (approved design, spec Section 2).

Fair value = EWMA of observed trades.  Symmetric quotes fv ± half_spread, resting
MAKER (GTC).  At the inventory cap, quote only the inventory-reducing side.
Edge = pure spread − adverse selection (geopolitics: 0% fee, 0 rebate).
Inventory-skew (v2): `gamma` mid-shift (fv − γ·inv_frac) + `skew_delta` asymmetric spread;
default 0 = v1 behaviour. Stand-aside `quote_band` boundary guard. See ADR 0018 / spec 2026-06-09.
"""

from __future__ import annotations

from decimal import Decimal

from pat.core.types import Fill, Order, OrderType, Side
from pat.strategies.base import CancelOrder, OrderAction, PostOrder


class MarketMaker:
    """Stateful fixed-spread market maker for a single token."""

    def __init__(
        self,
        token_id: str,
        half_spread: Decimal,
        size: Decimal,
        inventory_cap: Decimal,
        alpha: Decimal = Decimal("0.3"),
        tick: Decimal = Decimal("0.01"),
        quote_band: Decimal = Decimal("0"),
        gamma: Decimal = Decimal("0"),
        skew_delta: Decimal = Decimal("0"),
    ) -> None:
        self.token_id = token_id
        self.half_spread = Decimal(str(half_spread))
        self.size = Decimal(str(size))
        self.inventory_cap = Decimal(str(inventory_cap))
        self.alpha = Decimal(str(alpha))
        self.tick = Decimal(str(tick))
        # Stand aside when fair value is within quote_band of 0/1 (near-resolved binary).
        # 0 (default) = always quote (legacy behaviour).
        self.quote_band = Decimal(str(quote_band))
        # Inventory skew (ADR 0018 / spec 2026-06-09). 0 = no skew (v1).
        self.gamma = Decimal(str(gamma))            # mid-shift: fv_eff = fv - gamma*inv_frac
        self.skew_delta = Decimal(str(skew_delta))  # asymmetric spread on the building side

        self.fv: Decimal | None = None
        self.inventory: Decimal = Decimal("0")
        self._side: dict[str, Side] = {}      # client_id -> Side (for inventory updates)
        self._bid_id: str | None = None
        self._ask_id: str | None = None
        self._counter: int = 0

    # -- protocol --------------------------------------------------------------

    def on_fills(self, fills: list[Fill]) -> None:
        for fill in fills:
            side = self._side.get(fill.order_id)
            if side is None:
                continue
            self.inventory += fill.size if side is Side.BUY else -fill.size

    def on_trade(self, price: Decimal, size: Decimal) -> list[OrderAction]:
        # `size` is part of the Strategy interface; v1 quoting does not use trade size.
        self.fv = (
            price
            if self.fv is None
            else self.alpha * price + (Decimal("1") - self.alpha) * self.fv
        )
        actions: list[OrderAction] = []

        # cancel existing quotes before requoting
        if self._bid_id is not None:
            actions.append(CancelOrder(self._bid_id))
            self._bid_id = None
        if self._ask_id is not None:
            actions.append(CancelOrder(self._ask_id))
            self._ask_id = None

        # Boundary guard (ADR 0018): stand aside on near-resolved binaries. Within quote_band of
        # 0/1 the symmetric quotes degenerate to the price clamp and the flow is dominated by
        # resolution-direction informed trades. quote_band=0 disables this (legacy behaviour).
        if self.quote_band > Decimal("0") and (
            self.fv < self.quote_band or self.fv > Decimal("1") - self.quote_band
        ):
            return actions

        inv_frac = self.inventory / self.inventory_cap
        inv_frac = max(Decimal("-1"), min(Decimal("1"), inv_frac))   # bound the shift
        fv_eff = self.fv - self.gamma * inv_frac
        bid_off = self.half_spread + self.skew_delta * max(Decimal("0"), inv_frac)
        ask_off = self.half_spread + self.skew_delta * max(Decimal("0"), -inv_frac)
        bid_px = self._clamp(fv_eff - bid_off)
        ask_px = self._clamp(fv_eff + ask_off)
        # No-cross postcondition: clamp can collapse them near 0/1 -> force a >=1-tick gap.
        if ask_px - bid_px < self.tick:
            if ask_px >= Decimal("1") - self.tick:
                bid_px = self._clamp(ask_px - self.tick)
            else:
                ask_px = self._clamp(bid_px + self.tick)

        if self.inventory < self.inventory_cap:  # room to go more long
            self._bid_id = self._new_id("bid")
            self._side[self._bid_id] = Side.BUY
            actions.append(PostOrder(self._order(self._bid_id, Side.BUY, bid_px)))
        if self.inventory > -self.inventory_cap:  # room to go more short
            self._ask_id = self._new_id("ask")
            self._side[self._ask_id] = Side.SELL
            actions.append(PostOrder(self._order(self._ask_id, Side.SELL, ask_px)))

        return actions

    def side_of(self, client_id: str) -> Side | None:
        """Expose the side a client_id was quoted on (for PnL attribution)."""
        return self._side.get(client_id)

    # -- helpers ---------------------------------------------------------------

    def _order(self, client_id: str, side: Side, price: Decimal) -> Order:
        return Order(
            client_id=client_id, token_id=self.token_id, side=side, price=price,
            size=self.size, order_type=OrderType.GTC, reason="mm-quote",
        )

    def _clamp(self, p: Decimal) -> Decimal:
        lo, hi = self.tick, Decimal("1") - self.tick
        return min(max(p.quantize(self.tick), lo), hi)

    def _new_id(self, tag: str) -> str:
        self._counter += 1
        return f"{self.token_id}-{tag}-{self._counter}"
