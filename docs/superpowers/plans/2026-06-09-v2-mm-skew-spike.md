# v2 MM Inventory-Skew Spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two composable inventory-skew knobs to the market maker and a sweep runner/spike script, then run them on the existing geopolitics dataset to decide greenlight-vs-pivot for v2.

**Architecture:** `MarketMaker` gains `gamma` (mid-shift `fv−γ·inv_frac`) and `skew_delta` (asymmetric spread), default 0 = exact v1. `run_mm_backtest` extracts a shared `_evaluate_config` helper (used by the unchanged `run_sweep` and a new `run_skew_sweep(configs)`). A thin `run_skew_spike.py` sweeps γ/δ at two half-spreads and prints per-hs tables. 0 CU — reuses `data/raw/geopolitics_88082000_88090000.json`.

**Tech Stack:** Python 3.11, `pytest`, `ruff`, `mypy`, `uv`, `Decimal`, `structlog`. Spec: `docs/superpowers/specs/2026-06-09-v2-mm-skew-spike-design.md`.

---

## File structure
- `src/pat/strategies/market_maker.py` — add `gamma`/`skew_delta` params + skew math + no-cross postcondition in `on_trade`.
- `scripts/run_mm_backtest.py` — add `_evaluate_config`, refactor `run_sweep` to call it, add `run_skew_sweep`. (`import Side`.)
- `scripts/run_skew_spike.py` — NEW; grid (2 half-spreads × γ-trend/δ-trend/combo) → tables.
- `tests/strategies/test_market_maker.py` — skew unit tests (+ no-cross invariant).
- `tests/scripts/test_mm_backtest.py` — `run_skew_sweep` equivalence + respects-configs tests.
- After the run: `docs/decisions/0019-v2-skew-spike-verdict.md` (NEW), update `docs/strategies/market-making.md`, `docs/HANDOFF.md`.

Gates after each task: `uv run --extra dev pytest -q && uv run --extra dev ruff check . && uv run --extra dev mypy src`.

---

## Task 1: Inventory skew in `MarketMaker`

**Files:**
- Modify: `src/pat/strategies/market_maker.py`
- Test: `tests/strategies/test_market_maker.py`

- [ ] **Step 1: Add a quotes helper + failing skew tests**

Add to `tests/strategies/test_market_maker.py` (the file already imports `Decimal, Fill, Liquidity, Side, CancelOrder, PostOrder, MarketMaker` and has the `_mm` helper):

```python
def _quotes(actions: list) -> dict:
    return {a.order.side: a.order.price for a in actions if isinstance(a, PostOrder)}


def _set_long(mm: MarketMaker, shares: str) -> None:
    """Seed fv=0.50 + post quotes, then fill the bid to push inventory long by `shares`."""
    mm.on_trade(Decimal("0.50"), Decimal("10"))
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"),
                      size=Decimal(shares), fee=Decimal("0"),
                      liquidity=Liquidity.MAKER, mode="backtest", ts=1)])


def test_gamma_long_lowers_both_quotes() -> None:
    base = _mm(inventory_cap=Decimal("100"), gamma=Decimal("0"))
    skew = _mm(inventory_cap=Decimal("100"), gamma=Decimal("0.10"))
    _set_long(base, "50")   # inv_frac = 0.5
    _set_long(skew, "50")
    b = _quotes(base.on_trade(Decimal("0.50"), Decimal("10")))
    s = _quotes(skew.on_trade(Decimal("0.50"), Decimal("10")))
    assert s[Side.BUY] < b[Side.BUY]
    assert s[Side.SELL] < b[Side.SELL]


def test_skew_delta_long_deepens_bid_only() -> None:
    base = _mm(inventory_cap=Decimal("100"), skew_delta=Decimal("0"))
    skew = _mm(inventory_cap=Decimal("100"), skew_delta=Decimal("0.10"))
    _set_long(base, "50")
    _set_long(skew, "50")
    b = _quotes(base.on_trade(Decimal("0.50"), Decimal("10")))
    s = _quotes(skew.on_trade(Decimal("0.50"), Decimal("10")))
    assert s[Side.BUY] < b[Side.BUY]       # bid deeper
    assert s[Side.SELL] == b[Side.SELL]    # ask unchanged


def test_skew_zero_identical_to_v1() -> None:
    plain = _mm(inventory_cap=Decimal("100"))
    skew = _mm(inventory_cap=Decimal("100"), gamma=Decimal("0"), skew_delta=Decimal("0"))
    _set_long(plain, "50")
    _set_long(skew, "50")
    assert _quotes(plain.on_trade(Decimal("0.50"), Decimal("10"))) == \
           _quotes(skew.on_trade(Decimal("0.50"), Decimal("10")))


def test_inv_frac_clamped_bounds_shift() -> None:
    mm = _mm(inventory_cap=Decimal("10"), gamma=Decimal("0.10"))
    mm.on_trade(Decimal("0.50"), Decimal("10"))
    bid_id = next(c for c, s in mm._side.items() if s is Side.BUY)
    mm.on_fills([Fill(order_id=bid_id, token_id="t", price=Decimal("0.48"),
                      size=Decimal("20"), fee=Decimal("0"),     # inv=+20 > cap=10 -> frac clamped to 1
                      liquidity=Liquidity.MAKER, mode="backtest", ts=1)])
    q = _quotes(mm.on_trade(Decimal("0.50"), Decimal("10")))
    assert Side.BUY not in q                       # over cap -> only ask posts
    assert q[Side.SELL] == Decimal("0.52")         # fv_eff=0.50-0.10*1=0.40, ask=0.40+... wait see note


def test_no_cross_invariant_across_grid() -> None:
    grid = [Decimal("0"), Decimal("0.05"), Decimal("0.10")]
    for gamma in grid:
        for delta in grid:
            for fv in (Decimal("0.02"), Decimal("0.50"), Decimal("0.98")):
                for inv in (Decimal("-99"), Decimal("0"), Decimal("99")):
                    mm = _mm(inventory_cap=Decimal("100"), half_spread=Decimal("0.05"),
                             quote_band=Decimal("0"), gamma=gamma, skew_delta=delta)
                    mm.fv = fv
                    mm.inventory = inv
                    q = _quotes(mm.on_trade(fv, Decimal("10")))
                    if Side.BUY in q and Side.SELL in q:
                        assert q[Side.SELL] - q[Side.BUY] >= mm.tick
```

> NOTE for `test_inv_frac_clamped_bounds_shift`: with `half_spread=0.02` (the `_mm` default), `fv_eff=0.50−0.10·1=0.40`, `ask=clamp(0.40+0.02)=0.42`. **Fix the assertion to `== Decimal("0.42")`** before running (the inline `0.52` above is a deliberate stub to make the test fail first; change it to `0.42` in Step 3).

- [ ] **Step 2: Run the tests — verify they FAIL**

Run: `uv run --extra dev pytest tests/strategies/test_market_maker.py -q`
Expected: FAIL — `MarketMaker.__init__() got an unexpected keyword argument 'gamma'`.

- [ ] **Step 3: Implement skew in `MarketMaker`**

In `src/pat/strategies/market_maker.py`, add params to `__init__` (after `tick`, alongside the existing `quote_band`):
```python
        quote_band: Decimal = Decimal("0"),
        gamma: Decimal = Decimal("0"),
        skew_delta: Decimal = Decimal("0"),
    ) -> None:
```
and in the body (after `self.quote_band = Decimal(str(quote_band))`):
```python
        # Inventory skew (ADR 0018 / spec 2026-06-09). 0 = no skew (v1).
        self.gamma = Decimal(str(gamma))            # mid-shift: fv_eff = fv - gamma*inv_frac
        self.skew_delta = Decimal(str(skew_delta))  # asymmetric spread on the building side
```
Then in `on_trade`, **replace** the two lines:
```python
        bid_px = self._clamp(self.fv - self.half_spread)
        ask_px = self._clamp(self.fv + self.half_spread)
```
with:
```python
        inv_frac = self.inventory / self.inventory_cap
        inv_frac = max(Decimal("-1"), min(Decimal("1"), inv_frac))   # bound the shift
        fv_eff = self.fv - self.gamma * inv_frac
        bid_off = self.half_spread + self.skew_delta * max(Decimal("0"), inv_frac)
        ask_off = self.half_spread + self.skew_delta * max(Decimal("0"), -inv_frac)
        bid_px = self._clamp(fv_eff - bid_off)
        ask_px = self._clamp(fv_eff + ask_off)
        # No-cross postcondition: clamp can collapse them to one tick near 0/1 -> force a >=1-tick gap.
        if ask_px - bid_px < self.tick:
            if ask_px >= Decimal("1") - self.tick:
                bid_px = self._clamp(ask_px - self.tick)
            else:
                ask_px = self._clamp(bid_px + self.tick)
```
Also change `test_inv_frac_clamped_bounds_shift`'s assertion to `q[Side.SELL] == Decimal("0.42")` (per the NOTE).

- [ ] **Step 4: Run the tests — verify they PASS**

Run: `uv run --extra dev pytest tests/strategies/test_market_maker.py -q`
Expected: PASS (all, including the pre-existing v1 tests — γ=δ=0 keeps them identical).

- [ ] **Step 5: Gates + commit**

```bash
uv run --extra dev pytest -q && uv run --extra dev ruff check . && uv run --extra dev mypy src
git add src/pat/strategies/market_maker.py tests/strategies/test_market_maker.py
git commit -m "feat(mm): inventory skew (gamma mid-shift + skew_delta asym spread), default 0 = v1"
```

---

## Task 2: `_evaluate_config` refactor + `run_skew_sweep`

**Files:**
- Modify: `scripts/run_mm_backtest.py`
- Test: `tests/scripts/test_mm_backtest.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/scripts/test_mm_backtest.py` (it already has `_mkt`, `_oscillating_stream`, and imports `run_sweep`; add `run_skew_sweep` to the import):
```python
def test_run_skew_sweep_zero_coeffs_matches_run_sweep() -> None:
    from scripts.run_mm_backtest import run_skew_sweep
    streams = {"t": _oscillating_stream(40)}
    hss = [Decimal("0.01"), Decimal("0.02")]
    base = run_sweep(streams, market=_mkt(), half_spreads=hss,
                     size=Decimal("10"), inventory_cap=Decimal("100"), alpha=Decimal("0.5"))
    configs = [{"half_spread": hs, "gamma": Decimal("0"), "skew_delta": Decimal("0")} for hs in hss]
    skew = run_skew_sweep(streams, market=_mkt(), configs=configs,
                          size=Decimal("10"), inventory_cap=Decimal("100"), alpha=Decimal("0.5"))
    for b, s in zip(base, skew, strict=True):
        assert b["result"].net_pnl == s["result"].net_pnl
        assert b["result"].n_trades == s["result"].n_trades


def test_run_skew_sweep_respects_configs() -> None:
    from scripts.run_mm_backtest import run_skew_sweep
    # one-sided down-drift leaves the MM long; gamma>0 must change the outcome
    streams = {"t": [(Decimal("0.50"), Decimal("10"))] + [(Decimal("0.40"), Decimal("10"))] * 20}
    configs = [
        {"half_spread": Decimal("0.02"), "gamma": Decimal("0"), "skew_delta": Decimal("0")},
        {"half_spread": Decimal("0.02"), "gamma": Decimal("0.05"), "skew_delta": Decimal("0")},
    ]
    rows = run_skew_sweep(streams, market=_mkt(), configs=configs,
                          size=Decimal("10"), inventory_cap=Decimal("100"), alpha=Decimal("0.5"))
    assert rows[0]["result"].net_pnl != rows[1]["result"].net_pnl
    assert "residual_abs_shares" in rows[1]
    assert "net_pnl_per_fill" in rows[1]
```

- [ ] **Step 2: Run — verify FAIL**

Run: `uv run --extra dev pytest tests/scripts/test_mm_backtest.py -q`
Expected: FAIL — `cannot import name 'run_skew_sweep'`.

- [ ] **Step 3: Refactor + implement**

In `scripts/run_mm_backtest.py`: add `Side` to the core import →
`from pat.core.types import Category, Fill, Market, Side, Venue`.

Add the shared helper (above `run_sweep`):
```python
def _evaluate_config(
    streams: dict[str, Stream],
    market: Market,
    *,
    half_spread: Decimal,
    gamma: Decimal,
    skew_delta: Decimal,
    size: Decimal,
    inventory_cap: Decimal,
    alpha: Decimal,
    quote_band: Decimal,
) -> dict[str, Any]:
    """Run the MM over every token stream for one config; return result + verdict + residual."""
    fill_dicts: list[dict[str, Any]] = []
    marks: dict[str, Decimal] = {}
    residual: dict[str, Decimal] = {}
    for token_id, trades in streams.items():
        broker = BacktestBroker(market=market)
        mm = MarketMaker(token_id=token_id, half_spread=half_spread, size=size,
                         inventory_cap=inventory_cap, alpha=alpha, tick=market.tick_size,
                         quote_band=quote_band, gamma=gamma, skew_delta=skew_delta)
        fills = run_replay(mm, broker, trades)
        for f in fills:
            side = mm.side_of(f.order_id)
            if side is None:
                continue
            fill_dicts.append({"side": side.value, "price": f.price,
                               "size": f.size, "fee": f.fee, "token_id": f.token_id})
            signed = f.size if side is Side.BUY else -f.size
            residual[token_id] = residual.get(token_id, Decimal("0")) + signed
        if trades:
            marks[token_id] = trades[-1][0]
    result = summarize(fill_dicts, marks=marks, inventory_haircut=MARKET_HALF_SPREAD)
    verdict = Verdict.from_metrics(result.sharpe, result.net_pnl, result.n_trades)
    residual_abs_shares = sum((abs(v) for v in residual.values()), Decimal("0"))
    return {"result": result, "verdict": verdict, "residual_abs_shares": residual_abs_shares}
```
Replace the body of `run_sweep` (keep its signature) with:
```python
    rows: list[dict[str, Any]] = []
    for hs in half_spreads:
        ev = _evaluate_config(streams, market, half_spread=hs, gamma=Decimal("0"),
                              skew_delta=Decimal("0"), size=size, inventory_cap=inventory_cap,
                              alpha=alpha, quote_band=quote_band)
        rows.append({"half_spread": hs, "result": ev["result"], "verdict": ev["verdict"]})
    return rows
```
Add `run_skew_sweep` (below `run_sweep`):
```python
def run_skew_sweep(
    streams: dict[str, Stream],
    market: Market,
    configs: list[dict[str, Decimal]],
    *,
    size: Decimal,
    inventory_cap: Decimal,
    alpha: Decimal,
    quote_band: Decimal = Decimal("0.10"),
) -> list[dict[str, Any]]:
    """Evaluate each {half_spread, gamma, skew_delta} config; rows carry net_pnl_per_fill + residual."""
    rows: list[dict[str, Any]] = []
    for cfg in configs:
        ev = _evaluate_config(streams, market, half_spread=cfg["half_spread"], gamma=cfg["gamma"],
                              skew_delta=cfg["skew_delta"], size=size, inventory_cap=inventory_cap,
                              alpha=alpha, quote_band=quote_band)
        n = ev["result"].n_trades
        npf = (ev["result"].net_pnl / Decimal(n)) if n else Decimal("0")
        rows.append({**cfg, "result": ev["result"], "verdict": ev["verdict"],
                     "residual_abs_shares": ev["residual_abs_shares"], "net_pnl_per_fill": npf})
    return rows
```
> Note: `run_sweep` must still pass `quote_band` through — it already has the `quote_band` param (default 0.10); keep it and forward it to `_evaluate_config`.

- [ ] **Step 4: Run — verify PASS**

Run: `uv run --extra dev pytest tests/scripts/test_mm_backtest.py -q`
Expected: PASS (incl. all pre-existing `run_sweep` tests — same return shape).

- [ ] **Step 5: Gates + commit**

```bash
uv run --extra dev pytest -q && uv run --extra dev ruff check . && uv run --extra dev mypy src
git add scripts/run_mm_backtest.py tests/scripts/test_mm_backtest.py
git commit -m "refactor(backtest): _evaluate_config helper + run_skew_sweep (gamma/delta configs)"
```

---

## Task 3: Spike script `scripts/run_skew_spike.py`

**Files:**
- Create: `scripts/run_skew_spike.py`

- [ ] **Step 1: Write the script**

```python
"""v2 inventory-skew spike — does skew move the v1 MM toward +EV on the existing geopolitics data?

Sweeps gamma (mid-shift) + skew_delta (asymmetric spread) at two half-spreads and prints per-hs
tables (gamma-trend / delta-trend / combo). 0 CU (no network). Reads the saved decoded JSON.
Spec: docs/superpowers/specs/2026-06-09-v2-mm-skew-spike-design.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pat.core.types import Category, Market, Venue  # noqa: E402
from pat.data.polymarket_history import parse_orderfilled  # noqa: E402
from pat.logging import TradeJournal  # noqa: E402
from scripts.run_mm_backtest import (  # noqa: E402
    run_skew_sweep,
    run_sweep,
    streams_from_fills,
)

log = structlog.get_logger(__name__)

HALF_SPREADS = [Decimal("0.01"), Decimal("0.03")]
GAMMAS = [Decimal("0"), Decimal("0.02"), Decimal("0.04"), Decimal("0.06"), Decimal("0.10")]
DELTAS = [Decimal("0.02"), Decimal("0.04"), Decimal("0.06"), Decimal("0.10")]
COMBO = [(Decimal("0.02"), Decimal("0.02")), (Decimal("0.04"), Decimal("0.04")),
         (Decimal("0.06"), Decimal("0.06"))]
_SIZE, _CAP, _ALPHA = Decimal("10"), Decimal("100"), Decimal("0.3")  # match v1 defaults


def _print_table(title: str, rows: list[dict[str, Any]]) -> None:
    print(title)  # noqa: T201
    print("  gamma | delta |     n |   net_pnl | gross_pnl | inv_value | net/fill | resid_sh | sharpe")  # noqa: T201,E501
    for r in rows:
        res = r["result"]
        print(  # noqa: T201
            f"  {r['gamma']!s:>5} | {r['skew_delta']!s:>5} | {res.n_trades:>5} | "
            f"{res.net_pnl:>9.2f} | {res.gross_pnl:>9.2f} | {res.inventory_value:>9.2f} | "
            f"{r['net_pnl_per_fill']:>8.4f} | {r['residual_abs_shares']:>8.1f} | {res.sharpe:>6.3f}"
        )


def _configs(hs: Decimal) -> dict[str, list[dict[str, Decimal]]]:
    return {
        "gamma-trend": [{"half_spread": hs, "gamma": g, "skew_delta": Decimal("0")} for g in GAMMAS],
        "delta-trend": [{"half_spread": hs, "gamma": Decimal("0"), "skew_delta": d} for d in DELTAS],
        "combo": [{"half_spread": hs, "gamma": g, "skew_delta": d} for g, d in COMBO],
    }


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
    parser = argparse.ArgumentParser(description="v2 inventory-skew spike (0 CU, local).")
    parser.add_argument("json_path", nargs="?",
                        default="data/raw/geopolitics_88082000_88090000.json")
    args = parser.parse_args()

    raw = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    fills = parse_orderfilled(raw)
    streams = streams_from_fills(fills)
    market = Market(id="geo-skew-spike", venue=Venue.POLYMARKET,
                    question="geo-skew-spike", category=Category.GEOPOLITICS)
    log.info("skew_spike.loaded", fills=len(fills), tokens=len(streams))

    # v1 baseline n-per-hs (gamma=delta=0) -> confirm the max-n half-spread.
    base = run_sweep(streams, market=market,
                     half_spreads=[Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), Decimal("0.05")],
                     size=_SIZE, inventory_cap=_CAP, alpha=_ALPHA)
    print("\n=== v1 baseline n-per-hs (gamma=delta=0) ===")  # noqa: T201
    for r in base:
        print(f"  hs={r['half_spread']} n={r['result'].n_trades} net={r['result'].net_pnl:.2f}")  # noqa: T201,E501

    journal = TradeJournal(path=Path("logs") / "skew_spike.jsonl", mode="backtest",
                           corr_id="skew-spike")
    for hs in HALF_SPREADS:
        for label, cfgs in _configs(hs).items():
            rows = run_skew_sweep(streams, market=market, configs=cfgs,
                                  size=_SIZE, inventory_cap=_CAP, alpha=_ALPHA)
            _print_table(f"\n=== hs={hs} | {label} ===", rows)
            for r in rows:
                journal.record(event="verdict", strategy="mm_v2_skew", half_spread=str(hs),
                               gamma=str(r["gamma"]), skew_delta=str(r["skew_delta"]),
                               n_trades=r["result"].n_trades, net_pnl=str(r["result"].net_pnl),
                               sharpe=r["result"].sharpe)
    print()  # noqa: T201
```

- [ ] **Step 2: Smoke + gates**

Run: `uv run python scripts/run_skew_spike.py --help`
Expected: argparse help, exit 0 (imports resolve).
Then: `uv run --extra dev ruff check . && uv run --extra dev mypy src` (mypy covers `src` only; ruff covers the script).

- [ ] **Step 3: Commit**

```bash
git add scripts/run_skew_spike.py
git commit -m "feat(scripts): run_skew_spike — gamma/delta sweep tables on existing data (0 CU)"
```

---

## Task 4: Run the spike, sign-off, record ADR 0019 (operational)

No new test code — the deliverable is the decision. Do NOT fabricate numbers; record exactly what the run prints.

- [ ] **Step 1: Run the spike**

```bash
uv run python scripts/run_skew_spike.py 2>&1 | tee logs/skew_spike_run.txt
```
Read: the v1 baseline n-per-hs (confirm hs=0.01 is max-n) + the per-hs γ-trend / δ-trend / combo tables.

- [ ] **Step 2: Apply the decision criterion (spec §4)**

Greenlight (fund a ≥2–3-window gate-valid v2) **iff** `net_pnl` shows a clear upward trend as γ / δ / combo increases AND reaches ≥ 0 **at both half-spreads** — a trend, not one point; cross-check with `n_trades` + `net_pnl_per_fill` (a "trend" that is just volume-throttling is not edge). Otherwise → pivot.

- [ ] **Step 3: Cost sign-off (fee-cost-auditor) BEFORE any greenlight**

Dispatch the `fee-cost-auditor` to confirm the `net_pnl` gross/`inventory_value`/haircut decomposition is honest for the skew configs (no double-count; haircut still `MARKET_HALF_SPREAD`; a net_pnl improvement is real spread capture / less residual, not an accounting artifact). Record its sign-off.

- [ ] **Step 4: Write ADR 0019 + update docs**

Create `docs/decisions/0019-v2-skew-spike-verdict.md` (use `docs/decisions/_template.md`): data provenance (same file, both exchanges), the γ/δ/combo tables at both hs, the trend read, the greenlight/pivot decision, the cost sign-off, and the claim ceiling (directional, not gate-valid). Update `docs/strategies/market-making.md` (v2 status + next) and `docs/HANDOFF.md`.

- [ ] **Step 5: Final gates + commit**

```bash
uv run --extra dev pytest -q && uv run --extra dev ruff check . && uv run --extra dev mypy src
git add docs/decisions/0019-v2-skew-spike-verdict.md docs/strategies/market-making.md docs/HANDOFF.md
git commit -m "phase2b/v2: inventory-skew spike verdict (ADR 0019) + greenlight/pivot decision"
```

---

## Self-review (against the spec)
- **Spec §1 (skew formulas + no-cross + quote_band-on-raw-fv + caveats):** Task 1 Step 3 (formulas, inv_frac clamp, no-cross block; the guard above the skew math is untouched so it still keys off raw `fv`). Tests: Task 1 Step 1 (gamma/delta/zero/clamp/no-cross). ✓
- **Spec §2 (runner: _evaluate_config + run_sweep refactor + run_skew_sweep + residual/per-fill):** Task 2. ✓
- **Spec §3 (spike script: n-per-hs baseline, 2 half-spreads, widened γ/δ grid, combo, rich columns):** Task 3. ✓
- **Spec §4 (decision metric = net_pnl, report panel, greenlight=fund-test, fee-auditor before greenlight, ADR 0019):** Task 4. ✓
- **Type consistency:** `gamma`/`skew_delta` (Decimal), `_evaluate_config` keyword-only signature reused identically by `run_sweep` + `run_skew_sweep`; config dict keys `half_spread`/`gamma`/`skew_delta` consistent across Task 2 + Task 3; `residual_abs_shares`/`net_pnl_per_fill` keys match between runner and script. ✓
- **Placeholders:** none — all code is concrete (the one stub assertion in Task 1 Step 1 is explicitly flagged + fixed in Step 3). ✓
