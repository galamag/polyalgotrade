# ADR 0013 — Phase-2 strategy catalog & verification order

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer (Phase-2 brainstorm)

## Context
Entering Phase 2 we need a set of candidate strategies spanning the risk spectrum (risk-free →
risky), to be verified **one at a time** by backtest. Market making is the roadmap-fixed first
wave (CLAUDE.md, `docs/roadmap.md`). The user asked for "strong strategies, from risky to
risk-free," and to **not bury** strategies the source research called dead — we verify them
ourselves. The binding constraint is **data**: we have on-chain `OrderFilled` trades (+ maker/taker addresses
*pending* primary-source ABI verification, claim I8) + Gamma metadata, but **no historical order
book** (see ADR 0014), which gates how honestly each strategy can be backtested today.

## Options considered
1. **Broad map + deep-design MM first** — catalog all ~9 strategies (hypothesis, risk tier,
   backtestability), then fully design only market making and carry it to a plan.
   *Pros:* see the whole field, no tunnel vision, still build one at a time. *Cons:* more upfront
   documentation.
2. **Narrow set (4–5 strongest by edge/complexity)** — only MM geopolitics, MM long-tail politics,
   copy-trading, combinatorial, dispute. *Pros:* focus. *Cons:* prematurely discards options the
   user explicitly wanted mapped (full spectrum).
3. **MM only now** — catalog as a name-list; all focus on MM. *Pros:* fastest to one verdict.
   *Cons:* loses the spectrum view the user asked for.

## Decision
**Option 1.** Adopt the full risk-mapped catalog (Tiers 0–3 + the `live book recorder` enabler)
and a fixed verification order:

```
B1 MM-geopolitics → B2 MM-politics(+rebate) → C1 copy-trading → A2 combinatorial-arb
   → D1 UMA-dispute → C2 cross-venue(Kalshi) → B3 informed-crypto-MM → D2 latency-arb → D3 news
```

Full catalog tables, edge/risk/backtestability per strategy, and rationale live in
`docs/superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md`. **Market making (B1) is the
first deep design** and the first to a verdict.

## Rationale
- Honors the roadmap (MM first) and the user's "full spectrum" intent (CLAUDE.md §0, §6).
- Order = roadmap-fixed first, then **backtestable-now & cheap** (C1, A2, D1), then **needs new
  data/infra** (C2, B3), then **verify-then-likely-bury** (D2) and **Phase-4** (D3). This front-
  loads strategies our current data can actually test honestly.
- Keeps "don't bury the dead" (CLAUDE.md): latency-arb (D2) stays in the catalog to be *verified*,
  not assumed dead.

## Consequences
- Positive: a single source of truth for what we test and in what order; each strategy still gets
  its own `docs/strategies/<name>.md` verdict and must pass the gate (n≥1000 ∧ net EV>0 ∧
  Sharpe>1.0) before advancing.
- Negative / risks: the order is a default, not a contract — a strong early result or a data
  blocker may reorder it (record any change as an ADR amendment).
- Follow-ups: ADR 0014 (book data + informed cross-venue MM); the MM deep design (spec Section 2)
  must fold in the ADR 0012 prerequisites (inventory mark-to-market + `assetId=="0"` parser fix)
  before any real MM verdict; `docs/roadmap.md` Phase 2/4 reference this catalog. **Before C1
  (copy-trading) is scheduled**, verify via `claims-verifier` that the V2 `OrderFilled` event ABI
  carries maker/taker addresses (claim I8, currently PENDING).
