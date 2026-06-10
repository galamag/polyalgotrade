"""Resolution-grounded P&L per wallet (ADR 0021 Step 1).

Pre-registered methodology — spec docs/superpowers/specs/2026-06-10-approach2-resolution-
pnl-design.md §4; formulas are FROZEN as of that spec's commit. Pure functions, no
network: joins saved data-api /trades rows (conditionId, eventSlug, outcomeIndex, side,
price, size, timestamp) with Gamma resolutions to compute TRUE realized P&L including
redemption payouts, aggregated per EVENT (eventSlug). Money = Decimal.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import structlog

log = structlog.get_logger(__name__)

RESOLVED = "resolved"
FRAME_INCOMPLETE = "frame_incomplete"
UNRESOLVED = "unresolved"
AMBIGUOUS = "ambiguous"
UNKNOWN = "unknown"


def parse_resolution(market: dict[str, Any]) -> dict[str, Any]:
    """Gamma market dict -> resolution record (STRICT binary winner detection).

    resolved  := closed AND outcomePrices has exactly one 1 with all others 0
    ambiguous := closed but prices not strictly binary (e.g. 50/50 refunds)
    unresolved otherwise (open market, or closed without prices).
    outcomePrices arrives as a JSON-encoded string (Gamma quirk) or a real list.

    Returns: {"conditionId": str, "status": str, "winning_index": int | None}
    FRAME_INCOMPLETE / UNKNOWN are produced by condition_pnls, not by this function.
    """
    condition_id = str(market.get("conditionId", ""))
    raw = market.get("outcomePrices")
    if isinstance(raw, str):
        raw = json.loads(raw)
    prices = [Decimal(str(p)) for p in (raw or [])]
    closed = bool(market.get("closed", False))
    if not closed or not prices:
        return {"conditionId": condition_id, "status": UNRESOLVED, "winning_index": None}
    ones = [i for i, p in enumerate(prices) if p == 1]
    n_zeros = sum(1 for p in prices if p == 0)
    if len(ones) == 1 and n_zeros == len(prices) - 1:
        return {"conditionId": condition_id, "status": RESOLVED, "winning_index": ones[0]}
    return {"conditionId": condition_id, "status": AMBIGUOUS, "winning_index": None}
