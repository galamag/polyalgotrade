# Phase 2b Data Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data layer that feeds real on-chain 0%-fee geopolitics Polymarket trades into the existing MM backtest and produce the first real edge verdict.

**Architecture:** A modular library (`decode_v2_orderfilled` + `enrich_timestamps` in `src/pat/data/polymarket_on_chain.py`; `select_geopolitics_tokens` in `src/pat/venues/polymarket/gamma.py`) plus a thin orchestration script (`scripts/fetch_geopolitics_data.py`) that produces a geopolitics-only decoded-events JSON. The existing `parse_orderfilled → streams_from_fills → run_sweep → Verdict` path consumes that JSON unchanged. All network I/O sits behind single monkeypatchable seams.

**Tech Stack:** Python 3.11, `uv`, `httpx` (sync `Client`), `pydantic`, `structlog`, `pytest`. No `web3`/`eth-abi` — hand-rolled `bytes.fromhex`/`int.from_bytes` decode per ADR 0016. Money is `Decimal`.

**Spec:** `docs/superpowers/specs/2026-06-08-phase2b-data-layer-design.md`. Read it first.

**Commands used throughout:**
- Test one: `uv run --extra dev pytest <path>::<test> -v`
- Test all: `uv run --extra dev pytest -q`
- Lint: `uv run --extra dev ruff check .` (auto-fixable issues like import-sorting/UP: `ruff check --fix .`, then re-run the plain check). Note: E501 line-length is NOT auto-fixed — keep lines ≤100.
- Types: `uv run --extra dev mypy src`

**Conventions (from the codebase — obey):** money is `Decimal`; network behind one seam + a "no real network" test; ruff `S` (bandit) active on `src` (httpx needs explicit `timeout`, no `assert` in `src`); mypy strict on `src` (full annotations, `from __future__ import annotations`); files read/written with `encoding="utf-8"`; NO `Co-Authored-By` trailer on commits.

---

## File Structure

**Create:**
- `src/pat/data/polymarket_on_chain.py` — V2 raw-log decoder + block-timestamp enrichment (Tasks 1-2).
- `src/pat/venues/polymarket/gamma.py` — geopolitics 0%-fee token selection (Task 3).
- `scripts/fetch_geopolitics_data.py` — orchestration: gamma → fetch → decode → filter → enrich → write (Task 5).
- `tests/data/test_polymarket_on_chain.py` (Tasks 1-2).
- `tests/venues/__init__.py`, `tests/venues/polymarket/__init__.py`, `tests/venues/polymarket/test_gamma.py` (Task 3).
- `tests/data/fixtures/gamma_events_sample.json` (Task 3).
- `tests/scripts/test_fetch_geopolitics_data.py` (Task 5).
- `docs/decisions/0018-geopolitics-mm-verdict.md` (Task 7).

**Modify:**
- `scripts/fetch_polymarket_history.py` — topic0 filter + NegRisk address + multi-address helper (Task 4).
- `tests/scripts/test_fetch_mocked.py` — tests for the above (Task 4).
- `scripts/run_mm_backtest.py` — `--record` verdict writer + TradeJournal (Task 6).
- `tests/scripts/test_mm_backtest.py` — tests for `--record` helpers (Task 6).
- `docs/strategies/market-making.md` — RESULTS markers in §7; verdict in §8 (Tasks 6-7).
- `docs/research/claims-verification.md` — NegRisk address+ABI verification entry (Task 7).

**Reused UNCHANGED:** `src/pat/data/polymarket_history.py` (`parse_orderfilled`), `scripts/run_mm_backtest.py` (`run_sweep`, `streams_from_fills`), `src/pat/analytics/metrics.py` (`summarize`, `Verdict`), `src/pat/costs/`.

---

## Task 1: V2 OrderFilled decoder (`decode_v2_orderfilled`)

**Files:**
- Create: `src/pat/data/polymarket_on_chain.py`
- Test: `tests/data/test_polymarket_on_chain.py`

- [ ] **Step 1: Write the failing test**

Create `tests/data/test_polymarket_on_chain.py`:
```python
from __future__ import annotations

from decimal import Decimal

from pat.data.polymarket_history import parse_orderfilled
from pat.data.polymarket_on_chain import TOPIC0_ORDERFILLED, decode_v2_orderfilled

# A real geopolitics-shaped ERC-1155 token id (decimal string), reused from the V1 fixture.
TOKEN = "71321045679252212594626385532706912750332728571942532289631379312455583992616"


def _make_raw_log(
    *,
    side: int,
    token_id: int,
    maker_amt: int,
    taker_amt: int,
    fee: int,
    tx: str = "0xtx",
    block: str = "0x539",  # 1337
    maker: str = "0x" + "11" * 20,
    taker: str = "0x" + "22" * 20,
    topic0: str = TOPIC0_ORDERFILLED,
) -> dict:
    """Build a synthetic raw eth_getLogs entry with known field values."""
    words = [side, token_id, maker_amt, taker_amt, fee, 0, 0]
    data = "0x" + "".join(f"{w:064x}" for w in words)

    def _pad(addr: str) -> str:
        return "0x" + addr.lower().removeprefix("0x").rjust(64, "0")

    return {
        "topics": [topic0, "0x" + "ab" * 32, _pad(maker), _pad(taker)],
        "data": data,
        "blockNumber": block,
        "transactionHash": tx,
    }


def test_decode_buy_bridges_to_usdc_maker_leg() -> None:
    # side=0 (BUY): maker gives USDC ("0"), taker gives shares. USDC 2.5 / shares 5 -> price 0.5.
    log = _make_raw_log(side=0, token_id=int(TOKEN), maker_amt=2_500_000, taker_amt=5_000_000, fee=25_000)
    dec = decode_v2_orderfilled(log)
    assert dec is not None
    assert dec["makerAssetId"] == "0"
    assert dec["takerAssetId"] == TOKEN
    assert dec["makerAmountFilled"] == 2_500_000
    assert dec["takerAmountFilled"] == 5_000_000
    assert dec["fee"] == 25_000
    assert dec["tokenId"] == TOKEN
    assert dec["side"] == 0
    assert dec["blockNumber"] == 1337
    assert dec["transactionHash"] == "0xtx"
    # maker/taker preserved for future copy-trading (decision 3 in the spec)
    assert dec["maker"] == "0x" + "11" * 20
    assert dec["taker"] == "0x" + "22" * 20


def test_decode_sell_bridges_to_shares_maker_leg() -> None:
    # side=1 (SELL): maker gives shares, taker gives USDC. shares 5 / USDC 2.5 -> price 0.5.
    log = _make_raw_log(side=1, token_id=int(TOKEN), maker_amt=5_000_000, taker_amt=2_500_000, fee=0)
    dec = decode_v2_orderfilled(log)
    assert dec is not None
    assert dec["makerAssetId"] == TOKEN
    assert dec["takerAssetId"] == "0"


def test_decode_feeds_parser_to_correct_fill() -> None:
    # End-to-end: decode -> parse_orderfilled yields the expected Fill (price 0.5, size 5).
    log = _make_raw_log(side=0, token_id=int(TOKEN), maker_amt=2_500_000, taker_amt=5_000_000, fee=25_000)
    dec = decode_v2_orderfilled(log)
    assert dec is not None
    dec["timestamp"] = 1_717_200_000_000  # normally injected by enrich_timestamps
    fill = parse_orderfilled([dec])[0]
    assert fill.price == Decimal("0.5")
    assert fill.size == Decimal("5")
    assert fill.fee == Decimal("0.025")
    assert fill.token_id == TOKEN


def test_decode_skips_non_orderfilled_topic() -> None:
    log = _make_raw_log(side=0, token_id=int(TOKEN), maker_amt=1, taker_amt=2, fee=0, topic0="0xdeadbeef")
    assert decode_v2_orderfilled(log) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/data/test_polymarket_on_chain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.data.polymarket_on_chain'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/pat/data/polymarket_on_chain.py`:
```python
"""V2 CTF Exchange raw-log layer: decode OrderFilled logs + enrich with block timestamps.

ADR 0016 specifies the decode recipe. This module bridges raw eth_getLogs entries
(V2: side + tokenId) to the V1-style dict (makerAssetId / takerAssetId) that the pure
parser `pat.data.polymarket_history.parse_orderfilled` already consumes — so the parser
stays unchanged. No web3/eth-abi dependency: hand-rolled bytes.fromhex + int.from_bytes.

Network isolation: the ONLY function that touches the wire is `_rpc_get_block_timestamp`.
Monkeypatch it (or pass `get_ts=`) in tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import structlog

# keccak256("OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)")
TOPIC0_ORDERFILLED = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"

_REQUEST_TIMEOUT = 30  # seconds — explicit to satisfy ruff S113
_DATA_WORDS = 7        # side, tokenId, makerAmt, takerAmt, fee, builder, metadata

log = structlog.get_logger(__name__)


def decode_v2_orderfilled(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Decode one raw eth_getLogs entry into the dict `parse_orderfilled` expects.

    Returns None if the log is not an OrderFilled event (topics[0] mismatch).
    The returned dict carries the parser's required keys plus extras (maker/taker/
    side/tokenId/blockNumber) preserved for future copy-trading. `timestamp` is NOT
    set here — `enrich_timestamps` injects it.
    """
    topics = raw["topics"]
    if topics[0].lower() != TOPIC0_ORDERFILLED:
        return None

    maker_addr = "0x" + topics[2][-40:]
    taker_addr = "0x" + topics[3][-40:]

    data_hex = raw["data"]
    if data_hex.startswith("0x"):
        data_hex = data_hex[2:]  # NB: do NOT use lstrip("0x") — it would strip leading data zeros
    data = bytes.fromhex(data_hex)
    words = [int.from_bytes(data[i : i + 32], "big") for i in range(0, _DATA_WORDS * 32, 32)]
    side, token_id, maker_amt, taker_amt, fee, builder, metadata = words

    # Bridge V2 (side+tokenId) -> V1-style makerAssetId/takerAssetId ("0" = USDC collateral leg).
    if side == 0:  # BUY: maker gives USDC, taker gives shares
        maker_asset_id, taker_asset_id = "0", str(token_id)
    else:  # SELL: maker gives shares, taker gives USDC
        maker_asset_id, taker_asset_id = str(token_id), "0"

    return {
        "makerAssetId": maker_asset_id,
        "takerAssetId": taker_asset_id,
        "makerAmountFilled": maker_amt,
        "takerAmountFilled": taker_amt,
        "fee": fee,
        "transactionHash": raw["transactionHash"],
        # extras (not read by the parser; preserved for copy-trading / provenance)
        "orderHash": topics[1],
        "maker": maker_addr,
        "taker": taker_addr,
        "side": side,
        "tokenId": str(token_id),
        "builder": hex(builder),
        "metadata": hex(metadata),
        "blockNumber": int(raw["blockNumber"], 16),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/data/test_polymarket_on_chain.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + types**

Run: `uv run --extra dev ruff check . && uv run --extra dev mypy src`
Expected: `All checks passed!` and `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add src/pat/data/polymarket_on_chain.py tests/data/test_polymarket_on_chain.py
git commit -m "feat(data): V2 OrderFilled raw-log decoder (ADR 0016)"
```

---

## Task 2: Block-timestamp enrichment (`enrich_timestamps`)

**Files:**
- Modify: `src/pat/data/polymarket_on_chain.py` (append)
- Test: `tests/data/test_polymarket_on_chain.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_polymarket_on_chain.py`:
```python
def test_enrich_timestamps_dedups_blocks_and_scales_to_ms() -> None:
    from pat.data import polymarket_on_chain as oc

    calls: list[int] = []

    def fake_get_ts(rpc_url: str, block_number: int) -> int:
        calls.append(block_number)
        return 1_700_000_000 + block_number  # epoch SECONDS

    events = [
        {"blockNumber": 100, "transactionHash": "0xa"},
        {"blockNumber": 100, "transactionHash": "0xb"},  # same block -> no extra RPC call
        {"blockNumber": 200, "transactionHash": "0xc"},
    ]
    out = oc.enrich_timestamps(events, rpc_url="x", get_ts=fake_get_ts)

    assert calls == [100, 200]  # deduped, first-seen order
    assert out[0]["timestamp"] == (1_700_000_000 + 100) * 1000  # seconds -> ms
    assert out[1]["timestamp"] == (1_700_000_000 + 100) * 1000
    assert out[2]["timestamp"] == (1_700_000_000 + 200) * 1000


def test_enrich_timestamps_no_real_network(monkeypatch) -> None:
    from pat.data import polymarket_on_chain as oc

    def _boom(*a, **k):
        raise AssertionError("Real network call detected")

    monkeypatch.setattr(httpx, "Client", _boom)
    events = [{"blockNumber": 1, "transactionHash": "0xa"}]
    out = oc.enrich_timestamps(events, rpc_url="x", get_ts=lambda rpc_url, block_number: 1_700_000_000)
    assert out[0]["timestamp"] == 1_700_000_000 * 1000
```
Add `import httpx` at the top of the test file (with the other imports).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/data/test_polymarket_on_chain.py -k enrich -v`
Expected: FAIL — `AttributeError: module 'pat.data.polymarket_on_chain' has no attribute 'enrich_timestamps'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/pat/data/polymarket_on_chain.py`:
```python
def _rpc_get_block_timestamp(rpc_url: str, block_number: int) -> int:
    """Return the Unix epoch SECONDS for *block_number* via eth_getBlockByNumber.

    The ONLY function that touches the wire. Monkeypatch it (or pass get_ts=) in tests.
    Alchemy cost: ~20 CU per call (ADR 0016 §4).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": [hex(block_number), False],
    }
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.post(rpc_url, json=payload)
        response.raise_for_status()
        body = response.json()
    if "error" in body:
        raise RuntimeError(f"JSON-RPC error: {body['error']}")
    return int(body["result"]["timestamp"], 16)


def enrich_timestamps(
    events: list[dict[str, Any]],
    rpc_url: str,
    get_ts: Callable[[str, int], int] | None = None,
) -> list[dict[str, Any]]:
    """Inject event['timestamp'] (epoch MILLISECONDS) by looking up each block once.

    Dedups by blockNumber so we make one eth_getBlockByNumber call per unique block
    (the CU saving). `parse_orderfilled` expects timestamp in MS, so we multiply the
    block's epoch-seconds by 1000.

    get_ts defaults to the module seam, resolved at CALL time (not as a default-arg
    object) so monkeypatching `polymarket_on_chain._rpc_get_block_timestamp` works.
    """
    if get_ts is None:
        get_ts = _rpc_get_block_timestamp
    cache: dict[int, int] = {}
    for ev in events:
        block = int(ev["blockNumber"])
        if block not in cache:
            cache[block] = get_ts(rpc_url, block)
        ev["timestamp"] = cache[block] * 1000
    log.info("orderfilled.timestamps_enriched", events=len(events), unique_blocks=len(cache))
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/data/test_polymarket_on_chain.py -v`
Expected: PASS (6 tests total).

- [ ] **Step 5: Lint + types**

Run: `uv run --extra dev ruff check . && uv run --extra dev mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/pat/data/polymarket_on_chain.py tests/data/test_polymarket_on_chain.py
git commit -m "feat(data): block-timestamp enrichment with per-block dedup"
```

---

## Task 3: Gamma geopolitics 0%-fee selection (`select_geopolitics_tokens`)

**Files:**
- Create: `src/pat/venues/polymarket/gamma.py`
- Create: `tests/venues/__init__.py`, `tests/venues/polymarket/__init__.py`
- Create: `tests/venues/polymarket/test_gamma.py`
- Create: `tests/data/fixtures/gamma_events_sample.json`

- [ ] **Step 1: Create the test package dirs + fixture**

Create `tests/venues/__init__.py` (empty) and `tests/venues/polymarket/__init__.py` (empty).

Create `tests/data/fixtures/gamma_events_sample.json`:
```json
[
  {
    "id": "evt-1",
    "title": "Geopolitics event with a 0%-fee market and a politics-fee market",
    "markets": [
      {
        "question": "Will country X do Y by 2027?",
        "feesEnabled": false,
        "clobTokenIds": ["111", "222"]
      },
      {
        "question": "Will leader Z leave office in 2026?",
        "feesEnabled": true,
        "clobTokenIds": ["333", "444"]
      }
    ]
  },
  {
    "id": "evt-2",
    "title": "Event whose clobTokenIds arrives as a JSON-encoded string (real Gamma quirk)",
    "markets": [
      {
        "question": "Will treaty A be signed in 2026?",
        "feesEnabled": false,
        "clobTokenIds": "[\"555\", \"666\"]"
      }
    ]
  }
]
```

- [ ] **Step 2: Write the failing test**

Create `tests/venues/polymarket/test_gamma.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from pat.venues.polymarket.gamma import select_geopolitics_tokens

FIX = Path(__file__).parents[2] / "data" / "fixtures"


def test_select_keeps_only_feesenabled_false_tokens() -> None:
    events = [
        {"markets": [
            {"feesEnabled": False, "clobTokenIds": ["111", "222"]},
            {"feesEnabled": True, "clobTokenIds": ["333", "444"]},
        ]},
    ]
    assert select_geopolitics_tokens(events) == {"111", "222"}


def test_select_handles_clobtokenids_as_json_string() -> None:
    # Real Gamma sometimes returns clobTokenIds as a JSON-encoded string, not an array.
    events = [{"markets": [{"feesEnabled": False, "clobTokenIds": "[\"555\", \"666\"]"}]}]
    assert select_geopolitics_tokens(events) == {"555", "666"}


def test_select_excludes_market_missing_feesenabled() -> None:
    # Conservative: only explicit feesEnabled is False is treated as 0%-fee.
    events = [{"markets": [{"clobTokenIds": ["999"]}]}]
    assert select_geopolitics_tokens(events) == set()


def test_select_from_fixture() -> None:
    events = json.loads((FIX / "gamma_events_sample.json").read_text(encoding="utf-8"))
    assert select_geopolitics_tokens(events) == {"111", "222", "555", "666"}


def test_select_cross_check_drops_nonzero_base_fee() -> None:
    events = [{"markets": [{"feesEnabled": False, "clobTokenIds": ["111", "222"]}]}]
    fee_rates = {"111": 0, "222": 5}  # 222 actually charges 5 bps -> drop it

    tokens = select_geopolitics_tokens(
        events, cross_check=True, get_fee_rate=lambda token_id: fee_rates[token_id]
    )
    assert tokens == {"111"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/venues/polymarket/test_gamma.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pat.venues.polymarket.gamma'`.

- [ ] **Step 4: Write minimal implementation**

Create `src/pat/venues/polymarket/gamma.py`:
```python
"""Polymarket Gamma / CLOB selection of genuinely 0%-fee geopolitics token ids.

Per claim I9: GET gamma /events?tag_id=100265 -> events[].markets[].clobTokenIds. The
TRUE 0%-fee selector is per-market `feesEnabled == false` (NOT the tag — some geopolitics
markets carry politics_fees 4%). Optional cross-check: clob /fee-rate?token_id= base_fee==0.

Network isolation: `_gamma_get_events` and `_clob_get_fee_rate` are the only functions
that touch the wire. Monkeypatch them (or pass get_events= / get_fee_rate=) in tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import structlog

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
GEOPOLITICS_TAG_ID = 100265

_REQUEST_TIMEOUT = 30  # seconds — explicit to satisfy ruff S113

log = structlog.get_logger(__name__)


def _coerce_token_ids(raw: Any) -> list[str]:
    """clobTokenIds is sometimes a real list, sometimes a JSON-encoded string."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [str(t) for t in raw]


def _gamma_get_events(
    tag_id: int = GEOPOLITICS_TAG_ID, *, limit: int = 500, offset: int = 0
) -> list[dict[str, Any]]:
    """Fetch geopolitics events from Gamma. ONLY wire-touching Gamma function."""
    params = {"tag_id": tag_id, "limit": limit, "offset": offset}
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{GAMMA}/events", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def _clob_get_fee_rate(token_id: str) -> int:
    """Return base_fee (bps) for a CLOB token. ONLY wire-touching CLOB function."""
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{CLOB}/fee-rate", params={"token_id": token_id})
        response.raise_for_status()
        body = response.json()
    return int(body.get("base_fee", 0))


def select_geopolitics_tokens(
    events: list[dict[str, Any]],
    *,
    cross_check: bool = False,
    get_fee_rate: Callable[[str], int] | None = None,
) -> set[str]:
    """Return the set of token_ids on markets with feesEnabled == False (the 0%-fee set).

    If cross_check, additionally drop any token whose CLOB base_fee != 0. get_fee_rate
    defaults to the module seam, resolved at CALL time so monkeypatching
    `gamma._clob_get_fee_rate` works.
    """
    tokens: set[str] = set()
    for event in events:
        for market in event.get("markets", []):
            if market.get("feesEnabled") is False:
                tokens.update(_coerce_token_ids(market.get("clobTokenIds", [])))
    if cross_check:
        gr = get_fee_rate or _clob_get_fee_rate
        tokens = {t for t in tokens if gr(t) == 0}
    log.info("gamma.geopolitics_selected", tokens=len(tokens), cross_check=cross_check)
    return tokens
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/venues/polymarket/test_gamma.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Lint + types**

Run: `uv run --extra dev ruff check . && uv run --extra dev mypy src`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/pat/venues/polymarket/gamma.py tests/venues tests/data/fixtures/gamma_events_sample.json
git commit -m "feat(venues): Gamma geopolitics 0%-fee token selection (I9)"
```

---

## Task 4: Extend the fetcher — topic0 filter + NegRisk address

**Files:**
- Modify: `scripts/fetch_polymarket_history.py`
- Modify: `tests/scripts/test_fetch_mocked.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/scripts/test_fetch_mocked.py`:
```python
def test_build_getlogs_payload_includes_topics() -> None:
    from scripts.fetch_polymarket_history import _build_getlogs_payload

    payload = _build_getlogs_payload("0xADDR", 10, 20, topics=["0xTOPIC"])
    params = payload["params"][0]
    assert params["address"] == "0xADDR"
    assert params["fromBlock"] == hex(10)
    assert params["toBlock"] == hex(20)
    assert params["topics"] == ["0xTOPIC"]


def test_build_getlogs_payload_omits_topics_when_none() -> None:
    from scripts.fetch_polymarket_history import _build_getlogs_payload

    payload = _build_getlogs_payload("0xADDR", 10, 20, topics=None)
    assert "topics" not in payload["params"][0]


def test_fetch_orderfilled_logs_queries_all_addresses(monkeypatch) -> None:
    from scripts import fetch_polymarket_history as f

    seen: list[str] = []

    def fake_get_logs(rpc_url, address, from_block, to_block, topics=None):
        seen.append(address)
        return [{"address": address}]

    monkeypatch.setattr(f, "_rpc_get_logs", fake_get_logs)
    out = f.fetch_orderfilled_logs("rpc", [f.EXCHANGE_V2, f.NEGRISK_V2], 1, 2)
    assert seen == [f.EXCHANGE_V2, f.NEGRISK_V2]
    assert len(out) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/scripts/test_fetch_mocked.py -k "payload or all_addresses" -v`
Expected: FAIL — `ImportError: cannot import name '_build_getlogs_payload'` / no `NEGRISK_V2`.

- [ ] **Step 3: Modify the fetcher**

In `scripts/fetch_polymarket_history.py`:

(a) Add the topic0 import as a FIRST-PARTY import group — after `import structlog` (line 25) insert a blank line then the import (matching `run_mm_backtest.py`'s `import structlog` → blank → `from pat...` ordering, to satisfy ruff I/isort and avoid E402):
```python
import structlog

from pat.data.polymarket_on_chain import TOPIC0_ORDERFILLED
```
And add the NegRisk constant near the existing constants (after `GAMMA = ...` on line 31):
```python
# NegRisk CTF Exchange V2 — geopolitics multi-outcome markets often trade here.
# Address came from a secondary read; Task 7 verifies it (claims-verifier) before trusting it.
NEGRISK_V2 = "0xe2222d279d744050d28e00520010520000310F59"
```

(b) Add the pure payload builder and refactor `_rpc_get_logs` to use it + accept `topics`. Replace the `payload = {...}` literal inside `_rpc_get_logs` (lines 64-75) and add the new function above `_rpc_get_logs`:
```python
def _build_getlogs_payload(
    address: str, from_block: int, to_block: int, topics: list[str] | None = None
) -> dict[str, Any]:
    """Build the eth_getLogs JSON-RPC payload. Pure (no I/O) so it is unit-testable."""
    log_filter: dict[str, Any] = {
        "address": address,
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
    }
    if topics is not None:
        log_filter["topics"] = topics
    return {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [log_filter]}
```
Update `_rpc_get_logs` signature to `def _rpc_get_logs(rpc_url, address, from_block, to_block, topics=None):` and replace the inline payload with `payload = _build_getlogs_payload(address, chunk_start, chunk_end, topics)`.

(c) Add the multi-address helper below `_rpc_get_logs`:
```python
def fetch_orderfilled_logs(
    rpc_url: str,
    addresses: list[str],
    from_block: int,
    to_block: int,
) -> list[dict[str, Any]]:
    """Fetch OrderFilled logs (topic0-filtered) across all *addresses*, concatenated."""
    out: list[dict[str, Any]] = []
    for address in addresses:
        out.extend(
            _rpc_get_logs(rpc_url, address, from_block, to_block, topics=[TOPIC0_ORDERFILLED])
        )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/scripts/test_fetch_mocked.py -v`
Expected: PASS (existing 4 tests + 3 new = 7). The existing `_rpc_get_logs`-patching tests still pass (the seam name is unchanged).

- [ ] **Step 5: Lint + types + full suite**

Run: `uv run --extra dev ruff check . && uv run --extra dev mypy src && uv run --extra dev pytest -q`
Expected: clean; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch_polymarket_history.py tests/scripts/test_fetch_mocked.py
git commit -m "feat(scripts): topic0 filter + NegRisk address + multi-address fetch helper"
```

---

## Task 5: Orchestration — `fetch_geopolitics_data.py`

**Files:**
- Create: `scripts/fetch_geopolitics_data.py`
- Test: `tests/scripts/test_fetch_geopolitics_data.py`

- [ ] **Step 1: Write the failing test**

Create `tests/scripts/test_fetch_geopolitics_data.py`:
```python
from __future__ import annotations

import json

import httpx


def _raw_log(token_id: str, *, side: int = 0, maker_amt: int = 2_500_000,
             taker_amt: int = 5_000_000, fee: int = 0, tx: str = "0xtx", block: str = "0x64") -> dict:
    from tests.data.test_polymarket_on_chain import _make_raw_log

    return _make_raw_log(side=side, token_id=int(token_id), maker_amt=maker_amt,
                         taker_amt=taker_amt, fee=fee, tx=tx, block=block)


def _patch_all_seams(monkeypatch, *, geo_token: str, other_token: str, ts_calls: list[int]) -> None:
    from pat.data import polymarket_on_chain as oc
    from pat.venues.polymarket import gamma
    from scripts import fetch_geopolitics_data as g

    # Gamma: one 0%-fee market (geo_token) + one fee-bearing market (other_token).
    monkeypatch.setattr(
        gamma, "_gamma_get_events",
        lambda *a, **k: [{"markets": [
            {"feesEnabled": False, "clobTokenIds": [geo_token]},
            {"feesEnabled": True, "clobTokenIds": [other_token]},
        ]}],
    )
    # Logs: one geo fill + one non-geo fill (different blocks).
    monkeypatch.setattr(
        g, "fetch_orderfilled_logs",
        lambda *a, **k: [_raw_log(geo_token, block="0x64"), _raw_log(other_token, block="0xC8")],
    )

    def fake_ts(rpc_url, block_number):
        ts_calls.append(block_number)
        return 1_700_000_000 + block_number

    monkeypatch.setattr(oc, "_rpc_get_block_timestamp", fake_ts)


def test_orchestration_writes_geo_only_with_timestamps(monkeypatch, tmp_path) -> None:
    from scripts import fetch_geopolitics_data as g

    geo, other = "111", "999"
    ts_calls: list[int] = []
    _patch_all_seams(monkeypatch, geo_token=geo, other_token=other, ts_calls=ts_calls)

    out_path = g.run(out_dir=tmp_path, from_block=1, to_block=300, rpc_url="rpc")
    written = json.loads(out_path.read_text(encoding="utf-8"))

    assert len(written) == 1                      # only the geo fill survives the filter
    assert written[0]["tokenId"] == geo
    assert written[0]["timestamp"] == (1_700_000_000 + 100) * 1000
    assert "maker" in written[0] and "taker" in written[0]   # preserved for copy-trading
    assert ts_calls == [100]                       # timestamps fetched ONLY for the geo block (CU saving)


def test_orchestration_no_real_network(monkeypatch, tmp_path) -> None:
    from scripts import fetch_geopolitics_data as g

    ts_calls: list[int] = []
    _patch_all_seams(monkeypatch, geo_token="111", other_token="999", ts_calls=ts_calls)

    def _boom(*a, **k):
        raise AssertionError("Real network call detected")

    monkeypatch.setattr(httpx, "Client", _boom)
    g.run(out_dir=tmp_path, from_block=1, to_block=300, rpc_url="rpc")  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/scripts/test_fetch_geopolitics_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.fetch_geopolitics_data'`.

- [ ] **Step 3: Write the orchestration script**

Create `scripts/fetch_geopolitics_data.py`:
```python
"""Orchestrate the Phase-2b geopolitics data fetch into a backtest-ready decoded JSON.

Pipeline (ordered for CU economy — timestamps only for geo fills):
    Gamma select 0%-fee geopolitics tokens
    -> eth_getLogs OrderFilled across [EXCHANGE_V2, NEGRISK_V2] (topic0-filtered)
    -> decode_v2_orderfilled
    -> filter to the geopolitics token set
    -> enrich_timestamps (one eth_getBlockByNumber per unique geo block)
    -> quarantine events that fail the parser
    -> write data/raw/geopolitics_{from}_{to}.json (with maker/taker preserved)

The resulting file is consumed UNCHANGED by scripts/run_mm_backtest.py.

Network isolation: all wire I/O is in the seams of the imported modules
(gamma._gamma_get_events, gamma._clob_get_fee_rate, fetch_polymarket_history._rpc_get_logs,
polymarket_on_chain._rpc_get_block_timestamp). Tests monkeypatch those.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from pat.data.polymarket_history import parse_orderfilled
from pat.data.polymarket_on_chain import decode_v2_orderfilled, enrich_timestamps
from pat.logging import TradeJournal
from pat.venues.polymarket import gamma
from scripts.fetch_polymarket_history import EXCHANGE_V2, NEGRISK_V2, fetch_orderfilled_logs

log = structlog.get_logger(__name__)


def _validate_and_quarantine(
    events: list[dict[str, Any]], journal: TradeJournal
) -> list[dict[str, Any]]:
    """Drop events that fail the parser (price>1, size<=0, etc.), counting them."""
    clean: list[dict[str, Any]] = []
    quarantined = 0
    for ev in events:
        try:
            parse_orderfilled([ev])  # reuse the parser as the validator (DRY)
        except (ValidationError, KeyError, ValueError):
            quarantined += 1
            journal.record(event="quarantine", reason="parse_failed", tx=ev.get("transactionHash"))
            continue
        clean.append(ev)
    log.info("geopolitics.quarantine", clean=len(clean), quarantined=quarantined)
    return clean


def run(
    out_dir: Path,
    from_block: int,
    to_block: int,
    rpc_url: str | None = None,
    *,
    cross_check: bool = False,
) -> Path:
    """Produce the geopolitics-only decoded JSON for [from_block, to_block]."""
    corr_id = str(uuid.uuid4())
    effective_rpc = rpc_url or os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"geopolitics_{from_block}_{to_block}.json"
    journal = TradeJournal(
        path=out_dir / "geopolitics_fetch.jsonl", mode="backtest", corr_id=corr_id
    )
    bound = log.bind(corr_id=corr_id, from_block=from_block, to_block=to_block)

    # 1. Gamma selection
    events = gamma._gamma_get_events()
    geo_tokens = gamma.select_geopolitics_tokens(events, cross_check=cross_check)
    journal.record(event="gamma_selection", tokens=len(geo_tokens))
    bound.info("geopolitics.tokens_selected", tokens=len(geo_tokens))

    # 2. Fetch all OrderFilled across both exchanges (topic0-filtered)
    raw_logs = fetch_orderfilled_logs(
        effective_rpc, [EXCHANGE_V2, NEGRISK_V2], from_block, to_block
    )
    bound.info("geopolitics.logs_fetched", raw_logs=len(raw_logs))

    # 3. Decode (skip non-OrderFilled)
    decoded = [d for raw in raw_logs if (d := decode_v2_orderfilled(raw)) is not None]

    # 4. Filter to the geopolitics token set BEFORE timestamps (the CU saving)
    geo_events = [d for d in decoded if d["tokenId"] in geo_tokens]
    bound.info("geopolitics.filtered", decoded=len(decoded), geo=len(geo_events))

    # 5. Enrich timestamps (one RPC per unique geo block)
    geo_events = enrich_timestamps(geo_events, effective_rpc)

    # 6. Quarantine parser-failing events
    clean = _validate_and_quarantine(geo_events, journal)

    # 7. Write
    out_path.write_text(json.dumps(clean, indent=2, default=str), encoding="utf-8")
    journal.record(event="fetch_complete", raw_logs=len(raw_logs), decoded=len(decoded),
                   geo=len(geo_events), written=len(clean), out_path=str(out_path))
    bound.info("geopolitics.written", written=len(clean), out_path=str(out_path))
    return out_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch geopolitics 0%-fee OrderFilled data.")
    parser.add_argument("--from-block", type=int, required=True)
    parser.add_argument("--to-block", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--rpc-url", type=str, default=None)
    parser.add_argument("--cross-check", action="store_true",
                        help="Also verify base_fee==0 per token via the CLOB /fee-rate endpoint.")
    return parser.parse_args()


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
    result = run(out_dir=args.out_dir, from_block=args.from_block, to_block=args.to_block,
                 rpc_url=args.rpc_url, cross_check=args.cross_check)
    print(result)  # noqa: T201
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/scripts/test_fetch_geopolitics_data.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + types + full suite**

Run: `uv run --extra dev ruff check . && uv run --extra dev mypy src && uv run --extra dev pytest -q`
Expected: clean; all tests pass. (mypy covers `src` only; the script is not type-checked but keep it annotated.)

- [ ] **Step 6: Commit**

```bash
git add scripts/fetch_geopolitics_data.py tests/scripts/test_fetch_geopolitics_data.py
git commit -m "feat(scripts): geopolitics data orchestration (gamma->fetch->decode->filter->enrich)"
```

---

## Task 6: Verdict recording + journal in `run_mm_backtest`

**Files:**
- Modify: `scripts/run_mm_backtest.py`
- Modify: `tests/scripts/test_mm_backtest.py`
- Modify: `docs/strategies/market-making.md` (seed RESULTS markers)

- [ ] **Step 1: Seed the RESULTS markers in the strategy doc**

In `docs/strategies/market-making.md`, in the §7 Results area, insert these two marker lines (with a blank line between) where the results table belongs:
```markdown
<!-- RESULTS:START -->
_No verdict recorded yet — produced by `run_mm_backtest.py --record`._
<!-- RESULTS:END -->
```

- [ ] **Step 2: Write the failing test**

Append to `tests/scripts/test_mm_backtest.py`:
```python
def test_render_frontier_markdown_has_table_and_provenance() -> None:
    from decimal import Decimal

    from pat.analytics.metrics import Result, Verdict
    from scripts.run_mm_backtest import render_frontier_markdown

    rows = [{
        "half_spread": Decimal("0.02"),
        "result": Result(gross_pnl=Decimal("5"), fee_drag=Decimal("0"), net_pnl=Decimal("4"),
                         win_rate=Decimal("0.5"), max_drawdown=Decimal("1"), n_trades=1200,
                         sharpe=1.4, inventory_value=Decimal("-1")),
        "verdict": Verdict(advance=True, reason="all gates passed"),
    }]
    md = render_frontier_markdown(rows, provenance={"block_window": "100-300", "tokens": 4, "fills": 1200})

    assert "| half_spread |" in md
    assert "0.02" in md and "1200" in md and "1.4" in md
    assert "block_window" in md and "100-300" in md
    assert "per-fill" in md.lower()  # the §8 caveat note is included


def test_write_results_section_replaces_between_markers(tmp_path) -> None:
    from scripts.run_mm_backtest import write_results_section

    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Strategy\n\nintro\n<!-- RESULTS:START -->\nold\n<!-- RESULTS:END -->\n\ntail\n",
        encoding="utf-8",
    )
    write_results_section(doc, "NEW CONTENT")
    text = doc.read_text(encoding="utf-8")

    assert "NEW CONTENT" in text
    assert "old" not in text
    assert text.startswith("# Strategy")
    assert text.rstrip().endswith("tail")
    assert "<!-- RESULTS:START -->" in text and "<!-- RESULTS:END -->" in text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/scripts/test_mm_backtest.py -k "render_frontier or write_results" -v`
Expected: FAIL — `ImportError: cannot import name 'render_frontier_markdown'`.

- [ ] **Step 4: Implement the helpers**

In `scripts/run_mm_backtest.py`, add `from pathlib import Path` to the imports, then add these two functions after `print_frontier` (after line 81):
```python
RESULTS_START = "<!-- RESULTS:START -->"
RESULTS_END = "<!-- RESULTS:END -->"


def render_frontier_markdown(rows: list[dict[str, Any]], *, provenance: dict[str, Any]) -> str:
    """Render the sweep frontier as a markdown table + verdict + §8 caveats + provenance."""
    header = (
        "| half_spread | n_trades | net_pnl | gross_pnl | fee_drag "
        "| inv_value | win_rate | max_dd | sharpe | advance |"
    )
    lines = [header, "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        res, v = r["result"], r["verdict"]
        lines.append(
            f"| {r['half_spread']} | {res.n_trades} | {res.net_pnl} "
            f"| {res.gross_pnl} | {res.fee_drag} | {res.inventory_value} "
            f"| {res.win_rate:.3f} | {res.max_drawdown} | {res.sharpe:.3f} "
            f"| {v.advance} |"
        )
    prov = ", ".join(f"{k}={val}" for k, val in provenance.items())
    caveats = (
        "_Caveats (§8): sharpe is per-fill (relative ranking, not "
        "annualized); win_rate ~50% by construction for a two-sided MM "
        "(lean on net_pnl incl. inventory MtM); sharpe & max_dd are "
        "realized-only; fills are a conservative lower bound (through-trade "
        "proxy, no order book — real proof is paper, Phase 3)._"
    )
    return "\n".join(lines) + f"\n\n**Provenance:** {prov}\n\n{caveats}\n"


def write_results_section(doc_path: Path, section_md: str) -> None:
    """Replace the content between RESULTS markers in *doc_path* with *section_md*."""
    text = doc_path.read_text(encoding="utf-8")
    start = text.index(RESULTS_START) + len(RESULTS_START)
    end = text.index(RESULTS_END)
    doc_path.write_text(text[:start] + "\n" + section_md + "\n" + text[end:], encoding="utf-8")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/scripts/test_mm_backtest.py -v`
Expected: PASS (existing tests + 2 new).

- [ ] **Step 6: Wire `--record` + journal into the CLI**

In the `__main__` block of `scripts/run_mm_backtest.py`, add a `--record` argument (after the `--alpha` arg) and, after `print_frontier(rows)`, record the verdict + journal. Add:
```python
    parser.add_argument("--record", type=Path, default=None,
                        help="If set, write the frontier into the RESULTS markers of this doc "
                             "(e.g. docs/strategies/market-making.md).")
```
And after `print_frontier(rows)`:
```python
    import uuid as _uuid

    from pat.logging import TradeJournal

    corr_id = str(_uuid.uuid4())
    journal = TradeJournal(
        path=Path("logs") / "mm_backtest.jsonl", mode="backtest", corr_id=corr_id
    )
    for r in rows:
        res, v = r["result"], r["verdict"]
        journal.record(event="verdict", strategy="market_maker", reason=v.reason,
                       half_spread=str(r["half_spread"]), n_trades=res.n_trades,
                       net_pnl=str(res.net_pnl), sharpe=res.sharpe, fee=str(res.fee_drag),
                       advance=v.advance)
    if args.record is not None:
        provenance = {"json_path": args.json_path, "tokens": len(streams),
                      "max_n_trades": max((r["result"].n_trades for r in rows), default=0)}
        write_results_section(args.record, render_frontier_markdown(rows, provenance=provenance))
        log.info("mm_backtest.verdict_recorded", doc=str(args.record))
```

- [ ] **Step 7: Run lint + types + full suite**

Run: `uv run --extra dev ruff check . && uv run --extra dev mypy src && uv run --extra dev pytest -q`
Expected: clean; all tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/run_mm_backtest.py tests/scripts/test_mm_backtest.py docs/strategies/market-making.md
git commit -m "feat(scripts): MM verdict recording (markdown + journal)"
```

---

## Task 7: Real-data run, verifications, and verdict (operational)

This task runs real network calls and routes decisions through subagents. There is no new unit-test code — the deliverable is a recorded verdict and the verifications behind it. Do NOT fabricate numbers; record exactly what the run produces.

**Files:**
- Modify: `docs/research/claims-verification.md` (NegRisk entry)
- Modify: `docs/strategies/market-making.md` (§8 verdict, via `--record`)
- Create: `docs/decisions/0018-geopolitics-mm-verdict.md`
- Create: `tests/data/fixtures/orderfilled_raw_v2.json` (real raw log, Step 4b)
- Modify: `tests/data/test_polymarket_on_chain.py` (real-fixture decode assertion, Step 4b)

- [ ] **Step 1: Verify the NegRisk address + ABI (claims-verifier)**

Dispatch the `claims-verifier` subagent to confirm (against a primary source — Polygonscan verified contract + a live tx) that `0xe2222d279d744050d28e00520010520000310F59` is the NegRisk CTF Exchange V2 and that it emits the same `OrderFilled` event (same `topic0`). Record the result as a new entry in `docs/research/claims-verification.md`. If it differs, drop `NEGRISK_V2` from the address list in `fetch_geopolitics_data.run` (use `[EXCHANGE_V2]` only) and note the fallback.

- [ ] **Step 2: Resolve the starting block + run a small probe window**

Find the current Polygon block (`eth_blockNumber`) and pick a recent ~7-day window (Polygon ≈ 2 s/block ≈ ~302,400 blocks/week). (Note: the spec's optional `resolve_window(days_back)` helper is intentionally dropped — for a one-off research fetch we pass `--from-block`/`--to-block` directly; add the helper only if Phase 3 needs it reusable.) Then run:
```bash
uv run python scripts/fetch_geopolitics_data.py --from-block <START> --to-block <END> --cross-check
```
Read the structlog output: `geopolitics.tokens_selected`, `geopolitics.logs_fetched`, `geopolitics.filtered` (geo count), `geopolitics.written`. This gives geo-fills-per-week density.

- [ ] **Step 3: Grow the window to clear n≥1000**

From the density, widen the block range so the expected backtest fills reach ≥1000-2000 (note: the through-trade fill rule yields fewer fills than raw trades — budget headroom). Re-run the fetch for the larger window. Watch the Alchemy CU budget (30M/mo); if a single `eth_getLogs` chunk errors on the 10k-result cap, lower `POLYGON_MAX_BLOCK_RANGE` (env) and re-run. If geo volume genuinely cannot reach 1000, the honest outcome is "insufficient data," recorded as such — not "no edge."

- [ ] **Step 4: Run the backtest and record the verdict**

```bash
uv run python scripts/run_mm_backtest.py data/raw/geopolitics_<from>_<to>.json --record docs/strategies/market-making.md
```
This prints the frontier and writes the table + verdict into `market-making.md` §7 (between the RESULTS markers). Confirm the file changed and the numbers match the printed frontier.

- [ ] **Step 4b: Capture the golden raw-log fixture (closes the spec's Task-1 deferral + ADR 0016 follow-up)**

Fetch a tiny RAW window that contains at least one geopolitics OrderFilled (the orchestration saves decoded JSON, so use the raw fetcher here):
```bash
uv run python scripts/fetch_polymarket_history.py --from-block <B> --to-block <B+50>
```
From the written `data/raw/orderfilled_<B>_<B+50>.json`, copy ONE raw entry whose `topics[0]` is the OrderFilled topic0 and whose decoded `tokenId` is in your geopolitics set into `tests/data/fixtures/orderfilled_raw_v2.json`. Then append a real-data assertion to `tests/data/test_polymarket_on_chain.py`:
```python
def test_decode_real_raw_log_fixture() -> None:
    import json
    from pathlib import Path

    raw = json.loads((Path(__file__).parent / "fixtures" / "orderfilled_raw_v2.json").read_text(encoding="utf-8"))
    dec = decode_v2_orderfilled(raw)
    assert dec is not None
    dec["timestamp"] = 1_700_000_000_000
    fill = parse_orderfilled([dec])[0]
    assert 0 <= fill.price <= 1 and fill.size > 0   # real V2 log decodes to a valid Fill
```
Run `uv run --extra dev pytest tests/data/test_polymarket_on_chain.py -k real_raw -v` → PASS. This is the only test whose values depend on real chain data; keep its assertions range-based, not exact.

- [ ] **Step 5: Cost-model sign-off (fee-cost-auditor)**

Dispatch the `fee-cost-auditor` subagent to ratify the static `Category.GEOPOLITICS = 0` decision for this verdict: confirm the selected tokens are truly 0%-fee (`feesEnabled=false` + `/fee-rate base_fee==0`), confirm there is no hidden cost the backtest omits, and specifically review `inventory_haircut` (a raw `Decimal` in `metrics.py`, not routed through `src/pat/costs/`) as the liquidation proxy. Record the auditor's verdict.

- [ ] **Step 6: Write the verdict ADR**

Create `docs/decisions/0018-geopolitics-mm-verdict.md` (use `docs/decisions/_template.md`) capturing: the data provenance (block window, both exchanges, token count, total fills), the recorded metrics per half_spread, the gate outcome (advance or trash), the cost-model sign-off, and the next step (Phase 3 paper if it advances; trash + lessons if not). Also fill `docs/strategies/market-making.md` §8 with the prose verdict + caveats.

- [ ] **Step 7: Final verification + commit**

Run: `uv run --extra dev pytest -q && uv run --extra dev ruff check . && uv run --extra dev mypy src`
Expected: clean.
```bash
git add docs/research/claims-verification.md docs/strategies/market-making.md docs/decisions/0018-geopolitics-mm-verdict.md
git commit -m "phase2b: real geopolitics MM verdict + NegRisk/cost verifications"
```
Then update `docs/HANDOFF.md` (state + next) and commit.

---

## Notes for the executor

- **Decode bug avoided:** the ADR 0016 recipe uses `log["data"].lstrip("0x")`, which would strip
  leading data zeros (e.g. a `side=0` word). This plan uses `[2:]` / `startswith("0x")` instead.
- **Timestamp unit:** the decoder never sets `timestamp`; `enrich_timestamps` owns seconds→ms (×1000).
  The parser passes `ts` through unscaled and expects ms.
- **token_id match:** the decoder emits `tokenId` as `str(int)`; Gamma `clobTokenIds` are decimal
  strings. Task 7 must confirm they match exactly on real data (the filter depends on it).
- **CU economy:** timestamps are fetched only for geo-filtered fills (Task 5 step 3 ordering) — keep
  that order; reversing it would burn the Alchemy quota on the whole exchange's volume.
- **Golden fixture from real data:** Task 1 builds raw logs inline from known ints (robust, no
  hand-encoded hex). After the first real fetch (Task 7), commit one real raw `eth_getLogs`
  OrderFilled entry as `tests/data/fixtures/orderfilled_raw_v2.json` and add a decode assertion —
  this closes the ADR 0016 follow-up "regenerate fixtures from real V2 log data."
- **Cross-test-module import:** Task 5's test reuses `_make_raw_log` via
  `from tests.data.test_polymarket_on_chain import _make_raw_log`. There is **no** `tests/__init__.py`
  (and none is needed): `tests` resolves as a PEP-420 implicit namespace package via `pythonpath=["."]`
  (pyproject), while `tests/data/__init__.py` exists — so the dotted import resolves. If collection
  ever fails on it, either add an empty `tests/__init__.py` or copy the helper into the Task 5 test.
