# Strategy: Market Making (first wave)

- **Status:** Hypothesis (implementation begins at roadmap Phase 2)
- **Roadmap phase:** 2
- **Owner subagent:** quant-researcher (+ fee-cost-auditor, risk-manager)

## 1. Hypothesis
On low-liquidity prediction markets (long-tail politics, geopolitics, niche), HFT market
makers don't fully cover the book, leaving spreads of ~3–8¢. By quoting both sides we earn
the spread and, where applicable, maker rebates — while paying little/no taker fee.

## 2. Edge thesis
- **Source of edge:** spread capture + (sometimes) maker rebate. ⚠️ **Corrected in Phase 0:**
  on **geopolitics the taker fee is 0% (C6 verified) — but the maker-rebate pool is therefore
  also 0**, so a geopolitics MM earns **pure spread, no rebate income**. Rebates (25% non-crypto
  / 20% crypto, C7) only exist where takers actually pay fees — i.e. **politics and other
  categories**, not geopolitics. So the two sub-niches have different economics: geopolitics =
  zero-fee spread capture; politics = spread + daily-batch rebate ($1/day gate).
- **Why it survives competition:** these markets are below the threshold where co-located HFT
  bothers to compete; the research names this the best edge/complexity ratio for small capital.
- **Expected gross edge:** the quoted half-spread per filled round-trip (TBD from data).
- **Expected NET edge after fees:** must be measured — geopolitics (0% taker) is the cleanest
  test; this is the Phase-2 gate.

## 3. Costs
- Geopolitics: 0% taker (verify C6). Politics: maker rebate (verify C7). Gas negligible (I7).
- Breakeven: spread captured must exceed adverse-selection losses + any fee. Route all of this
  through `src/pat/costs/`.

## 4. Data needed
- Categories: geopolitics, long-tail politics (low-liquidity). Crypto excluded initially
  (dynamic taker fee, HFT-dense).
- Window: the post-V2 period (since 2026-04-28) via `OrderFilled` (RPC) + Gamma metadata.
- Order-book depth/spread series to estimate fill probability.

## 5. Backtest plan
- **Conservative fill model:** assume back-of-queue; a maker quote fills only when the book
  trades through it; model adverse selection (we get filled when the market moves against us).
- Sample ≥1000 simulated quotes/fills.
- Metrics: net PnL, Sharpe, win-rate, max drawdown, **fee/rebate drag**, inventory risk.

## 6. Risk
- Sizing: ≤$5/position in paper/early-live; ≤25% bankroll total; 3–5 concurrent.
- Inventory limits (don't accumulate a one-sided book into a resolving event).
- **Don't hold to resolution** on dispute-prone markets (UMA risk) — flatten / sell winners
  ~$0.95+.
- Kill-switch on drawdown.

## 7. Results
| Run | Window | Trades | Net PnL | Sharpe | Win% | Max DD | Notes |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | pending Phase 2 |

## 8. Verdict
- [ ] EV > 0 after fees?  [ ] Sharpe > 1.0?  [ ] Survives pessimistic fills?
- **Decision:** pending. If yes → paper (Phase 3). If no after iteration → trash, pivot per the
  roadmap triggers.
