# ADR 0006 — Capital & gating policy: no real money before a proven edge

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer

## Context
Budget is $200. The source research argues that on this capital the cost of learning exceeds
the capital, and recommends treating $200 as infrastructure + tiny validation, not trading
capital. The user agreed to verify the ground first (backtest), then paper (real or our own
sim), then real money.

## Options considered
1. **Strict gating** — backtest → paper → small real ($50), advancing only on an EV/Sharpe
   verdict; real money only at Phase 5.
2. **Deploy a bot to production ASAP** to learn on live trades.
3. **Pure research** — never trade real money.

## Decision
**Option 1 (strict gating).** No real-money execution before Phase 5. A strategy advances a
stage only by meeting that stage's gate (`docs/roadmap.md`): backtest verdict (EV>0 net of
fees, Sharpe>1) → paper within 10% of backtest → ≤$5/position live for execution validation.

## Rationale
Neutralizes the research's core warning: we risk money only on edges we measured ourselves.
Matches the user's hybrid goal (research + learning + income, in that order). Risk limits
(≤25% bankroll/position, 3–5 positions, drawdown stop, kill-switch) are encoded in `risk/`.

## Consequences
- Positive: capital protected; decisions evidence-based; learning happens cheaply.
- Negative/risks: slower to first real trade — intended.
- Follow-ups: latency-arb on crypto is barred below a $2K bankroll regardless of verdict
  (cost structure). Re-verify KZ venue access and off-ramp before funding (claims C9, P2).
