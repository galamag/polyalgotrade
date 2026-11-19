# polyalgotrade

[![Made with Claude Code](https://img.shields.io/badge/Made%20with-Claude%20Code-d97757)](https://claude.com/claude-code)

> **This is a personal experiment, not a trading system.**
> These are purely my own experiments: four days in June 2026 spent finding out how algorithmic
> trading on prediction markets (Polymarket, Kalshi) actually works. **Nothing serious came out
> of it.** No strategy passed its own gate, nothing was deployed, and the code contains no
> order-placing or signing path at all, so it has never touched real money. I am publishing it
> as-is, as a record of what I tried. It is not maintained and it is not financial advice.

## What this is
A research sandbox built together with [Claude Code](https://claude.com/claude-code): a backtest
engine, a fee/cost model, read-only data fetchers and a few analysis scripts. The one rule was
that no real money is risked until an edge is proven after fees, through a fixed gate:

```
backtest  →  paper  →  small real ($50)  →  scale
```

The project never got past the first stage.

## What I tried and how it went

| Experiment | Outcome |
|---|---|
| Fact-checking second-hand research against primary sources | Done. Some claims needed correcting (SDK choice, fee formulas): see the [claims log](docs/research/claims-verification.md) and ADRs 0007–0009 |
| Data layer, fee/cost model, backtest core | Built and unit-tested |
| Market making on 0%-fee geopolitics markets | **Failed its gate.** Backtest on 21,748 real on-chain fills; the reported runs had negative net P&L ([ADR 0018](docs/decisions/0018-geopolitics-mm-verdict.md)) |
| The same strategy with inventory skew | **Did not rescue it.** No skew setting brought net P&L to zero or above; market making shelved ([ADR 0019](docs/decisions/0019-v2-skew-spike-verdict.md)) |
| Behavioural analysis of top leaderboard wallets | **Inconclusive.** Survivorship bias and an unreliable P&L proxy ([ADR 0020](docs/decisions/0020-wallet-analysis-verdict.md)) |
| Resolution-grounded P&L screen of the same wallets | Passed a pre-registered screen, which justified more research and nothing else. No edge is claimed ([ADR 0022](docs/decisions/0022-resolution-screen-verdict.md)) |
| Read-only structural-arbitrage scanner | Built; no feasibility verdict was reached |
| Paper trading, live trading | Never started |

**Bottom line: no profitable strategy was found.** The negative results, written down honestly,
are the main output.

## Status
Not under active development. All research and code date from 7–10 June 2026. The
[roadmap](docs/roadmap.md) and [handoff notes](docs/HANDOFF.md) describe next steps as they were
planned then; read them as a snapshot, not a promise.

## What is in here
```
src/pat/
  costs/          fee/cost model for Polymarket and Kalshi (unit-tested)
  execution/      backtest broker and no-look-ahead replay loop
  data/           on-chain OrderFilled decoding, wallet histories
  venues/         read-only Polymarket clients: Gamma, CLOB books, trades, leaderboard
  analytics/      P&L metrics, wallet features, resolution P&L, arb-window scan
  strategies/     one strategy: a market maker that failed its backtest gate
  risk/ signals/  empty placeholders
tests/            pytest, mirrors src/
scripts/          one-off runners: data fetch, backtests, screens
docs/             design spec, ADRs (every decision and verdict), research notes
.claude/agents/   the Claude Code subagents used during development
```

## Documentation
- 🧭 [Design spec](docs/superpowers/specs/2026-06-07-polyalgotrade-foundation-design.md) — the original plan
- 📍 [Roadmap](docs/roadmap.md) — phases 0–6 and where it stopped
- 🔬 [Claims verification](docs/research/claims-verification.md) — the fact-check log
- 🏛️ [Architecture](docs/architecture/overview.md) · 🧱 [Decisions (ADRs)](docs/decisions/) · ⚙️ [Operations](docs/operations/)
- Full index: [`docs/README.md`](docs/README.md)

## Running it
```bash
uv sync          # install dependencies
uv run pytest    # run the tests
```
The fetch scripts only make read-only API calls. The on-chain ones need a Polygon RPC URL in the
`POLYGON_RPC_URL` environment variable. Nothing here needs a wallet key: `.env.example` lists
keys for a live phase that was never built.

---
_Made with [Claude Code](https://claude.com/claude-code)._
