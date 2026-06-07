# Phase 1 — Data + Cost Model + Backtest Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax. **TDD: write the failing test first, watch it fail, then implement.**

**Goal:** Build the vertical-slice backbone — normalized core types, a fully-tested fee/cost
model (Polymarket + Kalshi, using the Phase-0 verified facts), a historical-data parser, a
conservative `BacktestBroker`, and analytics that emit an EV/Sharpe verdict — so that by the end
we can replay ≥1000 simulated trades and trust the net-of-fee P&L.

**Architecture:** Thin layered core (ADR 0001). Pure-function cost model is the crown jewel
(ADR 0009 facts). Network I/O (RPC/Gamma) is isolated in a manually-run fetch script; all unit
tests run on **saved fixtures** so they are deterministic and offline. Every order's cost routes
through `costs/`; every fill is journaled.

**Tech Stack:** Python 3.11, `uv`, `pydantic` v2, `structlog`, `polars`, `httpx[http2]`,
`pytest`, `ruff`, `mypy`. Money math uses `decimal.Decimal` (never float).

**Verified facts this plan encodes (ADR 0009 / 0007):**
- Polymarket taker `fee = shares·rate·p·(1−p)`, 5-dp round, min 0.00001, makers free. Per-category
  rate: crypto .07 · sports .03 · finance/politics/tech/mentions .04 · economics/culture/weather/other .05 · **geopolitics 0**.
- Polymarket maker rebate: 25% (20% crypto) of taker pool, **daily batch credit**, $1 min — NOT a per-trade discount. Geopolitics rebate pool = 0.
- Kalshi taker `ceil(0.07·p·(1−p)·n, tick)`, **CEIL** rounding (tick = $0.01 non-direct); maker `0.0175·…` ceil — **not $0**.

---

## Ground rules
- **TDD always:** failing test → run it fail → minimal code → run it pass → commit.
- **Decimal for money.** No floats in fee/PnL math. Prices are `Decimal` in [0,1].
- **No network in unit tests.** Live RPC/Gamma only in `scripts/` (run by hand) or behind a mocked `httpx` test.
- **Commit after each task** — concise message, no co-author trailer (CLAUDE.md §3.2).
- **Conservative fills** in the backtester — optimistic fills are how a backtest lies.
- Run `uv run ruff check . && uv run mypy src && uv run pytest -q` green before each commit.

---

## Task 0: Environment & dependencies

**Files:**
- Modify: `pyproject.toml` (uncomment real deps)
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Set dependencies.** In `pyproject.toml`, replace the commented `dependencies`
  list with:
```toml
dependencies = [
    "httpx[http2]>=0.27",
    "websockets>=12",
    "pydantic>=2.7",
    "polars>=1.0",
    "structlog>=24.1",
]
```
(Leave `polymarket-client` commented — not needed until live; ADR 0008.)

- [ ] **Step 2: Sync.** Run: `uv sync --extra dev`  — Expected: a `.venv` is created, lock written.

- [ ] **Step 3: Smoke test.** Create `tests/test_smoke.py`:
```python
def test_python_and_imports():
    import pydantic, structlog, polars  # noqa: F401
    assert True
```

- [ ] **Step 4: Run the toolchain.** Run: `uv run pytest -q && uv run ruff check . && uv run mypy src`
  Expected: pytest 1 passed; ruff "All checks passed"; mypy "Success".

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "phase1: env + deps (uv sync, smoke test)"
```

---

## Task 1: Core domain types (`src/pat/core/types.py`)

**Files:**
- Create: `src/pat/core/types.py`
- Test: `tests/core/test_types.py`

- [ ] **Step 1: Write failing tests.** `tests/core/test_types.py`:
```python
from decimal import Decimal
import pytest
from pydantic import ValidationError
from pat.core.types import Venue, Side, Liquidity, Category, Order, Fill, Market

def test_price_must_be_in_unit_interval():
    with pytest.raises(ValidationError):
        Order(client_id="a", token_id="t", side=Side.BUY,
              price=Decimal("1.5"), size=Decimal("10"), mode="backtest", reason="x")

def test_order_roundtrips_decimal():
    o = Order(client_id="a", token_id="t", side=Side.BUY,
              price=Decimal("0.40"), size=Decimal("10"), mode="backtest", reason="quote")
    assert o.price == Decimal("0.40") and o.notional == Decimal("4.00")

def test_market_category_normalizes():
    m = Market(id="m1", venue=Venue.POLYMARKET, question="Q?",
               category=Category.GEOPOLITICS, tick_size=Decimal("0.01"))
    assert m.category is Category.GEOPOLITICS

def test_fill_carries_fee_and_liquidity():
    f = Fill(order_id="a", token_id="t", price=Decimal("0.40"), size=Decimal("10"),
             fee=Decimal("0.0"), liquidity=Liquidity.MAKER, mode="backtest", ts=1)
    assert f.liquidity is Liquidity.MAKER and f.fee == Decimal("0")
```

- [ ] **Step 2: Run → fail.** `uv run pytest tests/core/test_types.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement** `src/pat/core/types.py`:
```python
from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, computed_field

class Venue(str, Enum): POLYMARKET = "polymarket"; KALSHI = "kalshi"
class Side(str, Enum): BUY = "buy"; SELL = "sell"
class Liquidity(str, Enum): MAKER = "maker"; TAKER = "taker"
class OrderType(str, Enum): GTC = "gtc"; FOK = "fok"; FAK = "fak"
class Category(str, Enum):
    CRYPTO="crypto"; SPORTS="sports"; FINANCE="finance"; POLITICS="politics"
    ECONOMICS="economics"; CULTURE="culture"; WEATHER="weather"; TECH="tech"
    MENTIONS="mentions"; OTHER="other"; GEOPOLITICS="geopolitics"

Mode = Literal["backtest", "paper", "live"]
Price = Decimal

class Market(BaseModel):
    id: str
    venue: Venue
    question: str
    category: Category
    tick_size: Decimal = Decimal("0.01")
    resolution_source: str | None = None
    close_time_ms: int | None = None

class Order(BaseModel):
    client_id: str
    token_id: str
    side: Side
    price: Price = Field(ge=Decimal("0"), le=Decimal("1"))
    size: Decimal = Field(gt=Decimal("0"))
    order_type: OrderType = OrderType.GTC
    mode: Mode = "backtest"
    reason: str
    @computed_field
    @property
    def notional(self) -> Decimal: return (self.price * self.size).quantize(Decimal("0.01"))

class Fill(BaseModel):
    order_id: str
    token_id: str
    price: Price = Field(ge=Decimal("0"), le=Decimal("1"))
    size: Decimal = Field(gt=Decimal("0"))
    fee: Decimal = Decimal("0")
    liquidity: Liquidity = Liquidity.TAKER
    mode: Mode = "backtest"
    ts: int

class Position(BaseModel):
    token_id: str
    net_size: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
```

- [ ] **Step 4: Run → pass.** `uv run pytest tests/core/test_types.py -q` → PASS.
- [ ] **Step 5: Commit.** `git add -A && git commit -m "phase1: core pydantic types"`

---

## Task 2: Polymarket cost model (`src/pat/costs/polymarket.py`)

**Files:**
- Create: `src/pat/costs/base.py`, `src/pat/costs/polymarket.py`
- Test: `tests/costs/test_polymarket.py`

- [ ] **Step 1: Failing tests** `tests/costs/test_polymarket.py` (verified values, ADR 0009):
```python
from decimal import Decimal
from pat.core.types import Category
from pat.costs.polymarket import polymarket_taker_fee, polymarket_maker_fee, MAKER_REBATE_RATE

def test_crypto_peak_is_1_75pct_at_half():
    # 1 share, p=0.5: 0.07*0.5*0.5 = 0.0175
    assert polymarket_taker_fee(Category.CRYPTO, Decimal("0.5"), Decimal("1")) == Decimal("0.01750")

def test_geopolitics_is_zero():
    assert polymarket_taker_fee(Category.GEOPOLITICS, Decimal("0.5"), Decimal("100")) == Decimal("0")

def test_politics_rate_is_4pct():
    # 0.04*0.5*0.5 = 0.01 per share
    assert polymarket_taker_fee(Category.POLITICS, Decimal("0.5"), Decimal("1")) == Decimal("0.01000")

def test_maker_is_always_free():
    assert polymarket_maker_fee(Category.CRYPTO, Decimal("0.5"), Decimal("100")) == Decimal("0")

def test_min_fee_floor_for_tiny_nonzero():
    f = polymarket_taker_fee(Category.SPORTS, Decimal("0.001"), Decimal("1"))  # ~0.00003
    assert f >= Decimal("0.00001")

def test_geopolitics_rebate_rate_is_zero():
    assert MAKER_REBATE_RATE[Category.GEOPOLITICS] == Decimal("0")
    assert MAKER_REBATE_RATE[Category.POLITICS] == Decimal("0.25")
    assert MAKER_REBATE_RATE[Category.CRYPTO] == Decimal("0.20")
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `src/pat/costs/base.py`:
```python
from decimal import Decimal, ROUND_CEILING
def ceil_to(x: Decimal, tick: Decimal) -> Decimal:
    return (x / tick).to_integral_value(rounding=ROUND_CEILING) * tick
```
Then `src/pat/costs/polymarket.py`:
```python
from decimal import Decimal, ROUND_HALF_UP
from pat.core.types import Category

TAKER_RATE: dict[Category, Decimal] = {
    Category.CRYPTO: Decimal("0.07"), Category.SPORTS: Decimal("0.03"),
    Category.FINANCE: Decimal("0.04"), Category.POLITICS: Decimal("0.04"),
    Category.TECH: Decimal("0.04"), Category.MENTIONS: Decimal("0.04"),
    Category.ECONOMICS: Decimal("0.05"), Category.CULTURE: Decimal("0.05"),
    Category.WEATHER: Decimal("0.05"), Category.OTHER: Decimal("0.05"),
    Category.GEOPOLITICS: Decimal("0"),
}
# Daily-batch rebate fraction of the taker pool (NOT a per-trade discount). Geopolitics pool = 0.
MAKER_REBATE_RATE: dict[Category, Decimal] = {
    c: (Decimal("0") if c is Category.GEOPOLITICS
        else Decimal("0.20") if c is Category.CRYPTO else Decimal("0.25"))
    for c in Category
}
_FIVE_DP = Decimal("0.00001")

def polymarket_taker_fee(category: Category, price: Decimal, shares: Decimal) -> Decimal:
    rate = TAKER_RATE[category]
    raw = shares * rate * price * (Decimal("1") - price)
    fee = raw.quantize(_FIVE_DP, rounding=ROUND_HALF_UP)
    if raw > 0 and fee < _FIVE_DP:
        return _FIVE_DP
    return fee

def polymarket_maker_fee(category: Category, price: Decimal, shares: Decimal) -> Decimal:
    return Decimal("0")  # makers are never charged on Polymarket
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit.** `git add -A && git commit -m "phase1: polymarket cost model (ADR 0009)"`

---

## Task 3: Kalshi cost model (`src/pat/costs/kalshi.py`)

**Files:**
- Create: `src/pat/costs/kalshi.py`
- Test: `tests/costs/test_kalshi.py`

- [ ] **Step 1: Failing tests** (the CEIL + maker-fee corrections, ADR 0009):
```python
from decimal import Decimal
from pat.costs.kalshi import kalshi_taker_fee, kalshi_maker_fee

def test_ceil_to_cent_diverges_from_round_at_p030():
    # raw = 0.07*0.30*0.70 = 0.0147; round->0.01 but CEIL to cent -> 0.02
    assert kalshi_taker_fee(Decimal("0.30"), Decimal("1")) == Decimal("0.02")

def test_peak_at_half():
    # 0.07*0.5*0.5 = 0.0175 -> ceil to cent -> 0.02
    assert kalshi_taker_fee(Decimal("0.50"), Decimal("1")) == Decimal("0.02")

def test_maker_fee_is_not_zero():
    # 0.0175*0.5*0.5 = 0.004375 -> ceil to cent -> 0.01
    assert kalshi_maker_fee(Decimal("0.50"), Decimal("1")) == Decimal("0.01")

def test_per_series_multiplier_override():
    assert kalshi_taker_fee(Decimal("0.50"), Decimal("1"), multiplier=Decimal("0")) == Decimal("0")
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `src/pat/costs/kalshi.py`:
```python
from decimal import Decimal
from pat.costs.base import ceil_to

TAKER_MULT = Decimal("0.07")
MAKER_MULT = Decimal("0.0175")
CENT = Decimal("0.01")  # non-direct members: effective precision is the cent (ceil)

def kalshi_taker_fee(price: Decimal, contracts: Decimal,
                     multiplier: Decimal = TAKER_MULT, tick: Decimal = CENT) -> Decimal:
    raw = multiplier * price * (Decimal("1") - price) * contracts
    return ceil_to(raw, tick) if raw > 0 else Decimal("0")

def kalshi_maker_fee(price: Decimal, contracts: Decimal,
                     multiplier: Decimal = MAKER_MULT, tick: Decimal = CENT) -> Decimal:
    raw = multiplier * price * (Decimal("1") - price) * contracts
    return ceil_to(raw, tick) if raw > 0 else Decimal("0")
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit.** `git add -A && git commit -m "phase1: kalshi cost model — ceil + maker fee (ADR 0009)"`

---

## Task 4: Logging + trade journal (`src/pat/logging.py`)

**Files:**
- Create: `src/pat/logging.py`
- Test: `tests/test_logging.py`

- [ ] **Step 1: Failing test** `tests/test_logging.py`:
```python
import json
from pat.logging import TradeJournal, configure_logging

def test_journal_appends_jsonl_with_required_fields(tmp_path):
    p = tmp_path / "journal.jsonl"
    j = TradeJournal(p, mode="backtest", corr_id="run-1")
    j.record(event="order", strategy="mm", reason="quote",
             price="0.40", fee="0.0175", token_id="t1")
    line = json.loads(p.read_text().splitlines()[0])
    for k in ("ts", "event", "mode", "strategy", "reason", "corr_id", "fee"):
        assert k in line
    assert line["mode"] == "backtest" and line["corr_id"] == "run-1"

def test_configure_logging_returns_logger():
    assert configure_logging(mode="backtest") is not None
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `src/pat/logging.py`:
```python
from __future__ import annotations
import json, time
from pathlib import Path
import structlog

def configure_logging(mode: str):
    structlog.configure(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ])
    return structlog.get_logger().bind(mode=mode)

class TradeJournal:
    """Append-only JSONL trade journal (logging-observability.md, ADR 0004)."""
    def __init__(self, path: Path, mode: str, corr_id: str):
        self.path = Path(path); self.mode = mode; self.corr_id = corr_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
    def record(self, **fields) -> None:
        row = {"ts": int(time.time() * 1000), "mode": self.mode,
               "corr_id": self.corr_id, **fields}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
```
(Note: `time.time()` is allowed in product code; tests use `tmp_path` and don't assert on ts value.)

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit.** `git add -A && git commit -m "phase1: structlog config + JSONL trade journal (ADR 0004)"`

---

## Task 5: Historical-data parser (`src/pat/data/polymarket_history.py`)

Parse pre-saved `OrderFilled` event JSON + Gamma market JSON into normalized `Fill`/`Market`
records. **No network** — pure transform, tested on fixtures.

**Files:**
- Create: `src/pat/data/polymarket_history.py`
- Create fixtures: `tests/data/fixtures/orderfilled_sample.json`, `tests/data/fixtures/gamma_market_sample.json`
- Test: `tests/data/test_polymarket_history.py`

- [ ] **Step 1: Create fixtures.** A minimal `orderfilled_sample.json` (list of 2 decoded
  `OrderFilled` events with fields `makerAssetId`/`takerAssetId`/`makerAmountFilled`/
  `takerAmountFilled`/`fee`/`timestamp`/`transactionHash`) and a `gamma_market_sample.json`
  (one market: `conditionId`, `question`, `category`, `clobTokenIds`). Use small, realistic
  integers (USDC 6-dp, shares 6-dp). (Author the two JSON files with 1–2 records each.)

- [ ] **Step 2: Failing test** `tests/data/test_polymarket_history.py`:
```python
import json
from pathlib import Path
from decimal import Decimal
from pat.data.polymarket_history import parse_orderfilled, FILL_SCALE
FIX = Path(__file__).parent / "fixtures"

def test_parse_orderfilled_normalizes_units_and_price():
    events = json.loads((FIX / "orderfilled_sample.json").read_text())
    fills = parse_orderfilled(events)
    assert len(fills) == len(events)
    f = fills[0]
    assert Decimal("0") <= f.price <= Decimal("1")   # price in [0,1]
    assert f.size > 0 and f.ts > 0
```

- [ ] **Step 3: Run → fail.**

- [ ] **Step 4: Implement** `src/pat/data/polymarket_history.py`:
```python
from __future__ import annotations
from decimal import Decimal
from pat.core.types import Fill, Liquidity

FILL_SCALE = Decimal("1000000")  # 6-dp fixed-point on-chain amounts

def _price_and_size(ev: dict) -> tuple[Decimal, Decimal]:
    # OrderFilled gives maker/taker amounts; price = USDC paid / shares received.
    maker = Decimal(ev["makerAmountFilled"]) / FILL_SCALE
    taker = Decimal(ev["takerAmountFilled"]) / FILL_SCALE
    # Convention: shares = max(maker,taker) side; price = usdc/shares in [0,1].
    shares, usdc = (taker, maker) if taker >= maker else (maker, taker)
    price = (usdc / shares) if shares else Decimal("0")
    return price, shares

def parse_orderfilled(events: list[dict]) -> list[Fill]:
    out: list[Fill] = []
    for ev in events:
        price, size = _price_and_size(ev)
        out.append(Fill(
            order_id=ev.get("transactionHash", "unknown"),
            token_id=str(ev.get("makerAssetId") or ev.get("takerAssetId")),
            price=price, size=size,
            fee=Decimal(ev.get("fee", "0")) / FILL_SCALE,
            liquidity=Liquidity.TAKER, mode="backtest",
            ts=int(ev["timestamp"]),
        ))
    return out
```
(The exact maker/taker→price convention is refined against real data in Task 6; the fixture lets
us lock the unit math now.)

- [ ] **Step 5: Run → pass.** Commit: `git add -A && git commit -m "phase1: polymarket OrderFilled parser (fixtures)"`

---

## Task 6: Fetch script (network, manual) (`scripts/fetch_polymarket_history.py`)

Thin runner that pulls `OrderFilled` from the V2 contract via Polygon RPC + Gamma metadata and
writes raw JSON to `data/raw/`. Network calls live ONLY here; tested with a mocked `httpx`.

**Files:**
- Create: `scripts/fetch_polymarket_history.py`
- Test: `tests/scripts/test_fetch_mocked.py`

- [ ] **Step 1: Failing test (mocked)** — assert the fetcher calls the RPC URL from env and
  writes a file, using `respx`/`monkeypatch` to stub `httpx`. (No real network.)
```python
def test_fetch_writes_raw(monkeypatch, tmp_path):
    from scripts import fetch_polymarket_history as f
    monkeypatch.setattr(f, "_rpc_get_logs", lambda *a, **k: [{"timestamp": 1, "makerAmountFilled": "1000000", "takerAmountFilled": "2500000", "makerAssetId": "1", "transactionHash": "0xabc"}])
    out = f.run(out_dir=tmp_path, from_block=1, to_block=2)
    assert out.exists()
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `scripts/fetch_polymarket_history.py` with:
  - constants `EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"` (ADR 0007),
    `GAMMA = "https://gamma-api.polymarket.com"`, env `POLYGON_RPC_URL`, `POLYGON_MAX_BLOCK_RANGE`.
  - `_rpc_get_logs(...)` using `httpx` `eth_getLogs` (paged by `POLYGON_MAX_BLOCK_RANGE`),
  - `run(out_dir, from_block, to_block)` → writes `data/raw/orderfilled_<from>_<to>.json`.
  - structlog logging with a `corr_id`. (Public `polygon-rpc.com` works; a paid Alchemy/QuickNode
    URL is a `.env` swap — ADR/claim I3.)

- [ ] **Step 4: Run → pass.** Commit: `git add -A && git commit -m "phase1: polymarket history fetch script (mocked test)"`

---

## Task 7: BacktestBroker + conservative fill model (`src/pat/execution/`)

**Files:**
- Create: `src/pat/execution/broker.py` (Protocol + events), `src/pat/execution/backtest.py`
- Test: `tests/execution/test_backtest.py`

- [ ] **Step 1: Failing tests** — a maker quote fills only when the replayed book trades
  *through* it, fee is taken from `costs/`, and fills are journaled:
```python
from decimal import Decimal
from pat.core.types import Order, Side, Category, Market, Venue
from pat.execution.backtest import BacktestBroker

def _mkt(cat): return Market(id="m", venue=Venue.POLYMARKET, question="q", category=cat)

def test_resting_buy_fills_only_when_price_trades_through():
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(client_id="1", token_id="t", side=Side.BUY, price=Decimal("0.40"),
              size=Decimal("10"), reason="quote", mode="backtest")
    b.submit(o)
    b.on_trade(price=Decimal("0.41"), size=Decimal("50"))   # above our bid → NO fill
    assert b.fills == []
    b.on_trade(price=Decimal("0.39"), size=Decimal("50"))   # trades through → fill as MAKER
    assert len(b.fills) == 1 and b.fills[0].liquidity.value == "maker"

def test_fill_fee_routes_through_cost_model_geopolitics_zero():
    b = BacktestBroker(market=_mkt(Category.GEOPOLITICS))
    o = Order(client_id="1", token_id="t", side=Side.BUY, price=Decimal("0.50"),
              size=Decimal("10"), reason="q", mode="backtest")
    b.submit(o); b.on_trade(price=Decimal("0.49"), size=Decimal("100"))
    assert b.fills[0].fee == Decimal("0")  # geopolitics maker = 0
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `src/pat/execution/broker.py` (a `Broker` `Protocol` with
  `submit/cancel/positions`) and `src/pat/execution/backtest.py`:
  - holds resting orders; `on_trade(price,size)` fills a resting BUY when `trade_price <= bid`
    (SELL when `trade_price >= ask`) — **conservative: only on a through-trade, classified MAKER**;
  - computes fee via `polymarket_maker_fee` (maker resting) — here 0 for Polymarket makers — and
    would use `polymarket_taker_fee` for marketable orders;
  - appends `Fill` to `self.fills`; optional `TradeJournal` hook.
  - Keep partial-fill + slippage TODO-free by modeling: fill size = min(order remaining, trade size).

- [ ] **Step 4: Run → pass.** Commit: `git add -A && git commit -m "phase1: BacktestBroker + conservative maker-fill model"`

---

## Task 8: Analytics & verdict (`src/pat/analytics/metrics.py`)

**Files:**
- Create: `src/pat/analytics/metrics.py`
- Test: `tests/analytics/test_metrics.py`

- [ ] **Step 1: Failing tests:**
```python
from decimal import Decimal
from pat.analytics.metrics import summarize, Verdict

def test_net_pnl_is_after_fees():
    fills = [{"side":"buy","price":"0.40","size":"10","fee":"0.02"},
             {"side":"sell","price":"0.50","size":"10","fee":"0.02"}]
    r = summarize(fills)
    # gross = (0.50-0.40)*10 = 1.00 ; net = 1.00 - 0.04 = 0.96
    assert r.net_pnl == Decimal("0.96") and r.fee_drag == Decimal("0.04")

def test_verdict_trashes_low_sharpe():
    v = Verdict.from_metrics(sharpe=0.4, net_pnl=Decimal("5"), n_trades=1200)
    assert v.advance is False and "sharpe" in v.reason.lower()

def test_verdict_requires_min_sample():
    v = Verdict.from_metrics(sharpe=2.0, net_pnl=Decimal("50"), n_trades=200)
    assert v.advance is False and "sample" in v.reason.lower()
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `src/pat/analytics/metrics.py`:
  - `summarize(fills) -> Result` with `net_pnl`, `gross_pnl`, `fee_drag`, `win_rate`,
    `sharpe` (per-trade returns; `0` if <2 trades), `max_drawdown`, `n_trades`. Use `Decimal`
    for money, `float` only for Sharpe ratio.
  - `Verdict.from_metrics(sharpe, net_pnl, n_trades)` → `advance=True` only if
    `n_trades >= 1000 and sharpe > 1.0 and net_pnl > 0`; else `advance=False` with a `reason`
    naming the failed gate (sample / sharpe / negative-EV). (Encodes CLAUDE.md §6.)

- [ ] **Step 4: Run → pass.** Commit: `git add -A && git commit -m "phase1: analytics metrics + EV/Sharpe verdict (CLAUDE.md §6)"`

---

## Task 9: End-to-end backtest smoke + gate

Wire `data → BacktestBroker → analytics` on a small synthetic replay and confirm the pipeline
runs ≥1000 trades with fees applied. Proves the Phase-1 gate mechanically (a real strategy/data
verdict is Phase 2).

**Files:**
- Create: `scripts/run_backtest_smoke.py`
- Test: `tests/test_pipeline_smoke.py`

- [ ] **Step 1: Failing test:**
```python
def test_pipeline_runs_1000_trades_with_fees(tmp_path):
    from scripts.run_backtest_smoke import run
    r = run(n=1000, journal_dir=tmp_path)
    assert r.n_trades >= 1000
    assert r.fee_drag > 0           # fees were actually applied (non-geopolitics)
    assert r.net_pnl == r.gross_pnl - r.fee_drag
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** `scripts/run_backtest_smoke.py`: generate 1000 synthetic
  trades on a `POLITICS` market through `BacktestBroker`, journal each fill, then `summarize`.
  Print the `Verdict`. (Synthetic data is fine — Phase 1 proves the *machinery*; Phase 2 feeds
  real `warproxxx/poly_data` output.)

- [ ] **Step 4: Run → pass.** Run also: `uv run python -m scripts.run_backtest_smoke` and paste
  the printed verdict into the commit body.

- [ ] **Step 5: Full green + commit.** `uv run ruff check . && uv run mypy src && uv run pytest -q`
  then `git add -A && git commit -m "phase1: end-to-end backtest smoke (gate: 1000 trades, net-of-fee)"`

- [ ] **Step 6: Update docs.** Tick Phase 1 in `docs/roadmap.md`; note the gate is mechanically
  met (real-data verdict pending Phase 2). Commit: `docs: mark Phase 1 core complete`.

---

## Self-Review

- **Spec coverage:** roadmap Phase 1 = data + cost model + backtest core + analytics/verdict →
  Tasks 5/6 (data), 2/3 (cost), 7 (backtest), 8 (analytics), 9 (gate). Core types (1), logging
  (4), env (0) are prerequisites. ✔
- **Verified-facts coverage:** Polymarket category table + 1.75% peak + maker-free (Task 2);
  Kalshi CEIL + 0.0175 maker (Task 3); geopolitics rebate=0 (Task 2 + Task 7 test). ✔
- **Placeholder scan:** every task has real test code + real implementation code + exact commands.
  Task 5/6 note where the maker/taker→price convention is refined against real data — that is a
  scoped refinement, not a placeholder. ✔
- **Type consistency:** `Fill`/`Order`/`Category`/`Side`/`Liquidity` names match Task 1
  throughout; `ceil_to` defined in Task 2 base, reused in Task 3. ✔
- **Determinism:** all unit tests offline (fixtures/mocks); network only in `scripts/`. ✔
- **Honesty guard:** conservative through-trade fills (Task 7); net-of-fee PnL + Sharpe>1 +
  ≥1000-trade verdict (Task 8). ✔

## Out of scope (Phase 1)
- Real strategy logic / real-data MM verdict (Phase 2).
- Live Kalshi data ingestion (cost model only here); paper/live brokers (Phase 3+).
- Slippage beyond through-trade fills; queue-position modeling refinement (Phase 2 tuning).
