# ADR 0020 — Top-wallet behavioral analysis (lean): INCONCLUSIVE → escalate to Approach 2

- **Date:** 2026-06-09
- **Status:** Accepted
- **Deciders:** user + AI engineer (spec/plan + subagent-driven build + quant-researcher sign-off)

## Context
ADR 0019 shelved market-making and pivoted to characterizing the *winners*: classify the top
Polymarket wallets by P&L into behavioral archetypes to steer the next strategy (copy-trading C1 vs
directional/news D3, ADR-0013 catalog). We ran the **lean spike (Approach 1)** per
`specs/2026-06-09-wallet-analysis-spike-design.md`.

**Acquisition pivot (mid-run):** on-chain `eth_getLogs` per wallet **exploded on hyper-active top
wallets** — 1M CU burned, **0 wallets completed**, stuck on wallet #1 (top-P&L wallets have
1e5–1e6 fills → the result-set bisection recurses into thousands of calls). We pivoted the
acquisition to the **keyless `data-api.polymarket.com/trades`** endpoint (REST pagination,
volume-immune; claim **I13**), capped at the most-recent ≤2000 trades/wallet, with maker/taker role
recovered via a `takerOnly` true-vs-false set diff. The analytics pipeline (features → archetype →
skill screen → recommendation) was reused unchanged. Frame: top-50 by all-time PnL (data-api
leaderboard, I11/I12) + 25 median-activity control wallets from our V2-geopolitics dataset.

## Decision
**The lean read is INCONCLUSIVE. We do NOT select a strategy.** The result does not meet the
pre-registered gates:
- **§2 / B1 control gate FAILS** — the dominant archetype is `directional-holder` (40/50), whose
  designated discriminating feature `roundtrip_return_median` is **0 for all 40** (they don't sell
  on the book) → it cannot "beat control."
- **§9 / S1 skill cohort = 0/50** — no wallet passes `pnl_proxy>0 ∧ realized_share≥0.30 ∧ …`.

**Escalate to Approach 2 (resolution-grounded P&L)** — *not* "more wallets" (§13 Top-100) — because
the binding problem is **P&L measurement**, not sample size. **C1 (copy-trading) and D3
(directional/news) both remain open**, to be decided after Approach 2 (+ Approach 3 lag/fee replay
for C1).

## Evidence (results + why they don't support a pick)
Report: `docs/research/2026-06-09-wallet-analysis.md`; per-wallet features: `logs/wallet_features.jsonl`.

| feature | winners (median) | control (median) |
|---|---|---|
| maker_fill_ratio | 0.955 | 0.583 |
| flip_rate | 0.000 | 0.932 |
| realized_share | 0.000 | 1.000 |
| roundtrip_return_median | 0.000 | 0.000 |
| entry_price_mean | 0.514 | 0.496 |

Archetypes — winners: 40 directional-holder, 7 unclassified, 3 longshot-farmer; control: 25 unclassified.

**🔴 Binding caveat — SURVIVORSHIP (the most important line of this ADR):** the leaderboard is
`timePeriod=ALL, orderBy=PNL` — it **mechanically selects** wallets whose large directional bets
**won**; directional losers are structurally invisible. So "40/50 winners are directional-holders" is
**near-tautological** (big realized P&L mostly comes from big directional wins) and is **NOT**
evidence that buy-and-hold directional trading is +EV, an edge, or replicable. Any directional/copy
hypothesis from this spike is **survivorship-unproven** until tested on a non-survivorship sample
(wallets ranked **at entry**, not by outcome) with resolution-grounded P&L.

**Artifact disclosure (the label is partly manufactured by the method):** the `directional-holder`
label rests on `flip_rate=0` / `realized_share=0` / high `maker_fill_ratio`, all corrupted by
acquisition: **46/50** winners hit the 2000-trade recency cap (we see only a thin recent window);
**32/50** show *no exit leg at all*; **redemptions/resolutions are not in `/trades`**, so a winner's
actual gain (buy 0.4 → redeem 1.0) is invisible; **33/50** P&L-leaderboard winners compute
`pnl_proxy < 0` — i.e. **the trade-only P&L proxy is falsified by its own sampling frame.** The
`maker_fill_ratio` contrast (the one that clears the IQR bar) is itself a recency-window statistic,
not a lifetime behavioral trait, and is not the directional discriminator.

**What we CAN conclude:** within the recent window, the *winning* population skews to buy-side,
maker-led, hold-rather-than-flip behavior — qualitatively unlike ordinary geopolitics scalpers
(control). **What we CANNOT conclude:** that this style is +EV, skillful (vs lucky/survivorship), or
that an information edge exists. **C1 vs D3 is unresolved** — and note hold-to-resolution is the
*most* structurally copyable pattern, so C1 is **not** excluded by the "they hold" observation.

## Rationale
- The whole point of a cheap spike is a defensible go/no-go. It delivered one: **lean, trade-only
  data cannot judge these winners** (their edge lives in resolution payouts, which aren't trades),
  and the frame is survivorship-biased. Spending more on the same lean method (more wallets) would
  return more broken rows. The correct, cheap next step is to add the missing data (resolutions).
- This honors §1 (honesty about EV over optimism) and the §6 verdict discipline — we refuse to
  upgrade an artifact-laden, survivorship-tautological pattern into a "directional edge found."

## Consequences
- **Positive:** the spike was cheap (data-api keyless ≈ $0; the on-chain detour cost ≈ $0.45 of CU
  and bought the lesson that on-chain getLogs doesn't scale to active-wallet history). The 75-wallet
  trades dataset (`data/raw/wallet_trades/`) + the full pipeline are **reusable for Approach 2**.
- **Negative / honest:** we did **not** pick the next strategy. We narrowed the *method* needed to
  pick it (resolution-grounded P&L + a non-survivorship sample), not the strategy itself.
- **Process:** quant-researcher returned **GO-WITH-CHANGES**; this ADR + the report recommendation
  were rewritten from the original "build D3" to the inconclusive verdict above.

## Follow-ups / next
1. **Approach 2 — resolution-grounded P&L** (the gating next step): join each trade's `conditionId`
   → Gamma resolution (winning outcome) → compute true realized P&L **including redemption payouts**;
   re-screen skill vs luck. Reuses the saved trades dataset.
2. **Non-survivorship sample:** rank candidates **at entry** (e.g. all wallets active in a market set
   in a past window), not by all-time outcome, so directional losers are visible.
3. **Then** decide C1 vs D3; if C1, run **Approach 3** (replay with our lag + taker fee + slippage).
4. Carried: category-matched control (spec S3); `n_tokens` by `conditionId` not `asset` (S5 — the
   conditionId IS saved in the trades JSON, cheap fix); a narrow **on-chain spot-check** to verify
   data-api `/trades` matches chain on 1–2 wallets (the deferred trust step).
5. **Claim ceiling:** recent-window, all-time-PnL-survivorship sample; no resolution P&L. We are
   **not** claiming directional MM/copy is impossible — only that this lean read cannot decide.
