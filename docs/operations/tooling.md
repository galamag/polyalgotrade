# Tooling — MCP / plugins / skills

**Framing:** MCP servers attach to *Claude Code* (dev-time research convenience). They are
**never** part of the production bot, which executes via its own audited code. Decision: ADR
[`0005`](../decisions/0005-mcp-tooling-stance.md). Status: **nothing connected yet (clean
start).**

## Security rule (hard)
Connect only **read-only data** servers, and only after reviewing their source. **Never**
connect an MCP that holds trade or private keys.

## Candidate MCP servers (read-only data) — connect later if useful

| Server | Provides | Notes |
|---|---|---|
| [JamesANZ/prediction-market-mcp](https://github.com/JamesANZ/prediction-market-mcp) | Polymarket + PredictIt + Kalshi data | read-only |
| [guangxiangdebizi/PolyMarket-MCP](https://github.com/guangxiangdebizi/PolyMarket-MCP) | Polymarket markets / positions / history | review scope |
| [PMXT](https://github.com/pmxt-dev) | Unified Polymarket + Kalshi API + MCP | unification convenience |
| [Nayshins/mcp-server-ccxt](https://github.com/Nayshins/mcp-server-ccxt) | Spot prices, 100+ exchanges (Binance/Coinbase) | for latency-arb research |

**Excluded:** IQ AI execute-capable servers (and any trade-capable MCP) — they require keys;
forbidden by the security rule.

## Future candidates to evaluate (user-requested, later)
- **TradingView** MCP (charts / indicators)
- **News** MCPs (headline/event feeds for the news strategy)
- **Research** MCPs (broader source aggregation)

## Skills / plugins (already available)
- **`deep-research`** — workhorse for Phase-0 claims verification.
- Installed plugins (`superpowers`, `anthropic-skills`, `commit-commands`) are sufficient; no
  trading-specific plugin needed now.

## How to connect (when we decide to)
Add the server to the Claude Code MCP config, review its tools, prefer read-only scopes, and
record the decision in an ADR.
