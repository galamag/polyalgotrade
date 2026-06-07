# ADR 0012 — Phase-1 analytics/data limitations deferred to Phase 2

- **Date:** 2026-06-07
- **Status:** Accepted (deferred work, recorded so it is not lost)
- **Deciders:** AI engineer (final Phase-1 code review)

## Context
The Phase-1 final review (verdict SHIP_WITH_NITS) confirmed the honesty-critical paths are
sound (net = gross − fees, no rebate income, conservative strict-inequality fills, Decimal
money). It flagged two consequential limitations that are fine for the Phase-1 *machinery* but
MUST be addressed before any real-data strategy verdict (CLAUDE.md §6). Recording them here so
Phase 2 picks them up.

## Decisions (what we deferred, and why it's safe for now)

1. **`gross_pnl` is realized cash-flow only — open inventory is not marked to market.**
   `summarize()` computes `gross_pnl = Σsells − Σbuys`. A strategy that ends a window holding
   shares shows a falsely negative PnL; one that ends net-short shows false profit. The Phase-1
   smoke is balanced (500 buys / 500 sells) so this doesn't bite. **Phase-2 requirement:** value
   open `net_size` at resolution (or last/mid price) before computing the EV/Sharpe verdict, or
   the gate will mis-rank any strategy that ends with inventory. This is the single most
   important analytics gap.

2. **The OrderFilled parser uses a magnitude heuristic, not the authoritative USDC leg.**
   `_price_and_size` picks "shares = the larger leg," but `parse_orderfilled` already identifies
   the collateral leg via `assetId == "0"`. The heuristic is fragile near price 1.0 and
   internally inconsistent. It's flagged "provisional" and no real data is parsed yet.
   **Phase-2 requirement:** derive price/size from the asset-ID leg identification (USDC leg =
   `assetId == "0"`), and validate against a real fetched sample.

## Minor nits (track, low priority)
- `run_backtest_smoke.run()` computes a `Verdict` and discards it (dead code) — return or drop.
- `Order.notional` uses default `ROUND_HALF_EVEN` vs the cost layer's deliberate
  `ROUND_HALF_UP`/`ROUND_CEILING`; not used in PnL today, but a future use could disagree by a cent.
- Test coverage to add in Phase 2: a `win_rate` value assertion; a `max_drawdown` test against a
  known peak-to-trough series; the parser's `price==1` tie-break and zero-shares guard.

## Consequences
- Phase-1 core ships as the validated *pipeline* (≥1000 trades, net-of-fee, honest verdict).
- Phase 2 must implement inventory mark-to-market and the asset-ID parser fix **before** trusting
  any strategy's EV/Sharpe verdict. These are entry criteria for the Phase-2 gate.
