# Roadmap — Order of Validation

The spine of the project. Each phase has a **gate**; we do not advance until it is met.
Real money appears only at Phase 5, and only for strategies with a confirmed positive,
fee-adjusted edge.

**Current position: Phase 0 (foundation in place; claims verification next).**

---

## Phase 0 — Foundation & claims verification
- [x] Git, repo skeleton, `CLAUDE.md`, docs structure, subagents, design spec.
- [ ] Verify architecture-critical research claims against primary sources
      (`research/claims-verification.md`): CTF Exchange V2 addresses, `py-clob-client-v2`
      existence/version, fee formulas, KZ venue access today, CLOB endpoints.
- [ ] `ping`/`mtr` a candidate VPS region → Polymarket CLOB; record real latency.
- **Gate:** all *critical* claims marked VERIFIED or REFUTED (not PENDING).

## Phase 1 — Data + cost model + backtest core
- [ ] Data layer: historical `OrderFilled` (Polygon RPC + Gamma) → normalized schema.
- [ ] **Cost model** (`src/pat/costs/`): dynamic taker fees, maker rebates, gas, ramp — tested.
- [ ] `BacktestBroker` + analytics/verdict (PnL, Sharpe, win-rate).
- **Gate:** pipeline replays ≥1000 simulated trades; fees match the verified formulas.

## Phase 2 — Market making (first wave)
- [ ] `strategies/market_maker.py`: quote both sides, fixed spread, capped size.
- [ ] Backtest on geopolitics (0% taker fee) and long-tail politics (maker rebate).
- **Gate:** verdict — **EV > 0 after fees** and **Sharpe > 1.0**? If no → iterate or trash.

## Phase 3 — Paper trading
- [ ] `PaperBroker` (our own "drawn" sim — Polymarket has no usable testnet) + Kalshi demo.
- [ ] Run MM in paper; compare to backtest; validate full execution flow + logs.
- **Gate:** paper PnL ≈ backtest PnL (deviation < 10%); no recurring technical errors.

## Phase 4 — Remaining strategies (one at a time, same pipeline)
Order: **cross-market / combinatorial → copy-trading → latency-arb (verify, don't bury) →
news (intelligence layer activates)**. Each gets its own `strategies/<name>.md` verdict.
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
