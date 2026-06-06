# ADR 0005 — MCP / tooling stance: document now, connect read-only later

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer

## Context
The user asked which MCP connectors / plugins / skills to attach to Claude Code for this
domain. A web search found community MCP servers for prediction markets (JamesANZ,
guangxiangdebizi, PMXT, shaanmajid) and crypto (CCXT: Nayshins, LazyDino), plus trade-capable
ones (IQ AI). The MCP registry returned no one-click connectors for these.

## Options considered
1. **Document candidates now; connect a read-only data MCP later** when manual market research
   warrants it; never connect anything now.
2. **Connect a read-only data MCP now** (e.g. PMXT or prediction-market-mcp).
3. **No third-party MCP at all** — only our own code + primary sources.

## Decision
**Option 1.** List candidates with a security stance in `docs/operations/tooling.md`; connect
nothing now (clean start). Revisit MCP selection later (the user also wants to consider
TradingView, news, and research MCPs).

## Rationale
- MCP servers attach to *Claude Code* (dev-time convenience), never to the production bot —
  the bot executes via its own audited code.
- Security: third-party servers see the session context; connect only **read-only data**
  servers, only after reviewing their code; **never** one holding trade/private keys
  (rules out IQ AI execute-capable servers with keys).
- No need yet — Phase 0/1 rely on primary sources and our own pipeline.

## Consequences
- Positive: clean, safe start; options preserved and documented.
- Negative/risks: slightly more manual market lookup until we connect a data MCP — acceptable.
- Follow-ups: evaluate TradingView / news / research MCPs in a later session; any connection
  gets a code review and an ADR.
