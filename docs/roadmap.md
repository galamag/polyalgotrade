# Roadmap — Order of Validation

The spine of the project. Each phase has a **gate**; we do not advance until it is met.
Real money appears only at Phase 5, and only for strategies with a confirmed positive,
fee-adjusted edge.

**Current position: Phase 0 ✅ + Phase 1 core ✅ (gates passed 2026-06-07) → Phase 2 in progress.**
Phase-2 strategy catalog + verification order **approved**; market making (B1) in design.
See [`research/phase0-verdict.md`](research/phase0-verdict.md),
[`superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md`](superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md),
ADR [0013](decisions/0013-phase2-strategy-catalog.md) / [0014](decisions/0014-orderbook-data-and-informed-crossvenue-mm.md).

---

## Phase 0 — Foundation & claims verification  ✅ COMPLETE
- [x] Git, repo skeleton, `CLAUDE.md`, docs structure, subagents, design spec.
- [x] Verify architecture-critical research claims against primary sources
      (`research/claims-verification.md`): V2 addresses ✅, SDK → `polymarket-client` (ADR 0008),
      fee formulas (corrected, ADR 0009), KZ access ✅, endpoints. Verdict: `phase0-verdict.md`.
- [ ] ~~`ping`/`mtr` VPS → CLOB latency~~ → **deferred to VPS setup** (needs a real VPS; L1).
- **Gate: ✅ PASSED** — no critical claim PENDING. Corrections captured in ADRs 0007–0009.
- **Carried into Phase 1:** I5 (UMA-vs-Chainlink settlement — on-chain check), I6 (KYC), and
  the SDK/fee/endpoint corrections.

## Phase 1 — Data + cost model + backtest core
- [ ] Data layer: historical `OrderFilled` (Polygon RPC + Gamma) → normalized schema.
- [x] **Cost model** (`src/pat/costs/`): dynamic taker fees, maker rebates, gas, ramp — tested.
- [x] `BacktestBroker` + analytics/verdict (PnL, Sharpe, win-rate).
- [x] End-to-end smoke: pipeline processes ≥1000 synthetic taker fills net-of-fee; fee_drag > 0;
      net_pnl == gross_pnl − fee_drag; TradeJournal records every fill. Core mechanically complete.
- **Gate (core): PASSED 2026-06-07** — pipeline runs ≥1000 trades net-of-fee.
  Real-data verdict pending Phase 2 (data layer + strategy needed for live Sharpe/EV gate).

## Phase 2 — Market making (first wave)
> Full strategy **catalog** (risk-free → risky, all ~9 candidates) and the fixed verification
> order live in [`superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md`](superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md)
> and ADR [0013](decisions/0013-phase2-strategy-catalog.md). Market making (B1) is verified first.
- [ ] **Prerequisites (ADR [0012](decisions/0012-phase1-analytics-limitations.md)) before any real MM verdict:**
      inventory mark-to-market in `analytics/metrics.py`; parser uses `assetId=="0"` for the USDC leg.
- [ ] `strategies/market_maker.py`: quote both sides, fixed spread, capped size.
- [ ] Backtest on geopolitics (0% taker fee = pure spread) and long-tail politics (maker rebate).
      Backtest fidelity is capped by the **through-trade proxy** — no historical Polymarket book
      exists (ADR [0014](decisions/0014-orderbook-data-and-informed-crossvenue-mm.md)); real
      validation is paper (Phase 3). Build a **`live book recorder`** early to feed paper + future backtests.
- **Gate:** verdict — **EV > 0 after fees** and **Sharpe > 1.0**? If no → iterate or trash.

## Phase 3 — Paper trading
- [ ] `PaperBroker` (our own "drawn" sim — Polymarket has no usable testnet) + Kalshi demo.
- [ ] Run MM in paper; compare to backtest; validate full execution flow + logs.
- **Gate:** paper PnL ≈ backtest PnL (deviation < 10%); no recurring technical errors.

## Phase 4 — Remaining strategies (one at a time, same pipeline)
Authoritative order = the Phase-2 **catalog** (ADR [0013](decisions/0013-phase2-strategy-catalog.md)):
after MM (B1/B2) → **copy-trading → combinatorial arb → UMA-dispute reversion → cross-venue
(Kalshi) → informed cross-venue crypto MM → latency-arb (verify, don't bury) → news (intelligence
layer activates)**. Each gets its own `strategies/<name>.md` verdict.
- **Gate (per strategy):** its own EV/Sharpe verdict before paper.

## Phase 5 — Small real capital ($50)
- [ ] Fund pUSD via Binance → MetaMask (not MoonPay). One validated strategy, ≤$5/position.
- [ ] Goal is **execution validation, not income**.
- **Gate:** live PnL tracks paper; stable, no repeated errors.

## Phase 6 — Scale / hybrid
- Only if stably positive for 3 consecutive months. Combine validated strategies.

---

### Triggers to change strategy (from research)
- 60 days of paper MM on geopolitics not reaching a stable +1–3%/mo → MM isn't for us; pivot.
- Polymarket adds a fee on geopolitics → main MM edge gone; replan to cross-market / disputes.
