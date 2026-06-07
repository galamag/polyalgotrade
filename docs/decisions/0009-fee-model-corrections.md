# ADR 0009 — Fee-model corrections from Phase-0 verification (Polymarket + Kalshi)

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** AI engineer (Phase-0 verification) + fee-cost-auditor mindset

## Context
The cost model is the heart of honesty (`CLAUDE.md` §1.3). Phase 0 verified the fee claims
(C5, C6, C7 Polymarket; C8 Kalshi) against official fee docs. Several specifics were wrong in
ways that would silently bias backtests.

## Decision — `src/pat/costs/` must encode these verified facts

**Polymarket taker fee:** `fee = shares · feeRate · p · (1−p)`, rounded to 5 dp (smallest
charged fee 0.00001; **anything smaller rounds to zero** — corrected per the Task-2 fee audit;
the earlier "min 0.00001 floor" was wrong). Domain-guarded (price∈[0,1], shares≥0).
- Per-category `feeRate` (config table, never hard-coded peaks):
  Crypto 0.07 · Sports 0.03 · Finance 0.04 · Politics 0.04 · Economics 0.05 · Culture 0.05 ·
  Weather 0.05 · Tech 0.04 · Mentions 0.04 · Other 0.05 · **Geopolitics 0.0**.
- Peak is **exactly 1.75%** at p=0.5 for crypto (the research's "1.56–1.80%" is wrong — derive
  from the formula, don't store a constant).
- **Makers are never charged** on Polymarket.

**Polymarket geopolitics (C6):** `feeRate = 0`. Nuance: the maker-rebate pool is also 0 there →
a geopolitics MM earns **pure spread**, no rebate income. (Affects the Phase-2 MM thesis.)

**Polymarket maker rebate (C7):** 25% non-crypto / 20% crypto of the taker pool, **daily pUSD,
$1 minimum** (rolls over). Model as a **separate daily batch credit**, NOT a per-trade fee
reduction. On a $50 bankroll the $1/day gate may rarely trigger — don't assume rebate income.

**Kalshi (C8):**
- Taker: `ceil(0.07 · p · (1−p) · contracts, $0.0001)` — **CEIL** rounding (to the cent for
  non-direct members), NOT `round(,2)`.
- **Maker fee is 0.0175** (25% of taker), also ceil-rounded — **not $0** as the research claimed.
- Per-series `fee_multiplier` can override 0.07 — fetch per series, default 0.07 taker / 0.0175 maker.

## Rationale
A wrong rounding direction or a "free" maker fee turns a losing strategy into a fake winner. The
auditor rule: assume the cost model is wrong until tested against the real schedule.

## Consequences
- Cost-model unit tests must include boundary prices where `ceil` ≠ `round` (e.g. p=0.20, 0.30)
  and the geopolitics zero-rate path.
- The MM strategy doc (`docs/strategies/market-making.md`) is updated: geopolitics MM = pure
  spread (no rebate); the rebate is a daily-batch credit with a $1 gate.
- Fee schedules are `STALE`-prone (taker-rebate program launched 2026-05-28) → re-audit before live.
