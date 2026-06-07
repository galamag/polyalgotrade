# Phase 2 — Market Making (B1, geopolitics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully-tested market-making backtest pipeline for low-liquidity geopolitics markets (simple fixed-spread quoting), producing an honest net-of-fee EV/Sharpe verdict.

**Architecture:** A `Strategy` plugin emits post/cancel `OrderAction`s in reaction to a replayed trade stream; the existing `BacktestBroker` (conservative through-trade fill model) executes them. A replay loop wires strategy↔broker with **no look-ahead** (the broker matches each trade against *pre-existing* quotes before the strategy requotes). Analytics gains **inventory mark-to-market** so a strategy that ends a window holding inventory is valued honestly. A parameter-sweep runner finds the +EV frontier. Tasks 1–7 are fully offline-testable; Task 8 runs it on real geopolitics data (RPC-gated).

**Tech Stack:** Python 3.11+, `pydantic` v2, `decimal.Decimal` for all money, `pytest`, `ruff`, `mypy`, `uv`. Fees route through `src/pat/costs/` only. Same strategy code runs across `BacktestBroker`/`PaperBroker`/`LiveBroker` (CLAUDE.md principle 8).

**Spec:** `docs/superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md` Section 2.
**Decisions folded in:** ADR 0012 (inventory MtM + `assetId=="0"` parser fix are entry criteria). Geopolitics = 0% taker / 0 rebate → pure spread (ADR 0009). Geopolitics resolves via UMA → flatten before resolution (ADR 0010).

**Definition of done (every task):** `uv run pytest <task tests> -v` green; `uv run ruff check .` clean; `uv run mypy src` clean; commit. Never claim pass without showing command output.

**Out of scope (Phase 3+):** the live `risk/` controls — bankroll-% sizing, kill-switch, flatten-before-resolution (UMA), drawdown stop — are paper/live concerns; in the backtest the only risk knobs are `size` and `inventory_cap`. Async `PaperBroker`/`LiveBroker` are also Phase 3. This plan delivers the **backtest verdict** only.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `src/pat/analytics/metrics.py` (modify) | add inventory mark-to-market to `summarize()` | 1 |
| `src/pat/data/polymarket_history.py` (modify) | identify USDC leg via `assetId=="0"` (not magnitude) | 2 |
| `src/pat/strategies/base.py` (create) | `OrderAction` (`PostOrder`/`CancelOrder`) + `Strategy` protocol | 3 |
| `src/pat/execution/broker.py` (modify) | add `cancel()` to `Broker` protocol | 4 |
| `src/pat/execution/backtest.py` (modify) | implement `cancel()`; `on_trade()` returns new fills | 4 |
| `src/pat/strategies/market_maker.py` (create) | fixed-spread MM: EWMA fair value, inventory cap | 5 |
| `src/pat/execution/replay.py` (create) | no-look-ahead strategy↔broker replay loop | 6 |
| `scripts/run_mm_backtest.py` (create) | parameter sweep → frontier of Result+Verdict | 7 |
| `docs/strategies/market-making.md` (modify) | record real-data verdict | 8 |

New test dirs need an `__init__.py` (mirrors existing `tests/*/__init__.py`) — **except `tests/scripts/`, which deliberately has NO `__init__.py`** (it would shadow the root `scripts/` package and break `from scripts... import`). Tasks 7–8 add files under the existing `tests/scripts/` and must **NOT** create `tests/scripts/__init__.py`.

---

## Task 1: Inventory mark-to-market in analytics

**Why:** `summarize()` today computes `gross_pnl = Σsells − Σbuys` (realized cash-flow only). An MM almost always ends a window holding inventory; without marking it, the verdict lies (ADR 0012, "the single most important analytics gap"). We value residual inventory at **last trade price − a liquidation haircut** (cost of crossing to flatten). Backward-compatible: when no `marks` are passed, behaviour is unchanged.

**Files:**
- Modify: `src/pat/analytics/metrics.py`
- Test: `tests/analytics/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/analytics/test_metrics.py`:

```python
# ---------------------------------------------------------------------------
# Inventory mark-to-market (ADR 0012)
# ---------------------------------------------------------------------------


def test_long_inventory_marked_at_last_minus_haircut() -> None:
    """Open long valued at net_size*mark - |net_size|*haircut, added to net_pnl."""
    fills = [{"side": "buy", "price": "0.40", "size": "10", "fee": "0.00", "token_id": "t"}]
    r = summarize(fills, marks={"t": Decimal("0.50")}, inventory_haircut=Decimal("0.01"))
    # gross (realized) = -4.00 ; inventory_value = 10*0.50 - 10*0.01 = 4.90
    # net = gross + inventory_value - fee = -4.00 + 4.90 - 0.00 = 0.90
    assert r.inventory_value == Decimal("4.90")
    assert r.net_pnl == Decimal("0.90")


def test_short_inventory_marked() -> None:
    """Open short is a liability: net_size negative; closing costs the haircut too."""
    fills = [{"side": "sell", "price": "0.60", "size": "10", "fee": "0.00", "token_id": "t"}]
    r = summarize(fills, marks={"t": Decimal("0.50")}, inventory_haircut=Decimal("0.01"))
    # gross = +6.00 ; inventory_value = -10*0.50 - 10*0.01 = -5.10 ; net = 6.00 - 5.10 = 0.90
    assert r.inventory_value == Decimal("-5.10")
    assert r.net_pnl == Decimal("0.90")


def test_balanced_inventory_has_zero_value() -> None:
    """A flat book (net 0) contributes no inventory value."""
    fills = [
        {"side": "buy", "price": "0.40", "size": "10", "fee": "0.00", "token_id": "t"},
        {"side": "sell", "price": "0.50", "size": "10", "fee": "0.00", "token_id": "t"},
    ]
    r = summarize(fills, marks={"t": Decimal("0.45")}, inventory_haircut=Decimal("0.01"))
    assert r.inventory_value == Decimal("0")
    assert r.net_pnl == Decimal("1.00")  # realized only


def test_no_marks_is_realized_only_and_backward_compatible() -> None:
    """Without marks, inventory_value is 0 and net_pnl is the legacy realized number."""
    fills = [{"side": "buy", "price": "0.40", "size": "10", "fee": "0.02"}]
    r = summarize(fills)
    assert r.inventory_value == Decimal("0")
    assert r.net_pnl == Decimal("-4.02")


def test_marks_without_token_id_raises() -> None:
    """If marks are supplied, every fill must carry token_id."""
    import pytest

    fills = [{"side": "buy", "price": "0.40", "size": "10", "fee": "0.00"}]
    with pytest.raises(ValueError, match="token_id"):
        summarize(fills, marks={"t": Decimal("0.50")})
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/analytics/test_metrics.py -k "inventory or marks or backward" -v`
Expected: FAIL (`summarize()` has no `marks`/`inventory_haircut` params; `Result` has no `inventory_value`).

- [ ] **Step 3: Implement**

In `src/pat/analytics/metrics.py`:

(a) Add a field to `Result` (after `sharpe`, with a default so it is last):

```python
    sharpe: float
    inventory_value: Decimal = Decimal("0")  # mark-to-market of residual open inventory
```

(b) Change the `summarize` signature and add the inventory computation. Replace the signature line and the two `Result(...)` return sites:

```python
def summarize(
    fills: list[dict[str, Any]],
    marks: dict[str, Decimal] | None = None,
    inventory_haircut: Decimal = Decimal("0"),
) -> Result:
```

In the empty-fills early return, add `inventory_value=Decimal("0"),`.

After `net_pnl = gross_pnl - fee_drag` compute the inventory adjustment and fold it in:

```python
    inventory_value = (
        _inventory_value(fills, marks, inventory_haircut)
        if marks is not None
        else Decimal("0")
    )
    net_pnl = gross_pnl + inventory_value - fee_drag
```

In the final `Result(...)` return, add `inventory_value=inventory_value,`.

(c) Add the helper near the other private helpers:

```python
def _inventory_value(
    fills: list[dict[str, Any]],
    marks: dict[str, Decimal],
    haircut: Decimal,
) -> Decimal:
    """Mark-to-market of residual open inventory per token.

    value = Σ_token [ net_size * mark − |net_size| * haircut ]
    where net_size = Σ(+size for buy, −size for sell).  The haircut is the cost
    of crossing the spread to flatten; it always reduces value (long or short).
    """
    inv: dict[str, Decimal] = {}
    for fill in fills:
        token = fill.get("token_id")
        if token is None:
            msg = "inventory mark-to-market requires 'token_id' on every fill"
            raise ValueError(msg)
        size = Decimal(str(fill["size"]))
        signed = size if fill["side"] == "buy" else -size
        inv[token] = inv.get(token, Decimal("0")) + signed

    total = Decimal("0")
    for token, net in inv.items():
        if net == Decimal("0"):
            continue
        mark = marks.get(token)
        if mark is None:
            msg = f"no mark price supplied for token {token!r}"
            raise ValueError(msg)
        total += net * mark - abs(net) * haircut
    return total
```

(d) Update the module docstring's HONESTY RULE block to note: `net_pnl = gross_pnl + inventory_value − fee_drag` (inventory marked at last − haircut; Sharpe/drawdown remain realized-only, a documented limitation — terminal MtM is a point estimate, not a per-fill series).

- [ ] **Step 4: Run to verify pass + no regressions**

Run: `uv run pytest tests/analytics/test_metrics.py -v`
Expected: PASS (all new + all pre-existing metrics tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy src
git add src/pat/analytics/metrics.py tests/analytics/test_metrics.py
git commit -m "phase2: inventory mark-to-market in analytics (ADR 0012 prereq)"
```

---

## Task 2: Parser identifies the USDC leg via `assetId=="0"`

**Why:** `_price_and_size` uses a magnitude heuristic ("larger leg is shares"), fragile near price 1.0 (ADR 0012). The collateral (USDC) leg is authoritatively the one with `assetId == "0"`. Switch to that, falling back to the heuristic only for the rare token/token swap (neither leg is collateral).

**Files:**
- Modify: `src/pat/data/polymarket_history.py`
- Test: `tests/data/test_polymarket_history.py`

- [ ] **Step 1: Write the failing test (discriminating) + happy-path assertions**

Note: for *valid* data the old magnitude heuristic is accidentally correct (usdc = price·shares ≤ shares whenever price ≤ 1), so it only misbehaves on price-1 ties and corrupt data. The test that **drives** the fix is therefore the authority case: when the USDC leg has *more* units than the shares leg (corrupt / price > 1), the old heuristic silently swaps legs to force price ≤ 1, hiding the bad data; the assetId-based code keeps the USDC leg authoritative and lets pydantic surface the anomaly.

Append to `tests/data/test_polymarket_history.py`:

```python
def test_price_from_taker_collateral_leg() -> None:
    """takerAssetId=='0' → taker is USDC, maker is shares; price = usdc/shares."""
    events = [{
        "makerAssetId": "999", "takerAssetId": "0",
        "makerAmountFilled": 4_000_000, "takerAmountFilled": 3_600_000,  # 4 shares, 3.6 USDC
        "fee": 0, "timestamp": 1, "transactionHash": "0xaa",
    }]
    f = parse_orderfilled(events)[0]
    assert f.price == Decimal("0.9") and f.size == Decimal("4")


def test_price_from_maker_collateral_leg() -> None:
    """makerAssetId=='0' → maker is USDC, taker is shares."""
    events = [{
        "makerAssetId": "0", "takerAssetId": "888",
        "makerAmountFilled": 950_000, "takerAmountFilled": 1_000_000,  # 0.95 USDC, 1 share
        "fee": 0, "timestamp": 1, "transactionHash": "0xbb",
    }]
    f = parse_orderfilled(events)[0]
    assert f.price == Decimal("0.95") and f.size == Decimal("1")


def test_usdc_leg_is_authoritative_not_magnitude() -> None:
    """Corrupt event: USDC leg (maker, assetId 0) has MORE units than the shares leg.

    Correct: USDC=1.5, shares=1.0 → price 1.5 → pydantic rejects (anomaly surfaced).
    Old heuristic would call the larger (1.5) leg 'shares' → price 0.667, hiding it.
    """
    import pytest
    from pydantic import ValidationError

    events = [{
        "makerAssetId": "0", "takerAssetId": "888",
        "makerAmountFilled": 1_500_000, "takerAmountFilled": 1_000_000,  # 1.5 USDC, 1.0 shares
        "fee": 0, "timestamp": 1, "transactionHash": "0xcc",
    }]
    with pytest.raises(ValidationError):
        parse_orderfilled(events)
```

- [ ] **Step 2: Run to verify the discriminating test fails**

Run: `uv run pytest tests/data/test_polymarket_history.py -k "collateral or authoritative" -v`
Expected: `test_usdc_leg_is_authoritative_not_magnitude` FAILS on the old code (no exception — the heuristic swaps legs to price 0.667). The two collateral happy-path tests pass either way. After the fix all three pass.

- [ ] **Step 3: Implement**

Replace `_price_and_size` in `src/pat/data/polymarket_history.py`:

```python
def _price_and_size(ev: dict[str, object]) -> tuple[Decimal, Decimal]:
    """Return (price, shares) from a raw OrderFilled event dict.

    The collateral (USDC) leg is authoritatively the one with assetId == "0".
    The other leg is shares.  price = usdc / shares.  If neither leg is
    collateral (rare token/token swap), fall back to the magnitude heuristic.
    """
    maker_id = str(ev.get("makerAssetId", ""))
    taker_id = str(ev.get("takerAssetId", ""))
    maker_amt = Decimal(str(ev["makerAmountFilled"])) / FILL_SCALE
    taker_amt = Decimal(str(ev["takerAmountFilled"])) / FILL_SCALE

    if taker_id == "0":
        usdc, shares = taker_amt, maker_amt
    elif maker_id == "0":
        usdc, shares = maker_amt, taker_amt
    else:
        # Neither leg is USDC collateral — fall back to magnitude (larger = shares).
        log.warning("orderfilled.no_collateral_leg", maker_id=maker_id, taker_id=taker_id)
        if taker_amt >= maker_amt:
            shares, usdc = taker_amt, maker_amt
        else:
            shares, usdc = maker_amt, taker_amt

    price = (usdc / shares) if shares else Decimal("0")
    return price, shares
```

- [ ] **Step 4: Run to verify pass + no regressions**

Run: `uv run pytest tests/data/test_polymarket_history.py -v`
Expected: PASS (new tests + the original fixture tests — fixture event 0 has `takerAssetId=="0"`, so price=2.5/5=0.5 unchanged).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy src
git add src/pat/data/polymarket_history.py tests/data/test_polymarket_history.py
git commit -m "phase2: parser identifies USDC leg via assetId==0 (ADR 0012 prereq)"
```

---

## Task 3: Strategy interface (`OrderAction` + `Strategy` protocol)

**Why:** One strategy must run unchanged across all three brokers (CLAUDE.md principle 8). The strategy is pure decision logic that *reacts* to trade events and emits intentions (post/cancel); the broker owns fills.

**Files:**
- Create: `src/pat/strategies/base.py`
- Create: `tests/strategies/__init__.py` (empty)
- Test: `tests/strategies/test_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/strategies/test_base.py`:

```python
from decimal import Decimal

from pat.core.types import Fill, Order, Side
from pat.strategies.base import CancelOrder, PostOrder, Strategy


def _order() -> Order:
    return Order(client_id="c1", token_id="t", side=Side.BUY,
                 price=Decimal("0.40"), size=Decimal("10"), reason="q", mode="backtest")


def test_post_and_cancel_actions_carry_payload() -> None:
    p = PostOrder(order=_order())
    c = CancelOrder(client_id="c1")
    assert p.order.client_id == "c1"
    assert c.client_id == "c1"


def test_actions_are_frozen() -> None:
    import dataclasses
    import pytest

    c = CancelOrder(client_id="c1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.client_id = "c2"  # type: ignore[misc]


def test_a_minimal_strategy_satisfies_the_protocol() -> None:
    class Noop:
        def on_trade(self, price: Decimal, size: Decimal) -> list:
            return []

        def on_fills(self, fills: list[Fill]) -> None:
            return None

    assert isinstance(Noop(), Strategy)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/strategies/test_base.py -v`
Expected: FAIL (`pat.strategies.base` does not exist).

- [ ] **Step 3: Implement**

Create `src/pat/strategies/base.py`:

```python
"""Strategy plugin interface — one strategy, three brokers (CLAUDE.md principle 8).

A Strategy reacts to trade events and emits OrderActions (post/cancel).  It owns
no execution: the broker matches and fills.  The same code runs against
BacktestBroker, PaperBroker, and LiveBroker.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pat.core.types import Fill, Order


@dataclass(frozen=True)
class PostOrder:
    """Intent to rest a new limit order."""

    order: Order


@dataclass(frozen=True)
class CancelOrder:
    """Intent to cancel a resting order by its client_id."""

    client_id: str


OrderAction = PostOrder | CancelOrder


@runtime_checkable
class Strategy(Protocol):
    """Pure decision logic. Stateful across calls; emits intents, never fills."""

    def on_trade(self, price: Decimal, size: Decimal) -> list[OrderAction]:
        """React to an observed trade; return quote post/cancel intents."""
        ...

    def on_fills(self, fills: list[Fill]) -> None:
        """Receive fills produced by the broker so the strategy can update state."""
        ...
```

> **Spec reconciliation:** the spec's `on_event(...)` contract is realised here as
> `on_trade(price, size)` for the trade-only v1 (a backtest has only trade events). Paper/live may
> add a book callback later; the post/cancel intent model is unchanged.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/strategies/test_base.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy src
git add src/pat/strategies/base.py tests/strategies/__init__.py tests/strategies/test_base.py
git commit -m "phase2: Strategy protocol + OrderAction (post/cancel)"
```

---

## Task 4: BacktestBroker — `cancel()` and fill-returning `on_trade()`

**Why:** An MM requotes constantly, so it must be able to **cancel** stale quotes (else the book accumulates and double-fills). The replay loop also needs the fills produced by each trade to feed back to the strategy's inventory, so `on_trade()` must return them. Both changes are backward-compatible (existing callers ignore the return value).

**Files:**
- Modify: `src/pat/execution/broker.py`
- Modify: `src/pat/execution/backtest.py`
- Test: `tests/execution/test_backtest.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/execution/test_backtest.py`:

```python
def test_cancel_removes_resting_order() -> None:
    """A cancelled order does not fill on a subsequent through-trade."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(client_id="x", token_id="t", side=Side.BUY, price=Decimal("0.40"),
              size=Decimal("10"), reason="q", mode="backtest")
    b.submit(o)
    b.cancel("x")
    b.on_trade(price=Decimal("0.30"), size=Decimal("50"))
    assert b.fills == []


def test_cancel_unknown_id_is_noop() -> None:
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    b.cancel("nope")  # must not raise


def test_on_trade_returns_new_fills() -> None:
    b = BacktestBroker(market=_mkt(Category.GEOPOLITICS))
    o = Order(client_id="x", token_id="t", side=Side.BUY, price=Decimal("0.40"),
              size=Decimal("10"), reason="q", mode="backtest")
    b.submit(o)
    produced = b.on_trade(price=Decimal("0.39"), size=Decimal("50"))
    assert len(produced) == 1 and produced[0].order_id == "x"


def test_on_trade_returns_empty_when_no_fill() -> None:
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(client_id="x", token_id="t", side=Side.BUY, price=Decimal("0.40"),
              size=Decimal("10"), reason="q", mode="backtest")
    b.submit(o)
    assert b.on_trade(price=Decimal("0.41"), size=Decimal("50")) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/execution/test_backtest.py -k "cancel or returns" -v`
Expected: FAIL (`cancel` missing; `on_trade` returns `None`).

- [ ] **Step 3: Implement**

In `src/pat/execution/broker.py`, add to the `Broker` protocol (after `on_trade`):

```python
    def cancel(self, client_id: str) -> None:
        """Remove a resting order by client_id. No-op if not present."""
        ...
```

Change the `on_trade` return annotation in the protocol to `-> list[Fill]` and import `Fill`:

```python
from pat.core.types import Fill, Order, Position
```
```python
    def on_trade(self, price: Decimal, size: Decimal) -> list[Fill]:
```

In `src/pat/execution/backtest.py`:

(a) Add the `cancel` method (after `submit`):

```python
    def cancel(self, client_id: str) -> None:
        """Remove a resting order by client_id (no-op if absent)."""
        self._book = [r for r in self._book if r.order.client_id != client_id]
        if self._journal is not None:
            self._journal.record(event="cancel", client_id=client_id, mode="backtest")
```

(b) Change `on_trade` to collect and return the fills it produces. Change its signature to `-> list[Fill]`, add `new_fills: list[Fill] = []` at the top, `new_fills.append(fill)` right after `self.fills.append(fill)`, and `return new_fills` at the end.

- [ ] **Step 4: Run to verify pass + no regressions**

Run: `uv run pytest tests/execution/test_backtest.py -v`
Expected: PASS (new tests + all pre-existing broker tests — they ignore the new return value).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy src
git add src/pat/execution/broker.py src/pat/execution/backtest.py tests/execution/test_backtest.py
git commit -m "phase2: BacktestBroker cancel() + on_trade returns new fills"
```

---

## Task 5: MarketMaker strategy (fixed-spread, EWMA fair value, inventory cap)

**Why:** The v1 strategy itself (approved design). Fair value = EWMA of trades; symmetric quotes `fv ± half_spread`; at the inventory cap, quote only the reducing side. v1 requotes (cancel+repost) on **every** trade — the spec's "requote when fv moves beyond a threshold" is a v2 optimisation, deferred (YAGNI); per-trade requoting is simpler and deterministic for the backtest.

**Files:**
- Create: `src/pat/strategies/market_maker.py`
- Test: `tests/strategies/test_market_maker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/strategies/test_market_maker.py`:

```python
from decimal import Decimal

from pat.core.types import Fill, Liquidity, Side
from pat.strategies.base import CancelOrder, PostOrder
from pat.strategies.market_maker import MarketMaker


def _mm(**kw: object) -> MarketMaker:
    base = dict(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                inventory_cap=Decimal("50"), alpha=Decimal("0.5"), tick=Decimal("0.01"))
    base.update(kw)
    return MarketMaker(**base)  # type: ignore[arg-type]


def test_first_trade_initializes_fv_and_posts_two_quotes() -> None:
    mm = _mm()
    actions = mm.on_trade(Decimal("0.50"), Decimal("10"))
    posts = [a for a in actions if isinstance(a, PostOrder)]
    assert len(actions) == 2 and len(posts) == 2  # no cancels on first quote
    by_side = {p.order.side: p.order.price for p in posts}
    assert by_side[Side.BUY] == Decimal("0.48")
    assert by_side[Side.SELL] == Decimal("0.52")


def test_requote_cancels_previous_quotes() -> None:
    mm = _mm()
    first = mm.on_trade(Decimal("0.50"), Decimal("10"))
    first_ids = {p.order.client_id for p in first if isinstance(p, PostOrder)}
    second = mm.on_trade(Decimal("0.50"), Decimal("10"))
    cancel_ids = {c.client_id for c in second if isinstance(c, CancelOrder)}
    assert cancel_ids == first_ids


def test_ewma_updates_fair_value() -> None:
    mm = _mm(alpha=Decimal("0.5"))
    mm.on_trade(Decimal("0.50"), Decimal("10"))     # fv = 0.50
    actions = mm.on_trade(Decimal("0.60"), Decimal("10"))  # fv = 0.5*0.60 + 0.5*0.50 = 0.55
    posts = {a.order.side: a.order.price for a in actions if isinstance(a, PostOrder)}
    assert posts[Side.BUY] == Decimal("0.53") and posts[Side.SELL] == Decimal("0.57")


def test_inventory_cap_blocks_adding_side() -> None:
    mm = _mm(inventory_cap=Decimal("10"), size=Decimal("10"))
    mm.on_trade(Decimal("0.50"), Decimal("10"))                  # posts bid+ask
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"),
                      size=Decimal("10"), fee=Decimal("0"),
                      liquidity=Liquidity.MAKER, mode="backtest", ts=1)])
    assert mm.inventory == Decimal("10")  # at the long cap
    actions = mm.on_trade(Decimal("0.50"), Decimal("10"))
    posted_sides = {a.order.side for a in actions if isinstance(a, PostOrder)}
    assert Side.BUY not in posted_sides and Side.SELL in posted_sides


def test_on_fills_updates_inventory_both_directions() -> None:
    mm = _mm()
    mm.on_trade(Decimal("0.50"), Decimal("10"))
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    ask_id = next(c for c, s in mm._side.items() if s is Side.SELL)
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"), size=Decimal("4"),
                      fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=1)])
    mm.on_fills([Fill(order_id=ask_id, token_id="t", price=Decimal("0.52"), size=Decimal("1"),
                      fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=2)])
    assert mm.inventory == Decimal("3")  # +4 - 1


def test_quote_prices_clamped_into_range() -> None:
    mm = _mm(half_spread=Decimal("0.05"))
    actions = mm.on_trade(Decimal("0.99"), Decimal("10"))  # fv 0.99 → ask would be 1.04
    asks = [a.order.price for a in actions if isinstance(a, PostOrder) and a.order.side is Side.SELL]
    assert asks and asks[0] == Decimal("0.99")  # clamped to 1 - tick
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/strategies/test_market_maker.py -v`
Expected: FAIL (`market_maker` module missing).

- [ ] **Step 3: Implement**

Create `src/pat/strategies/market_maker.py`:

```python
"""MarketMaker v1 — simple fixed-spread quoting (approved design, spec Section 2).

Fair value = EWMA of observed trades.  Symmetric quotes fv ± half_spread, resting
MAKER (GTC).  At the inventory cap, quote only the inventory-reducing side.
Edge = pure spread − adverse selection (geopolitics: 0% fee, 0 rebate).
Inventory-skew (Avellaneda–Stoikov) is deferred to v2 (YAGNI).
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
    ) -> None:
        self.token_id = token_id
        self.half_spread = Decimal(str(half_spread))
        self.size = Decimal(str(size))
        self.inventory_cap = Decimal(str(inventory_cap))
        self.alpha = Decimal(str(alpha))
        self.tick = Decimal(str(tick))

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

        bid_px = self._clamp(self.fv - self.half_spread)
        ask_px = self._clamp(self.fv + self.half_spread)

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
            size=self.size, order_type=OrderType.GTC, mode="backtest", reason="mm-quote",
        )

    def _clamp(self, p: Decimal) -> Decimal:
        lo, hi = self.tick, Decimal("1") - self.tick
        return min(max(p.quantize(self.tick), lo), hi)

    def _new_id(self, tag: str) -> str:
        self._counter += 1
        return f"{self.token_id}-{tag}-{self._counter}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/strategies/test_market_maker.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy src
git add src/pat/strategies/market_maker.py tests/strategies/test_market_maker.py
git commit -m "phase2: MarketMaker v1 (fixed-spread, EWMA fv, inventory cap)"
```

---

## Task 6: Replay loop (no look-ahead)

**Why:** Wire strategy↔broker with the **correct sequencing**: the broker matches each trade against *pre-existing* quotes first (so a trade never hits a quote that was posted *because of* that same trade — no look-ahead), then the strategy updates inventory from fills and requotes for the future.

**Files:**
- Create: `src/pat/execution/replay.py`
- Test: `tests/execution/test_replay.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/execution/test_replay.py`:

```python
from decimal import Decimal

from pat.core.types import Category, Market, Side, Venue
from pat.execution.backtest import BacktestBroker
from pat.execution.replay import run_replay
from pat.strategies.market_maker import MarketMaker


def _mkt() -> Market:
    return Market(id="m", venue=Venue.POLYMARKET, question="q", category=Category.GEOPOLITICS)


def test_first_trade_produces_no_fill_but_posts_quotes() -> None:
    """No look-ahead: the first trade can't fill (no resting quotes yet)."""
    broker = BacktestBroker(market=_mkt())
    mm = MarketMaker(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                     inventory_cap=Decimal("50"))
    fills = run_replay(mm, broker, [(Decimal("0.50"), Decimal("10"))])
    assert fills == []
    assert mm.fv == Decimal("0.50")  # strategy did observe the trade and quote


def test_bid_fills_on_adverse_down_move() -> None:
    """Quote at 0.50, then price trades through the 0.48 bid → we buy into a fall."""
    broker = BacktestBroker(market=_mkt())
    mm = MarketMaker(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                     inventory_cap=Decimal("50"))
    fills = run_replay(mm, broker, [
        (Decimal("0.50"), Decimal("10")),   # posts bid 0.48 / ask 0.52
        (Decimal("0.47"), Decimal("10")),   # 0.47 < 0.48 → bid fills (adverse)
    ])
    assert len(fills) == 1
    assert fills[0].price == Decimal("0.48")
    assert mm.inventory == Decimal("10")  # we are now long into a falling market


def test_returns_all_broker_fills() -> None:
    broker = BacktestBroker(market=_mkt())
    mm = MarketMaker(token_id="t", half_spread=Decimal("0.02"), size=Decimal("10"),
                     inventory_cap=Decimal("50"))
    fills = run_replay(mm, broker, [
        (Decimal("0.50"), Decimal("10")),
        (Decimal("0.47"), Decimal("10")),
        (Decimal("0.55"), Decimal("10")),
    ])
    assert fills is broker.fills
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/execution/test_replay.py -v`
Expected: FAIL (`replay` module missing).

- [ ] **Step 3: Implement**

Create `src/pat/execution/replay.py`:

```python
"""No-look-ahead replay loop: drive a Strategy against a Broker over a trade stream.

Per trade, in order:
  1. broker matches the trade against EXISTING resting quotes -> new fills
  2. strategy.on_fills(new_fills)        -> update inventory
  3. strategy.on_trade(price, size)      -> requote intents for the FUTURE
  4. apply intents (cancel / submit)

Step 1 precedes step 3 so a trade can never fill a quote that was posted because
of that same trade.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from pat.core.types import Fill
from pat.execution.broker import Broker
from pat.strategies.base import CancelOrder, PostOrder, Strategy


def run_replay(
    strategy: Strategy,
    broker: Broker,
    trades: Iterable[tuple[Decimal, Decimal]],
) -> list[Fill]:
    """Replay (price, size) trades; return all fills the broker produced."""
    for price, size in trades:
        new_fills = broker.on_trade(price, size)
        strategy.on_fills(new_fills)
        for action in strategy.on_trade(price, size):
            if isinstance(action, CancelOrder):
                broker.cancel(action.client_id)
            elif isinstance(action, PostOrder):
                broker.submit(action.order)
    return broker.fills
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/execution/test_replay.py -v`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run mypy src
git add src/pat/execution/replay.py tests/execution/test_replay.py
git commit -m "phase2: no-look-ahead replay loop (strategy<->broker)"
```

---

## Task 7: Parameter-sweep backtest runner

**Why:** Find the +EV frontier across `half_spread ∈ {1,2,3,5}¢` rather than guessing one config (approved decision). Aggregates fills across all token streams, marks residual inventory (last − half-spread haircut), and produces a `Result`+`Verdict` per config. Includes a deterministic synthetic end-to-end test proving the whole pipeline reaches ≥1000 fills offline.

**Files:**
- Create: `scripts/run_mm_backtest.py`
- Create: `tests/scripts/test_mm_backtest.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_mm_backtest.py`:

```python
from decimal import Decimal

from pat.core.types import Category, Market, Venue
from scripts.run_mm_backtest import run_sweep


def _mkt() -> Market:
    return Market(id="m", venue=Venue.POLYMARKET, question="q", category=Category.GEOPOLITICS)


def _oscillating_stream(n: int) -> list[tuple[Decimal, Decimal]]:
    """Deterministic saw-tooth around 0.50 that repeatedly trades through ±2-5c quotes."""
    out: list[tuple[Decimal, Decimal]] = []
    for i in range(n):
        # cycle 0.46, 0.50, 0.54, 0.50, ... to fill both bid and ask repeatedly
        step = [Decimal("0.46"), Decimal("0.50"), Decimal("0.54"), Decimal("0.50")][i % 4]
        out.append((step, Decimal("10")))
    return out


def test_sweep_returns_a_row_per_half_spread() -> None:
    streams = {"t": _oscillating_stream(40)}
    rows = run_sweep(streams, market=_mkt(),
                     half_spreads=[Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")],
                     size=Decimal("10"), inventory_cap=Decimal("100"), alpha=Decimal("0.5"))
    assert [r["half_spread"] for r in rows] == [Decimal("0.01"), Decimal("0.02"),
                                                Decimal("0.03"), Decimal("0.05")]
    assert all("result" in r and "verdict" in r for r in rows)


def test_sweep_aggregates_fills_across_streams() -> None:
    streams = {"a": _oscillating_stream(40), "b": _oscillating_stream(40)}
    rows = run_sweep(streams, market=_mkt(), half_spreads=[Decimal("0.02")],
                     size=Decimal("10"), inventory_cap=Decimal("100"), alpha=Decimal("0.5"))
    assert rows[0]["result"].n_trades > 0


def test_sweep_marks_open_inventory() -> None:
    # a one-sided down-drift leaves the MM long → inventory_value must be non-zero
    streams = {"t": [(Decimal("0.50"), Decimal("10"))] + [(Decimal("0.40"), Decimal("10"))] * 10}
    rows = run_sweep(streams, market=_mkt(), half_spreads=[Decimal("0.02")],
                     size=Decimal("10"), inventory_cap=Decimal("1000"), alpha=Decimal("0.5"))
    assert rows[0]["result"].inventory_value != Decimal("0")


def test_pipeline_reaches_1000_fills_and_produces_verdict() -> None:
    """End-to-end offline gate analog: ≥1000 MM fills, a Verdict object is produced.

    The saw-tooth stream fills ~50% of trades (2 per 4-trade cycle), so
    5 tokens × 600 trades = 3000 trades → ~1500 fills (comfortable margin over 1000).
    """
    streams = {f"t{k}": _oscillating_stream(600) for k in range(5)}
    rows = run_sweep(streams, market=_mkt(), half_spreads=[Decimal("0.02")],
                     size=Decimal("10"), inventory_cap=Decimal("100000"), alpha=Decimal("0.5"))
    r = rows[0]
    assert r["result"].n_trades >= 1000  # ~1500 expected
    assert r["verdict"].reason  # non-empty verdict string (advance True/False both fine)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/scripts/test_mm_backtest.py -v`
Expected: FAIL (`scripts.run_mm_backtest` missing).

- [ ] **Step 3: Implement**

Create `scripts/run_mm_backtest.py`:

```python
"""Phase-2 MM backtest — parameter sweep over half_spread, net-of-fee with inventory MtM.

Pure-function core (run_sweep) is deterministic and unit-tested offline.  The
__main__ block runs it on a saved per-token trade stream (Task 8 supplies real
geopolitics data).  Backtest fidelity is a conservative lower bound (no order
book); the real verdict is paper (ADR 0014).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pat.analytics.metrics import Result, Verdict, summarize
from pat.core.types import Market
from pat.execution.backtest import BacktestBroker
from pat.execution.replay import run_replay
from pat.strategies.market_maker import MarketMaker

Stream = list[tuple[Decimal, Decimal]]


def run_sweep(
    streams: dict[str, Stream],
    market: Market,
    half_spreads: list[Decimal],
    size: Decimal,
    inventory_cap: Decimal,
    alpha: Decimal,
) -> list[dict[str, Any]]:
    """Run the MM over every token stream for each half_spread; return frontier rows.

    Each row: {"half_spread", "result": Result, "verdict": Verdict}.
    Residual inventory is marked at last trade price minus a half_spread haircut.
    """
    rows: list[dict[str, Any]] = []
    for hs in half_spreads:
        fill_dicts: list[dict[str, Any]] = []
        marks: dict[str, Decimal] = {}
        for token_id, trades in streams.items():
            broker = BacktestBroker(market=market)
            mm = MarketMaker(token_id=token_id, half_spread=hs, size=size,
                             inventory_cap=inventory_cap, alpha=alpha, tick=market.tick_size)
            fills = run_replay(mm, broker, trades)
            for f in fills:
                side = mm.side_of(f.order_id)
                if side is None:
                    continue
                fill_dicts.append({"side": side.value, "price": f.price,
                                   "size": f.size, "fee": f.fee, "token_id": f.token_id})
            if trades:
                marks[token_id] = trades[-1][0]  # last trade price = mark
        result: Result = summarize(fill_dicts, marks=marks, inventory_haircut=hs)
        verdict: Verdict = Verdict.from_metrics(result.sharpe, result.net_pnl, result.n_trades)
        rows.append({"half_spread": hs, "result": result, "verdict": verdict})
    return rows


def print_frontier(rows: list[dict[str, Any]]) -> None:
    print("half_spread | n_trades | net_pnl | inv_value | sharpe | advance")  # noqa: T201
    for r in rows:
        res, v = r["result"], r["verdict"]
        print(  # noqa: T201
            f"  {r['half_spread']!s:>9} | {res.n_trades:>8} | {res.net_pnl:>7} | "
            f"{res.inventory_value:>9} | {res.sharpe:>6.3f} | {v.advance}"
        )
```

(The `__main__` block that loads real streams is added in Task 8.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/scripts/test_mm_backtest.py -v`
Expected: PASS (including the ≥1000-fill end-to-end test).

- [ ] **Step 5: Full suite, lint, type-check, commit**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy src scripts/run_mm_backtest.py
git add scripts/run_mm_backtest.py tests/scripts/test_mm_backtest.py
git commit -m "phase2: MM parameter-sweep backtest runner (inventory MtM, net-of-fee)"
```

---

## Task 8: Real geopolitics data → verdict (RPC-gated; may become its own plan)

**Why:** Tasks 1–7 are a tested engine on synthetic streams. The Phase-2 **gate** needs the verdict on **real geopolitics data**. This step has external dependencies (a Polygon RPC endpoint via `POLYGON_RPC_URL`; a Gamma query to select geopolitics markets and their `token_id`s). Its "test" is a smoke run, not a pure unit test, so it is isolated here.

> **⚠️ Verify-before-build (CLAUDE.md principle 2):** the exact Gamma query to list **geopolitics** markets and their CLOB `token_id`s is **not yet primary-verified**. Run `claims-verifier` (or read docs.polymarket.com Gamma reference) and log the result in `docs/research/claims-verification.md` before coding the selection. If this balloons, split it into a dedicated data-layer plan.

**Files:**
- Modify: `scripts/run_mm_backtest.py` (add a `streams_from_orderfilled()` helper + `__main__`)
- Modify: `docs/strategies/market-making.md` (record the verdict)

- [ ] **Step 1: Build per-token streams from parsed OrderFilled (unit-testable, offline)**

Add to `scripts/run_mm_backtest.py`:

```python
def streams_from_fills(fills: list, token_ids: set[str] | None = None) -> dict[str, Stream]:
    """Group parsed Fill records into per-token (price, size) streams, ts-ordered.

    Args:
        fills: list[pat.core.types.Fill] from parse_orderfilled().
        token_ids: if given, keep only these tokens (e.g. the geopolitics set).
    """
    by_token: dict[str, Stream] = {}
    for f in sorted(fills, key=lambda x: x.ts):
        if token_ids is not None and f.token_id not in token_ids:
            continue
        by_token.setdefault(f.token_id, []).append((f.price, f.size))
    return by_token
```

Add to `tests/scripts/test_mm_backtest.py`:

```python
def test_streams_from_fills_groups_orders_and_filters() -> None:
    from pat.core.types import Fill, Liquidity
    from scripts.run_mm_backtest import streams_from_fills

    fills = [
        Fill(order_id="o1", token_id="a", price=Decimal("0.5"), size=Decimal("3"),
             fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=2),
        Fill(order_id="o2", token_id="a", price=Decimal("0.4"), size=Decimal("1"),
             fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=1),
        Fill(order_id="o3", token_id="b", price=Decimal("0.6"), size=Decimal("2"),
             fee=Decimal("0"), liquidity=Liquidity.MAKER, mode="backtest", ts=3),
    ]
    streams = streams_from_fills(fills, token_ids={"a"})
    assert set(streams) == {"a"}                       # 'b' filtered out
    assert streams["a"] == [(Decimal("0.4"), Decimal("1")),
                            (Decimal("0.5"), Decimal("3"))]   # ts-ordered
```

Run it (FAIL → implement `streams_from_fills` → PASS).

- [ ] **Step 2: Document the operational run (no code claim without output)**

Add a `__main__` to `scripts/run_mm_backtest.py` that: reads a saved raw OrderFilled JSON (from `scripts/fetch_polymarket_history.py`), `parse_orderfilled()`s it, builds streams via `streams_from_fills(..., token_ids=<geopolitics set>)`, runs `run_sweep(...)`, and calls `print_frontier(...)`. Keep all network in the existing fetch script (already isolated).

Operational sequence (the engineer/user runs, with a working RPC):

```bash
# 1. fetch raw OrderFilled for the post-V2 window (needs POLYGON_RPC_URL)
export POLYGON_RPC_URL=...        # user-supplied paid RPC (public endpoint rate-limits)
uv run python scripts/fetch_polymarket_history.py --from-block <V2_START> --to-block <END>
# 2. (after verifying the Gamma query) save the geopolitics token_id set to data/geopolitics_tokens.json
# 3. run the sweep and capture the frontier
uv run python scripts/run_mm_backtest.py data/raw/orderfilled_<from>_<to>.json
```

- [ ] **Step 3: Record the verdict**

Paste the printed frontier table into `docs/strategies/market-making.md` §7 (Results) and fill §8 (Verdict): for the best config, does it meet **n≥1000 ∧ net EV>0 ∧ Sharpe>1.0**? Decide: advance to paper (Phase 3) / iterate (B2 politics, or v2 inventory-skew) / trash. Write an ADR if the decision is non-trivial (CLAUDE.md §6).

- [ ] **Step 4: Commit**

```bash
uv run pytest tests/scripts/test_mm_backtest.py -v && uv run ruff check . && uv run mypy src scripts/run_mm_backtest.py
git add scripts/run_mm_backtest.py tests/scripts/test_mm_backtest.py docs/strategies/market-making.md
git commit -m "phase2: real geopolitics MM backtest + verdict"
```

---

## After all tasks

Dispatch a final code reviewer over the whole Phase-2 diff, then use `superpowers:finishing-a-development-branch` to merge `phase-2-market-making`. If the verdict fails the gate, that is a **valid honest outcome** (CLAUDE.md §0/§6) — record it and follow the roadmap trigger (iterate B2/v2, or trash MM and move to the next catalog strategy).
