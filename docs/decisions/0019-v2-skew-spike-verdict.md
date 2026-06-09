# ADR 0019 — v2 inventory-skew spike: PIVOT (skew does not rescue MM on 0%-fee geopolitics)

- **Date:** 2026-06-09
- **Status:** Accepted
- **Deciders:** user + AI engineer (spec/plan/quant + final holistic review)

## Context
ADR 0018 trashed the v1 naive symmetric MM but left the *thesis* (MM on 0%-fee geopolitics) open —
the headline loss was mostly a boundary-clamp artifact, and the artifact-corrected run was
gate-invalid (n=339). The ADR-0018 priority-1 fix was **inventory skew**. Per the spec/plan
(`2026-06-09-v2-mm-skew-spike-*`), we ran a **cheap 0-CU spike**: add two composable skew knobs and
sweep them on the EXISTING dataset (21,748 fills, blocks 88082000–88090000) to decide
**greenlight (fund a ≥2–3-window gate-valid v2) vs pivot**.

**Pre-registered greenlight criterion:** `net_pnl` shows a clear upward trend as γ (mid-shift) / δ
(asym spread) / the combo diagonal increases **AND reaches ≥ 0 at both half-spreads** — a trend, not
a lucky point; cross-checked against `n_trades` + `net_pnl_per_fill` (so volume-throttling isn't
mistaken for edge).

## Decision
**PIVOT.** Inventory skew does **not** advance the MM thesis. No γ, δ, or combo config moves
`net_pnl` toward ≥ 0 at either half-spread. Do **not** fund a multi-window gate-valid MM v2. Shelve
passive market-making on 0%-fee geopolitics and pivot to the ADR-0018 alternatives.

## Evidence (spike tables, hs = 0.01 — the max-n config)
| config | n | net_pnl | gross_pnl | inv_value | resid_sh |
|---|---|---|---|---|---|
| γ=0 δ=0 (v1) | 339 | **−32.40** | −187.91 | +155.50 | 1223 |
| γ=0.02 | 336 | −46.19 | −73.15 | +26.96 | 1040 |
| γ=0.10 | 352 | −43.36 | −66.91 | +23.54 | 587 |
| δ=0.10 | 239 | −37.23 | −55.12 | +17.89 | 784 |
| γ=δ=0.06 (combo) | 293 | −39.84 | −25.96 | −13.88 | 638 |

At **hs = 0.03** every config is flat at **≈ −$15** (γ-trend −15.13→−15.87; δ-trend −14.9→−15.6;
combo ≈ −15.1). Full tables: `logs/skew_spike.jsonl` / reproducible via `scripts/run_skew_spike.py`.

## Rationale
- **Skew does its mechanical job — but it doesn't pay.** As γ rises, residual toxic inventory falls
  hard (`resid_sh` 1223 → 587; `inv_value` swing collapses +155 → +24) and realized `gross_pnl`
  improves (−188 → −67). So the knobs *work* — the bot ends far less toxically positioned. **Yet
  `net_pnl` does not turn positive** — it settles ≈ −$43 (hs=0.01) / −$15 (hs=0.03).
- **The v1 −$32 was partly luck.** The γ=0 baseline's net leaned on a **favourable** residual mark
  (+$155 `inv_value`); skew correctly flattens that exposure away, trading a lucky-mark for a flatter
  but still-negative book. The honest steady-state of even a *skewed* MM here is ≈ −$15…−43.
- **Realized capture is negative.** `gross_pnl` is negative/small across configs — the fills that
  happen are adversely selected (the market trades through the quote on its way to resolution). This
  is the structural ADR-0018 doubt confirmed: **0%-fee geopolitics is informed-flow-dominated; a
  passive MM, skewed or not, is the dumb-money counterparty.**
- **Cost-robust pivot (no fee-auditor gate needed).** This is a pivot, not a greenlight, so the
  spec's "fee-cost-auditor signs off before greenlight" gate is not triggered. The cost model is the
  ADR-0018-audited one (geo fee = 0; haircut = `MARKET_HALF_SPREAD`); the haircut is immaterial
  (≈ $6 of the −$43 at γ=0.10) and the loss lives in realized `gross_pnl` — no cost error is masking
  an edge.

## Consequences
- **Positive:** the cheap spike (0 CU, ~minutes) bought a defensible go/pivot decision **without** a
  large multi-window fetch and a likely-fruitless MM build-out — exactly its purpose. The skew code
  (`gamma`/`skew_delta`, default 0 = v1) is built + tested (144 green) and stays in the tree, reusable
  if MM is ever revisited with a real order book in paper (ADR 0014).
- **Negative / honest:** MM (B1) — the first roadmap strategy — does not yield an edge on its cleanest
  test. This is the research's own pre-stated pivot trigger ("MM isn't for us; pivot"). The roadmap
  advances to other strategies earlier than hoped.
- **Claim ceiling:** one 4.4h Iran/Israel window (correlated points). We are **not** claiming MM is
  impossible everywhere; we are declining to spend more on *passive MM on 0%-fee geo* given a clean
  spike where the mechanism works yet EV stays negative at both spreads.
- **Follow-ups / next:**
  - **Pivot target (recommended first):** top-50 **wallet behavioral analysis** (C1 — maker/taker
    indexed → ~110k CU for full histories). Let the *winners'* on-chain behavior tell us whether the
    edge is directional/informed vs MM, before committing to the next strategy.
  - Then, per ADR-0013 catalog order: likely **directional / news (intelligence layer)** or
    **copy-trading**. Each gets its own spec → plan → verdict.
  - MM is **shelved, not deleted** — revisit only with order-book data in paper (ADR 0014), not in the
    no-book backtest.
  - Still pending from Phase 2b: golden raw-log fixture (plan 2026-06-08 Task 7 Step 4b).
