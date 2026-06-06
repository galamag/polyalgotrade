# ADR 0004 — Logging standard v1 (structlog JSON + append-only trade journal)

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer

## Context
The user requires clear logging **everywhere — even ordinary scripts**. A trading system must
be auditable: we have to be able to reconstruct *why* the bot acted, and we need a dataset for
PnL attribution and the EV/Sharpe verdict.

## Options considered
1. **v1 now: `structlog` JSON + append-only JSONL trade journal**; upgrade to SQLite/parquet +
   dashboard later when a strategy proves out.
2. **Full observability now** — SQLite/parquet journal + dashboard + metrics from day one.
3. **Minimal logging** — stdlib `logging`, no structured journal.

## Decision
**Option 1.** Start with `structlog` JSON (with `corr_id`, `mode`, `strategy`) plus an
append-only JSONL trade journal capturing every decision/order/fill with its **reason** and
**computed fee**. Defer dashboard/SQLite to an explicit later discussion.

## Rationale
Captures the non-negotiable audit trail and the analytics dataset immediately, with minimal
overhead, while avoiding building a dashboard before there's a strategy worth watching (YAGNI).
The user explicitly chose "simple now, upgrade later".

## Consequences
- Positive: every decision reconstructable from day one; cheap; analytics-ready.
- Negative/risks: JSONL is clumsy at large volume — fine until a strategy scales.
- Follow-ups: when upgrading, write a new ADR for the SQLite/parquet + dashboard choice.
  Standard documented in `docs/architecture/logging-observability.md`.
