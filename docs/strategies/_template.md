# Strategy: <name>

- **Status:** Hypothesis | Backtesting | Paper | Live | Trashed
- **Roadmap phase:** <n>
- **Owner subagent:** quant-researcher (+ fee-cost-auditor for the cost check)

## 1. Hypothesis
One paragraph: what inefficiency do we think exists, and why might it persist (who is *not*
already arbitraging it away)?

## 2. Edge thesis
- Source of edge:
- Why it survives competition (research says HFT killed simple arb — what's our angle?):
- Expected gross edge (bps):
- **Expected NET edge after fees** (the only number that matters):

## 3. Costs (route through `src/pat/costs/`)
- Taker fee / maker rebate applicable:
- Gas, slippage assumptions:
- Breakeven edge:

## 4. Data needed
- Markets / categories:
- Historical window:
- Source (Gamma / RPC / prices-history / Kalshi):

## 5. Backtest plan
- Fill model assumptions (be conservative):
- Sample size (≥1000 trades):
- Metrics: net PnL, Sharpe, win-rate, max drawdown, fee drag.

## 6. Risk
- Position sizing, max concurrent, stop rules, failure modes (resolution divergence, UMA,
  illiquidity).

## 7. Results
| Run | Window | Trades | Net PnL | Sharpe | Win% | Max DD | Notes |
|---|---|---|---|---|---|---|---|

## 8. Verdict
- [ ] EV > 0 after fees?  [ ] Sharpe > 1.0?  [ ] Robust to pessimistic fills?
- **Decision:** advance to paper / iterate / trash. Link the ADR.
