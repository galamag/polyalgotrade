# A2 Structural Arb Scanner v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the read-only polling scanner that measures frequency & magnitude of structural price-sum violations on live Polymarket markets, net of fees + gas + depth slippage (ADR 0021 Step 2).

**Architecture:** Two cost primitives (`gas_cost`, `depth_vwap`) in `costs/`; one new wire seam (`books.py`, CLOB `POST /books`); a Gamma no-tag active-events pager; a pure math module `arb_scan.py` implementing the FROZEN spec §4 formulas; a long-running loop driver appending JSONL snapshots. Offline window-dedup analysis (`windows_from_snapshots`) ships with the math module.

**Tech Stack:** Python 3.11, `httpx`, `pydantic`, `structlog`, `pytest`, `Decimal` money. Run via `uv run`.

**Spec (binding, frozen §4 formulas + §5 gate):** `docs/superpowers/specs/2026-06-10-a2-arb-scanner-design.md`. Decision: `docs/decisions/0021-post-wallet-spike-direction.md` (Step 2).

**Context for the engineer:**
- Conventions: line ≤ 100 (ruff), money = `Decimal(str(x))`, tests NEVER touch the network (injectable seams — see `_gamma_get_events`/`get_page` pattern in `src/pat/venues/polymarket/gamma.py`), structlog JSON, no `Co-Authored-By` trailer. mypy covers `src/` only. Script tests load via `importlib.util.spec_from_file_location` (see `tests/scripts/test_fetch_resolutions.py:10-16`).
- `Category` is a `StrEnum` in `src/pat/core/types.py` (values `"crypto"`, `"politics"`, …, `"other"`, `"geopolitics"`). `polymarket_taker_fee(category, price, shares)` already exists in `src/pat/costs/polymarket.py` (fee = shares·rate·p·(1−p), 5dp quantize; GEOPOLITICS rate 0).
- Gamma quirk: list-ish fields (`clobTokenIds`, `outcomePrices`) arrive as JSON-encoded strings OR real lists.
- I14 lesson: verify wire behavior empirically before trusting it (Task 8 probes `POST /books`).

**File map:**

| File | Responsibility |
|---|---|
| `src/pat/costs/polymarket.py` (modify) | + `POLYGON_TX_GAS_USDC`, `gas_cost`, `depth_vwap` |
| `src/pat/venues/polymarket/gamma.py` (modify) | + `_gamma_get_events_page` (no tag, wire) + `fetch_active_events` |
| `src/pat/venues/polymarket/books.py` (create) | CLOB `POST /books` batch seam + book normalization |
| `src/pat/analytics/arb_scan.py` (create) | frozen §4 math: targets, violations, universe, window dedup |
| `scripts/run_arb_scanner.py` (create) | long-running loop driver + JSONL snapshots + CLI |
| `tests/costs/test_polymarket.py` (modify) | gas_cost + depth_vwap tests |
| `tests/venues/polymarket/test_gamma_active_events.py` (create) | pager tests |
| `tests/venues/polymarket/test_books.py` (create) | batch/normalize tests |
| `tests/analytics/test_arb_scan.py` (create) | all §4 formulas + universe + windows |
| `tests/scripts/test_run_arb_scanner.py` (create) | one-iteration loop, graceful stop, refresh-failure |

---

### Task 1: cost primitives — `gas_cost` + `depth_vwap`

**Files:**
- Modify: `src/pat/costs/polymarket.py` (append at end)
- Test: `tests/costs/test_polymarket.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/costs/test_polymarket.py`:

```python
from pat.costs.polymarket import POLYGON_TX_GAS_USDC, depth_vwap, gas_cost


def test_gas_cost_is_per_tx():
    assert gas_cost(1) == POLYGON_TX_GAS_USDC
    assert gas_cost(3) == POLYGON_TX_GAS_USDC * 3
    assert gas_cost(0) == Decimal("0")


def test_gas_cost_rejects_negative():
    with pytest.raises(ValueError):
        gas_cost(-1)


def test_depth_vwap_walks_levels_best_first():
    levels = [(Decimal("0.40"), Decimal("5")), (Decimal("0.50"), Decimal("5"))]
    assert depth_vwap(levels, Decimal("5")) == Decimal("0.40")
    assert depth_vwap(levels, Decimal("10")) == Decimal("0.45")  # (2 + 2.5) / 10


def test_depth_vwap_partial_second_level():
    levels = [(Decimal("0.40"), Decimal("5")), (Decimal("0.50"), Decimal("10"))]
    # 5 @ 0.40 + 3 @ 0.50 = 3.5 / 8 = 0.4375
    assert depth_vwap(levels, Decimal("8")) == Decimal("0.4375")


def test_depth_vwap_insufficient_depth_is_none():
    levels = [(Decimal("0.40"), Decimal("5"))]
    assert depth_vwap(levels, Decimal("6")) is None
    assert depth_vwap([], Decimal("1")) is None


def test_depth_vwap_size_exactly_total_depth():
    levels = [(Decimal("0.40"), Decimal("5")), (Decimal("0.50"), Decimal("5"))]
    assert depth_vwap(levels, Decimal("10")) == Decimal("0.45")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/costs/test_polymarket.py -q`
Expected: FAIL — `ImportError: cannot import name 'POLYGON_TX_GAS_USDC'`

- [ ] **Step 3: Implement** — append to `src/pat/costs/polymarket.py`:

```python
# Conservative per-transaction gas on Polygon (claim I7: $0.002-0.005). CLOB trades cost
# the USER no gas (the operator settles); gas applies to split/merge/redeem transactions.
POLYGON_TX_GAS_USDC = Decimal("0.005")


def gas_cost(n_txs: int) -> Decimal:
    """Gas line item (USDC) for *n_txs* on-chain transactions (split/merge/redeem)."""
    if n_txs < 0:
        raise ValueError(f"n_txs must be >= 0, got {n_txs}")
    return POLYGON_TX_GAS_USDC * n_txs


def depth_vwap(
    levels: list[tuple[Decimal, Decimal]], size: Decimal
) -> Decimal | None:
    """Executable VWAP walking (price, size) levels best-first; None if depth < size.

    Slippage is implicit (VWAP vs top of book) — never a constant. `levels` must be
    best-first (bids descending / asks ascending); the caller normalizes.
    """
    remaining = size
    cost = Decimal("0")
    for price, level_size in levels:
        take = min(remaining, level_size)
        cost += price * take
        remaining -= take
        if remaining == 0:
            return cost / size
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/costs/test_polymarket.py -q`
Expected: all passed (existing + 5 new)

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/costs/polymarket.py tests/costs/test_polymarket.py
git commit -m "feat(costs): gas_cost + depth_vwap primitives for arb scanning"
```

---

### Task 2: Gamma active-events pager (no tag filter)

**Files:**
- Modify: `src/pat/venues/polymarket/gamma.py` (append)
- Test: `tests/venues/polymarket/test_gamma_active_events.py` (create)

- [ ] **Step 1: Write the failing tests** — create `tests/venues/polymarket/test_gamma_active_events.py`:

```python
"""Tests for gamma.fetch_active_events — no-tag pagination, no network."""

from __future__ import annotations

from pat.venues.polymarket.gamma import fetch_active_events


def test_paginates_and_dedups() -> None:
    pages = [
        [{"id": 1, "slug": "a"}, {"id": 2, "slug": "b"}],
        [{"id": 2, "slug": "b"}, {"id": 3, "slug": "c"}],
        [],
    ]
    calls: list[dict] = []

    def fake(*, closed: bool | None, limit: int, offset: int) -> list[dict]:
        calls.append({"closed": closed, "limit": limit, "offset": offset})
        idx = offset // limit
        return pages[idx] if idx < len(pages) else []

    out = fetch_active_events(get_page=fake)
    assert [e["id"] for e in out] == [1, 2, 3]
    assert all(c["closed"] is False for c in calls)
    assert calls[0]["offset"] == 0


def test_stops_on_short_page() -> None:
    def fake(*, closed: bool | None, limit: int, offset: int) -> list[dict]:
        assert offset == 0
        return [{"id": 1}]  # short page -> stop

    out = fetch_active_events(get_page=fake)
    assert len(out) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/venues/polymarket/test_gamma_active_events.py -q`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement** — append to `src/pat/venues/polymarket/gamma.py`:

```python
def _gamma_get_events_page(
    *, closed: bool | None = None, limit: int = _GAMMA_PAGE_SIZE, offset: int = 0
) -> list[dict[str, Any]]:
    """Fetch one /events page WITHOUT a tag filter. Wire-touching."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if closed is not None:
        params["closed"] = "true" if closed else "false"
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{GAMMA}/events", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def fetch_active_events(
    get_page: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Page through ALL active (closed=false) events; dedup by id; bounded pages.

    Same stopping rules as _gamma_get_all_events (empty page, short page, no-new page);
    bounded by _GAMMA_MAX_PAGES (silently capped — the count is logged for disclosure).
    """
    fetch = get_page or _gamma_get_events_page
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for page in range(_GAMMA_MAX_PAGES):
        events = fetch(closed=False, limit=_GAMMA_PAGE_SIZE, offset=page * _GAMMA_PAGE_SIZE)
        if not events:
            break
        new = 0
        for ev in events:
            eid = ev.get("id")
            key = eid if eid is not None else id(ev)
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
            new += 1
        if new == 0 or len(events) < _GAMMA_PAGE_SIZE:
            break
    log.info("gamma.active_events_fetched", events=len(out))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/venues/polymarket/ -q`
Expected: all passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/venues/polymarket/gamma.py tests/venues/polymarket/test_gamma_active_events.py
git commit -m "feat(gamma): no-tag active-events pager for the arb-scanner universe"
```

---

### Task 3: `books.py` — CLOB batch order books

**Files:**
- Create: `src/pat/venues/polymarket/books.py`
- Test: `tests/venues/polymarket/test_books.py` (create)

- [ ] **Step 1: Write the failing tests** — create `tests/venues/polymarket/test_books.py`:

```python
"""Tests for books.fetch_books — batching, normalization, split-on-failure. No network."""

from __future__ import annotations

from decimal import Decimal

import httpx

from pat.venues.polymarket.books import fetch_books


def _raw_book(token: str) -> dict:
    return {
        "asset_id": token,
        "bids": [{"price": "0.40", "size": "10"}, {"price": "0.50", "size": "5"}],
        "asks": [{"price": "0.70", "size": "1"}, {"price": "0.60", "size": "2"}],
    }


def _http_error() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://clob.polymarket.com/books")
    return httpx.HTTPStatusError(
        "400", request=req, response=httpx.Response(400, request=req)
    )


def test_batches_normalizes_and_sorts() -> None:
    calls: list[list[str]] = []

    def fake(chunk: list[str]) -> list[dict]:
        calls.append(list(chunk))
        return [_raw_book(t) for t in chunk]

    ids = [f"tok{i}" for i in range(5)]
    out = fetch_books(ids, batch_size=2, get_page=fake)
    assert [len(c) for c in calls] == [2, 2, 1]
    assert set(out) == set(ids)
    book = out["tok0"]
    # bids sorted DESC, asks sorted ASC, Decimal tuples
    assert book["bids"] == [
        (Decimal("0.50"), Decimal("5")), (Decimal("0.40"), Decimal("10"))
    ]
    assert book["asks"] == [
        (Decimal("0.60"), Decimal("2")), (Decimal("0.70"), Decimal("1"))
    ]


def test_failed_batch_splits_and_single_failure_is_skipped() -> None:
    ids = [f"tok{i}" for i in range(6)]
    bad = ids[2]

    def fake(chunk: list[str]) -> list[dict]:
        if bad in chunk:
            raise _http_error()
        return [_raw_book(t) for t in chunk]

    out = fetch_books(ids, batch_size=6, get_page=fake)
    assert bad not in out
    assert len(out) == 5


def test_malformed_book_is_skipped() -> None:
    def fake(chunk: list[str]) -> list[dict]:
        return [{"asset_id": chunk[0]}]  # no bids/asks keys

    out = fetch_books(["tokX"], get_page=fake)
    assert out == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/venues/polymarket/test_books.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.venues.polymarket.books'`

- [ ] **Step 3: Implement** — create `src/pat/venues/polymarket/books.py`:

```python
"""CLOB batch order books (POST /books) — the arb scanner's price source.

Network isolation: `_clob_post_books` is the ONLY wire-touching function; inject
`get_page` in tests. Books are normalized to Decimal (price, size) tuples sorted
best-first: bids DESCENDING, asks ASCENDING (what costs.depth_vwap expects).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import structlog

from pat.venues.polymarket.gamma import CLOB

_REQUEST_TIMEOUT = 30  # seconds

log = structlog.get_logger(__name__)

Book = dict[str, list[tuple[Decimal, Decimal]]]  # {"bids": [...], "asks": [...]}


def _clob_post_books(token_ids: list[str]) -> list[dict[str, Any]]:
    """POST /books for a batch of token ids. ONLY wire-touching function."""
    payload = [{"token_id": t} for t in token_ids]
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.post(f"{CLOB}/books", json=payload)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def _normalize_levels(raw: Any, *, descending: bool) -> list[tuple[Decimal, Decimal]]:
    levels = [
        (Decimal(str(lv["price"])), Decimal(str(lv["size"])))
        for lv in (raw or [])
    ]
    return sorted(levels, key=lambda pv: pv[0], reverse=descending)


def fetch_books(
    token_ids: list[str],
    *,
    batch_size: int = 100,
    get_page: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> dict[str, Book]:
    """Fetch + normalize order books for every token, `batch_size` ids per request.

    A failed batch (HTTPStatusError) splits in half; a single id that still fails is
    skipped with a warning (caller treats the missing book as zero depth). Books
    without both `bids` and `asks` keys are skipped + counted (`books.malformed`).
    Network-level errors propagate (infrastructure failure, not a bad token).
    """
    fetch = get_page or _clob_post_books
    raw_out: list[dict[str, Any]] = []

    def _fetch_chunk(chunk: list[str]) -> None:
        try:
            raw_out.extend(fetch(chunk))
        except httpx.HTTPStatusError as exc:
            if len(chunk) == 1:
                log.warning(
                    "books.fetch_failed", token_id=chunk[0],
                    status=exc.response.status_code,
                )
                return
            mid = len(chunk) // 2
            _fetch_chunk(chunk[:mid])
            _fetch_chunk(chunk[mid:])

    for i in range(0, len(token_ids), batch_size):
        _fetch_chunk(token_ids[i : i + batch_size])

    out: dict[str, Book] = {}
    malformed = 0
    for raw in raw_out:
        token = str(raw.get("asset_id", ""))
        if not token or "bids" not in raw or "asks" not in raw:
            malformed += 1
            continue
        out[token] = {
            "bids": _normalize_levels(raw["bids"], descending=True),
            "asks": _normalize_levels(raw["asks"], descending=False),
        }
    if malformed:
        log.warning("books.malformed", count=malformed)
    log.info("books.fetched", requested=len(token_ids), received=len(out))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/venues/polymarket/test_books.py -q`
Expected: 3 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/venues/polymarket/books.py tests/venues/polymarket/test_books.py
git commit -m "feat(venues): CLOB batch order-books seam with normalization"
```

---

### Task 4: `arb_scan.py` part 1 — negRisk buy_all / sell_all (frozen §4)

**Files:**
- Create: `src/pat/analytics/arb_scan.py`
- Test: `tests/analytics/test_arb_scan.py` (create)

- [ ] **Step 1: Write the failing tests** — create `tests/analytics/test_arb_scan.py`:

```python
"""Tests for the FROZEN spec §4 arb math (2026-06-10-a2-arb-scanner-design.md)."""

from __future__ import annotations

from decimal import Decimal

from pat.core.types import Category
from pat.analytics.arb_scan import (
    MarketRef,
    NegRiskTarget,
    scan_negrisk_event,
)


def _ref(cid: str, yes: str, no: str, cat: Category = Category.GEOPOLITICS) -> MarketRef:
    return MarketRef(condition_id=cid, yes_token=yes, no_token=no, category=cat)


def _book(bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> dict:
    return {
        "bids": [(Decimal(p), Decimal(s)) for p, s in bids],
        "asks": [(Decimal(p), Decimal(s)) for p, s in asks],
    }


def _target2() -> NegRiskTarget:
    return NegRiskTarget(
        event_slug="ev-k2",
        markets=[_ref("0xc1", "y1", "n1"), _ref("0xc2", "y2", "n2")],
    )


def test_buy_all_violation_zero_fee() -> None:
    # asks sum to 0.95/share, geopolitics (0 fee), deep books
    books = {
        "y1": _book([], [("0.40", "600")]),
        "y2": _book([], [("0.55", "600")]),
    }
    out = scan_negrisk_event(_target2(), books)
    v = next(x for x in out if x.type == "buy_all")
    # net(s) = s*0.05 - gas(1); best at s=500: 25 - 0.005 = 24.995
    assert v.best_size == Decimal("500")
    assert v.best_net == Decimal("24.995")
    assert v.grid["10"] == Decimal("0.495")
    assert v.key == "ev-k2"
    assert [leg.token_id for leg in v.legs] == ["y1", "y2"]


def test_sell_all_violation_uses_k_plus_1_gas() -> None:
    # bids sum to 1.05/share; K=2 -> gas_cost(3) = 0.015
    books = {
        "y1": _book([("0.60", "600")], []),
        "y2": _book([("0.45", "600")], []),
    }
    out = scan_negrisk_event(_target2(), books)
    v = next(x for x in out if x.type == "sell_all")
    assert v.best_size == Decimal("500")
    assert v.best_net == Decimal("24.985")  # 25 - 0.015


def test_fees_reduce_net_for_fee_category() -> None:
    target = NegRiskTarget(
        event_slug="ev-pol",
        markets=[
            _ref("0xc1", "y1", "n1", Category.POLITICS),
            _ref("0xc2", "y2", "n2", Category.POLITICS),
        ],
    )
    books = {
        "y1": _book([], [("0.30", "100")]),
        "y2": _book([], [("0.65", "100")]),
    }
    out = scan_negrisk_event(target, books)
    v = next(x for x in out if x.type == "buy_all")
    # s=10: gross 0.5; fees 10*0.04*(0.3*0.7) + 10*0.04*(0.65*0.35) = 0.084+0.091=0.175
    assert v.grid["10"] == Decimal("0.5") - Decimal("0.175") - Decimal("0.005")


def test_no_violation_when_sum_at_or_above_one() -> None:
    books = {
        "y1": _book([], [("0.50", "600")]),
        "y2": _book([], [("0.52", "600")]),
    }
    assert scan_negrisk_event(_target2(), books) == []


def test_grid_point_dropped_when_leg_lacks_depth() -> None:
    books = {
        "y1": _book([], [("0.40", "100")]),  # depth only to s=100
        "y2": _book([], [("0.55", "600")]),
    }
    out = scan_negrisk_event(_target2(), books)
    v = next(x for x in out if x.type == "buy_all")
    assert v.grid["500"] is None
    assert v.best_size == Decimal("100")


def test_missing_book_means_no_violation() -> None:
    books = {"y1": _book([], [("0.40", "600")])}  # y2 absent entirely
    assert scan_negrisk_event(_target2(), books) == []


def test_single_market_event_is_skipped() -> None:
    t = NegRiskTarget(event_slug="ev-1", markets=[_ref("0xc1", "y1", "n1")])
    assert scan_negrisk_event(t, {"y1": _book([], [("0.4", "600")])}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analytics/test_arb_scan.py -q`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement** — create `src/pat/analytics/arb_scan.py`:

```python
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
    grid: dict[str, Decimal | None] = {}
    best: tuple[Decimal, Decimal, list[Decimal]] | None = None
    for s in SIZE_GRID:
        r = _net_for_size(
            legs_levels, s, category=category, sell=sell, n_gas_txs=n_gas_txs
        )
        grid[str(s)] = r[0] if r is not None else None
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analytics/test_arb_scan.py -q`
Expected: 7 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/analytics/arb_scan.py tests/analytics/test_arb_scan.py
git commit -m "feat(analytics): negRisk buy_all/sell_all violation math (frozen spec §4)"
```

---

### Task 5: `arb_scan.py` part 2 — A1 single-market checks + `category_of`

**Files:**
- Modify: `src/pat/analytics/arb_scan.py` (append)
- Test: `tests/analytics/test_arb_scan.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/analytics/test_arb_scan.py`:

```python
from pat.analytics.arb_scan import BinaryTarget, category_of, scan_binary_market


def _binary(cat: Category = Category.GEOPOLITICS) -> BinaryTarget:
    return BinaryTarget(event_slug="ev-bin", market=_ref("0xb1", "by", "bn", cat))


def test_a1_buy_violation() -> None:
    # YES_ask + NO_ask = 0.95; depth caps executable size at 100
    books = {
        "by": _book([], [("0.40", "100")]),
        "bn": _book([], [("0.55", "100")]),
    }
    out = scan_binary_market(_binary(), books)
    v = next(x for x in out if x.type == "a1_buy")
    assert v.key == "0xb1"
    assert v.best_size == Decimal("100")
    assert v.best_net == Decimal("4.995")  # 100*0.05 - gas(1)
    assert v.grid["500"] is None


def test_a1_sell_violation() -> None:
    # YES_bid + NO_bid = 1.05; depth 50
    books = {
        "by": _book([("0.62", "50")], []),
        "bn": _book([("0.43", "50")], []),
    }
    out = scan_binary_market(_binary(), books)
    v = next(x for x in out if x.type == "a1_sell")
    assert v.best_size == Decimal("50")
    assert v.best_net == Decimal("2.495")  # 50*0.05 - gas(1)


def test_a1_no_violation_on_consistent_market() -> None:
    books = {
        "by": _book([("0.49", "500")], [("0.51", "500")]),
        "bn": _book([("0.48", "500")], [("0.50", "500")]),
    }
    assert scan_binary_market(_binary(), books) == []


def test_category_of_maps_known_and_falls_back() -> None:
    assert category_of("politics") is Category.POLITICS
    assert category_of("Geopolitics") is Category.GEOPOLITICS
    assert category_of("something-new") is Category.OTHER
    assert category_of(None) is Category.OTHER
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analytics/test_arb_scan.py -q`
Expected: FAIL — ImportError (scan_binary_market)

- [ ] **Step 3: Implement** — append to `src/pat/analytics/arb_scan.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analytics/test_arb_scan.py -q`
Expected: 11 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/analytics/arb_scan.py tests/analytics/test_arb_scan.py
git commit -m "feat(analytics): A1 single-market checks + category mapping"
```

---

### Task 6: `arb_scan.py` part 3 — `build_universe` + `windows_from_snapshots`

**Files:**
- Modify: `src/pat/analytics/arb_scan.py` (append; also add `import json` to module imports)
- Test: `tests/analytics/test_arb_scan.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/analytics/test_arb_scan.py`:

```python
from pat.analytics.arb_scan import Universe, build_universe, windows_from_snapshots


def _gmkt(cid: str, y: str, n: str, vol: float, cat: str | None = None) -> dict:
    return {
        "conditionId": cid,
        "clobTokenIds": f'["{y}", "{n}"]',
        "volume24hr": vol,
        "category": cat,
    }


def _gev(slug: str, *, negrisk: bool, markets: list[dict]) -> dict:
    return {"id": slug, "slug": slug, "negRisk": negrisk, "markets": markets}


def test_build_universe_negrisk_first_then_binaries_by_volume() -> None:
    events = [
        _gev("bin-low", negrisk=False, markets=[_gmkt("0xb1", "l1", "l2", 10.0)]),
        _gev("nr", negrisk=True, markets=[
            _gmkt("0xn1", "y1", "n1", 5.0), _gmkt("0xn2", "y2", "n2", 5.0)]),
        _gev("bin-high", negrisk=False, markets=[_gmkt("0xb2", "h1", "h2", 99.0)]),
    ]
    # budget: negrisk needs 4 tokens; one binary (2 tokens) fits; the low-vol one is cut
    u = build_universe(events, max_books=6)
    assert [t.event_slug for t in u.negrisk] == ["nr"]
    assert [b.market.condition_id for b in u.binaries] == ["0xb2"]  # volume desc
    assert u.n_tokens == 6
    assert u.truncated is True


def test_build_universe_skips_malformed_markets() -> None:
    events = [
        _gev("nr", negrisk=True, markets=[
            _gmkt("0xn1", "y1", "n1", 1.0),
            {"conditionId": "0xbad", "clobTokenIds": '["only-one"]'},
            _gmkt("0xn2", "y2", "n2", 1.0),
        ]),
    ]
    u = build_universe(events, max_books=100)
    assert len(u.negrisk[0].markets) == 2
    assert u.truncated is False


def test_build_universe_single_market_negrisk_event_dropped() -> None:
    events = [_gev("nr1", negrisk=True, markets=[_gmkt("0xn1", "y1", "n1", 1.0)])]
    u = build_universe(events, max_books=100)
    assert u.negrisk == []


def _snap(ts: int, keys: list[tuple[str, str]], net: str = "2") -> dict:
    return {
        "ts": ts,
        "violations": [
            {"key": k, "type": t, "best_net": net} for k, t in keys
        ],
    }


def test_windows_consecutive_scans_collapse_to_one() -> None:
    snaps = [
        _snap(0, [("ev-a", "buy_all")]),
        _snap(120, [("ev-a", "buy_all")], net="3"),
        _snap(240, []),
        _snap(360, [("ev-a", "buy_all")]),
    ]
    ws = windows_from_snapshots(snaps, interval_s=120)
    assert len(ws) == 2
    assert ws[0]["n_scans"] == 2
    assert ws[0]["max_best_net"] == Decimal("3")
    assert ws[1]["start_ts"] == 360


def test_windows_scanning_gap_ends_window() -> None:
    snaps = [
        _snap(0, [("ev-a", "buy_all")]),
        _snap(1000, [("ev-a", "buy_all")]),  # gap > 2*interval -> new window
    ]
    ws = windows_from_snapshots(snaps, interval_s=120)
    assert len(ws) == 2


def test_windows_distinct_types_are_distinct_windows() -> None:
    snaps = [_snap(0, [("ev-a", "buy_all"), ("ev-a", "sell_all")])]
    ws = windows_from_snapshots(snaps, interval_s=120)
    assert len(ws) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analytics/test_arb_scan.py -q`
Expected: FAIL — ImportError (build_universe)

- [ ] **Step 3: Implement** — append to `src/pat/analytics/arb_scan.py` (and add `import json` next to the existing imports at the top):

```python
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
            for m in markets_raw  # type: ignore[union-attr]
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
        for v in snap.get("violations", []):  # type: ignore[union-attr]
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analytics/test_arb_scan.py -q`
Expected: 17 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/analytics/arb_scan.py tests/analytics/test_arb_scan.py
git commit -m "feat(analytics): scan universe builder + window dedup for arb scanner"
```

---

### Task 7: `scripts/run_arb_scanner.py` — the loop driver

**Files:**
- Create: `scripts/run_arb_scanner.py`
- Test: `tests/scripts/test_run_arb_scanner.py` (create)

- [ ] **Step 1: Write the failing tests** — create `tests/scripts/test_run_arb_scanner.py`:

```python
"""Offline tests for scripts/run_arb_scanner.py — fake clock, injected seams."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "run_arb_scanner",
    Path(__file__).resolve().parents[2] / "scripts" / "run_arb_scanner.py",
)
assert _SPEC and _SPEC.loader
ras = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ras)


def _events() -> list[dict]:
    return [{
        "id": "ev1", "slug": "ev1", "negRisk": True,
        "markets": [
            {"conditionId": "0xc1", "clobTokenIds": '["y1", "n1"]',
             "volume24hr": 1.0, "category": "geopolitics"},
            {"conditionId": "0xc2", "clobTokenIds": '["y2", "n2"]',
             "volume24hr": 1.0, "category": "geopolitics"},
        ],
    }]


def _books(_ids: list[str], **_: object) -> dict:
    from decimal import Decimal as D
    book = {"bids": [], "asks": [(D("0.40"), D("600"))]}
    book2 = {"bids": [], "asks": [(D("0.55"), D("600"))]}
    empty = {"bids": [], "asks": []}
    return {"y1": book, "y2": book2, "n1": empty, "n2": empty}


def test_one_scan_writes_snapshot_with_violation(tmp_path: Path) -> None:
    out_dir = tmp_path / "scans"
    ras.main_loop(
        interval=120, max_books=100, out_dir=out_dir, max_scans=1,
        get_events=lambda: _events(), get_books=_books, sleep=lambda _s: None,
    )
    files = list(out_dir.glob("*.jsonl"))
    assert len(files) == 1
    snap = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert snap["n_events"] == 1
    assert snap["n_books"] == 4
    assert snap["universe_truncated"] is False
    assert len(snap["violations"]) == 1
    assert snap["violations"][0]["type"] == "buy_all"


def test_keyboard_interrupt_in_sleep_exits_cleanly(tmp_path: Path) -> None:
    def boom(_s: float) -> None:
        raise KeyboardInterrupt

    ras.main_loop(
        interval=120, max_books=100, out_dir=tmp_path / "s", max_scans=5,
        get_events=lambda: _events(), get_books=_books, sleep=boom,
    )  # must return, not raise
    assert len(list((tmp_path / "s").glob("*.jsonl"))) == 1


def test_universe_refresh_failure_reuses_previous(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky_events() -> list[dict]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("gamma down")
        return _events()

    ras.main_loop(
        interval=120, max_books=100, out_dir=tmp_path / "s", max_scans=2,
        refresh_every=1, get_events=flaky_events, get_books=_books,
        sleep=lambda _s: None,
    )
    lines = (
        next((tmp_path / "s").glob("*.jsonl")).read_text(encoding="utf-8")
        .strip().splitlines()
    )
    assert len(lines) == 2  # second scan ran on the previous universe
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_run_arb_scanner.py -q`
Expected: FAIL (script missing)

- [ ] **Step 3: Implement** — create `scripts/run_arb_scanner.py`:

```python
"""A2 structural arb scanner — long-running read-only loop (ADR 0021 Step 2).

Every --interval seconds: refresh universe (every --refresh-every scans), fetch CLOB
books, run the FROZEN spec §4 scan, append one JSONL snapshot line per scan to
data/raw/arb_scans/YYYY-MM-DD.jsonl. Keyless, $0, no orders. Ctrl+C to stop.
Coverage gaps (PC off) stay visible as timestamp gaps — that honesty is by design.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import structlog  # noqa: E402

from pat.analytics.arb_scan import (  # noqa: E402
    Universe,
    build_universe,
    scan_binary_market,
    scan_negrisk_event,
    universe_tokens,
)
from pat.venues.polymarket.books import fetch_books  # noqa: E402
from pat.venues.polymarket.gamma import fetch_active_events  # noqa: E402

log = structlog.get_logger(__name__)


def scan_once(
    universe: Universe, *, get_books: Any, max_books: int
) -> dict[str, Any]:
    """One scan: fetch books for the universe, evaluate every target, build a snapshot."""
    started = time.time()
    tokens = universe_tokens(universe)
    books = get_books(tokens, batch_size=100)
    violations = []
    for target in universe.negrisk:
        violations.extend(scan_negrisk_event(target, books))
    for binary in universe.binaries:
        violations.extend(scan_binary_market(binary, books))
    return {
        "ts": started,
        "scan_duration_s": round(time.time() - started, 3),
        "n_events": len(universe.negrisk) + len(universe.binaries),
        "n_markets": sum(len(t.markets) for t in universe.negrisk)
        + len(universe.binaries),
        "n_books": len(books),
        "n_bad_books": len(tokens) - len(books),
        "universe_truncated": universe.truncated,
        "max_books": max_books,
        "violations": [v.model_dump(mode="json") for v in violations],
    }


def _append_snapshot(out_dir: Path, snapshot: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.fromtimestamp(snapshot["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
    path = out_dir / f"{day}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot) + "\n")
    return path


def main_loop(
    *,
    interval: int,
    max_books: int,
    out_dir: Path,
    max_scans: int | None = None,
    refresh_every: int = 10,
    get_events: Any = None,
    get_books: Any = None,
    sleep: Any = None,
) -> None:
    """Scan forever (or max_scans times). KeyboardInterrupt exits cleanly."""
    corr_id = str(uuid.uuid4())
    blog = log.bind(corr_id=corr_id, mode="scan")
    ge = get_events or fetch_active_events
    gb = get_books or fetch_books
    zzz = sleep or time.sleep

    universe: Universe | None = None
    n_scans = 0
    try:
        while max_scans is None or n_scans < max_scans:
            if universe is None or n_scans % refresh_every == 0:
                try:
                    events = ge()
                    universe = build_universe(events, max_books=max_books)
                    blog.info(
                        "scanner.universe", negrisk=len(universe.negrisk),
                        binaries=len(universe.binaries),
                        n_tokens=universe.n_tokens, truncated=universe.truncated,
                    )
                except Exception as exc:  # noqa: BLE001 — keep scanning on old universe
                    if universe is None:
                        raise
                    blog.warning("scanner.universe_refresh_failed", error=str(exc))
            try:
                snapshot = scan_once(universe, get_books=gb, max_books=max_books)
                path = _append_snapshot(out_dir, snapshot)
                blog.info(
                    "scanner.scan", n=n_scans, violations=len(snapshot["violations"]),
                    n_books=snapshot["n_books"], out=str(path),
                )
            except Exception as exc:  # noqa: BLE001 — one bad scan must not kill the loop
                blog.warning("scanner.scan_failed", n=n_scans, error=str(exc))
            n_scans += 1
            if max_scans is None or n_scans < max_scans:
                zzz(interval)
    except KeyboardInterrupt:
        blog.info("scanner.stopped", scans=n_scans)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="A2 structural arb scanner (read-only polling loop)."
    )
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--max-books", type=int, default=1500)
    p.add_argument("--out-dir", type=Path, default=Path("data/raw/arb_scans"))
    p.add_argument("--refresh-every", type=int, default=10)
    p.add_argument("--max-scans", type=int, default=None,
                   help="Stop after N scans (default: run until Ctrl+C).")
    return p.parse_args()


if __name__ == "__main__":
    import logging

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    args = _parse_args()
    main_loop(
        interval=args.interval, max_books=args.max_books, out_dir=args.out_dir,
        max_scans=args.max_scans, refresh_every=args.refresh_every,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_run_arb_scanner.py -q`
Expected: 3 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add scripts/run_arb_scanner.py tests/scripts/test_run_arb_scanner.py
git commit -m "feat(scripts): A2 arb-scanner polling loop with JSONL snapshots"
```

---

### Task 8: Operational — probe `POST /books`, smoke scan, docs (controller-led)

**Files:**
- Possibly modify: `src/pat/venues/polymarket/books.py` (only if the probe contradicts the assumed wire shape)
- Modify: `docs/HANDOFF.md`, `docs/roadmap.md`, `docs/research/claims-verification.md` (new claim I15: POST /books shape + batch cap)

- [ ] **Step 1: Probe the real `POST /books` endpoint** (I14 lesson — verify before trusting)

Write a THROWAWAY probe (delete after): take 2 token ids from a live Gamma event
(`fetch_active_events()[0]`), POST `[{"token_id": ...}, ...]` to
`https://clob.polymarket.com/books`, print the response keys/shape and whether
`asset_id`, `bids[].price/size`, `asks[].price/size` match the assumptions in
`books.py`. Also probe a larger batch (e.g. 50 ids) to find practical caps.
If the shape differs → fix `_clob_post_books`/normalization + tests in a dedicated
commit BEFORE the smoke scan. Record findings as claim **I15** in
`docs/research/claims-verification.md`.

- [ ] **Step 2: Smoke scan (one iteration, live)**

Run: `uv run python scripts/run_arb_scanner.py --max-scans 1`
Expected: structlog `scanner.universe` (sane counts; truncated flag noted) +
`scanner.scan` + one JSONL line in `data/raw/arb_scans/<today>.jsonl`. Eyeball the
snapshot: violations present or empty are both fine; `n_bad_books` should be a small
fraction of `n_books`.

- [ ] **Step 3: Docs + commit**

Update `docs/HANDOFF.md` (scanner BUILT; launch command `uv run python
scripts/run_arb_scanner.py`; observation clock starts at first sustained launch;
verdict ADR only after the spec §5 gate window — ≥10 scanning-days) and
`docs/roadmap.md` (Step 2 in progress: accruing calendar data). Commit docs +
any probe-driven fixes:

```bash
git add docs/HANDOFF.md docs/roadmap.md docs/research/claims-verification.md
git commit -m "docs: A2 scanner operational - probe findings (I15) + launch runbook"
```

- [ ] **Step 4: Hand off to the user**

The user starts the long-running scanner whenever the PC is on:
`uv run python scripts/run_arb_scanner.py` (Ctrl+C to stop; gaps are fine and visible).
The §5 verdict run (windows_from_snapshots over accrued JSONL + ADR) happens in a
LATER session once ≥10 scanning-days accumulate — do NOT write a verdict ADR now.

---

## Self-review notes (done at plan-writing time)

- **Spec coverage:** §3 components → Tasks 1–3, 7; §4 frozen math → Tasks 4–5 (every
  formula hand-tested incl. K+1 gas), window unit → Task 6; §5 gate → deferred to the
  verdict session by design (Task 8 Step 4 says so explicitly); §6 error handling →
  Tasks 3 (split/skip), 7 (scan-failure isolation, refresh reuse); §7 schema → Task 7
  snapshot dict + test; §8 test list → all tasks; universe bounding + truncation
  disclosure → Task 6 + snapshot field.
- **Type consistency:** `Book` defined in books.py and arb_scan.py as the same alias
  shape (dict[str, list[tuple[Decimal, Decimal]]]); `fetch_books(ids, batch_size=...)`
  matches the driver's `get_books(tokens, batch_size=100)` call and the test fake's
  `(_ids, **_)` signature; `universe_tokens` feeds `fetch_books`; `Violation.model_dump
  (mode="json")` feeds the JSONL (Decimal-safe).
- **Frozen-gate guard:** SIZE_GRID, gas tx counts (1 / K+1 / 1 / 1), conservative I9
  fee rule are pinned by tests; §5 thresholds live in the spec, not in code (the
  verdict session reads them from the spec — nothing to tune in this build).
