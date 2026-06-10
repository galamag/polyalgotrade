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
from pydantic import BaseModel

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


class ConditionPnl(BaseModel):
    condition_id: str
    event_slug: str
    status: str  # resolved | frame_incomplete | unresolved | ambiguous | unknown
    pnl: Decimal = Decimal("0")  # resolution P&L; meaningful only when status == resolved
    unresolved_exposure: Decimal = Decimal("0")  # only when status == unresolved


def condition_pnls(
    trades: list[dict[str, Any]], resolutions: dict[str, dict[str, Any]]
) -> list[ConditionPnl]:
    """Per-conditionId resolution P&L for ONE wallet's saved trade rows (spec §4).

    Status precedence: frame_incomplete (any asset with net_shares < 0 — its cost basis
    lies outside the saved recent-2000 window) beats the resolution record. Rows with
    size <= 0 or missing conditionId/eventSlug are skipped with a warning counter.
    redemption = max(net_shares, 0) per winning-outcome asset ($1/share).
    """
    _REQUIRED = {"asset", "side", "price", "size", "outcomeIndex", "timestamp"}
    by_cond: dict[str, list[dict[str, Any]]] = {}
    skipped = 0
    for t in trades:
        cond = str(t.get("conditionId") or "")
        slug = str(t.get("eventSlug") or "")
        if not cond or not slug:
            skipped += 1
            continue
        if any(t.get(f) is None for f in _REQUIRED):
            skipped += 1
            continue
        if str(t["side"]).upper() not in {"BUY", "SELL"}:
            skipped += 1
            continue
        if Decimal(str(t.get("size", 0))) <= 0:
            skipped += 1
            continue
        by_cond.setdefault(cond, []).append(t)
    if skipped:
        log.warning("resolution_pnl.rows_skipped", skipped=skipped)

    out: list[ConditionPnl] = []
    for cond, rows in by_cond.items():
        event_slug = str(rows[0]["eventSlug"])
        assets: dict[str, dict[str, Any]] = {}
        for t in sorted(rows, key=lambda r: int(str(r["timestamp"]))):
            asset = str(t["asset"])
            a = assets.setdefault(
                asset,
                {
                    "net": Decimal("0"),
                    "cash": Decimal("0"),
                    "outcome_index": int(str(t["outcomeIndex"])),
                    "last_price": Decimal("0"),
                },
            )
            price = Decimal(str(t["price"]))
            size = Decimal(str(t["size"]))
            if str(t["side"]).upper() == "BUY":
                a["net"] += size
                a["cash"] -= price * size
            else:
                a["net"] -= size
                a["cash"] += price * size
            a["last_price"] = price

        rec = resolutions.get(cond, {"status": UNKNOWN, "winning_index": None})
        if any(a["net"] < 0 for a in assets.values()):
            status = FRAME_INCOMPLETE
        elif str(rec.get("status")) == RESOLVED and rec.get("winning_index") is None:
            log.warning("resolution_pnl.malformed_resolution", condition_id=cond)
            status = UNKNOWN
        else:
            status = str(rec["status"])

        pnl = Decimal("0")
        exposure = Decimal("0")
        if status == RESOLVED:
            win = int(rec["winning_index"])
            for a in assets.values():
                won = a["outcome_index"] == win
                redemption = max(a["net"], Decimal("0")) if won else Decimal("0")
                pnl += a["cash"] + redemption
        elif status == UNRESOLVED:
            for a in assets.values():
                exposure += max(a["net"], Decimal("0")) * a["last_price"]

        out.append(
            ConditionPnl(
                condition_id=cond,
                event_slug=event_slug,
                status=status,
                pnl=pnl,
                unresolved_exposure=exposure,
            )
        )
    return out


class WalletResolutionMetrics(BaseModel):
    wallet: str
    total_resolution_pnl: Decimal
    n_conditions_resolved: int
    n_events_resolved: int
    n_events_positive: int
    top1_share: float
    n_frame_incomplete: int
    n_unresolved: int
    n_ambiguous: int
    n_unknown: int
    unresolved_exposure: Decimal
    diversified: bool


_MIN_POSITIVE_EVENTS = 10  # spec §4: ">= 10 independent events with event_pnl > 0"
_MAX_TOP1_SHARE = 0.5  # spec §4: strict <
_KILL_MIN_DIVERSIFIED = 5  # ADR 0021: < 5 of 50 winners -> branch B closes


def wallet_metrics(
    wallet: str, conditions: list[ConditionPnl]
) -> WalletResolutionMetrics:
    """Aggregate per EVENT (eventSlug) and apply the pre-registered diversified rule.

    Gate-eligible = RESOLVED conditions only; every other status feeds its disclosure
    counter. top1_share is abs-based (a dominant loss also flags concentration).
    """
    event_pnl: dict[str, Decimal] = {}
    n_res = n_fi = n_unres = n_amb = n_unk = 0
    exposure = Decimal("0")
    for c in conditions:
        if c.status == RESOLVED:
            n_res += 1
            event_pnl[c.event_slug] = event_pnl.get(c.event_slug, Decimal("0")) + c.pnl
        elif c.status == FRAME_INCOMPLETE:
            n_fi += 1
        elif c.status == UNRESOLVED:
            n_unres += 1
            exposure += c.unresolved_exposure
        elif c.status == AMBIGUOUS:
            n_amb += 1
        else:
            n_unk += 1

    total = sum(event_pnl.values(), Decimal("0"))
    abs_vals = [abs(v) for v in event_pnl.values()]
    abs_total = sum(abs_vals, Decimal("0"))
    top1 = float(max(abs_vals) / abs_total) if abs_total > 0 else 0.0
    n_pos = sum(1 for v in event_pnl.values() if v > 0)
    diversified = (
        total > 0 and n_pos >= _MIN_POSITIVE_EVENTS and top1 < _MAX_TOP1_SHARE
    )
    return WalletResolutionMetrics(
        wallet=wallet,
        total_resolution_pnl=total,
        n_conditions_resolved=n_res,
        n_events_resolved=len(event_pnl),
        n_events_positive=n_pos,
        top1_share=top1,
        n_frame_incomplete=n_fi,
        n_unresolved=n_unres,
        n_ambiguous=n_amb,
        n_unknown=n_unk,
        unresolved_exposure=exposure,
        diversified=diversified,
    )


def screen_verdict(
    winner_metrics: list[WalletResolutionMetrics],
) -> tuple[int, bool]:
    """(n_diversified, branch_b_killed) per the pre-registered ADR 0021 kill criterion."""
    n = sum(1 for m in winner_metrics if m.diversified)
    return n, n < _KILL_MIN_DIVERSIFIED
