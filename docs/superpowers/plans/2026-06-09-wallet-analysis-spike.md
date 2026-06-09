# Wallet-Analysis Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Classify the top-50 Polymarket wallets (by leaderboard P&L) into behavioral archetypes from
their on-chain `OrderFilled` history, contrast vs a control group, and emit a ranked recommendation
for the next strategy (per spec `docs/superpowers/specs/2026-06-09-wallet-analysis-spike-design.md`).

**Architecture:** Pure, offline-testable analytics (`derive_wallet_fills` → `compute_wallet_features`
→ `classify`) fed by two network seams: a keyless leaderboard/data-api client (AI may run) and the
existing Alchemy `eth_getLogs` fetcher (USER runs — key isolation). A measure-first V1 gate decides
whether to build a V1 decoder before computing features.

**Tech Stack:** Python 3.11, `uv`, `pytest`, `ruff`, `mypy`, `pydantic`, `httpx`, `structlog`, `Decimal`.

**Conventions (binding):** money in `Decimal` (float only for ratios/scores). Network I/O only in
named seam functions (monkeypatched in tests). structlog + correlation-id in drivers. NO
`Co-Authored-By` trailer. 🔴 Never read `.env`/keys — the USER runs the Alchemy fetch.

---

## File structure

| File | Responsibility |
|---|---|
| `src/pat/venues/polymarket/leaderboard.py` (new) | keyless data-api leaderboard client + parse → ranked `proxyWallet` list |
| `src/pat/data/wallet_history.py` (new) | wallet→topic encoder; maker∪taker merge/dedup |
| `src/pat/data/polymarket_history.py` (modify) | promote `_price_and_size` → public `price_and_size` |
| `src/pat/analytics/wallet_features.py` (new) | `WalletFill`, `derive_wallet_fills`, `WalletFeatures`, `compute_wallet_features`, `is_skill_cohort`, `copyability_proxy` |
| `src/pat/analytics/wallet_archetype.py` (new) | archetype constants + `classify` |
| `src/pat/analytics/wallet_control.py` (new) | `sample_control_wallets` (median-activity from existing raw JSON) |
| `scripts/fetch_wallet_histories.py` (new) | leaderboard → 4-exchange maker∪taker `eth_getLogs` → save per-wallet raw; V1/V2 topic0 histogram (the gate) |
| `scripts/run_wallet_analysis.py` (new) | load saved raw → data-api marks → features → classify → report |
| `tests/...` mirrors each module | offline unit tests (seams monkeypatched) |

**Conditional (only if the V1 gate fires, §Task 10):** `src/pat/data/polymarket_on_chain.py` gains
`decode_v1_orderfilled`.

---

## Task 1: Leaderboard client

**Files:**
- Create: `src/pat/venues/polymarket/leaderboard.py`
- Test: `tests/venues/polymarket/test_leaderboard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/venues/polymarket/test_leaderboard.py
from __future__ import annotations

from decimal import Decimal

from pat.venues.polymarket.leaderboard import LeaderEntry, parse_leaderboard

# A redacted real-shaped data-api /v1/leaderboard page (I11 sample, 2026-06-09).
_RAW_PAGE = [
    {"rank": "1", "proxyWallet": "0x2CFF41636FE21FAD120FED603D54D4FDD96259DB",
     "userName": "ThisAgain", "vol": 2008.34, "pnl": 441640.87},
    {"rank": "2", "proxyWallet": "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
     "userName": "Theo4", "vol": 0.0, "pnl": 408000.0},
]


def test_parse_leaderboard_extracts_lowercased_addr_and_decimal_pnl() -> None:
    entries = parse_leaderboard(_RAW_PAGE)
    assert entries == [
        LeaderEntry(rank=1, wallet="0x2cff41636fe21fad120fed603d54d4fdd96259db",
                    user_name="ThisAgain", vol=Decimal("2008.34"), pnl=Decimal("441640.87")),
        LeaderEntry(rank=2, wallet="0x56687bf447db6ffa42ffe2204a05edaa20f55839",
                    user_name="Theo4", vol=Decimal("0.0"), pnl=Decimal("408000.0")),
    ]


def test_parse_leaderboard_skips_rows_without_proxywallet() -> None:
    assert parse_leaderboard([{"rank": "9", "userName": "ghost"}]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/venues/polymarket/test_leaderboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.venues.polymarket.leaderboard'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/pat/venues/polymarket/leaderboard.py
"""Keyless data-api leaderboard client — the SAMPLING FRAME for wallet analysis (claim I11).

GET data-api.polymarket.com/v1/leaderboard returns a `proxyWallet` (0x) per ranked trader.
The `pnl` field's exact definition is undocumented (I11 PARTIAL) → used as a frame only, never
as verdict input. Network isolation: `_leaderboard_get_page` is the ONLY wire-touching function.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

DATA_API = "https://data-api.polymarket.com"
_REQUEST_TIMEOUT = 30  # seconds — explicit to satisfy ruff S113
_PAGE_MAX = 50  # data-api caps limit at 50

log = structlog.get_logger(__name__)


class LeaderEntry(BaseModel):
    rank: int
    wallet: str  # proxyWallet, lowercased (== on-chain maker/taker, claim I12)
    user_name: str
    vol: Decimal
    pnl: Decimal


def parse_leaderboard(raw: list[dict[str, Any]]) -> list[LeaderEntry]:
    """Extract LeaderEntry rows; skip rows lacking a proxyWallet. Address lowercased."""
    out: list[LeaderEntry] = []
    for row in raw:
        addr = row.get("proxyWallet")
        if not addr:
            continue
        out.append(
            LeaderEntry(
                rank=int(row.get("rank", 0)),
                wallet=str(addr).lower(),
                user_name=str(row.get("userName", "")),
                vol=Decimal(str(row.get("vol", "0"))),
                pnl=Decimal(str(row.get("pnl", "0"))),
            )
        )
    return out


def _leaderboard_get_page(
    *, time_period: str, order_by: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    """Fetch ONE leaderboard page (keyless). The ONLY wire-touching function — monkeypatch in tests."""
    params = {
        "timePeriod": time_period, "orderBy": order_by,
        "limit": limit, "offset": offset, "category": "OVERALL",
    }
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{DATA_API}/v1/leaderboard", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def fetch_leaderboard(
    *,
    time_period: str = "ALL",
    order_by: str = "PNL",
    top_n: int = 50,
    get_page: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[LeaderEntry]:
    """Return the top-N ranked entries (paging the data-api, max 50/page)."""
    fetch = get_page or _leaderboard_get_page
    out: list[LeaderEntry] = []
    offset = 0
    while len(out) < top_n:
        page = fetch(
            time_period=time_period, order_by=order_by,
            limit=min(_PAGE_MAX, top_n - len(out)), offset=offset,
        )
        if not page:
            break
        out.extend(parse_leaderboard(page))
        offset += _PAGE_MAX
    log.info("leaderboard.fetched", n=len(out[:top_n]), time_period=time_period, order_by=order_by)
    return out[:top_n]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/venues/polymarket/test_leaderboard.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pat/venues/polymarket/leaderboard.py tests/venues/polymarket/test_leaderboard.py
git commit -m "feat(venues): data-api leaderboard client (sampling frame, I11)"
```

---

## Task 2: Wallet history helpers (topic encoder + maker∪taker merge)

**Files:**
- Create: `src/pat/data/wallet_history.py`
- Test: `tests/data/test_wallet_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/data/test_wallet_history.py
from __future__ import annotations

from pat.data.wallet_history import merge_maker_taker, wallet_to_topic


def test_wallet_to_topic_left_pads_to_32_bytes_lowercase() -> None:
    addr = "0x2CFF41636FE21FAD120FED603D54D4FDD96259DB"
    assert wallet_to_topic(addr) == "0x" + "0" * 24 + "2cff41636fe21fad120fed603d54d4fdd96259db"


def test_merge_maker_taker_dedups_by_tx_and_logindex() -> None:
    a = {"transactionHash": "0xaa", "logIndex": "0x1", "data": "m"}
    b = {"transactionHash": "0xaa", "logIndex": "0x2", "data": "t"}
    dup = {"transactionHash": "0xaa", "logIndex": "0x1", "data": "m"}  # same key as a
    merged = merge_maker_taker([a], [b, dup])
    # a and b survive (distinct keys); dup of a is dropped
    keys = {(e["transactionHash"], e["logIndex"]) for e in merged}
    assert keys == {("0xaa", "0x1"), ("0xaa", "0x2")}
    assert len(merged) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/data/test_wallet_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.data.wallet_history'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/pat/data/wallet_history.py
"""Per-wallet on-chain history helpers: address→topic encoding and maker∪taker merge.

Polymarket V2/V1 OrderFilled index maker at topics[2] and taker at topics[3] (claims I8/I12).
To get a wallet's full activity we run TWO topic-filtered eth_getLogs passes (maker, then taker)
and merge them, deduping by (transactionHash, logIndex). Pure: no network here.
"""

from __future__ import annotations

from typing import Any


def wallet_to_topic(address: str) -> str:
    """Left-pad a 20-byte address to a 32-byte topic (lowercased), as eth_getLogs expects."""
    raw = address.lower().removeprefix("0x")
    return "0x" + raw.rjust(64, "0")


def merge_maker_taker(
    maker_logs: list[dict[str, Any]], taker_logs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union the two passes, deduping by (transactionHash, logIndex)."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in (*maker_logs, *taker_logs):
        key = (str(entry.get("transactionHash")), str(entry.get("logIndex")))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/data/test_wallet_history.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pat/data/wallet_history.py tests/data/test_wallet_history.py
git commit -m "feat(data): wallet topic encoder + maker-taker merge/dedup"
```

---

## Task 3: Promote `price_and_size` + derive per-wallet fills

**Files:**
- Modify: `src/pat/data/polymarket_history.py:36` (rename `_price_and_size` → `price_and_size`; update the caller at line 87)
- Create: `src/pat/analytics/wallet_features.py` (the `WalletFill` + `derive_wallet_fills` part)
- Test: `tests/analytics/test_wallet_features.py`

- [ ] **Step 1: Promote the price helper (refactor, keep tests green first)**

In `src/pat/data/polymarket_history.py` rename `def _price_and_size(` → `def price_and_size(`
and change its one caller (in `parse_orderfilled`) from `_price_and_size(ev)` to `price_and_size(ev)`.
Run: `uv run pytest tests/data/ -q` → Expected: PASS (no behavior change).

- [ ] **Step 2: Write the failing test**

```python
# tests/analytics/test_wallet_features.py
from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_features import WalletFill, derive_wallet_fills
from pat.core.types import Side

W = "0x" + "11" * 20  # the wallet under analysis
OTHER = "0x" + "22" * 20


def _ev(*, side: int, token: str, maker_amt: int, taker_amt: int,
        maker: str, taker: str, block: int) -> dict:
    """A decoded-event dict shaped like decode_v2_orderfilled output (6-dp amounts)."""
    maker_asset, taker_asset = ("0", token) if side == 0 else (token, "0")
    return {
        "makerAssetId": maker_asset, "takerAssetId": taker_asset,
        "makerAmountFilled": maker_amt, "takerAmountFilled": taker_amt,
        "maker": maker, "taker": taker, "side": side, "tokenId": token,
        "blockNumber": block, "transactionHash": "0xtx",
    }


def test_derive_wallet_buy_as_maker() -> None:
    # side=0 BUY: maker gives USDC 2.5 for shares 5 -> price 0.5; wallet is maker -> BUY.
    ev = _ev(side=0, token="7", maker_amt=2_500_000, taker_amt=5_000_000,
             maker=W, taker=OTHER, block=100)
    fills = derive_wallet_fills([ev], W)
    assert fills == [WalletFill(token_id="7", side=Side.BUY, price=Decimal("0.5"),
                                size=Decimal("5"), block=100, is_maker=True,
                                cashflow=Decimal("-2.5"))]


def test_derive_wallet_buy_as_taker_when_other_is_maker_seller() -> None:
    # side=1 SELL means the MAKER sells; the wallet is taker -> wallet BUYS. shares 5, USDC 2.5.
    ev = _ev(side=1, token="7", maker_amt=5_000_000, taker_amt=2_500_000,
             maker=OTHER, taker=W, block=101)
    fills = derive_wallet_fills([ev], W)
    assert fills[0].side is Side.BUY
    assert fills[0].is_maker is False
    assert fills[0].cashflow == Decimal("-2.5")  # bought -> USDC out


def test_derive_wallet_skips_events_where_wallet_is_neither_leg() -> None:
    ev = _ev(side=0, token="7", maker_amt=1_000_000, taker_amt=2_000_000,
             maker=OTHER, taker="0x" + "33" * 20, block=102)
    assert derive_wallet_fills([ev], W) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/analytics/test_wallet_features.py -v`
Expected: FAIL — `ImportError: cannot import name 'WalletFill'`.

- [ ] **Step 4: Write minimal implementation**

```python
# src/pat/analytics/wallet_features.py
"""Per-wallet behavioral features from decoded OrderFilled events (lean, on-chain only).

`derive_wallet_fills` projects each decoded event onto the wallet's perspective (BUY/SELL,
price, size, cashflow). `compute_wallet_features` (next task) aggregates them. Money = Decimal.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from pat.core.types import Side
from pat.data.polymarket_history import price_and_size


class WalletFill(BaseModel):
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    block: int
    is_maker: bool
    cashflow: Decimal  # BUY -> negative (USDC out); SELL -> positive (USDC in)


def derive_wallet_fills(events: list[dict[str, object]], wallet: str) -> list[WalletFill]:
    """Project decoded events onto *wallet*'s perspective. Skips events not involving the wallet.

    side==0 (BUY order): maker gives USDC -> maker BUYS the token; taker SELLS.
    side==1 (SELL order): maker gives shares -> maker SELLS the token; taker BUYS.
    """
    w = wallet.lower()
    out: list[WalletFill] = []
    for ev in events:
        maker = str(ev.get("maker", "")).lower()
        taker = str(ev.get("taker", "")).lower()
        is_maker = maker == w
        is_taker = taker == w
        if not (is_maker or is_taker):
            continue
        side_int = int(str(ev["side"]))
        maker_buys = side_int == 0
        wallet_buys = maker_buys if is_maker else (not maker_buys)
        price, size = price_and_size(ev)
        if size == 0:
            continue
        side = Side.BUY if wallet_buys else Side.SELL
        cashflow = (-price * size) if wallet_buys else (price * size)
        out.append(
            WalletFill(
                token_id=str(ev["tokenId"]), side=side, price=price, size=size,
                block=int(str(ev["blockNumber"])), is_maker=is_maker, cashflow=cashflow,
            )
        )
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/analytics/test_wallet_features.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/pat/data/polymarket_history.py src/pat/analytics/wallet_features.py tests/analytics/test_wallet_features.py
git commit -m "feat(analytics): per-wallet fill derivation (buy/sell/cashflow) + public price_and_size"
```

---

## Task 4: Aggregate wallet features

**Files:**
- Modify: `src/pat/analytics/wallet_features.py` (add `WalletFeatures` + `compute_wallet_features`)
- Test: `tests/analytics/test_wallet_features.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/analytics/test_wallet_features.py
from pat.analytics.wallet_features import WalletFeatures, compute_wallet_features


def _wf(token: str, side: Side, price: str, size: str, block: int) -> WalletFill:
    p, s = Decimal(price), Decimal(size)
    cash = (-p * s) if side is Side.BUY else (p * s)
    return WalletFill(token_id=token, side=side, price=p, size=s, block=block,
                      is_maker=False, cashflow=cash)


def test_features_flip_roundtrip_and_pnl() -> None:
    # Token A: buy 10@0.40 (block 1), sell 10@0.60 (block 51) -> flipped, +2.0 realized.
    fills = [
        _wf("A", Side.BUY, "0.40", "10", 1),
        _wf("A", Side.SELL, "0.60", "10", 51),
    ]
    f = compute_wallet_features("0xw", fills, marks={})
    assert f.n_fills == 2
    assert f.n_tokens == 1
    assert f.flip_rate == 1.0
    assert f.median_hold_blocks == 50
    assert f.roundtrip_return_median == Decimal("0.20")
    assert f.pnl_proxy == Decimal("2.0")          # +6.0 - 4.0, residual 0
    assert f.realized_share == 1.0


def test_features_held_position_marked_at_curprice() -> None:
    # Buy 10@0.30, never sold; mark 0.50 -> residual value 5.0, cost 3.0 -> pnl +2.0.
    fills = [_wf("B", Side.BUY, "0.30", "10", 5)]
    f = compute_wallet_features("0xw", fills, marks={"B": Decimal("0.50")})
    assert f.flip_rate == 0.0
    assert f.entry_price_mean == Decimal("0.30")
    assert f.pnl_proxy == Decimal("2.0")          # -3.0 cashflow + 5.0 residual
    assert f.realized_share == 0.0                # all pnl is unrealized
    assert f.maker_fill_ratio == 0.0


def test_features_top1_token_share_flags_concentration() -> None:
    # Token X: +9 pnl; Token Y: +1 pnl -> top1 share 0.9.
    fills = [
        _wf("X", Side.BUY, "0.10", "10", 1), _wf("X", Side.SELL, "1.00", "10", 2),
        _wf("Y", Side.BUY, "0.50", "2", 1), _wf("Y", Side.SELL, "1.00", "2", 2),
    ]
    f = compute_wallet_features("0xw", fills, marks={})
    assert f.n_tokens == 2
    assert f.top1_token_pnl_share == 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/analytics/test_wallet_features.py -k features -v`
Expected: FAIL — `ImportError: cannot import name 'WalletFeatures'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/pat/analytics/wallet_features.py
from statistics import median


class WalletFeatures(BaseModel):
    wallet: str
    n_fills: int
    n_tokens: int
    maker_fill_ratio: float
    flip_rate: float
    median_hold_blocks: int
    entry_price_mean: Decimal
    turnover_usdc: Decimal
    pnl_proxy: Decimal
    realized_share: float
    top1_token_pnl_share: float
    positive_token_fraction: float
    roundtrip_return_median: Decimal


def _vwap(prices_sizes: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Size-weighted average price; 0 if no size."""
    tot = sum((s for _, s in prices_sizes), Decimal("0"))
    if tot == 0:
        return Decimal("0")
    return sum((p * s for p, s in prices_sizes), Decimal("0")) / tot


def compute_wallet_features(
    wallet: str, fills: list[WalletFill], marks: dict[str, Decimal]
) -> WalletFeatures:
    """Aggregate per-wallet behavioral features. `marks` = token_id -> current mark price.

    pnl_proxy per token = realized cashflow + residual_position * mark (mark falls back to the
    token's last trade price if absent). top1_token_pnl_share / positive_token_fraction use the
    per-token pnl. roundtrip_return_median / median_hold_blocks use only flipped tokens.
    """
    if not fills:
        return WalletFeatures(
            wallet=wallet, n_fills=0, n_tokens=0, maker_fill_ratio=0.0, flip_rate=0.0,
            median_hold_blocks=0, entry_price_mean=Decimal("0"), turnover_usdc=Decimal("0"),
            pnl_proxy=Decimal("0"), realized_share=0.0, top1_token_pnl_share=0.0,
            positive_token_fraction=0.0, roundtrip_return_median=Decimal("0"),
        )

    by_token: dict[str, list[WalletFill]] = {}
    for fl in fills:
        by_token.setdefault(fl.token_id, []).append(fl)

    buys_all: list[tuple[Decimal, Decimal]] = []
    hold_gaps: list[int] = []
    roundtrips: list[Decimal] = []
    token_pnl: dict[str, Decimal] = {}
    realized_total = Decimal("0")
    unrealized_total = Decimal("0")
    turnover = Decimal("0")
    flips = 0

    for token, tfills in by_token.items():
        tfills.sort(key=lambda f: f.block)
        buys = [(f.price, f.size) for f in tfills if f.side is Side.BUY]
        sells = [(f.price, f.size) for f in tfills if f.side is Side.SELL]
        buys_all.extend(buys)
        turnover += sum((f.price * f.size for f in tfills), Decimal("0"))
        realized_cash = sum((f.cashflow for f in tfills), Decimal("0"))
        net_size = sum((f.size if f.side is Side.BUY else -f.size for f in tfills), Decimal("0"))
        last_price = tfills[-1].price
        mark = marks.get(token, last_price)
        residual_value = net_size * mark
        token_pnl[token] = realized_cash + residual_value
        realized_total += realized_cash
        unrealized_total += residual_value
        if buys and sells:
            flips += 1
            entry_block = next(f.block for f in tfills if f.side is Side.BUY)
            exit_block = next(f.block for f in tfills if f.side is Side.SELL)
            hold_gaps.append(exit_block - entry_block)
            roundtrips.append(_vwap(sells) - _vwap(buys))

    n_tokens = len(by_token)
    pnl_proxy = realized_total + unrealized_total
    positive = [v for v in token_pnl.values() if v > 0]
    pos_total = sum(positive, Decimal("0"))
    top1_share = float(max(positive) / pos_total) if pos_total > 0 else 0.0
    realized_share = float(realized_total / pnl_proxy) if pnl_proxy != 0 else 0.0

    return WalletFeatures(
        wallet=wallet,
        n_fills=len(fills),
        n_tokens=n_tokens,
        maker_fill_ratio=sum(1 for f in fills if f.is_maker) / len(fills),
        flip_rate=flips / n_tokens,
        median_hold_blocks=int(median(hold_gaps)) if hold_gaps else 0,
        entry_price_mean=_vwap(buys_all),
        turnover_usdc=turnover,
        pnl_proxy=pnl_proxy,
        realized_share=max(0.0, min(1.0, realized_share)),
        top1_token_pnl_share=top1_share,
        positive_token_fraction=len(positive) / n_tokens,
        roundtrip_return_median=median(roundtrips) if roundtrips else Decimal("0"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/analytics/test_wallet_features.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/pat/analytics/wallet_features.py tests/analytics/test_wallet_features.py
git commit -m "feat(analytics): aggregate wallet features (flip/hold/roundtrip/pnl-proxy/top1)"
```

---

## Task 5: Archetype classifier

**Files:**
- Create: `src/pat/analytics/wallet_archetype.py`
- Test: `tests/analytics/test_wallet_archetype.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/analytics/test_wallet_archetype.py
from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_archetype import (
    ARBITRAGEUR, DIRECTIONAL_INFORMED, LONGSHOT_FARMER, MARKET_MAKER,
    RESOLUTION_HOLDER, UNCLASSIFIED, classify,
)
from pat.analytics.wallet_features import WalletFeatures


def _f(**kw: object) -> WalletFeatures:
    base: dict[str, object] = dict(
        wallet="0xw", n_fills=100, n_tokens=40, maker_fill_ratio=0.5, flip_rate=0.5,
        median_hold_blocks=200, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("1000"),
        pnl_proxy=Decimal("10"), realized_share=0.8, top1_token_pnl_share=0.2,
        positive_token_fraction=0.6, roundtrip_return_median=Decimal("0.0"),
    )
    base.update(kw)
    return WalletFeatures(**base)  # type: ignore[arg-type]


def test_classify_market_maker() -> None:
    f = _f(maker_fill_ratio=0.8, flip_rate=0.9, median_hold_blocks=50,
           entry_price_mean=Decimal("0.5"))
    assert classify(f)[0] == MARKET_MAKER


def test_classify_directional_informed() -> None:
    f = _f(maker_fill_ratio=0.2, flip_rate=0.6, median_hold_blocks=400,
           roundtrip_return_median=Decimal("0.08"))
    assert classify(f)[0] == DIRECTIONAL_INFORMED


def test_classify_longshot_farmer() -> None:
    f = _f(entry_price_mean=Decimal("0.12"), flip_rate=0.1, top1_token_pnl_share=0.7)
    assert classify(f)[0] == LONGSHOT_FARMER


def test_classify_resolution_holder() -> None:
    f = _f(entry_price_mean=Decimal("0.95"), flip_rate=0.1)
    assert classify(f)[0] == RESOLUTION_HOLDER


def test_classify_arbitrageur() -> None:
    f = _f(flip_rate=0.95, median_hold_blocks=0, maker_fill_ratio=0.5)
    assert classify(f)[0] == ARBITRAGEUR


def test_classify_unclassified_when_nothing_fits() -> None:
    f = _f(maker_fill_ratio=0.5, flip_rate=0.3, median_hold_blocks=200,
           entry_price_mean=Decimal("0.5"), top1_token_pnl_share=0.2)
    assert classify(f)[0] == UNCLASSIFIED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/analytics/test_wallet_archetype.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.analytics.wallet_archetype'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/pat/analytics/wallet_archetype.py
"""First-pass deterministic archetype labeler (spec §8). Thresholds are initial; the report
prints raw feature distributions so they can be sanity-checked, not blindly trusted.

Order matters: arbitrageur (instant flip) is checked before market-maker; resolution-holder /
longshot-farmer (price extremes) before the mid-price MM band.
"""

from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_features import WalletFeatures

ARBITRAGEUR = "arbitrageur"
MARKET_MAKER = "market-maker"
DIRECTIONAL_INFORMED = "directional-informed"
LONGSHOT_FARMER = "longshot-farmer"
RESOLUTION_HOLDER = "resolution-holder"
UNCLASSIFIED = "unclassified"

_MM_HOLD_MAX = 150          # blocks (~5 min on Polygon) — fast flip
_DIRECTIONAL_HOLD_MIN = 150  # holds through a move


def classify(f: WalletFeatures) -> tuple[str, float]:
    """Return (archetype, confidence in [0,1]). Confidence is a coarse rule-margin proxy."""
    # Arbitrageur: near-instant flips, both-sided.
    if f.flip_rate >= 0.9 and f.median_hold_blocks <= 2:
        return ARBITRAGEUR, 0.8
    # Price-extreme holders (check before the mid-price MM band).
    if f.entry_price_mean <= Decimal("0.2") and f.flip_rate <= 0.3:
        return LONGSHOT_FARMER, 0.7
    if f.entry_price_mean >= Decimal("0.85") and f.flip_rate <= 0.3:
        return RESOLUTION_HOLDER, 0.7
    # Market-maker: maker-led, fast two-sided flip in the mid band.
    if (
        f.maker_fill_ratio >= 0.6
        and f.flip_rate >= 0.6
        and f.median_hold_blocks <= _MM_HOLD_MAX
        and Decimal("0.2") <= f.entry_price_mean <= Decimal("0.8")
    ):
        return MARKET_MAKER, 0.8
    # Directional-informed: taker-led, positive round-trip, holds through the move.
    if (
        f.maker_fill_ratio <= 0.4
        and f.roundtrip_return_median > Decimal("0")
        and f.median_hold_blocks >= _DIRECTIONAL_HOLD_MIN
    ):
        return DIRECTIONAL_INFORMED, 0.7
    return UNCLASSIFIED, 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/analytics/test_wallet_archetype.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pat/analytics/wallet_archetype.py tests/analytics/test_wallet_archetype.py
git commit -m "feat(analytics): first-pass archetype classifier (spec thresholds)"
```

---

## Task 6: Skill-vs-luck screen + copyability proxy

**Files:**
- Modify: `src/pat/analytics/wallet_features.py` (add `is_skill_cohort`, `copyability_proxy`)
- Test: `tests/analytics/test_wallet_screen.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/analytics/test_wallet_screen.py
from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_features import WalletFeatures, copyability_proxy, is_skill_cohort


def _f(**kw: object) -> WalletFeatures:
    base: dict[str, object] = dict(
        wallet="0xw", n_fills=100, n_tokens=40, maker_fill_ratio=0.5, flip_rate=0.5,
        median_hold_blocks=200, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("1000"),
        pnl_proxy=Decimal("10"), realized_share=0.8, top1_token_pnl_share=0.2,
        positive_token_fraction=0.6, roundtrip_return_median=Decimal("0.05"),
    )
    base.update(kw)
    return WalletFeatures(**base)  # type: ignore[arg-type]


def test_skill_cohort_requires_breadth_low_concentration_and_consistency() -> None:
    assert is_skill_cohort(_f(n_tokens=40, top1_token_pnl_share=0.2,
                              positive_token_fraction=0.6)) is True


def test_luck_flagged_when_one_token_dominates() -> None:
    assert is_skill_cohort(_f(top1_token_pnl_share=0.7)) is False


def test_luck_flagged_when_too_few_independent_bets() -> None:
    assert is_skill_cohort(_f(n_tokens=10)) is False


def test_copyability_is_roundtrip_return_when_drift_is_slow() -> None:
    # Positive round-trip with a non-trivial hold gap -> copyable (returns the round-trip edge).
    assert copyability_proxy(_f(roundtrip_return_median=Decimal("0.05"),
                               median_hold_blocks=300)) == Decimal("0.05")


def test_copyability_zero_when_flip_is_instant_arb() -> None:
    # Instant flip (<=2 blocks) -> edge gone before we can follow -> 0.
    assert copyability_proxy(_f(roundtrip_return_median=Decimal("0.05"),
                               median_hold_blocks=1)) == Decimal("0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/analytics/test_wallet_screen.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_skill_cohort'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/pat/analytics/wallet_features.py
_SKILL_MIN_TOKENS = 30          # >= ~15 binary markets — "many independent bets"
_SKILL_MAX_TOP1_SHARE = 0.40    # no single bet dominates the P&L
_SKILL_MIN_POSITIVE_FRAC = 0.50  # positive across a majority of tokens
_COPY_MIN_HOLD_BLOCKS = 3       # below this, the move is too fast to follow with our lag


def is_skill_cohort(f: WalletFeatures) -> bool:
    """True if the wallet's P&L looks like repeatable skill, not one lucky jackpot (spec §9)."""
    return (
        f.n_tokens >= _SKILL_MIN_TOKENS
        and f.top1_token_pnl_share < _SKILL_MAX_TOP1_SHARE
        and f.positive_token_fraction > _SKILL_MIN_POSITIVE_FRAC
    )


def copyability_proxy(f: WalletFeatures) -> Decimal:
    """Lean zero-lag copyability = round-trip edge, but 0 if the flip is too fast to follow (§10)."""
    if f.median_hold_blocks < _COPY_MIN_HOLD_BLOCKS:
        return Decimal("0")
    return max(Decimal("0"), f.roundtrip_return_median)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/analytics/test_wallet_screen.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/pat/analytics/wallet_features.py tests/analytics/test_wallet_screen.py
git commit -m "feat(analytics): skill-vs-luck screen + lean copyability proxy"
```

---

## Task 7: Control-group sampler

**Files:**
- Create: `src/pat/analytics/wallet_control.py`
- Test: `tests/analytics/test_wallet_control.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/analytics/test_wallet_control.py
from __future__ import annotations

from pat.analytics.wallet_control import sample_control_wallets


def _ev(maker: str, taker: str) -> dict:
    return {"maker": maker, "taker": taker}


def test_sample_control_picks_median_activity_excludes_given_set() -> None:
    # Wallets with fill counts: A=5, B=4, C=3, D=2, E=1 (as maker). Exclude A (a "winner").
    events: list[dict] = []
    op = "0x" + "00" * 20  # operator/zero-ish counterparty, ignored
    for addr, count in {"0xa": 5, "0xb": 4, "0xc": 3, "0xd": 2, "0xe": 1}.items():
        events += [_ev(addr, op) for _ in range(count)]
    picked = sample_control_wallets(events, n=3, exclude={"0xa"})
    # Median-activity 3 of {B,C,D,E} closest to the median fill count.
    assert "0xa" not in picked
    assert len(picked) == 3
    assert "0xc" in picked  # the median-most wallet is always included
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/analytics/test_wallet_control.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.analytics.wallet_control'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/pat/analytics/wallet_control.py
"""Control-group sampler: median-activity wallets from existing decoded fills (spec §5, §11).

Survivorship-bias guard — "ordinary active traders". Deterministic (no RNG): rank distinct
wallets by fill count and take the n closest to the median count. The zero address and a
caller-supplied exclude set (the winners) are dropped.
"""

from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any

_ZERO = "0x" + "00" * 20


def sample_control_wallets(
    events: list[dict[str, Any]], *, n: int = 25, exclude: set[str] | None = None
) -> list[str]:
    """Return n median-activity proxyWallets appearing as maker/taker in *events*."""
    drop = {a.lower() for a in (exclude or set())} | {_ZERO}
    counts: Counter[str] = Counter()
    for ev in events:
        for role in ("maker", "taker"):
            addr = str(ev.get(role, "")).lower()
            if addr and addr not in drop:
                counts[addr] += 1
    if not counts:
        return []
    med = median(counts.values())
    # Sort by closeness to the median fill count (ties -> higher activity first, then address).
    ranked = sorted(counts.items(), key=lambda kv: (abs(kv[1] - med), -kv[1], kv[0]))
    return [addr for addr, _ in ranked[:n]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/analytics/test_wallet_control.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add src/pat/analytics/wallet_control.py tests/analytics/test_wallet_control.py
git commit -m "feat(analytics): deterministic median-activity control sampler"
```

---

## Task 8: Fetch driver (leaderboard → 4-exchange maker∪taker getLogs → save; V1/V2 gate)

**Files:**
- Create: `scripts/fetch_wallet_histories.py`
- Test: `tests/scripts/test_fetch_wallet_histories.py`

This driver is USER-run (Alchemy key). Network goes through the existing `_rpc_get_logs`
(auto-split, 429-retry, key redaction). Tests monkeypatch it — no real network.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_fetch_wallet_histories.py
from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "fetch_wallet_histories",
    Path(__file__).resolve().parents[2] / "scripts" / "fetch_wallet_histories.py",
)
assert _SPEC and _SPEC.loader
fwh = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fwh)


def test_topic0_histogram_counts_orderfilled_share() -> None:
    logs = [
        {"topics": ["0xV2OF"], "transactionHash": "0x1", "logIndex": "0x0"},
        {"topics": ["0xV2OF"], "transactionHash": "0x2", "logIndex": "0x0"},
        {"topics": ["0xOTHER"], "transactionHash": "0x3", "logIndex": "0x0"},
    ]
    hist = fwh.topic0_histogram(logs)
    assert hist == {"0xv2of": 2, "0xother": 1}


def test_fetch_one_wallet_runs_maker_and_taker_passes(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_get_logs(rpc_url, address, from_block, to_block, topics=None):
        calls.append((address, tuple(topics) if topics else None))
        # Return one synthetic log keyed by the topic filter so merge dedups correctly.
        wallet_topic = topics[2] if topics and len(topics) > 2 and topics[2] else topics[3]
        return [{"topics": ["0xV2OF", "0xoh", wallet_topic or "0x", "0x"],
                 "transactionHash": "0x" + address[-2:], "logIndex": "0x0"}]

    monkeypatch.setattr(fwh, "_rpc_get_logs", fake_get_logs)
    out = fwh.fetch_one_wallet(
        "0x" + "11" * 20, rpc_url="http://x", from_block=0, to_block=10,
        exchanges_topic0=[("0xExch", "0xV2OF")],
    )
    # one exchange * (maker pass + taker pass) = 2 calls
    assert len(calls) == 2
    assert len(out) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scripts/test_fetch_wallet_histories.py -v`
Expected: FAIL — `AttributeError: module 'fetch_wallet_histories' has no attribute 'topic0_histogram'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/fetch_wallet_histories.py
"""Fetch top-wallet + control on-chain OrderFilled history across all 4 Polymarket exchanges.

USER-RUNS THIS (Alchemy key in POLYGON_RPC_URL). Per wallet, two topic-filtered passes
(maker=topics[2], taker=topics[3]) per exchange, merged. Saves data/raw/wallets/<addr>.json.
Also reports a topic0 histogram per wallet -> the measure-first V1 gate (spec §6): if V1
OrderFilled > 20% of fills for the median wallet, we build a V1 decoder before features.

🔴 Never read .env — the key lives in POLYGON_RPC_URL or is passed via --rpc-url.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

# --- sys.path bootstrap so `python scripts/...` finds the src/ package ---------
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import structlog  # noqa: E402

from pat.analytics.wallet_control import sample_control_wallets  # noqa: E402
from pat.data.wallet_history import merge_maker_taker, wallet_to_topic  # noqa: E402
from pat.venues.polymarket.leaderboard import fetch_leaderboard  # noqa: E402
from scripts.fetch_polymarket_history import _rpc_get_logs  # noqa: E402

# topic0s per exchange. V2 OrderFilled is known; V1 OrderFilled topic0 is observed from the
# histogram on first run (spec §6) — keep V1 as None to fetch ALL of the wallet's V1 logs.
V2_TOPIC0 = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
EXCHANGES: list[tuple[str, str | None]] = [
    ("0xE111180000d2663C0091e4f400237545B87B996B", V2_TOPIC0),  # V2 main
    ("0xe2222d279d744050d28e00520010520000310F59", V2_TOPIC0),  # V2 neg-risk
    ("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", None),       # V1 main (observe topic0)
    ("0xC5d563A36AE78145C45a50134d48A1215220f80a", None),       # V1 neg-risk (observe topic0)
]

log = structlog.get_logger(__name__)


def topic0_histogram(logs: list[dict[str, Any]]) -> dict[str, int]:
    """Count logs by topics[0] (lowercased) — used to identify/measure V1 vs V2 OrderFilled."""
    c: Counter[str] = Counter()
    for entry in logs:
        topics = entry.get("topics") or []
        if topics:
            c[str(topics[0]).lower()] += 1
    return dict(c)


def fetch_one_wallet(
    wallet: str, *, rpc_url: str, from_block: int, to_block: int,
    exchanges_topic0: list[tuple[str, str | None]],
) -> list[dict[str, Any]]:
    """Two topic-filtered passes (maker, taker) per exchange, merged + deduped."""
    wtopic = wallet_to_topic(wallet)
    maker_logs: list[dict[str, Any]] = []
    taker_logs: list[dict[str, Any]] = []
    for address, topic0 in exchanges_topic0:
        maker_logs += _rpc_get_logs(rpc_url, address, from_block, to_block,
                                    topics=[topic0, None, wtopic])
        taker_logs += _rpc_get_logs(rpc_url, address, from_block, to_block,
                                    topics=[topic0, None, None, wtopic])
    return merge_maker_taker(maker_logs, taker_logs)


def run(out_dir: Path, *, from_block: int, to_block: int, top_n: int, control_n: int,
        control_src: Path, rpc_url: str | None = None) -> Path:
    corr_id = str(uuid.uuid4())
    blog = log.bind(corr_id=corr_id, from_block=from_block, to_block=to_block)
    effective_rpc = rpc_url or os.environ.get("POLYGON_RPC_URL")
    if not effective_rpc:
        raise SystemExit("Set POLYGON_RPC_URL (or pass --rpc-url). Never read .env.")

    out_dir.mkdir(parents=True, exist_ok=True)
    leaders = fetch_leaderboard(top_n=top_n)
    winners = [e.wallet for e in leaders]
    control_events = json.loads(control_src.read_text(encoding="utf-8"))
    control = sample_control_wallets(control_events, n=control_n, exclude=set(winners))
    (out_dir / "_winners.json").write_text(json.dumps(winners), encoding="utf-8")
    (out_dir / "_control.json").write_text(json.dumps(control), encoding="utf-8")
    blog.info("wallets.selected", winners=len(winners), control=len(control))

    v1_total = 0
    of_total = 0
    for wallet in (*winners, *control):
        logs = fetch_one_wallet(wallet, rpc_url=effective_rpc, from_block=from_block,
                                to_block=to_block, exchanges_topic0=EXCHANGES)
        hist = topic0_histogram(logs)
        v2 = hist.get(V2_TOPIC0.lower(), 0)
        v1 = sum(v for k, v in hist.items() if k != V2_TOPIC0.lower())
        v1_total += v1
        of_total += v1 + v2
        (out_dir / f"{wallet}.json").write_text(json.dumps(logs, indent=2), encoding="utf-8")
        blog.info("wallet.fetched", wallet=wallet, n=len(logs), v2=v2, v1_or_other=v1)

    v1_share = (v1_total / of_total) if of_total else 0.0
    blog.info("v1_gate", v1_share=round(v1_share, 3),
              decision="BUILD_V1_DECODER" if v1_share > 0.20 else "V2_ONLY_OK")
    return out_dir


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch top-wallet + control OrderFilled history.")
    p.add_argument("--from-block", type=int, required=True)
    p.add_argument("--to-block", type=int, required=True)
    p.add_argument("--top-n", type=int, default=50)
    p.add_argument("--control-n", type=int, default=25)
    p.add_argument("--control-src", type=Path,
                   default=Path("data/raw/geopolitics_88082000_88090000.json"))
    p.add_argument("--out-dir", type=Path, default=Path("data/raw/wallets"))
    p.add_argument("--rpc-url", type=str, default=None)
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
    result = run(args.out_dir, from_block=args.from_block, to_block=args.to_block,
                 top_n=args.top_n, control_n=args.control_n, control_src=args.control_src,
                 rpc_url=args.rpc_url)
    print(result)  # noqa: T201
```

Note: `from scripts.fetch_polymarket_history import _rpc_get_logs` requires `scripts/__init__.py`
to exist (it does, used by the existing test layout). If import-by-path fails in the test, the
test loads the module via `importlib` (as written) and monkeypatches `fwh._rpc_get_logs`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scripts/test_fetch_wallet_histories.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/fetch_wallet_histories.py tests/scripts/test_fetch_wallet_histories.py
git commit -m "feat(scripts): wallet-history fetch driver (4 exchanges, maker-taker, V1 gate)"
```

---

## Task 9: Analysis driver + report

**Files:**
- Create: `scripts/run_wallet_analysis.py`
- Test: `tests/scripts/test_run_wallet_analysis.py`

Loads saved per-wallet raw logs, decodes (V2), pulls keyless data-api marks (seam), computes
features, classifies, contrasts vs control, writes the report. AI may run this (no Alchemy key).

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_run_wallet_analysis.py
from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "run_wallet_analysis",
    Path(__file__).resolve().parents[2] / "scripts" / "run_wallet_analysis.py",
)
assert _SPEC and _SPEC.loader
rwa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rwa)

from pat.analytics.wallet_features import WalletFeatures  # noqa: E402


def _feat(wallet: str, archetype_hint: str) -> WalletFeatures:
    # Minimal feature object; values chosen so the row renders.
    return WalletFeatures(
        wallet=wallet, n_fills=10, n_tokens=40, maker_fill_ratio=0.8, flip_rate=0.9,
        median_hold_blocks=50, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("100"),
        pnl_proxy=Decimal("5"), realized_share=1.0, top1_token_pnl_share=0.2,
        positive_token_fraction=0.6, roundtrip_return_median=Decimal("0.02"),
    )


def test_archetype_counts_tallies_labels() -> None:
    rows = [
        {"archetype": "market-maker"}, {"archetype": "market-maker"},
        {"archetype": "directional-informed"},
    ]
    assert rwa.archetype_counts(rows) == {"market-maker": 2, "directional-informed": 1}


def test_render_report_contains_recommendation_and_counts() -> None:
    winners = [{"wallet": "0xw1", "archetype": "market-maker", "skill": True,
                "copyability": Decimal("0.0"), "features": _feat("0xw1", "mm")}]
    control = [{"wallet": "0xc1", "archetype": "unclassified", "skill": False,
                "copyability": Decimal("0.0"), "features": _feat("0xc1", "u")}]
    md = rwa.render_report(winners, control, v1_share=0.05, provenance={"top_n": 1})
    assert "market-maker" in md
    assert "Recommendation" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scripts/test_run_wallet_analysis.py -v`
Expected: FAIL — `AttributeError: module 'run_wallet_analysis' has no attribute 'archetype_counts'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/run_wallet_analysis.py
"""Analyze saved per-wallet OrderFilled history -> archetype map + recommendation (spec §H).

AI may run this (keyless): decode V2 logs, pull data-api marks (seam), compute features,
classify, contrast vs control, render the report. Per the measure-first gate, if the fetch
flagged V1 as material, decode_v1_orderfilled (Task 10) must exist and be wired in first.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import httpx  # noqa: E402
import structlog  # noqa: E402

from pat.analytics.wallet_archetype import classify  # noqa: E402
from pat.analytics.wallet_features import (  # noqa: E402
    compute_wallet_features, copyability_proxy, derive_wallet_fills, is_skill_cohort,
)
from pat.data.polymarket_on_chain import decode_v2_orderfilled  # noqa: E402

DATA_API = "https://data-api.polymarket.com"
_REQUEST_TIMEOUT = 30  # seconds
log = structlog.get_logger(__name__)


def _data_api_marks(wallet: str) -> dict[str, Decimal]:
    """token_id -> curPrice for the wallet's OPEN positions (keyless). The wire seam (mock in tests)."""
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.get(f"{DATA_API}/positions", params={"user": wallet, "limit": 500})
        resp.raise_for_status()
        positions: list[dict[str, Any]] = resp.json()
    return {str(p["asset"]): Decimal(str(p["curPrice"])) for p in positions if "curPrice" in p}


def analyze_wallet(
    wallet: str, raw_logs: list[dict[str, Any]], marks: dict[str, Decimal]
) -> dict[str, Any]:
    """Decode -> derive fills -> features -> classify -> screen. Pure given marks."""
    decoded = [d for d in (decode_v2_orderfilled(x) for x in raw_logs) if d is not None]
    fills = derive_wallet_fills(decoded, wallet)
    features = compute_wallet_features(wallet, fills, marks)
    archetype, _conf = classify(features)
    return {
        "wallet": wallet, "archetype": archetype, "skill": is_skill_cohort(features),
        "copyability": copyability_proxy(features), "features": features,
    }


def archetype_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(r["archetype"] for r in rows))


def _recommend(winners: list[dict[str, Any]]) -> str:
    """Apply the pre-registered decision rule (spec §2) to the skill cohort."""
    skilled = [r for r in winners if r["skill"]]
    counts = Counter(r["archetype"] for r in skilled)
    if not skilled:
        return "No skill-cohort winners (P&L luck-dominated) -> structural strategies (A2/D1)."
    top = counts.most_common(1)[0][0]
    copyable = any(r["copyability"] > Decimal("0") for r in skilled if r["archetype"] == top)
    if top == "directional-informed" and not copyable:
        return "Winners are directional-informed but not copyable -> directional/news (D3)."
    if top == "market-maker":
        return "Winners are market-makers -> revisit MM only with an order book (ADR 0014)."
    if copyable:
        return f"Skilled, copyable '{top}' archetype -> C1 copy-trading; next run Approach 3 (sim)."
    return f"Dominant skilled archetype '{top}' is not cheaply copyable -> see §2 / structural."


def render_report(
    winners: list[dict[str, Any]], control: list[dict[str, Any]],
    *, v1_share: float, provenance: dict[str, Any],
) -> str:
    lines = ["# Wallet Behavioral Analysis — Results", ""]
    lines.append(f"**Provenance:** {provenance} · V1 share = {v1_share:.1%}")
    lines.append("")
    lines.append("## Archetype counts (winners)")
    for arch, n in sorted(archetype_counts(winners).items(), key=lambda kv: -kv[1]):
        lines.append(f"- {arch}: {n}")
    lines.append("")
    lines.append("## Archetype counts (control)")
    for arch, n in sorted(archetype_counts(control).items(), key=lambda kv: -kv[1]):
        lines.append(f"- {arch}: {n}")
    lines.append("")
    lines.append(f"## Recommendation\n\n{_recommend(winners)}")
    return "\n".join(lines)


def run(wallets_dir: Path, winners: list[str], control: list[str], out_path: Path,
        *, v1_share: float, get_marks: Any = None) -> Path:
    marks_fn = get_marks or _data_api_marks

    def _rows(addrs: list[str]) -> list[dict[str, Any]]:
        rows = []
        for w in addrs:
            f = wallets_dir / f"{w}.json"
            if not f.exists():
                continue
            raw = json.loads(f.read_text(encoding="utf-8"))
            rows.append(analyze_wallet(w, raw, marks_fn(w)))
        return rows

    win_rows, ctrl_rows = _rows(winners), _rows(control)
    md = render_report(win_rows, ctrl_rows, v1_share=v1_share,
                       provenance={"winners": len(win_rows), "control": len(ctrl_rows)})
    out_path.write_text(md, encoding="utf-8")
    # Raw per-wallet features for the ADR's feature-vs-control contrast (spec §11, §12).
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    with (logs_dir / "wallet_features.jsonl").open("w", encoding="utf-8") as fh:
        for group, rows in (("winner", win_rows), ("control", ctrl_rows)):
            for r in rows:
                rec = {**r["features"].model_dump(mode="json"), "archetype": r["archetype"],
                       "skill": r["skill"], "copyability": str(r["copyability"]), "group": group}
                fh.write(json.dumps(rec) + "\n")
    log.info("analysis.written", out_path=str(out_path))
    return out_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze saved wallet histories -> archetype report.")
    p.add_argument("--wallets-dir", type=Path, default=Path("data/raw/wallets"))
    p.add_argument("--winners", type=Path, required=True, help="JSON list of winner addresses")
    p.add_argument("--control", type=Path, required=True, help="JSON list of control addresses")
    p.add_argument("--v1-share", type=float, default=0.0)
    p.add_argument("--out", type=Path, default=Path("docs/research/2026-06-09-wallet-analysis.md"))
    return p.parse_args()


if __name__ == "__main__":
    import logging

    structlog.configure(
        processors=[structlog.processors.add_log_level,
                    structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )
    a = _parse_args()
    out = run(a.wallets_dir, json.loads(a.winners.read_text()),
              json.loads(a.control.read_text()), a.out, v1_share=a.v1_share)
    print(out)  # noqa: T201
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scripts/test_run_wallet_analysis.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full gate + commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy src
git add scripts/run_wallet_analysis.py tests/scripts/test_run_wallet_analysis.py
git commit -m "feat(scripts): wallet-analysis driver (decode->features->classify->report)"
```

---

## Task 10 (CONDITIONAL — only if the V1 gate fires): V1 OrderFilled decoder

Run ONLY if Task 11's fetch reports `v1_share > 0.20`. Otherwise skip (document the small V1 gap
in the report).

**Files:**
- Modify: `src/pat/data/polymarket_on_chain.py` (add `decode_v1_orderfilled` + `TOPIC0_ORDERFILLED_V1`)
- Modify: `scripts/run_wallet_analysis.py` (dispatch by topics[0]: V2 vs V1 decoder)
- Test: `tests/data/test_polymarket_on_chain.py` (append a V1 decode test)

- [ ] **Step 1: Confirm the V1 topic0.** From the fetch's topic0 histogram on the V1 exchanges,
  identify the OrderFilled topic0 (the dominant non-V2 one), and cross-check it on Polygonscan
  against the V1 signature `OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)`.
  Record it as `TOPIC0_ORDERFILLED_V1`.

- [ ] **Step 2: Write the failing test** (V1 layout: 5 data words — makerAssetId, takerAssetId,
  makerAmountFilled, takerAmountFilled, fee; maker=topics[2], taker=topics[3], orderHash=topics[1]).

```python
# append to tests/data/test_polymarket_on_chain.py
from pat.data.polymarket_on_chain import TOPIC0_ORDERFILLED_V1, decode_v1_orderfilled


def test_decode_v1_orderfilled_reads_asset_ids_directly() -> None:
    # V1 BUY: makerAssetId=0 (USDC) 2.5, takerAssetId=TOKEN 5 -> price 0.5.
    words = [0, int(TOKEN), 2_500_000, 5_000_000, 25_000]
    data = "0x" + "".join(f"{w:064x}" for w in words)

    def _pad(a: str) -> str:
        return "0x" + a.lower().removeprefix("0x").rjust(64, "0")

    raw = {"topics": [TOPIC0_ORDERFILLED_V1, "0x" + "ab" * 32,
                      _pad("0x" + "11" * 20), _pad("0x" + "22" * 20)],
           "data": data, "blockNumber": "0x539", "transactionHash": "0xv1"}
    dec = decode_v1_orderfilled(raw)
    assert dec is not None
    assert dec["makerAssetId"] == "0"
    assert dec["takerAssetId"] == TOKEN
    assert dec["makerAmountFilled"] == 2_500_000
    assert dec["maker"] == "0x" + "11" * 20
    assert dec["tokenId"] == TOKEN  # non-zero leg
```

- [ ] **Step 3: Implement `decode_v1_orderfilled`** in `src/pat/data/polymarket_on_chain.py`:

```python
# V1 OrderFilled(bytes32 orderHash, address maker, address taker, uint256 makerAssetId,
#   uint256 takerAssetId, uint256 makerAmountFilled, uint256 takerAmountFilled, uint256 fee)
TOPIC0_ORDERFILLED_V1 = "<confirmed in Step 1>"
_DATA_WORDS_V1 = 5  # makerAssetId, takerAssetId, makerAmountFilled, takerAmountFilled, fee


def decode_v1_orderfilled(raw: dict[str, Any]) -> dict[str, Any] | None:
    topics = raw["topics"]
    if topics[0].lower() != TOPIC0_ORDERFILLED_V1.lower():
        return None
    maker_addr = "0x" + topics[2][-40:]
    taker_addr = "0x" + topics[3][-40:]
    data_hex = raw["data"]
    if data_hex.startswith("0x"):
        data_hex = data_hex[2:]
    data = bytes.fromhex(data_hex)
    words = [int.from_bytes(data[i:i + 32], "big") for i in range(0, _DATA_WORDS_V1 * 32, 32)]
    maker_asset_id, taker_asset_id, maker_amt, taker_amt, fee = words
    token_id = str(maker_asset_id) if maker_asset_id != 0 else str(taker_asset_id)
    return {
        "makerAssetId": str(maker_asset_id), "takerAssetId": str(taker_asset_id),
        "makerAmountFilled": maker_amt, "takerAmountFilled": taker_amt, "fee": fee,
        "transactionHash": raw["transactionHash"], "orderHash": topics[1],
        "maker": maker_addr, "taker": taker_addr,
        # V1 has no `side` field: derive it so derive_wallet_fills works unchanged
        # (side=0 BUY when makerAssetId==0/USDC, else side=1 SELL).
        "side": 0 if maker_asset_id == 0 else 1,
        "tokenId": token_id, "blockNumber": int(raw["blockNumber"], 16),
    }
```

- [ ] **Step 4: Wire the dispatch** in `scripts/run_wallet_analysis.py` `analyze_wallet`: try
  `decode_v2_orderfilled` then `decode_v1_orderfilled`, keeping the first non-None. Add
  `TOPIC0_ORDERFILLED_V1` to `fetch_wallet_histories.EXCHANGES` so the V1 passes filter on topic0.

- [ ] **Step 5: Run tests + commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy src
git add src/pat/data/polymarket_on_chain.py scripts/ tests/data/test_polymarket_on_chain.py
git commit -m "feat(data): V1 OrderFilled decoder (gate fired: V1 material)"
```

---

## Task 11 (OPERATIONAL — user-run fetch): real run + ADR 0020

This is not a code task; it produces the verdict. 🔴 The USER runs the Alchemy fetch.

- [ ] **Step 1: AI prepares the exact commands.** Pick a block range covering V2 history (from
  ~block 80,000,000, the V2 era, to a recent block). Provide:

```bash
# USER runs (Alchemy key in env; never printed). bash inside the project venv:
export POLYGON_RPC_URL="https://polygon-mainnet.g.alchemy.com/v2/<KEY>"
python scripts/fetch_wallet_histories.py --from-block 80000000 --to-block <recent> \
    --top-n 50 --control-n 25
```

- [ ] **Step 2: AI reads back the structlog counters** — `wallets.selected`, per-wallet
  `wallet.fetched` (n / v2 / v1_or_other), and the `v1_gate` line (`v1_share`, decision).

- [ ] **Step 3: V1 gate decision.** If `v1_share > 0.20` → do Task 10, re-run the fetch with the
  V1 topic0 wired, then continue. Else proceed V2-only.

- [ ] **Step 4: AI runs the analysis (keyless).**

```bash
uv run python scripts/run_wallet_analysis.py \
    --winners data/raw/wallets/_winners.json --control data/raw/wallets/_control.json \
    --v1-share <observed>
```

(Task 8's `run()` writes these winner/control address lists to
`data/raw/wallets/_winners.json` / `_control.json` alongside the per-wallet files.)

- [ ] **Step 5: Read the report, sanity-check feature distributions vs control**, apply the §2
  decision rule, and check the escalation triggers (§13: thin spectrum, ambiguous classification).

- [ ] **Step 6: Write ADR 0020** (`docs/decisions/0020-wallet-analysis-verdict.md`) — the archetype
  map, the skill-cohort, the contrast vs control, and the recommended next strategy + escalation
  status. Update `docs/HANDOFF.md` + `docs/roadmap.md` + `docs/strategies/` if a strategy is chosen.

- [ ] **Step 7: Final gate + commit.**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy src
git add docs/ data/raw/wallets/_winners.json data/raw/wallets/_control.json
git commit -m "spike: wallet-analysis verdict (ADR 0020) + archetype report"
```

---

## Notes for the implementer

- **Network seams only:** `_leaderboard_get_page`, `_rpc_get_logs` (reused), `_data_api_marks`,
  `_rpc_get_block_timestamp` (unused here). Everything else is pure and offline-tested.
- **`scripts/__init__.py`** exists; if `from scripts.fetch_polymarket_history import _rpc_get_logs`
  fails under pytest, the affected test loads the driver via `importlib` (Tasks 8–9 already do).
- **Timestamps:** the lean spike uses `blockNumber` directly for hold-time (block order == time
  order); no per-block timestamp RPC needed (saves CU). `derive_wallet_fills` reads `blockNumber`.
- **YAGNI:** no resolution fetch, no null-model test, no lag simulation (Approaches 2/3 are
  escalations, not in this plan). No category_mix gate — category is descriptive color only and
  is omitted from the lean classifier (it needs a broad Gamma fetch we are not doing).
