# ADR 0018 — Geopolitics MM v1 verdict: do not advance (artifact-corrected)

- **Date:** 2026-06-09
- **Status:** Accepted
- **Deciders:** user + AI engineer (with `quant-researcher` + `fee-cost-auditor` sign-offs)

## Context
Phase-2b gate (CLAUDE.md §6): produce a fee-adjusted EV/Sharpe verdict for the **v1 naive symmetric
market maker** on **real 0%-fee geopolitics data** (≥1000 simulated trades) to decide
backtest → paper.

- **Data:** 21,748 geopolitics 0%-fee `OrderFilled` fills, Polygon blocks **88082000–88090000**
  (~4.4 h, 2026-06-07), **680 tokens** with fills, both CTF Exchange V2 (`0xE111…996B`) + NegRisk
  (`0xe2222…0F59`, same ABI — claim I10). Selection: Gamma `tag_id=100265`, **`closed=false`,
  `feesEnabled=false`, paginated** (live markets — see the I9 selection gotcha).
- **Strategy:** `fv`=EWMA(α=0.3); symmetric `bid/ask = fv ± half_spread`; size 10; inventory cap 100;
  resting MAKER. Backtest = conservative through-trade fill, **no order book** (ADR 0014 → lower bound).
- **Gate** (`metrics.py`): advance iff `n_trades≥1000 ∧ net_pnl>0 ∧ sharpe>1.0` (per-fill sharpe).

## Options considered
1. **Record the first gate-valid run (n=1335) as the verdict** — REJECTED: adversarial review showed
   it is artifact-contaminated (see Rationale).
2. **Trash the MM-on-geopolitics thesis outright** — REJECTED: not supported; the headline negative
   was mostly artifact, and the corrected margin is thin, not decisively −EV.
3. **Big fetch (~32k blocks) for a gate-valid *corrected* v1 number** — REJECTED (for now): low
   marginal value — naive symmetric v1 does not advance regardless; spend the next data on v2.
4. **(CHOSEN) Record do-not-advance v1 with artifact-corrected analysis + the code fixes, downgrade
   I9, and defer the thesis to v2 (inventory skew) on a larger dataset.**

## Decision
**Do NOT advance v1 (naive symmetric MM) to paper. No version clears the gate:**

| run | config | n_trades | net_pnl | sharpe | advance |
|---|---|---|---|---|---|
| gate-valid (contaminated) | hs=0.01, no boundary guard | 1335 | −$129 | 0.33 | False |
| artifact-corrected | hs=0.01, boundary guard 0.10 + market haircut | 339 | −$32 | −0.11 | **False (n<1000)** |

The MM-on-geopolitics **thesis is UNRESOLVED** (corrected margin is small/noisy and tradeable
mid-price geo is too sparse for a gate-valid MM verdict in one window). Pursue it in **v2 (inventory
skew)** on a larger multi-window dataset — not by re-confirming v1.

## Rationale — the artifacts and fixes (the heart of this ADR)
Adversarial sign-offs found the initial "decisive −$129 (gross +$2041 spread vs −$2170 adverse
selection)" was **largely an artifact, not a clean adverse-selection result**:

1. **Clamp/boundary artifact (HIGH).** 68.5% of the 1335 fills executed at the clamped prices
   0.01/0.99; **80% of fills were on tokens marked ≤0.10 or ≥0.90** (near-resolved binaries), where
   symmetric quotes degenerate to the tick and the flow is resolution-direction informed flow.
   → **Fix:** boundary guard (`quote_band`, default 0.10 in the sweep) — the MM stands aside within
   0.10 of 0/1. This removed ~75% of fills (1335→339); the removed fills were near-resolved churn,
   not real two-sided market-making.
2. **Accounting illusion (HIGH).** The recorded "−$2170 adverse selection" was mostly **inventory
   cost-basis** (−$2096, i.e. cash paid for shares now worth ~that), **not a loss**. True adverse
   selection (residual marked vs its own entry) ≈ **−$61**. Do **not** carry −$2170 forward as
   "adverse selection."
3. **Haircut mis-spec + cost-model violation (MEDIUM / blocker for magnitude).** `inventory_haircut`
   was set to the strategy's *own* `half_spread`, passed raw — **not routed through `src/pat/costs/`**
   (CLAUDE.md §1.3). You unwind at the *market's* spread, not the width you quoted. → **Fix:**
   `MARKET_HALF_SPREAD` (1 tick) + tested `liquidation_haircut()` in `costs/polymarket.py`; the sweep
   now uses it, independent of the quote spread.
4. **Through-trade fill = pessimistic lower bound (MEDIUM).** The MM fills only on trades that move
   *through* its quote (pre-selected adverse); benign at-touch fills are invisible. The real result
   is bounded below by this — unfixable in the harness (paper, ADR 0014).

**Cost sign-off (`fee-cost-auditor`):** the **SIGN** (do-not-advance) is honest and robust — it
survives `haircut=0` (original still −$56; corrected ≈ −$11…−$32). The **MAGNITUDE** is a soft lower
bound (every omitted cost — gas, slippage, realistic haircut — pushes more negative; none could mask
a hidden edge). No fee-model error wrongly turned an edge negative.

This is the gate working as designed (CLAUDE.md §0/§1.1): a non-viable strategy gated out **before**
real money, and adversarial review caught a **false "big loss" narrative before it was recorded**.

## Consequences
- **Positive:** v1 correctly gated out at zero capital risk; two real defects fixed (boundary guard;
  haircut routed through `costs/` + tested); the full data layer + backtest harness validated on real
  data (21,748 fills, both exchanges); the review process prevented a wrong verdict.
- **Negative / risks:** the MM-on-geopolitics thesis is **not settled** — the corrected run is
  gate-invalid (n<1000); mid-price 0%-fee geo is thin (~339 MM fills / 4.4 h) → a gate-valid MM
  verdict needs a much larger / multi-window dataset; the harness still cannot model benign-flow fill
  probability (paper-only, ADR 0014).
- **Follow-ups:**
  - **I9 / C6 downgraded VERIFIED → PARTIAL:** `feesEnabled=false` does **not** guarantee 0% on-chain
    — **885 / 21,748 fills (4.1%) on 73 tokens carried a nonzero on-chain fee** (e.g. "Will Alberta
    join the US?"), while *both* Gamma `feesEnabled` and CLOB `/fee-rate` reported 0. Negligible here
    ($17 total, on takers; our MM is a maker), but a **taker strategy / live must check the on-chain
    fee, not the metadata flag.** (`claims-verification.md` updated.)
  - **v2 (next cycle — brainstorm → spec → plan):** (1) inventory skew `fv − γ·inventory`
    (priority 1, testable in-harness) + boundary guard (already in); (2) vol-adaptive spread
    (priority 2, testable); (3) order-flow toxicity / VPIN — **paper-only** (no aggressor side / order
    book in our `(price,size)` stream). Test on **≥2–3 independent windows** (different days).
  - **Cost-model backlog:** route gas + slippage line items through `costs/`; replace the 1-tick
    haircut with a thinness/tail-aware model if v2 residuals land near 0/1.
  - **Golden raw-log fixture** (plan Task 7 Step 4b) still pending — needs one tiny raw fetch.
  - **Exploratory research candidates (not roadmap-committed):** top-50 wallet behavioral analysis
    (C1 — maker/taker are indexed → cheap per-wallet history, ~110k CU for 50 wallets); news-driven
    directional / "become-the-informed-flow" (§4 intelligence layer, Phase 4, paper-first).
