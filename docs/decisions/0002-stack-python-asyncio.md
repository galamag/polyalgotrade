# ADR 0002 — Stack: Python 3.11+ / asyncio / uv

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer

## Context
We need a language/runtime for the framework. The Polymarket developer community is
Python-centric (`py-clob-client-v2` is the maintained V2 SDK — claim C4). The user is
intermediate in code. Official SDKs also exist in TypeScript; Rust V2 client is not yet
released per the research.

## Options considered
1. **Python + asyncio** — community default; maintained V2 SDK; rich data/analytics
   ecosystem (`polars`/`pandas`); good fit for the user's level.
2. **TypeScript** — official hot-swap SDK exists; but smaller data-science ecosystem and a
   second language for the user to carry.
3. **Rust** — best latency; but no V2-only SDK yet, steepest curve, and we are explicitly not
   competing on sub-100ms execution.

## Decision
**Python 3.11+ with `asyncio`** (single event loop, not threading). Tooling: `uv` (deps/venv),
`ruff` (lint/format), `mypy` (types), `pytest` (tests). Libraries: `httpx[http2]`,
`websockets`, `pydantic`, `polars`/`pandas`, `structlog`.

## Rationale
Maximizes use of the maintained SDK and the data/analytics ecosystem, matches the user's
level and the community, and our strategy set (MM, arb, copy) does not require Rust-level
latency. We deliberately are not building a sub-100ms HFT system.

## Consequences
- Positive: fastest path to working code; one language; strong typing via pydantic+mypy.
- Negative/risks: Python isn't ideal for the lowest-latency strategies — acceptable because
  latency-arb on small capital is out of scope (research) until ≥$2K bankroll.
- Follow-ups: pin exact deps in `pyproject.toml` during Phase 1.
