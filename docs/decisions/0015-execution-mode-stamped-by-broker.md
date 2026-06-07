# ADR 0015 — Execution `mode` is a broker concern, not a strategy concern

- **Date:** 2026-06-07
- **Status:** Accepted (partial now; full enforcement is a Phase-3 entry criterion)
- **Deciders:** AI engineer (Phase-2 Task-5 code review)

## Context
The Phase-2 Task-5 code review (MarketMaker v1) flagged an **important** seam issue: the strategy's
`_order()` hardcoded `mode="backtest"` into every `Order` it emitted. CLAUDE.md **principle 8**
requires the *same strategy code* to run unchanged across `BacktestBroker` / `PaperBroker` /
`LiveBroker`. A strategy that bakes a backend value into its output violates that: at Phase 3 the
same `MarketMaker` driven by a `PaperBroker` would emit orders journaled as `mode="backtest"`,
**corrupting the audit trail** (CLAUDE.md §3.1 makes `mode` a required journal field). The same
"mode hardcode" smell also appeared in `BacktestBroker.cancel()`'s journal call (already fixed —
the journal now uses its configured `self.mode`).

`mode` is an **execution-backend** fact, not a trading decision. It must originate from whichever
broker is running, never from the strategy.

## Options considered
1. **Strategy sets mode** (status quo) — simplest, but couples the strategy to a backend and
   corrupts paper/live journals. Rejected.
2. **Strategy omits mode; rely on the `Order`/`Fill` pydantic default (`"backtest"`)** — removes the
   strategy-level coupling now, but the default is still backtest-biased, so a paper/live order would
   still default wrong unless the broker overrides it.
3. **Broker stamps mode** — each broker sets the correct `mode` on orders it accepts (on `submit`)
   and fills it produces, for its own backend. The strategy never sets `mode`. Correct and complete.

## Decision
Adopt **option 3 as the target**, applied in two steps:
- **Now (Phase 2, backtest-only):** the strategy must NOT set `mode`. `MarketMaker._order()` no
  longer passes `mode` (the `Order` default `"backtest"` applies, which is correct while only the
  backtest backend exists). `BacktestBroker`'s own fill `mode="backtest"` literal is acceptable — it
  *is* the backtest broker.
- **Phase 3 (entry criterion, before any paper/live run):** `PaperBroker`/`LiveBroker` must **stamp**
  their own `mode` onto accepted orders and produced fills, and we reconsider whether the
  `Order`/`Fill` `mode` field should default to `"backtest"` at all (likely make the broker the sole
  source of truth). No strategy may set `mode`.

## Rationale
Honors principle 8 (backend-agnostic strategy) and §3.1 (correct, reconstructable audit trail).
Doing the *full* broker-stamping refactor now would be premature — `PaperBroker`/`LiveBroker` do not
yet exist, so there is nothing to stamp from. Recording it as a gated Phase-3 criterion (CLAUDE.md
§6) prevents the latent bug from reaching real money.

## Consequences
- Positive: the strategy is now backend-agnostic at the source; the latent paper/live audit-trail
  bug is documented and gated, not silently shipped.
- Negative / risks: until Phase 3, `Order`/`Fill` still default `mode="backtest"`, so the seam is
  only *partially* closed — a Phase-3 implementer MUST complete it (broker stamping) before paper.
- Follow-ups: Phase-3 `PaperBroker`/`LiveBroker` tasks must (a) stamp `mode` on submit + fills,
  (b) revisit the `Order`/`Fill` `mode` default, (c) add a test asserting a strategy-emitted order
  gets the broker's mode, not a hardcoded one.
