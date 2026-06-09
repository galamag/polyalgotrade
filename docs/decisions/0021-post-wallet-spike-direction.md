# ADR 0021 — Post-wallet-spike direction: sequenced hybrid with pre-registered kill criteria

- **Date:** 2026-06-10
- **Status:** Accepted
- **Deciders:** user + advisor session (Cowork); to be executed by AI engineer

## Context
ADR 0020 left us at a fork: **(A)** switch to a testable-now catalog strategy
(combinatorial-arb A2 / UMA-dispute D1, per ADR 0013) vs **(B)** deepen wallet analysis
via Approach 2 (resolution-grounded P&L + non-survivorship sample) to decide C1 vs D3.

Treating this as a binary choice is wrong because (B) is not one unit of work. It splits into:
- a **cheap half** — Approach 2 on the already-saved 75-wallet dataset
  (`data/raw/wallet_trades/`, pipeline reusable, only the conditionId → Gamma resolution
  join is new), and
- an **expensive half** — the non-survivorship sample (enumerate all wallets active in a
  past market window, fetch their trades, persistence testing) — a new acquisition effort
  of unknown size, feeding a strategy (C1) whose copyability prior is moderate at best
  (the winners' edge lives at *entry*; a copier enters later at a worse price, as taker).

Constraints: limited session budget (focus risk if we run two tracks loosely), the §6 gate
(n ≥ 1000 fee-adjusted trades) which D1 structurally cannot meet (dispute frequency is far
too low), and the 6-month goal being a **validated codebase**, not a first-try strategy pick.

## Options considered
1. **Pure (A): jump to A2/D1** — fastest path to a gateable verdict, but discards the
   already-paid-for 75-wallet dataset and leaves the C1/D3 question permanently open on a
   method we know was inconclusive rather than negative.
2. **Pure (B): full Approach 2 + non-survivorship build** — answers C1/D3 properly, but
   commits the expensive half before knowing whether even the *survivors'* true P&L looks
   systematic; risks weeks of analytics work with no strategy verdict and no
   infrastructure spillover toward Phase 3.
3. **Sequenced hybrid (chosen)** — run the cheap half of (B) first as an
   information-buying step with a pre-registered kill criterion; start the A2 feasibility
   scan next regardless of the outcome; spend on the expensive half of (B) only if the
   cheap half clears the bar.

## Decision
**Step 1 — time-boxed (1–2 sessions): Approach 2 on the saved 75 wallets.**
Join each saved trade's `conditionId` → Gamma resolution → compute TRUE realized P&L
including redemption payouts. Deliverable is a **concentration screen**, not a C1/D3 pick:
per wallet, is resolution-grounded P&L spread across many independent winning markets
(systematic) or concentrated in 1–3 bets (single-shot whale)? Carried fixes ride along:
S5 (`n_tokens` by `conditionId`) and the on-chain spot-check of `/trades` on 1–2 wallets
(trust step for I13).

**Kill criterion (pre-registered, before the run):** if **< 5 of 50** top wallets show a
diversified profile — resolution-grounded P&L > 0 spread across **≥ 10 independent
conditionIds** with **top1_share < 0.5** — branch (B) closes entirely: no non-survivorship
build, C1 archived with a follow-up ADR. If **≥ 5** qualify, the expensive half of (B) is
justified and proceeds (entry-ranked sample + persistence test, then Approach 3 for C1).

**Step 2 — A2 combinatorial-arb feasibility scanner** (read-only, current markets):
measure frequency and magnitude of price-sum violations across mutually-exclusive outcome
structures, **net of fees and gas**. Prerequisite: route **gas + slippage as line items
through `src/pat/costs/`** (existing backlog item; mandatory for thin-margin arb verdicts).
The scanner accrues **calendar data** (arb-window frequency cannot be bought
retroactively), so it starts early and runs in the background regardless of Step 1's outcome.

**Step 3 — conditional:** kill criterion passed → build the non-survivorship sample;
failed → full focus on A2 (and, if A2 also reads "swept clean", on order-book recorder +
Phase-3 paper infrastructure).

**D1 (UMA-dispute) is deprioritized as a first candidate:** dispute frequency is
incompatible with the §6 n ≥ 1000 gate; a verdict on tens of events is invalid by our own
rules. It stays in the ADR 0013 catalog as an opportunistic, low-frequency strategy for later.

## Rationale
- §1 (honesty about EV): the cheap half of (B) buys the exact information that decides
  whether the expensive half is worth anything, instead of betting weeks on a moderate prior.
- §6 (verdict discipline): the kill criterion is fixed *before* the run so the goalposts
  cannot move after seeing results — the same discipline that saved us in ADR 0018/0020.
- 6-month goal: A2 builds infrastructure (price/book snapshots, live scanning) that
  Phase 3 needs anyway — positive spillover even on a negative verdict. Pure (B) exercises
  analytics only.
- Focus risk is contained by strict ordering and the Step-1 time-box, not by parallelism.

## Consequences
- **Positive:** the paid-for dataset gets used; C1/D3 gets a defensible go/no-go for ~1–2
  sessions of work; A2 scanner starts accruing irreplaceable calendar data early; gas/slippage
  cost-model gap closes as a forced prerequisite.
- **Negative / risks:** Step 1 may still be frame-limited (recent-2000 window caps what
  resolutions we can see) — if the join yields too few resolved positions per wallet, the
  concentration screen itself may come back inconclusive; cap the response to the time-box,
  do not extend it. A2 carries a real "already swept by faster bots" risk — that is a valid,
  cheap negative verdict, not a failure.
- **Follow-ups:** ADR on Step-1 outcome (kill criterion verdict); update `docs/roadmap.md`
  and `docs/HANDOFF.md`; golden raw-log fixture remains open backlog; MM revisit still
  gated on an order-book recorder (ADR 0014).
