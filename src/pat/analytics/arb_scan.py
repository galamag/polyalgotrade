"""Structural arb-scan math (A2 v1) — spec 2026-06-10-a2-arb-scanner-design.md §4, FROZEN.

Pure functions, no network. Violations are computed net of taker fees (conservative
category rate per leg, regardless of feesEnabled — claim I9), gas (per tx count), and
book-depth slippage (depth_vwap). Money = Decimal.
"""

from __future__ import annotations

import json
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


def category_of(raw: object) -> Category:
    """Map a Gamma category string to our Category; conservative OTHER (5%) fallback."""
    if not raw:
        return Category.OTHER
    try:
        return Category(str(raw).strip().lower())
    except ValueError:
        return Category.OTHER


def scan_binary_market(
    target: BinaryTarget, books: dict[str, Book]
) -> list[Violation]:
    """A1 checks on ONE market (spec §4, K=2 collapse).

    a1_buy:  YES_ask + NO_ask < 1 → buy both + merge; gas = 1 tx (merge).
    a1_sell: YES_bid + NO_bid > 1 → split + sell both; gas = 1 tx (split).
    """
    m = target.market
    tokens = [m.yes_token, m.no_token]
    asks = [books.get(t, {}).get("asks", []) for t in tokens]
    bids = [books.get(t, {}).get("bids", []) for t in tokens]

    out: list[Violation] = []
    buy = _grid_violation(
        key=m.condition_id, vtype=A1_BUY, event_slug=target.event_slug,
        condition_ids=[m.condition_id], tokens=tokens, legs_levels=asks,
        category=m.category, sell=False, n_gas_txs=1,
    )
    if buy:
        out.append(buy)
    sell = _grid_violation(
        key=m.condition_id, vtype=A1_SELL, event_slug=target.event_slug,
        condition_ids=[m.condition_id], tokens=tokens, legs_levels=bids,
        category=m.category, sell=True, n_gas_txs=1,
    )
    if sell:
        out.append(sell)
    return out


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


# ---------------------------------------------------------------------------
# Task 6: Universe builder + window dedup
# ---------------------------------------------------------------------------

class Universe(BaseModel):
    negrisk: list[NegRiskTarget]
    binaries: list[BinaryTarget]
    n_tokens: int
    truncated: bool


def _coerce_token_pair(raw: object) -> tuple[str, str] | None:
    """clobTokenIds (JSON string or list) -> (yes, no); None unless exactly 2 ids."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    return str(raw[0]), str(raw[1])


def _market_ref(m: dict[str, object]) -> MarketRef | None:
    pair = _coerce_token_pair(m.get("clobTokenIds"))
    cid = str(m.get("conditionId") or "")
    if pair is None or not cid:
        return None
    return MarketRef(
        condition_id=cid, yes_token=pair[0], no_token=pair[1],
        category=category_of(m.get("category")),
    )


def _vol(m: dict[str, object]) -> float:
    try:
        return float(str(m.get("volume24hr") or 0))
    except ValueError:
        return 0.0


def build_universe(events: list[dict[str, object]], *, max_books: int) -> Universe:
    """negRisk events first (by Σ market volume desc), then binaries by volume desc,
    within the max_books token budget. Markets without exactly 2 token ids are skipped;
    negRisk events with < 2 valid markets are dropped (no Σ to check)."""
    nr_events: list[tuple[float, NegRiskTarget]] = []
    bins: list[tuple[float, BinaryTarget]] = []
    for ev in events:
        slug = str(ev.get("slug") or "")
        markets_raw = ev.get("markets") or []
        refs = [
            (r, _vol(m))
            for m in markets_raw  # type: ignore[attr-defined]
            if (r := _market_ref(m)) is not None
        ]
        if not refs or not slug:
            continue
        if ev.get("negRisk") is True:
            if len(refs) >= 2:
                target = NegRiskTarget(event_slug=slug, markets=[r for r, _ in refs])
                nr_events.append((sum(v for _, v in refs), target))
        else:
            for r, v in refs:
                bins.append((v, BinaryTarget(event_slug=slug, market=r)))

    nr_events.sort(key=lambda t: t[0], reverse=True)
    bins.sort(key=lambda t: t[0], reverse=True)

    budget = max_books
    truncated = False
    negrisk_out: list[NegRiskTarget] = []
    for _, target in nr_events:
        need = 2 * len(target.markets)
        if need > budget:
            truncated = True
            continue
        negrisk_out.append(target)
        budget -= need
    binaries_out: list[BinaryTarget] = []
    for _, b in bins:
        if budget < 2:
            truncated = True
            break
        binaries_out.append(b)
        budget -= 2
    return Universe(
        negrisk=negrisk_out, binaries=binaries_out,
        n_tokens=max_books - budget, truncated=truncated,
    )


def universe_tokens(universe: Universe) -> list[str]:
    """All token ids the scanner must fetch books for (YES+NO everywhere, deduped)."""
    tokens: list[str] = []
    for t in universe.negrisk:
        for m in t.markets:
            tokens.extend((m.yes_token, m.no_token))
    for b in universe.binaries:
        tokens.extend((b.market.yes_token, b.market.no_token))
    return list(dict.fromkeys(tokens))


def windows_from_snapshots(
    snapshots: list[dict[str, object]], *, interval_s: int
) -> list[dict[str, object]]:
    """Collapse per-scan violations into WINDOWS (spec §4 frequency unit).

    A window = the same (key, type) present in consecutive scans; it ends when a scan
    no longer reports it OR when the gap between scans exceeds 2×interval_s (coverage
    hole — PC off). Offline analysis helper for the §5 verdict run.
    """
    out: list[dict[str, object]] = []
    active: dict[tuple[str, str], dict[str, object]] = {}
    prev_ts: float | None = None
    for snap in sorted(snapshots, key=lambda s: float(str(s["ts"]))):
        ts = float(str(snap["ts"]))
        if prev_ts is not None and (ts - prev_ts) > 2 * interval_s:
            out.extend(active.values())
            active = {}
        seen: set[tuple[str, str]] = set()
        for v in snap.get("violations", []):  # type: ignore[attr-defined]
            k = (str(v["key"]), str(v["type"]))
            seen.add(k)
            net = Decimal(str(v["best_net"]))
            if k in active:
                w = active[k]
                w["end_ts"] = ts
                w["n_scans"] = int(str(w["n_scans"])) + 1
                if net > Decimal(str(w["max_best_net"])):
                    w["max_best_net"] = net
            else:
                active[k] = {
                    "key": k[0], "type": k[1], "start_ts": ts, "end_ts": ts,
                    "n_scans": 1, "max_best_net": net,
                }
        for k in list(active):
            if k not in seen:
                out.append(active.pop(k))
        prev_ts = ts
    out.extend(active.values())
    return sorted(out, key=lambda w: float(str(w["start_ts"])))
