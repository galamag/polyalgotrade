# Runbook

Operational procedures. Fills out as the system is built (Phase 1+). Placeholder commands use
`uv`.

## Common commands (to be implemented)
```bash
uv sync                      # install/lock deps
uv run pytest                # tests
uv run ruff check . && uv run mypy src   # lint + types
uv run python -m pat.scripts.fetch_data  # historical data (Phase 1)
uv run python -m pat.scripts.backtest --strategy market_maker --window 6w  # (Phase 2)
uv run python -m pat.scripts.paper --strategy market_maker                  # (Phase 3)
```

## Modes
- `backtest` — offline replay, deterministic.
- `paper` — live data, simulated fills, no money (+ Kalshi demo where used).
- `live` — real execution (Phase 5 only; ≤$5/position).

## Kill-switch (must exist before any live run)
- A single action that: cancels all open orders, stops new order generation, and logs the
  halt with `corr_id`. Document the exact command here once implemented.

## Incident checklist
1. Hit the kill-switch.
2. Capture the trade journal + logs for the window.
3. Reconstruct the decision chain by `corr_id`.
4. Write an ADR if the cause changes a decision; update `claims-verification.md` if a fact was
   wrong.

## Daily/operational checks (once live)
- Uptime of the systemd unit; journal growing; no repeated errors.
- Realized vs expected fees (cost-model drift = a `fee-cost-auditor` task).
- Drawdown vs limit; bankroll vs sizing rules.
