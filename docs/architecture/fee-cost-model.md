# Fee & Cost Model (`src/pat/costs/`)

**The most important module for honesty.** On $200, fees decide profitability. Every
order/fill — in backtest, paper, and live — gets its cost from here. No fee math lives
anywhere else. Owned/audited by the `fee-cost-auditor` subagent.

> ✅ **Verified 2026-06-07** against official fee docs (claims C5–C8; ADR
> [0009](../decisions/0009-fee-model-corrections.md)). Constants below are the verified values;
> keep them *configurable* (a fee schedule can change) and re-audit before live.

## What the model must account for

1. **Polymarket taker fee.** `fee = shares · feeRate · p · (1−p)`, rounded to 5 dp (smallest
   charged fee 0.00001; anything smaller rounds to **zero**). Domain-guarded: price∈[0,1],
   shares≥0 (a negative fee would be a fake credit). **Per-category `feeRate`** (config table): Crypto 0.07 · Sports 0.03 · Finance 0.04
   · Politics 0.04 · Economics 0.05 · Culture 0.05 · Weather 0.05 · Tech 0.04 · Mentions 0.04 ·
   Other 0.05 · **Geopolitics 0.0**. Crypto peak is **exactly 1.75%** at p=0.5 — derive from
   the formula, never hard-code the peak. **Makers are never charged.**
2. **Geopolitics = 0% taker fee** (C6, verified). Nuance: the maker-rebate pool there is also
   0 → a geopolitics maker earns **pure spread, no rebate income**.
3. **Polymarket maker rebate** (C7, verified). 25% non-crypto / 20% crypto of the taker pool,
   paid **daily in pUSD, $1 minimum** (rolls over). Model as a **separate daily batch credit**,
   NOT a per-trade fee reduction. On a $50 bankroll the $1/day gate may rarely trigger.
4. **Kalshi fee** (C8, verified — research was wrong). Taker:
   `ceil(0.07 · p · (1−p) · contracts, $0.0001)` — **CEIL** rounding, not `round(,2)`. **Maker
   fee = 0.0175** (25% of taker), also ceil-rounded — **not $0**. Per-series `fee_multiplier`
   can override 0.07.
5. **Gas.** Polygon tx ≈ $0.0024 (claim I7) — negligible but logged, never ignored.
6. **On/off-ramp (verified 2026-06-07).** Cheapest route: **Freedom Bank → Binance KZ** (USDT
   ~1:1, **~free** via direct bank gateway) → on-chain transfer to/from Polymarket; the only real
   cost is the **crypto transfer/withdrawal fee** (small). Card/Apple-Pay deposit to Polymarket ≈
   **2.18%** ($2.16 processing + $0.02 network per $100) — **avoid for funding**. Withdrawal is
   crypto-only. Tracked at bankroll level, not per trade.
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
