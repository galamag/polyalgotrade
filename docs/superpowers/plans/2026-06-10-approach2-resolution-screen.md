# Approach 2 — Resolution-Grounded P&L Concentration Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Join the saved 75-wallet trades dataset to Gamma resolutions and compute TRUE realized P&L (incl. redemption payouts), then apply the pre-registered ADR 0021 kill criterion (concentration screen).

**Architecture:** One new wire seam in `gamma.py` (batch `/markets?condition_ids=`), one new pure-analytics module `resolution_pnl.py` (parse → per-condition P&L → per-wallet metrics → kill verdict), two thin drivers (`fetch_resolutions.py` idempotent fetch, `run_resolution_screen.py` report). Carried fixes: S5 (`n_tokens` by conditionId) and the I13 on-chain spot-check via point `eth_getTransactionReceipt` lookups (never range getLogs).

**Tech Stack:** Python 3.11, `httpx`, `pydantic`, `structlog`, `pytest`, `Decimal` for money. Run everything via `uv run`.

**Spec (binding, pre-registered formulas):** `docs/superpowers/specs/2026-06-10-approach2-resolution-pnl-design.md`. Decision: `docs/decisions/0021-post-wallet-spike-direction.md`.

**Context for the engineer:**
- Saved trades: `data/raw/wallet_trades/0x<addr>.json` (75 files) + `_winners.json` / `_control.json` (address lists). Each trade row has: `proxyWallet, side ("BUY"/"SELL", wallet perspective), asset (token id), conditionId, size, price, timestamp (epoch SECONDS), eventSlug, outcome, outcomeIndex, transactionHash, is_maker`, and more.
- Money is ALWAYS `Decimal(str(x))` — never float arithmetic on prices/sizes.
- Network-touching functions are isolated seams, injectable in tests (see `_gamma_get_events` in `src/pat/venues/polymarket/gamma.py` for the pattern). Tests NEVER hit the network.
- Script tests load the script module via `importlib.util.spec_from_file_location` (see `tests/scripts/test_fetch_wallet_trades.py:10-16`).
- Verification gates for every task: `uv run pytest -q` green, `uv run ruff check .` clean, `uv run mypy src` clean. Line length ≤ 100 (ruff E501).

**File map (created/modified by this plan):**

| File | Responsibility |
|---|---|
| `src/pat/venues/polymarket/gamma.py` (modify) | + `_gamma_get_markets` (wire) + `fetch_markets_by_condition_ids` (batching/fallback) |
| `src/pat/analytics/resolution_pnl.py` (create) | parse_resolution, condition_pnls, wallet_metrics, screen_verdict — pure, no network |
| `scripts/fetch_resolutions.py` (create) | collect conditionIds → fetch → `data/raw/resolutions.json` (idempotent) |
| `scripts/run_resolution_screen.py` (create) | driver: trades + resolutions → report + jsonl + kill verdict |
| `src/pat/analytics/wallet_features.py` (modify) | S5: `WalletFill.condition_id`, `n_tokens` = unique markets |
| `scripts/spot_check_trades.py` (create) | I13 trust step: receipts-by-txHash vs data-api rows (CU-capped) |
| `tests/venues/polymarket/test_gamma_markets.py` (create) | batching, split-on-4xx, single-id skip |
| `tests/analytics/test_resolution_pnl.py` (create) | all §4 formulas + edge cases |
| `tests/scripts/test_fetch_resolutions.py` (create) | idempotency, unknown recording, --refresh |
| `tests/scripts/test_run_resolution_screen.py` (create) | report rendering + verdict line + jsonl |
| `tests/analytics/test_wallet_features.py` (modify) | S5 tests |
| `tests/scripts/test_spot_check_trades.py` (create) | match/mismatch/cap on fixture receipts |

---

### Task 1: `fetch_markets_by_condition_ids` in gamma.py

**Files:**
- Modify: `src/pat/venues/polymarket/gamma.py` (append at end)
- Test: `tests/venues/polymarket/test_gamma_markets.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/venues/polymarket/test_gamma_markets.py`:

```python
"""Tests for gamma.fetch_markets_by_condition_ids — batching + fallback, no network."""

from __future__ import annotations

import httpx

from pat.venues.polymarket.gamma import fetch_markets_by_condition_ids


def _mk(cid: str) -> dict:
    return {"conditionId": cid, "closed": True, "outcomePrices": '["1", "0"]'}


def _http_error() -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://gamma-api.polymarket.com/markets")
    return httpx.HTTPStatusError(
        "400", request=req, response=httpx.Response(400, request=req)
    )


def test_batches_and_collects_all() -> None:
    calls: list[list[str]] = []

    def fake(chunk: list[str]) -> list[dict]:
        calls.append(list(chunk))
        return [_mk(c) for c in chunk]

    ids = [f"0x{i:02d}" for i in range(45)]
    out = fetch_markets_by_condition_ids(ids, batch_size=20, get_page=fake)
    assert [len(c) for c in calls] == [20, 20, 5]
    assert {m["conditionId"] for m in out} == set(ids)


def test_failed_batch_splits_and_single_failure_is_skipped() -> None:
    ids = [f"0x{i:02d}" for i in range(10)]
    bad = ids[3]

    def fake(chunk: list[str]) -> list[dict]:
        if bad in chunk:
            raise _http_error()
        return [_mk(c) for c in chunk]

    out = fetch_markets_by_condition_ids(ids, batch_size=10, get_page=fake)
    got = {m["conditionId"] for m in out}
    assert bad not in got
    assert len(got) == 9


def test_empty_input_no_calls() -> None:
    def fake(chunk: list[str]) -> list[dict]:  # pragma: no cover - must not run
        raise AssertionError("should not be called")

    assert fetch_markets_by_condition_ids([], get_page=fake) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/venues/polymarket/test_gamma_markets.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_markets_by_condition_ids'`

- [ ] **Step 3: Implement**

Append to `src/pat/venues/polymarket/gamma.py` (after `select_geopolitics_tokens`):

```python
def _gamma_get_markets(condition_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch /markets for a batch of condition ids. ONLY wire-touching /markets function."""
    params: list[tuple[str, str]] = [("condition_ids", c) for c in condition_ids]
    params.append(("limit", str(len(condition_ids))))
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{GAMMA}/markets", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def fetch_markets_by_condition_ids(
    condition_ids: list[str],
    *,
    batch_size: int = 20,
    get_page: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch Gamma market dicts for every conditionId, `batch_size` ids per request.

    A failed batch (HTTPStatusError) is split in half and retried; a single id that
    still fails is skipped with a warning (the caller records it as unknown).
    """
    fetch = get_page or _gamma_get_markets
    out: list[dict[str, Any]] = []

    def _fetch_chunk(chunk: list[str]) -> None:
        try:
            out.extend(fetch(chunk))
        except httpx.HTTPStatusError as exc:
            if len(chunk) == 1:
                log.warning(
                    "gamma.market_fetch_failed",
                    condition_id=chunk[0],
                    status=exc.response.status_code,
                )
                return
            mid = len(chunk) // 2
            _fetch_chunk(chunk[:mid])
            _fetch_chunk(chunk[mid:])

    for i in range(0, len(condition_ids), batch_size):
        _fetch_chunk(condition_ids[i : i + batch_size])
    log.info(
        "gamma.markets_fetched", requested=len(condition_ids), received=len(out)
    )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/venues/polymarket/test_gamma_markets.py -q`
Expected: 3 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`
Expected: all green/clean.

```bash
git add src/pat/venues/polymarket/gamma.py tests/venues/polymarket/test_gamma_markets.py
git commit -m "feat(gamma): batch market fetch by condition_ids with split-on-failure"
```

---

### Task 2: `resolution_pnl.parse_resolution` (strict-binary winner)

**Files:**
- Create: `src/pat/analytics/resolution_pnl.py`
- Test: `tests/analytics/test_resolution_pnl.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/analytics/test_resolution_pnl.py`:

```python
"""Tests for the pre-registered resolution-grounded P&L methodology (spec §4)."""

from __future__ import annotations

from pat.analytics.resolution_pnl import (
    AMBIGUOUS,
    RESOLVED,
    UNRESOLVED,
    parse_resolution,
)


def test_resolved_strict_binary_winner_index() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc1", "closed": True, "outcomePrices": '["0", "1"]'}
    )
    assert rec == {"conditionId": "0xc1", "status": RESOLVED, "winning_index": 1}


def test_open_market_is_unresolved() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc2", "closed": False, "outcomePrices": '["0.7", "0.3"]'}
    )
    assert rec["status"] == UNRESOLVED
    assert rec["winning_index"] is None


def test_closed_5050_refund_is_ambiguous() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc3", "closed": True, "outcomePrices": '["0.5", "0.5"]'}
    )
    assert rec["status"] == AMBIGUOUS


def test_outcome_prices_as_real_list_also_parses() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc4", "closed": True, "outcomePrices": ["1", "0"]}
    )
    assert rec["status"] == RESOLVED
    assert rec["winning_index"] == 0


def test_closed_without_prices_is_unresolved() -> None:
    rec = parse_resolution({"conditionId": "0xc5", "closed": True})
    assert rec["status"] == UNRESOLVED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analytics/test_resolution_pnl.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.analytics.resolution_pnl'`

- [ ] **Step 3: Implement**

Create `src/pat/analytics/resolution_pnl.py`:

```python
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
    zeros = [p for p in prices if p == 0]
    if len(ones) == 1 and len(zeros) == len(prices) - 1:
        return {"conditionId": condition_id, "status": RESOLVED, "winning_index": ones[0]}
    return {"conditionId": condition_id, "status": AMBIGUOUS, "winning_index": None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analytics/test_resolution_pnl.py -q`
Expected: 5 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/analytics/resolution_pnl.py tests/analytics/test_resolution_pnl.py
git commit -m "feat(analytics): parse_resolution with strict-binary winner detection"
```

---

### Task 3: `condition_pnls` — per-condition P&L with statuses

**Files:**
- Modify: `src/pat/analytics/resolution_pnl.py` (append)
- Test: `tests/analytics/test_resolution_pnl.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/analytics/test_resolution_pnl.py`:

```python
from decimal import Decimal

from pat.analytics.resolution_pnl import (
    FRAME_INCOMPLETE,
    UNKNOWN,
    ConditionPnl,
    condition_pnls,
)


def _row(
    cond: str,
    asset: str,
    side: str,
    price: str,
    size: str,
    *,
    idx: int = 0,
    ts: int = 100,
    slug: str = "ev-a",
) -> dict:
    return {
        "conditionId": cond,
        "eventSlug": slug,
        "asset": asset,
        "side": side,
        "price": price,
        "size": size,
        "outcomeIndex": idx,
        "timestamp": ts,
    }


_RES = {
    "0xw": {"status": "resolved", "winning_index": 0},
    "0xl": {"status": "resolved", "winning_index": 1},
    "0xu": {"status": "unresolved", "winning_index": None},
}


def _one(rows: list[dict], res: dict | None = None) -> ConditionPnl:
    out = condition_pnls(rows, res if res is not None else _RES)
    assert len(out) == 1
    return out[0]


def test_buy_and_redeem_win() -> None:
    # buy 10 @ 0.4 of outcome 0; outcome 0 wins -> pnl = -4 + 10 = +6
    c = _one([_row("0xw", "tokA", "BUY", "0.4", "10", idx=0)])
    assert c.status == "resolved"
    assert c.pnl == Decimal("6")


def test_buy_and_lose() -> None:
    # buy 10 @ 0.4 of outcome 0; outcome 1 wins -> pnl = -4
    c = _one([_row("0xl", "tokA", "BUY", "0.4", "10", idx=0)])
    assert c.pnl == Decimal("-4")


def test_roundtrip_before_resolution_is_pure_cashflow() -> None:
    # buy 10 @ 0.4, sell 10 @ 0.7 -> net 0 shares, pnl = +3 (no redemption leg)
    c = _one(
        [
            _row("0xw", "tokA", "BUY", "0.4", "10", ts=100),
            _row("0xw", "tokA", "SELL", "0.7", "10", ts=200),
        ]
    )
    assert c.pnl == Decimal("3")


def test_both_outcome_tokens_one_condition() -> None:
    # buy 10 YES (idx0) @ 0.6 and 10 NO (idx1) @ 0.5; idx0 wins:
    # YES: -6 + 10 = +4; NO: -5 + 0 = -5 -> total -1
    c = _one(
        [
            _row("0xw", "tokY", "BUY", "0.6", "10", idx=0),
            _row("0xw", "tokN", "BUY", "0.5", "10", idx=1),
        ]
    )
    assert c.pnl == Decimal("-1")


def test_negative_net_shares_is_frame_incomplete_even_if_resolved() -> None:
    c = _one([_row("0xw", "tokA", "SELL", "0.7", "5")])
    assert c.status == FRAME_INCOMPLETE


def test_unresolved_exposure_at_last_trade_price() -> None:
    # buy 10 @ 0.4 then 2 @ 0.55 -> net 12, last price 0.55 -> exposure 6.6
    c = _one(
        [
            _row("0xu", "tokA", "BUY", "0.4", "10", ts=100),
            _row("0xu", "tokA", "BUY", "0.55", "2", ts=200),
        ]
    )
    assert c.status == "unresolved"
    assert c.unresolved_exposure == Decimal("6.6")
    assert c.pnl == Decimal("0")


def test_condition_missing_from_resolutions_is_unknown() -> None:
    c = _one([_row("0xmissing", "tokA", "BUY", "0.4", "10")], res={})
    assert c.status == UNKNOWN


def test_zero_size_and_missing_fields_rows_are_skipped() -> None:
    rows = [
        _row("0xw", "tokA", "BUY", "0.4", "0"),          # zero size
        {"conditionId": "", "eventSlug": "x", "asset": "t", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 1},  # no cond
        _row("0xw", "tokA", "BUY", "0.4", "10"),
    ]
    out = condition_pnls(rows, _RES)
    assert len(out) == 1
    assert out[0].pnl == Decimal("6")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analytics/test_resolution_pnl.py -q`
Expected: FAIL — `ImportError: cannot import name 'ConditionPnl'`

- [ ] **Step 3: Implement**

Append to `src/pat/analytics/resolution_pnl.py`:

```python
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
    by_cond: dict[str, list[dict[str, Any]]] = {}
    skipped = 0
    for t in trades:
        cond = str(t.get("conditionId") or "")
        slug = str(t.get("eventSlug") or "")
        if not cond or not slug or Decimal(str(t.get("size", 0))) <= 0:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analytics/test_resolution_pnl.py -q`
Expected: 13 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/analytics/resolution_pnl.py tests/analytics/test_resolution_pnl.py
git commit -m "feat(analytics): per-condition resolution P&L with frame-incomplete guard"
```

---

### Task 4: `wallet_metrics` + `screen_verdict` (the pre-registered gate)

**Files:**
- Modify: `src/pat/analytics/resolution_pnl.py` (append)
- Test: `tests/analytics/test_resolution_pnl.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/analytics/test_resolution_pnl.py`:

```python
from pat.analytics.resolution_pnl import (
    WalletResolutionMetrics,
    screen_verdict,
    wallet_metrics,
)


def _cond(slug: str, pnl: str, status: str = "resolved") -> ConditionPnl:
    return ConditionPnl(
        condition_id=f"0x{slug}-{pnl}",
        event_slug=slug,
        status=status,
        pnl=Decimal(pnl),
    )


def test_event_aggregation_sums_conditions_within_event() -> None:
    m = wallet_metrics("0xw", [_cond("ev-a", "2"), _cond("ev-a", "-1"), _cond("ev-b", "3")])
    assert m.total_resolution_pnl == Decimal("4")
    assert m.n_conditions_resolved == 3
    assert m.n_events_resolved == 2
    assert m.n_events_positive == 2  # ev-a: +1, ev-b: +3


def test_diversified_requires_10_positive_events() -> None:
    ten = [_cond(f"ev-{i}", "1") for i in range(10)]
    assert wallet_metrics("0xw", ten).diversified is True
    nine = [_cond(f"ev-{i}", "1") for i in range(9)]
    assert wallet_metrics("0xw", nine).diversified is False


def test_diversified_rejects_top1_share_at_exactly_half() -> None:
    # events: one +9 and nine +1 -> abs_total 18, top1 = 0.5 -> NOT diversified
    conds = [_cond("ev-big", "9")] + [_cond(f"ev-{i}", "1") for i in range(9)]
    m = wallet_metrics("0xw", conds)
    assert m.n_events_positive == 10
    assert m.top1_share == 0.5
    assert m.diversified is False


def test_diversified_requires_positive_total() -> None:
    # ten +1 events and ten -1 events -> total 0, n_pos=10, top1=0.05 -> NOT diversified
    conds = [_cond(f"ev-p{i}", "1") for i in range(10)] + [
        _cond(f"ev-n{i}", "-1") for i in range(10)
    ]
    m = wallet_metrics("0xw", conds)
    assert m.total_resolution_pnl == Decimal("0")
    assert m.diversified is False


def test_disclosure_counters_and_exposure() -> None:
    conds = [
        _cond("ev-a", "1"),
        ConditionPnl(condition_id="0xf", event_slug="ev-f", status=FRAME_INCOMPLETE),
        ConditionPnl(
            condition_id="0xu", event_slug="ev-u", status="unresolved",
            unresolved_exposure=Decimal("6.6"),
        ),
        ConditionPnl(condition_id="0xa", event_slug="ev-x", status=AMBIGUOUS),
        ConditionPnl(condition_id="0xk", event_slug="ev-k", status=UNKNOWN),
    ]
    m = wallet_metrics("0xw", conds)
    assert m.n_frame_incomplete == 1
    assert m.n_unresolved == 1
    assert m.n_ambiguous == 1
    assert m.n_unknown == 1
    assert m.unresolved_exposure == Decimal("6.6")


def _metric(div: bool) -> WalletResolutionMetrics:
    return WalletResolutionMetrics(
        wallet="0xw", total_resolution_pnl=Decimal("1"), n_conditions_resolved=1,
        n_events_resolved=1, n_events_positive=1, top1_share=0.1,
        n_frame_incomplete=0, n_unresolved=0, n_ambiguous=0, n_unknown=0,
        unresolved_exposure=Decimal("0"), diversified=div,
    )


def test_screen_verdict_kill_boundary() -> None:
    four = [_metric(True)] * 4 + [_metric(False)] * 46
    assert screen_verdict(four) == (4, True)  # < 5 -> branch B killed
    five = [_metric(True)] * 5 + [_metric(False)] * 45
    assert screen_verdict(five) == (5, False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analytics/test_resolution_pnl.py -q`
Expected: FAIL — `ImportError: cannot import name 'WalletResolutionMetrics'`

- [ ] **Step 3: Implement**

Append to `src/pat/analytics/resolution_pnl.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analytics/test_resolution_pnl.py -q`
Expected: 19 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/analytics/resolution_pnl.py tests/analytics/test_resolution_pnl.py
git commit -m "feat(analytics): wallet resolution metrics + pre-registered kill verdict"
```

---

### Task 5: `scripts/fetch_resolutions.py` (idempotent, keyless)

**Files:**
- Create: `scripts/fetch_resolutions.py`
- Test: `tests/scripts/test_fetch_resolutions.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_fetch_resolutions.py`:

```python
"""Offline tests for scripts/fetch_resolutions.py — idempotency + unknown recording."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "fetch_resolutions",
    Path(__file__).resolve().parents[2] / "scripts" / "fetch_resolutions.py",
)
assert _SPEC and _SPEC.loader
fr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fr)


def _trades_dir(tmp_path: Path) -> Path:
    d = tmp_path / "trades"
    d.mkdir()
    rows = [
        {"conditionId": "0xres", "eventSlug": "e1", "asset": "a", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 1},
        {"conditionId": "0xopen", "eventSlug": "e2", "asset": "b", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 2},
        {"conditionId": "0xgone", "eventSlug": "e3", "asset": "c", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 3},
    ]
    (d / "0xaaa.json").write_text(json.dumps(rows), encoding="utf-8")
    return d


def _fake_markets(chunks_seen: list[list[str]]):
    def fake(ids: list[str], **_: object) -> list[dict]:
        chunks_seen.append(list(ids))
        out = []
        if "0xres" in ids:
            out.append({"conditionId": "0xres", "closed": True,
                        "outcomePrices": '["1", "0"]'})
        if "0xopen" in ids:
            out.append({"conditionId": "0xopen", "closed": False,
                        "outcomePrices": '["0.6", "0.4"]'})
        # 0xgone never comes back -> unknown
        return out

    return fake


def test_fetch_writes_records_and_unknown(tmp_path: Path) -> None:
    trades = _trades_dir(tmp_path)
    out = tmp_path / "resolutions.json"
    calls: list[list[str]] = []
    fr.run(trades, out, fetch_markets=_fake_markets(calls))
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["0xres"] == {"status": "resolved", "winning_index": 0}
    assert data["0xopen"]["status"] == "unresolved"
    assert data["0xgone"]["status"] == "unknown"


def test_second_run_without_refresh_fetches_nothing(tmp_path: Path) -> None:
    trades = _trades_dir(tmp_path)
    out = tmp_path / "resolutions.json"
    fr.run(trades, out, fetch_markets=_fake_markets([]))
    calls: list[list[str]] = []
    fr.run(trades, out, fetch_markets=_fake_markets(calls))
    assert calls == []  # everything already recorded


def test_refresh_refetches_only_non_final(tmp_path: Path) -> None:
    trades = _trades_dir(tmp_path)
    out = tmp_path / "resolutions.json"
    fr.run(trades, out, fetch_markets=_fake_markets([]))
    calls: list[list[str]] = []
    fr.run(trades, out, refresh=True, fetch_markets=_fake_markets(calls))
    refetched = {c for chunk in calls for c in chunk}
    assert refetched == {"0xopen", "0xgone"}  # resolved is final, never re-fetched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_fetch_resolutions.py -q`
Expected: FAIL — `FileNotFoundError` (script does not exist yet)

- [ ] **Step 3: Implement**

Create `scripts/fetch_resolutions.py`:

```python
"""Keyless: collect unique conditionIds from saved wallet trades -> Gamma resolutions.

Writes data/raw/resolutions.json: {conditionId: {"status": ..., "winning_index": ...}}.
Idempotent: RESOLVED/AMBIGUOUS records are final and never re-fetched; unresolved/unknown
are re-fetched only with --refresh. Network goes through the injectable
`fetch_markets_by_condition_ids` seam — monkeypatch in tests. No keys, no CU.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import structlog  # noqa: E402

from pat.analytics.resolution_pnl import AMBIGUOUS, RESOLVED, UNKNOWN, parse_resolution  # noqa: E402
from pat.venues.polymarket.gamma import fetch_markets_by_condition_ids  # noqa: E402

log = structlog.get_logger(__name__)

_FINAL_STATUSES = {RESOLVED, AMBIGUOUS}


def run(
    trades_dir: Path,
    out_path: Path,
    *,
    refresh: bool = False,
    fetch_markets: Any = None,
) -> Path:
    """Fetch resolution records for every conditionId in *trades_dir*; merge + save."""
    corr_id = str(uuid.uuid4())
    blog = log.bind(corr_id=corr_id, mode="backtest")

    conds: set[str] = set()
    for f in sorted(trades_dir.glob("0x*.json")):
        for t in json.loads(f.read_text(encoding="utf-8")):
            c = t.get("conditionId")
            if c:
                conds.add(str(c))

    existing: dict[str, dict[str, Any]] = {}
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))

    if refresh:
        todo = sorted(
            c for c in conds
            if c not in existing or existing[c]["status"] not in _FINAL_STATUSES
        )
    else:
        todo = sorted(c for c in conds if c not in existing)
    blog.info("resolutions.todo", total=len(conds), todo=len(todo), refresh=refresh)

    fm = fetch_markets or fetch_markets_by_condition_ids
    markets: list[dict[str, Any]] = fm(todo) if todo else []

    fetched: dict[str, dict[str, Any]] = {}
    for m in markets:
        rec = parse_resolution(m)
        cid = str(rec.pop("conditionId"))
        if cid:
            fetched[cid] = rec
    for c in todo:
        if c not in fetched and c not in existing:
            fetched[c] = {"status": UNKNOWN, "winning_index": None}

    merged = {**existing, **fetched}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=1, sort_keys=True), encoding="utf-8")

    counts: dict[str, int] = {}
    for rec in merged.values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    blog.info("resolutions.saved", out=str(out_path), **counts)
    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch Gamma resolutions for all saved wallet-trade conditionIds."
    )
    p.add_argument("--trades-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument("--out", type=Path, default=Path("data/raw/resolutions.json"))
    p.add_argument(
        "--refresh", action="store_true",
        help="Re-fetch unresolved/unknown entries (resolved entries are final).",
    )
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
    print(run(args.trades_dir, args.out, refresh=args.refresh))  # noqa: T201
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_fetch_resolutions.py -q`
Expected: 3 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add scripts/fetch_resolutions.py tests/scripts/test_fetch_resolutions.py
git commit -m "feat(scripts): idempotent keyless resolution fetcher (conditionId -> Gamma)"
```

---

### Task 6: `scripts/run_resolution_screen.py` (driver + report)

**Files:**
- Create: `scripts/run_resolution_screen.py`
- Test: `tests/scripts/test_run_resolution_screen.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_run_resolution_screen.py`:

```python
"""Offline tests for scripts/run_resolution_screen.py — report + verdict + jsonl."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "run_resolution_screen",
    Path(__file__).resolve().parents[2] / "scripts" / "run_resolution_screen.py",
)
assert _SPEC and _SPEC.loader
rrs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rrs)


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    trades_dir = tmp_path / "trades"
    trades_dir.mkdir()

    def _rows(cond: str, slug: str, price: str) -> list[dict]:
        return [
            {"conditionId": cond, "eventSlug": slug, "asset": f"tok-{cond}",
             "side": "BUY", "price": price, "size": "10", "outcomeIndex": 0,
             "timestamp": 1}
        ]

    # winner W1: one winning resolved event; winner W2: one losing event
    (trades_dir / "0xw1.json").write_text(
        json.dumps(_rows("0xc1", "ev-1", "0.4")), encoding="utf-8")
    (trades_dir / "0xw2.json").write_text(
        json.dumps(_rows("0xc2", "ev-2", "0.6")), encoding="utf-8")
    (trades_dir / "0xctl.json").write_text(
        json.dumps(_rows("0xc1", "ev-1", "0.5")), encoding="utf-8")
    (trades_dir / "_winners.json").write_text(
        json.dumps(["0xw1", "0xw2"]), encoding="utf-8")
    (trades_dir / "_control.json").write_text(json.dumps(["0xctl"]), encoding="utf-8")

    res_path = tmp_path / "resolutions.json"
    res_path.write_text(json.dumps({
        "0xc1": {"status": "resolved", "winning_index": 0},
        "0xc2": {"status": "resolved", "winning_index": 1},
    }), encoding="utf-8")
    return trades_dir, res_path


def test_run_writes_report_with_kill_verdict_and_jsonl(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)  # jsonl goes to ./logs/
    trades_dir, res_path = _setup(tmp_path)
    out = tmp_path / "report.md"
    rrs.run(trades_dir, res_path, out)
    md = out.read_text(encoding="utf-8")
    assert "KILL" in md  # 0 diversified < 5
    assert "n_diversified = 0" in md
    assert "0xw1" in md  # per-wallet winners table
    jsonl = (tmp_path / "logs" / "resolution_features.jsonl").read_text(encoding="utf-8")
    recs = [json.loads(line) for line in jsonl.strip().splitlines()]
    assert {r["wallet"] for r in recs} == {"0xw1", "0xw2", "0xctl"}
    assert {r["group"] for r in recs} == {"winner", "control"}


def test_missing_wallet_file_is_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    trades_dir, res_path = _setup(tmp_path)
    winners = json.loads((trades_dir / "_winners.json").read_text()) + ["0xghost"]
    (trades_dir / "_winners.json").write_text(json.dumps(winners), encoding="utf-8")
    out = tmp_path / "report.md"
    rrs.run(trades_dir, res_path, out)
    assert "0xghost" not in out.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_run_resolution_screen.py -q`
Expected: FAIL — `FileNotFoundError` (script does not exist yet)

- [ ] **Step 3: Implement**

Create `scripts/run_resolution_screen.py`:

```python
"""Resolution-grounded concentration screen (ADR 0021 Step 1) over saved wallet trades.

Reads data/raw/wallet_trades/ + data/raw/resolutions.json (both produced by earlier
scripts; fully offline here), computes per-wallet resolution metrics, renders the
winners-vs-control report and the PRE-REGISTERED kill verdict. Money = Decimal.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import structlog  # noqa: E402

from pat.analytics.resolution_pnl import (  # noqa: E402
    WalletResolutionMetrics,
    condition_pnls,
    screen_verdict,
    wallet_metrics,
)

log = structlog.get_logger(__name__)

_TABLE_FEATS = [
    "total_resolution_pnl", "n_conditions_resolved", "n_events_resolved",
    "n_events_positive", "top1_share", "n_frame_incomplete", "n_unresolved",
    "unresolved_exposure",
]


def _median_table(
    winners: list[WalletResolutionMetrics], control: list[WalletResolutionMetrics]
) -> str:
    lines = ["| Metric | Winners median | Control median |", "|---|---|---|"]
    for feat in _TABLE_FEATS:
        wv = [float(getattr(m, feat)) for m in winners]
        cv = [float(getattr(m, feat)) for m in control]
        w_med = f"{statistics.median(wv):.4f}" if wv else "n/a"
        c_med = f"{statistics.median(cv):.4f}" if cv else "n/a"
        lines.append(f"| {feat} | {w_med} | {c_med} |")
    return "\n".join(lines)


def _winners_table(winners: list[WalletResolutionMetrics]) -> str:
    lines = [
        "| Wallet | resolution P&L | events+ | top1 | frame-inc | unresolved | div? |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in sorted(winners, key=lambda m: m.total_resolution_pnl, reverse=True):
        lines.append(
            f"| {m.wallet} | {m.total_resolution_pnl:.2f} | {m.n_events_positive} "
            f"| {m.top1_share:.2f} | {m.n_frame_incomplete} | {m.n_unresolved} "
            f"| {'YES' if m.diversified else 'no'} |"
        )
    return "\n".join(lines)


def render_report(
    winners: list[WalletResolutionMetrics],
    control: list[WalletResolutionMetrics],
) -> str:
    n_div, killed = screen_verdict(winners)
    lines = ["# Resolution-Grounded Concentration Screen — Results", ""]
    lines.append(
        f"**Frame:** {len(winners)} winners / {len(control)} control; gate defined on the "
        "50-winner frame (ADR 0021). Resolution P&L = trades cashflow + redemption at the "
        "actual outcome; RESOLVED markets only (no curPrice in the gate)."
    )
    lines.append("")
    if killed:
        lines.append(
            f"## VERDICT: KILL — n_diversified = {n_div} < 5\n\n"
            "Branch (B) CLOSES per the pre-registered ADR 0021 criterion: no "
            "non-survivorship build; C1 archived via follow-up ADR. Focus -> A2."
        )
    else:
        lines.append(
            f"## VERDICT: PASS — n_diversified = {n_div} >= 5\n\n"
            "The expensive half of branch (B) is justified: build the non-survivorship "
            "sample + persistence test (ADR 0021 Step 3)."
        )
    lines.append("")
    lines.append("## Winners vs Control (medians)")
    lines.append("")
    lines.append(_median_table(winners, control))
    lines.append("")
    lines.append("## Per-winner metrics")
    lines.append("")
    lines.append(_winners_table(winners))
    lines.append("")
    lines.append(
        "> **Caveats (binding):** all-time-PnL survivorship frame (ADR 0020); "
        "recent-2000 trade window -> frame_incomplete/unresolved counters show how much "
        "the window hides. The diversified flag is a screen, not an edge claim."
    )
    return "\n".join(lines)


def run(trades_dir: Path, resolutions_path: Path, out_path: Path) -> Path:
    resolutions: dict[str, dict[str, Any]] = json.loads(
        resolutions_path.read_text(encoding="utf-8")
    )
    winners_addrs: list[str] = json.loads(
        (trades_dir / "_winners.json").read_text(encoding="utf-8")
    )
    control_addrs: list[str] = json.loads(
        (trades_dir / "_control.json").read_text(encoding="utf-8")
    )

    def _metrics(addrs: list[str]) -> list[WalletResolutionMetrics]:
        out: list[WalletResolutionMetrics] = []
        for w in addrs:
            f = trades_dir / f"{w}.json"
            if not f.exists():
                log.warning("wallet.file_missing", wallet=w)
                continue
            trades = json.loads(f.read_text(encoding="utf-8"))
            out.append(wallet_metrics(w, condition_pnls(trades, resolutions)))
        return out

    win, ctrl = _metrics(winners_addrs), _metrics(control_addrs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(win, ctrl), encoding="utf-8")

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    with (logs_dir / "resolution_features.jsonl").open("w", encoding="utf-8") as fh:
        for group, rows in (("winner", win), ("control", ctrl)):
            for m in rows:
                fh.write(
                    json.dumps({**m.model_dump(mode="json"), "group": group}) + "\n"
                )
    n_div, killed = screen_verdict(win)
    log.info("screen.written", out=str(out_path), n_diversified=n_div, killed=killed)
    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Resolution-grounded concentration screen (ADR 0021 Step 1)."
    )
    p.add_argument("--trades-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument("--resolutions", type=Path, default=Path("data/raw/resolutions.json"))
    p.add_argument(
        "--out", type=Path,
        default=Path("docs/research/2026-06-10-resolution-screen.md"),
    )
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
    print(run(args.trades_dir, args.resolutions, args.out))  # noqa: T201
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_run_resolution_screen.py -q`
Expected: 2 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add scripts/run_resolution_screen.py tests/scripts/test_run_resolution_screen.py
git commit -m "feat(scripts): resolution screen driver with pre-registered kill verdict"
```

---

### Task 7: S5 — `n_tokens` counts markets (conditionId), not assets

**Files:**
- Modify: `src/pat/analytics/wallet_features.py`
- Test: `tests/analytics/test_wallet_features.py` (append)

**Background:** S5 (spec 2026-06-09 §19) — a binary market has 2 outcome tokens; counting
assets double-counts breadth. `n_tokens` becomes "unique markets" (conditionId when
available, token_id fallback for the on-chain path). IMPORTANT: `flip_rate` and
`positive_token_fraction` keep their original per-token-group denominators — grouping
both outcome tokens of one condition would fabricate flips (buy YES + sell NO is NOT a
round-trip on one token). Only the breadth metric changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/analytics/test_wallet_features.py`:

```python
def test_s5_n_tokens_counts_markets_by_condition_id() -> None:
    trades = [
        {"asset": "tokYES", "side": "BUY", "price": "0.6", "size": "10",
         "timestamp": 100, "is_maker": False, "conditionId": "0xc1"},
        {"asset": "tokNO", "side": "BUY", "price": "0.5", "size": "10",
         "timestamp": 200, "is_maker": False, "conditionId": "0xc1"},
    ]
    fills = wallet_fills_from_trades(trades)
    assert all(f.condition_id == "0xc1" for f in fills)
    f = compute_wallet_features("0xw", fills, {})
    assert f.n_tokens == 1  # one MARKET, even though two assets


def test_s5_flip_rate_denominator_stays_per_token_group() -> None:
    # tokA is flipped (balanced buy+sell), tokB is buy-only; same condition.
    trades = [
        {"asset": "tokA", "side": "BUY", "price": "0.4", "size": "10",
         "timestamp": 100, "is_maker": False, "conditionId": "0xc1"},
        {"asset": "tokA", "side": "SELL", "price": "0.6", "size": "10",
         "timestamp": 200, "is_maker": False, "conditionId": "0xc1"},
        {"asset": "tokB", "side": "BUY", "price": "0.5", "size": "10",
         "timestamp": 300, "is_maker": False, "conditionId": "0xc1"},
    ]
    f = compute_wallet_features("0xw", wallet_fills_from_trades(trades), {})
    assert f.n_tokens == 1          # market breadth (S5)
    assert f.flip_rate == 0.5       # flips / token groups — UNCHANGED denominator


def test_s5_on_chain_fills_without_condition_fall_back_to_token_id() -> None:
    from decimal import Decimal as D

    from pat.core.types import Side

    fills = [
        WalletFill(token_id="a", side=Side.BUY, price=D("0.4"), size=D("1"),
                   block=1, is_maker=False, cashflow=D("-0.4")),
        WalletFill(token_id="b", side=Side.BUY, price=D("0.4"), size=D("1"),
                   block=2, is_maker=False, cashflow=D("-0.4")),
    ]
    f = compute_wallet_features("0xw", fills, {})
    assert f.n_tokens == 2
```

(Imports of `wallet_fills_from_trades`, `compute_wallet_features`, `WalletFill` already
exist at the top of this test file — extend the existing import line if any name is
missing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analytics/test_wallet_features.py -q`
Expected: FAIL — `WalletFill` has no field `condition_id` / `n_tokens == 2 != 1`

- [ ] **Step 3: Implement**

In `src/pat/analytics/wallet_features.py`:

(a) Add the field to `WalletFill` (after `cashflow`):

```python
class WalletFill(BaseModel):
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    block: int
    is_maker: bool
    cashflow: Decimal  # BUY -> negative (USDC out); SELL -> positive (USDC in)
    condition_id: str | None = None  # market id (S5); None on the on-chain path
```

(b) In `wallet_fills_from_trades`, populate it — add to the `WalletFill(` constructor
call:

```python
                condition_id=(str(t["conditionId"]) if t.get("conditionId") else None),
```

(c) In `compute_wallet_features`, replace the line `n_tokens = len(by_token)` with:

```python
    # S5: breadth = unique MARKETS (conditionId when present, token_id fallback).
    n_tokens = len({f.condition_id or f.token_id for f in fills})
    n_token_groups = len(by_token)
```

and replace the two per-token-denominator usages so they keep the OLD denominator:
`flip_rate=flips / n_tokens,` becomes `flip_rate=flips / n_token_groups,` and
`positive_token_fraction=len(positive) / n_tokens,` becomes
`positive_token_fraction=len(positive) / n_token_groups,`.

(d) Update the docstring of `compute_wallet_features` — append one line:

```
    n_tokens counts unique markets (condition_id or token_id fallback, S5); flip_rate
    and positive_token_fraction keep per-token-group denominators.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analytics/ -q`
Expected: all passed (existing lean-screen tests must stay green — they use one asset
per condition or no condition_id, so n_tokens is unchanged for them).

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add src/pat/analytics/wallet_features.py tests/analytics/test_wallet_features.py
git commit -m "feat(analytics): S5 - n_tokens counts markets by conditionId"
```

---

### Task 8: `scripts/spot_check_trades.py` (I13 trust step, CU-capped)

**Files:**
- Create: `scripts/spot_check_trades.py`
- Test: `tests/scripts/test_spot_check_trades.py` (create)

**Background:** Verify data-api `/trades` rows against the chain: for sampled rows, fetch
the transaction receipt by `transactionHash` (POINT lookup ≈ 15 CU on Alchemy — never
range `getLogs`, which exploded in ADR 0020), decode `OrderFilled` logs with the existing
`pat.data.polymarket_on_chain.decode_v2_orderfilled`, and match price/size/side/asset.
Claim I12 (verified): `proxyWallet` IS the on-chain maker/taker address. Hard cap
`_MAX_RECEIPTS = 40` per run (CU rail; ~40 × 15 CU ≈ 600 CU ≈ $0.0003).

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_spot_check_trades.py`:

```python
"""Offline tests for scripts/spot_check_trades.py — fixture receipts, no network."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "spot_check_trades",
    Path(__file__).resolve().parents[2] / "scripts" / "spot_check_trades.py",
)
assert _SPEC and _SPEC.loader
sct = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sct)

from pat.data.polymarket_on_chain import TOPIC0_ORDERFILLED  # noqa: E402

_WALLET = "0x" + "ab" * 20
_OTHER = "0x" + "cd" * 20


def _word(v: int) -> str:
    return f"{v:064x}"


def _addr_topic(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:]


def _receipt(tx: str, *, side: int, token_id: int, maker_amt: int, taker_amt: int,
             maker: str, taker: str) -> dict:
    data = "0x" + _word(side) + _word(token_id) + _word(maker_amt) + _word(taker_amt) \
        + _word(0) + _word(0) + _word(0)
    return {"logs": [{
        "topics": [TOPIC0_ORDERFILLED, "0x" + "11" * 32,
                   _addr_topic(maker), _addr_topic(taker)],
        "data": data,
        "transactionHash": tx,
        "blockNumber": "0x10",
    }]}


def _trade(tx: str, *, side: str = "BUY", price: str = "0.4", size: str = "10",
           ts: int = 100) -> dict:
    return {"transactionHash": tx, "asset": "777", "side": side, "price": price,
            "size": size, "timestamp": ts}


def test_matching_taker_buy_counts_as_match() -> None:
    # wallet is TAKER and BUYS 10 @ 0.4 -> on-chain order side=1 (maker SELLS),
    # maker_amt = shares (10e6), taker_amt = USDC (4e6)
    receipts = {"0xt1": _receipt("0xt1", side=1, token_id=777, maker_amt=10_000_000,
                                 taker_amt=4_000_000, maker=_OTHER, taker=_WALLET)}
    res = sct.check_wallet(
        _WALLET, [_trade("0xt1")], "http://rpc",
        get_receipt=lambda _u, h: receipts[h],
    )
    assert res["n_checked"] == 1
    assert res["n_matched"] == 1
    assert res["mismatches"] == []


def test_size_mismatch_is_recorded() -> None:
    receipts = {"0xt1": _receipt("0xt1", side=1, token_id=777, maker_amt=9_000_000,
                                 taker_amt=4_000_000, maker=_OTHER, taker=_WALLET)}
    res = sct.check_wallet(
        _WALLET, [_trade("0xt1")], "http://rpc",
        get_receipt=lambda _u, h: receipts[h],
    )
    assert res["n_matched"] == 0
    assert len(res["mismatches"]) == 1


def test_receipt_cap_limits_lookups() -> None:
    calls: list[str] = []

    def fake(_u: str, h: str) -> dict:
        calls.append(h)
        return _receipt(h, side=1, token_id=777, maker_amt=10_000_000,
                        taker_amt=4_000_000, maker=_OTHER, taker=_WALLET)

    trades = [_trade(f"0xt{i}", ts=i) for i in range(60)]
    res = sct.check_wallet(_WALLET, trades, "http://rpc", n_sample=60, get_receipt=fake)
    assert len(calls) <= sct._MAX_RECEIPTS
    assert res["n_checked"] <= sct._MAX_RECEIPTS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_spot_check_trades.py -q`
Expected: FAIL — `FileNotFoundError` (script does not exist yet)

- [ ] **Step 3: Implement**

Create `scripts/spot_check_trades.py`:

```python
"""On-chain spot-check of data-api /trades rows (claim I13 trust step).

POINT lookups only: eth_getTransactionReceipt per saved trade's transactionHash.
NEVER range getLogs here — that exploded on active wallets (ADR 0020). Hard cap
_MAX_RECEIPTS per run is the CU rail (~40 x 15 CU ~ 600 CU ~ $0.0003 on Alchemy PAYG).

Reads POLYGON_RPC_URL from the environment (or --rpc-url). Report-only: prints a
match-rate per wallet; the human upgrades claim I13 in docs/research/claims-verification.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx  # noqa: E402
import structlog  # noqa: E402

from pat.data.polymarket_history import price_and_size  # noqa: E402
from pat.data.polymarket_on_chain import decode_v2_orderfilled  # noqa: E402

log = structlog.get_logger(__name__)

_MAX_RECEIPTS = 40  # hard CU rail per run
_PRICE_TOL = Decimal("0.005")  # data-api rounds; on-chain is 6-dp fixed point
_SIZE_TOL = Decimal("0.01")
_REQUEST_TIMEOUT = 30  # seconds


def _rpc_get_receipt(rpc_url: str, tx_hash: str) -> dict[str, Any]:
    """eth_getTransactionReceipt. The ONLY wire-touching function — monkeypatch in tests."""
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getTransactionReceipt", "params": [tx_hash],
    }
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.post(rpc_url, json=payload)
        response.raise_for_status()
        body = response.json()
    if "error" in body:
        raise RuntimeError(f"JSON-RPC error: {body['error']}")
    result: dict[str, Any] = body["result"]
    return result


def _row_matches_log(wallet: str, trade: dict[str, Any], dec: dict[str, Any]) -> bool:
    """One decoded OrderFilled log vs one data-api row: asset, role, side, price, size."""
    if dec["tokenId"] != str(trade["asset"]):
        return False
    w = wallet.lower()
    is_maker = dec["maker"].lower() == w
    is_taker = dec["taker"].lower() == w
    if not (is_maker or is_taker):
        return False
    maker_buys = int(dec["side"]) == 0
    wallet_buys = maker_buys if is_maker else (not maker_buys)
    row_buys = str(trade["side"]).upper() == "BUY"
    if wallet_buys != row_buys:
        return False
    price, size = price_and_size(dec)
    return (
        abs(price - Decimal(str(trade["price"]))) <= _PRICE_TOL
        and abs(size - Decimal(str(trade["size"]))) <= _SIZE_TOL
    )


def check_wallet(
    wallet: str,
    trades: list[dict[str, Any]],
    rpc_url: str,
    *,
    n_sample: int = 15,
    get_receipt: Any = None,
) -> dict[str, Any]:
    """Sample the most recent *n_sample* rows; verify each against its tx receipt."""
    gr = get_receipt or _rpc_get_receipt
    sample = sorted(trades, key=lambda t: int(str(t["timestamp"])), reverse=True)
    sample = sample[: min(n_sample, _MAX_RECEIPTS)]

    receipt_cache: dict[str, dict[str, Any]] = {}
    matched = 0
    mismatches: list[dict[str, Any]] = []
    n_checked = 0
    for t in sample:
        tx = str(t["transactionHash"])
        if tx not in receipt_cache:
            if len(receipt_cache) >= _MAX_RECEIPTS:
                log.warning("spot_check.receipt_cap_hit", cap=_MAX_RECEIPTS)
                break
            receipt_cache[tx] = gr(rpc_url, tx)
        n_checked += 1
        decoded = []
        for lg in receipt_cache[tx].get("logs", []):
            if not lg.get("topics"):
                continue
            d = decode_v2_orderfilled(lg)
            if d is not None:
                decoded.append(d)
        if any(_row_matches_log(wallet, t, d) for d in decoded):
            matched += 1
        else:
            mismatches.append({"tx": tx, "asset": t["asset"], "side": t["side"],
                               "price": t["price"], "size": t["size"]})
    return {
        "wallet": wallet, "n_checked": n_checked, "n_matched": matched,
        "mismatches": mismatches,
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Spot-check data-api /trades vs on-chain receipts (I13 trust step)."
    )
    p.add_argument("--trades-dir", type=Path, default=Path("data/raw/wallet_trades"))
    p.add_argument(
        "--wallets", nargs="*", default=None,
        help="Addresses to check (default: first winner + first control).",
    )
    p.add_argument("--n-sample", type=int, default=15)
    p.add_argument("--rpc-url", default=os.environ.get("POLYGON_RPC_URL", ""))
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
    if not args.rpc_url:
        print("POLYGON_RPC_URL not set and --rpc-url missing")  # noqa: T201
        sys.exit(2)
    wallets = args.wallets
    if not wallets:
        winners = json.loads(
            (args.trades_dir / "_winners.json").read_text(encoding="utf-8"))
        control = json.loads(
            (args.trades_dir / "_control.json").read_text(encoding="utf-8"))
        wallets = [winners[0], control[0]]
    for w in wallets:
        rows = json.loads((args.trades_dir / f"{w}.json").read_text(encoding="utf-8"))
        res = check_wallet(w, rows, args.rpc_url, n_sample=args.n_sample)
        rate = res["n_matched"] / res["n_checked"] if res["n_checked"] else 0.0
        log.info("spot_check.result", wallet=w, n_checked=res["n_checked"],
                 n_matched=res["n_matched"], match_rate=round(rate, 3))
        print(f"{w}: {res['n_matched']}/{res['n_checked']} matched "  # noqa: T201
              f"({rate:.0%}); mismatches: {res['mismatches']}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_spot_check_trades.py -q`
Expected: 3 passed

- [ ] **Step 5: Full gates + commit**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`

```bash
git add scripts/spot_check_trades.py tests/scripts/test_spot_check_trades.py
git commit -m "feat(scripts): on-chain spot-check of data-api trades via tx receipts"
```

---

### Task 9: Operational run + verdict ADR (controller/user, not a subagent)

**Files:**
- Create (generated): `data/raw/resolutions.json`, `docs/research/2026-06-10-resolution-screen.md`, `logs/resolution_features.jsonl`
- Create: `docs/decisions/0022-<outcome>.md` (number = next free)
- Modify: `docs/research/claims-verification.md` (I13), `docs/HANDOFF.md`, `docs/roadmap.md`

- [ ] **Step 1: Fetch resolutions (keyless, ~180 Gamma requests)**

Run: `uv run python scripts/fetch_resolutions.py`
Expected: prints `data/raw/resolutions.json`; structlog shows per-status counts.
Sanity: `resolved` should dominate (most saved markets are old enough).

- [ ] **Step 2: Run the screen**

Run: `uv run python scripts/run_resolution_screen.py`
Expected: prints the report path; report contains the VERDICT line (KILL or PASS) and
per-winner table.

- [ ] **Step 3: Adversarial review before trusting the verdict**

Dispatch `quant-researcher` with the report + `logs/resolution_features.jsonl` + the spec
(`docs/superpowers/specs/2026-06-10-approach2-resolution-pnl-design.md`) and ask:
"Does the data support the verdict under the PRE-REGISTERED gates? Any artifact
(frame_incomplete share, unknown share, ambiguous share) large enough to invalidate the
screen?" Do NOT write the ADR until sign-off.

- [ ] **Step 4: User runs the spot-check (needs POLYGON_RPC_URL)**

User runs: `uv run python scripts/spot_check_trades.py`
Expected: two lines `0x...: N/M matched (..%)`. On match-rate ≈ 100% → update I13 in
`docs/research/claims-verification.md` (PARTIAL → VERIFIED, citing the spot-check). On
mismatches → investigate before trusting any /trades-derived number.

- [ ] **Step 5: Record the verdict ADR + update docs**

Write `docs/decisions/0022-resolution-screen-verdict.md` (next free number; use
`docs/decisions/_template.md`): the kill-criterion outcome, n_diversified, artifact
shares, and the Step-3 consequence (KILL → archive C1, focus A2; PASS → schedule the
non-survivorship build). Update `docs/HANDOFF.md` ("Next action") and `docs/roadmap.md`
(Phase-2 gate paragraph) to the outcome. Commit the report + data + ADR + doc updates:

```bash
git add data/raw/resolutions.json docs/research/2026-06-10-resolution-screen.md \
  docs/decisions/0022-resolution-screen-verdict.md docs/research/claims-verification.md \
  docs/HANDOFF.md docs/roadmap.md
git commit -m "analytics: resolution screen verdict (ADR 0022) + I13 spot-check"
```

---

## Self-review notes (done at plan-writing time)

- **Spec coverage:** §3 components → Tasks 1/5/6; §4 formulas → Tasks 3/4 (every formula
  has a test); §5 error handling → Tasks 1 (split/skip), 3 (row skip), 5 (unknown);
  §6 test list → Tasks 1–8; §7 spot-check → Task 8; S5 → Task 7; operational + ADR → Task 9.
- **Frozen-gate guard:** `_MIN_POSITIVE_EVENTS`, `_MAX_TOP1_SHARE`, `_KILL_MIN_DIVERSIFIED`
  are module constants with spec references — reviewers must reject any change to them.
- **Known non-goals:** no curPrice in the gate; no non-survivorship build; no A2 work.
