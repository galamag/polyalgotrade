# polyalgotrade

[![Made with Claude Code](https://img.shields.io/badge/Made%20with-Claude%20Code-d97757)](https://claude.com/claude-code)

Algorithmic-trading **research** framework for prediction markets — Polymarket (primary) and
Kalshi (price source / cross-market monitoring).

## Philosophy
The goal is a **validated codebase**, not deposit-to-profit. We never risk real money until
the system itself has proven an edge — *after fees* — through a mandatory gate:

```
backtest  →  paper (own sim + Kalshi demo)  →  small real ($50)  →  scale
```

Strategies are plugins behind one interface, run unchanged across all three execution
backends, so a backtest verdict is a trustworthy prediction of live behavior. Fees are a
first-class, fully-tested concern (they decide profitability on small capital). Every
decision is recorded as an ADR.

## Status
**Phase 0** — foundation in place; research-claims verification next. See
[`docs/roadmap.md`](docs/roadmap.md).

## Documentation
- 🧭 [Design spec](docs/superpowers/specs/2026-06-07-polyalgotrade-foundation-design.md) — the full picture
- 📍 [Roadmap](docs/roadmap.md) — phases 0–6 and gates
- 🔬 [Claims verification](docs/research/claims-verification.md) — Phase-0 fact-check worklist
- 🏛️ [Architecture](docs/architecture/overview.md) · 🧱 [Decisions (ADRs)](docs/decisions/) · ⚙️ [Operations](docs/operations/)
- Full index: [`docs/README.md`](docs/README.md)

## Layout
```
src/pat/      # 7-layer core: data · venues · execution · costs · strategies · risk · analytics (+ signals seam)
tests/        # pytest, mirrors src/
scripts/      # one-off runners (data fetch, backtests)
docs/         # specs, architecture, strategies, decisions, operations
.claude/agents/   # 7 dev-time subagents
```

## Setup (early)
```bash
uv sync                 # install deps (added per phase)
uv run pytest           # tests
cp .env.example .env    # fill in secrets — NEVER commit .env
```

---
_Made with [Claude Code](https://claude.com/claude-code)._
