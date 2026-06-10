"""Structural arb-scan math (A2 v1) — spec 2026-06-10-a2-arb-scanner-design.md §4, FROZEN.

Pure functions, no network. Violations are computed net of taker fees (conservative
category rate per leg, regardless of feesEnabled — claim I9), gas (per tx count), and
book-depth slippage (depth_vwap). Money = Decimal.
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from pydantic import BaseModel

from pat.core.types import Category
from pat.costs.polymarket import depth_vwap, gas_cost, polymarket_taker_fee

log = structlog.get_logger(__name__)

SIZE_GRID = (Decimal("10"), Decimal("50"), Decimal("100"), Decimal("500"))

Book = dict[str, list[tuple[Decimal, Decimal]]]

BUY_ALL = "buy_all"
SELL_ALL = "sell_all"
A1_BUY = "a1_buy"
A1_SELL = "a1_sell"


class MarketRef(BaseModel):
    condition_id: str
    yes_token: str
    no_token: str
    category: Category


class NegRiskTarget(BaseModel):
    event_slug: str
    markets: list[MarketRef]


class BinaryTarget(BaseModel):
    event_slug: str
    market: MarketRef


class Leg(BaseModel):
    # top = best price on the relevant side (best ask for buy legs, best bid for sell
    # legs — levels[0][0]); None if the book side is empty.
    token_id: str
    top: Decimal | None
    vwap: Decimal | None


class Violation(BaseModel):
    key: str
    type: str  # buy_all | sell_all | a1_buy | a1_sell
    event_slug: str
    condition_ids: list[str]
    grid: dict[str, Decimal | None]  # str(size) -> net (None = not executable)
    best_size: Decimal
    best_net: Decimal
    legs: list[Leg]


def _net_for_size(
    legs_levels: list[list[tuple[Decimal, Decimal]]],
    size: Decimal,
    *,
    category: Category,
    sell: bool,
    n_gas_txs: int,
) -> tuple[Decimal, list[Decimal]] | None:
    """One grid point: net edge + per-leg VWAPs; None if ANY leg lacks depth.

    buy  (sell=False): net = size - Σ vwap·size - Σ fee - gas
    sell (sell=True):  net = Σ vwap·size - size - Σ fee - gas
    Fee per leg = polymarket_taker_fee(category, leg VWAP, size) — conservative (I9).
    """
    total = Decimal("0")
    fees = Decimal("0")
    vwaps: list[Decimal] = []
    for levels in legs_levels:
        v = depth_vwap(levels, size)
        if v is None:
            return None
        vwaps.append(v)
        total += v * size
        fees += polymarket_taker_fee(category, v, size)
    gross = (total - size) if sell else (size - total)
    return gross - fees - gas_cost(n_gas_txs), vwaps


def _grid_violation(
    *,
    key: str,
    vtype: str,
    event_slug: str,
    condition_ids: list[str],
    tokens: list[str],
    legs_levels: list[list[tuple[Decimal, Decimal]]],
    category: Category,
    sell: bool,
    n_gas_txs: int,
) -> Violation | None:
    """Evaluate the size grid; return a Violation only if the best net edge is > 0."""
    assert len(tokens) == len(legs_levels), "tokens and legs_levels must align"  # noqa: S101
    grid: dict[str, Decimal | None] = {}
    best: tuple[Decimal, Decimal, list[Decimal]] | None = None
    for s in SIZE_GRID:
        r = _net_for_size(
            legs_levels, s, category=category, sell=sell, n_gas_txs=n_gas_txs
        )
        grid[str(s)] = r[0] if r is not None else None
        # strict > keeps the FIRST (smallest) size on a net tie — smaller size is more
        # executable (less slippage, easier to fill).
        if r is not None and (best is None or r[0] > best[0]):
            best = (r[0], s, r[1])
    if best is None or best[0] <= 0:
        return None
    net, size, vwaps = best
    legs = [
        Leg(
            token_id=tok,
            top=(levels[0][0] if levels else None),
            vwap=vwap,
        )
        for tok, levels, vwap in zip(tokens, legs_levels, vwaps, strict=True)
    ]
    return Violation(
        key=key, type=vtype, event_slug=event_slug, condition_ids=condition_ids,
        grid=grid, best_size=size, best_net=net, legs=legs,
    )


def scan_negrisk_event(
    target: NegRiskTarget, books: dict[str, Book]
) -> list[Violation]:
    """Σ-violations across one negRisk event's K mutually-exclusive YES legs (spec §4).

    buy_all:  Σ asks < 1  → buy every YES, exactly one redeems $1; gas = 1 tx (redeem).
    sell_all: Σ bids > 1  → split $1→YES+NO on EACH market, sell all YES, K−1 NOs pay $1;
              gas = K+1 txs (K splits + 1 redeem) — conservative, no adapter batching assumed.
    """
    k = len(target.markets)
    if k < 2:
        return []
    category = target.markets[0].category
    cids = [m.condition_id for m in target.markets]
    yes_tokens = [m.yes_token for m in target.markets]
    asks = [books.get(t, {}).get("asks", []) for t in yes_tokens]
    bids = [books.get(t, {}).get("bids", []) for t in yes_tokens]

    out: list[Violation] = []
    buy = _grid_violation(
        key=target.event_slug, vtype=BUY_ALL, event_slug=target.event_slug,
        condition_ids=cids, tokens=yes_tokens, legs_levels=asks,
        category=category, sell=False, n_gas_txs=1,
    )
    if buy:
        out.append(buy)
    sell = _grid_violation(
        key=target.event_slug, vtype=SELL_ALL, event_slug=target.event_slug,
        condition_ids=cids, tokens=yes_tokens, legs_levels=bids,
        category=category, sell=True, n_gas_txs=k + 1,
    )
    if sell:
        out.append(sell)
    return out
