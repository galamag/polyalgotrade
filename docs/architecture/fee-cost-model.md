# Fee & Cost Model (`src/pat/costs/`)

**The most important module for honesty.** On $200, fees decide profitability. Every
order/fill — in backtest, paper, and live — gets its cost from here. No fee math lives
anywhere else. Owned/audited by the `fee-cost-auditor` subagent.

> All formulas below are **PENDING verification** (claims C5–C8 in
> [../research/claims-verification.md](../research/claims-verification.md)). Implement them as
> *configurable* parameters, and verify against the live API before trusting any backtest.

## What the model must account for

1. **Polymarket taker fee (dynamic).** Research: `fee = C · 0.07 · p · (1−p)` per share on
   crypto, peaking ~1.56–1.80% at `p=0.50`. Must be per-category (crypto vs other) and
   ideally read live via `getClobMarketInfo` rather than hard-coded.
2. **Geopolitics = 0% taker fee** (claim C6) — the Phase-2 MM edge. Verify per-market.
3. **Maker rebate.** ~25% of the taker pool (20% on crypto), paid daily in pUSD, min $1
   (claim C7). Model it as expected rebate per filled maker size.
4. **Kalshi fee.** `round(0.07 · price · (1−price), 2)` per contract; maker effectively $0 by
   rounding (claim C8).
5. **Gas.** Polygon tx ≈ $0.0024 (claim I7) — negligible but logged, never ignored.
6. **On/off-ramp.** USDC↔Binance↔P2P ≈ 1–2% (claim P2); MoonPay debit 2–3% (avoid). Applied
   at the bankroll level, not per trade, but tracked.
7. **Slippage** — not a fee, but modeled alongside (see broker fill model).

## Interface (illustrative)
```python
class CostModel(Protocol):
    def taker_fee(self, venue, market, price, size) -> Decimal: ...
    def maker_rebate(self, venue, market, price, size) -> Decimal: ...   # expected
    def gas_cost(self, venue, action) -> Decimal: ...
    def net_pnl(self, fills: list[Fill]) -> Decimal: ...                 # after all costs
```

## Non-negotiables
- **Breakeven is explicit.** Analytics must report the *net* (after-fee) EV; a strategy whose
  edge < fee is reported as losing, full stop.
- **Parameters are config, not magic numbers** — so when a verified formula changes, one file
  changes and every backtest re-runs.
- **Tested first.** The cost model gets unit tests (known price/size → known fee) before any
  strategy uses it. A wrong cost model silently turns a losing strategy into a "winner".
- **Fee changes are events.** If a verified fee schedule changes (e.g. geopolitics stops being
  0%), that's an ADR and a roadmap trigger.
