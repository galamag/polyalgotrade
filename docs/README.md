# polyalgotrade — Documentation Index

Algorithmic-trading **research** framework for prediction markets (Polymarket primary,
Kalshi secondary). The goal is a *validated codebase*: prove an edge in backtest → paper →
small real capital, before risking money. See [`../CLAUDE.md`](../CLAUDE.md) for the
operating manual.

## Start here
- 📍 **[roadmap.md](roadmap.md)** — phases 0–6 and the current position
- 🧭 **[superpowers/specs/2026-06-07-polyalgotrade-foundation-design.md](superpowers/specs/2026-06-07-polyalgotrade-foundation-design.md)** — master design spec
- 🔬 **[research/claims-verification.md](research/claims-verification.md)** — Phase-0 fact-check worklist

## Map
| Folder | Contents |
|---|---|
| `research/` | Source research (frozen) + claims verification tracker |
| `architecture/` | System design: layers, schema, cost model, brokers, intelligence, logging |
| `strategies/` | One doc per strategy: hypothesis → backtest → verdict (`_template.md`) |
| `decisions/` | 🔴 ADRs — every decision, numbered (`_template.md`) |
| `operations/` | VPS, security, runbook, tooling/MCP candidates |
| `superpowers/specs/` | Design specs from brainstorming |

## Conventions
- **Every decision → an ADR** in `decisions/` (mandatory).
- Docs in English; conversation in Russian.
- A strategy is "done" only with a fee-adjusted EV/Sharpe verdict on ≥1000 sim trades.
