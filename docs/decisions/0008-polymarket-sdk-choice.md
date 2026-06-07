# ADR 0008 — Polymarket Python SDK: use `polymarket-client` (py-sdk), not `py-clob-client-v2`

- **Date:** 2026-06-07
- **Status:** Accepted (supersedes the research's C4 recommendation)
- **Deciders:** AI engineer (Phase-0 verification)

## Context
The research (claim C4) said to use `py-clob-client-v2 >= 1.0.1`. Phase-0 verification against
PyPI, GitHub, and the official docs found this is **already one generation behind**.

Findings (2026-06-07):
- `py-clob-client` (v0.34.6) — **archived, non-functional**, with a migration notice.
- `py-clob-client-v2` (v1.0.1, 2026-05-09) — exists, official, **but its own README says
  "use `Polymarket/py-sdk` for new projects."**
- `polymarket-client` (PyPI `0.1.0b3`, 2026-05-27; repo `Polymarket/py-sdk`) — the **unified
  SDK the official docs install** (`docs.polymarket.com/dev-tooling/python`). Status: **beta**.

## Options considered
1. **`polymarket-client` (py-sdk)** — official current recommendation; beta.
2. `py-clob-client-v2` — works but explicitly deprecated-in-favor-of py-sdk; tech debt on day 1.
3. Pin nothing yet — defer to Phase 1.

## Decision
Depend on **`polymarket-client`** (the unified py-sdk). Pin the exact beta version in `uv.lock`.
Keep our thin `src/pat/venues/polymarket/` adapter as the isolation layer so beta API churn
touches one file only.

## Rationale
Building on the officially-recommended SDK avoids immediate migration debt. The beta risk is
real but contained by the adapter pattern (ADR 0001). Aligns with "don't trust research on
faith" — the research's SDK name was stale.

## Consequences
- `pyproject.toml` dependency = `polymarket-client>=0.1.0b3` (allow pre-release), added in Phase 1.
- Beta churn risk → watch releases; the adapter absorbs surface changes.
- Re-confirm the signing struct (ADR 0007) against the actual `polymarket-client` internals when
  we wire it.
