# ADR 0001 — Architecture: own thin core, vertical slice (Approach A)

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer (brainstorming)

## Context
We need a framework to research multiple prediction-market strategies and progress each
through backtest → paper → live, on a $200 budget, with an intermediate-level user whose
goals include learning. The strategy set will grow (MM first, then cross-market, copy,
latency, news) and may later combine into a hybrid.

## Options considered
1. **A — own thin core, vertical slice first.** Plugin strategies; one strategy interface,
   three brokers (backtest/paper/live); build the MM slice end-to-end first, then widen.
   - Pros: fast path to "see edge ourselves" on MM; clean plugin design; full understanding
     (serves learning); full control over honest fee accounting.
   - Cons: we write some infrastructure ourselves.
2. **B — adopt `nautilus_trader` + write adapters.**
   - Pros: battle-tested backtest/execution/risk.
   - Cons: steep curve; heavy; poor fit for prediction-market semantics (binary outcome
     tokens, resolution, UMA); overkill for $200; worse for learning the fundamentals.
3. **C — scripts + pandas, no framework.**
   - Pros: fastest to first backtest numbers.
   - Cons: throwaway; no path to paper/live; violates "one code across backtest→paper→live".

## Decision
**Approach A.** Build a thin core we own, vertical-slice for market making first, extend via
plugins.

## Rationale
A uniquely satisfies "one strategy interface, three execution backends" (the basis of
trustworthy verdicts), matches the MM-first roadmap, and best serves the learning goal. We
will still borrow ideas/code from `warproxxx/poly_data` and study `nautilus_trader`, but keep
our core thin and comprehensible.

## Consequences
- Positive: clean seams (`signals/` for later intelligence layer); each layer testable in
  isolation; hybrid = new plugin.
- Negative/risks: we maintain our own backtest fill model — must keep it conservative to
  avoid optimistic-fill bias.
- Follow-ups: ADR 0002 (stack), 0004 (logging); the 7-layer spec in
  `docs/architecture/overview.md`.
