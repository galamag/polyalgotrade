# Logging & Observability (standard v1)

A first-class, cross-cutting concern — applied **everywhere, even one-off scripts in
`scripts/`**. A trading system you can't audit is one you can't trust. Decision: ADR
[`0004`](../decisions/0004-logging-standard-v1.md).

## v1 (now)
- **`structlog` → JSON to stdout.** Every log line carries:
  - `ts` (UTC ms), `level`, `event`, `mode` (`backtest`/`paper`/`live`), `strategy`,
  - `corr_id` — a correlation id threaded through one logical operation (signal → order →
    fill), so a decision can be reconstructed end-to-end.
- **Append-only trade journal.** v1 = newline-delimited JSON (`JSONL`) file per run. Every
  *decision* and order/fill is a record with full context:
  - what: `Order`/`Fill` fields,
  - **why**: `reason` (the strategy's rationale),
  - money: `price`, **`fee`** (from `costs/`), expected EV at decision time,
  - linkage: `corr_id`, `market_id`, `token_id`.
- **LLM calls (when the intelligence layer exists):** log `prompt`, `model`, `latency_ms`,
  `tokens`, `response`, and the parsed `signal` — so we can audit the LLM's contribution to PnL.
- **Secrets never logged.** No private keys, no API secrets — ever. (Enforced by review.)

## Why the journal matters
- It is the **audit trail**: "why did the bot place this order?" must always be answerable.
- It is the **dataset** `analytics/` consumes for PnL attribution and the EV/Sharpe verdict.
- It is how we compare paper vs backtest (Phase-3 gate) and live vs paper (Phase-5 gate).

## Later (explicit upgrade, to be discussed)
When a strategy proves out and volume grows: migrate the journal to **SQLite/parquet**, add a
**dashboard** (PnL, fills, latency, drawdown), log rotation/retention, and possibly metrics
(Prometheus-style). We deliberately do *not* build this until there's a strategy worth
watching — see roadmap. Revisit the dashboard/SQLite choice together at that point.

## Conventions
- Library code logs; it does not configure logging. Entry points (`scripts/`, services)
  configure the `structlog` processor chain once.
- One run → one journal file under `logs/` (gitignored), named with run id + UTC date.
