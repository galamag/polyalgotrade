# polyalgotrade — Design Spec (Foundation)

- **Date:** 2026-06-07
- **Status:** Approved (brainstorming complete)
- **Owner:** galamag
- **Source research:** [`docs/research/2026-06-07-original-research.md`](../../research/2026-06-07-original-research.md)

> This is the master design document produced during brainstorming. It captures the
> project vision, principles, architecture, validation roadmap, tooling, and constraints.
> Per-phase implementation plans are written separately (see roadmap → `writing-plans`).

---

## 1. Vision & Goal

Build a **prediction-market algorithmic trading research & execution framework** for
Polymarket (primary) and Kalshi (price source / cross-market monitoring).

**Primary goal (3–6 months): hybrid — research, learning, and income, in that order.**
We do **not** risk real money until we have proven an edge with our own eyes. The
mandatory progression is:

```
backtest  →  paper (our own "drawn" sim + Kalshi demo)  →  small real capital ($50)  →  scale
```

The deliverable for the next 6 months is a **validated codebase**, not deposit-to-profit.
Real money is risked only on strategies the system itself has shown to be EV-positive
after fees.

### Why this approach
The source research's hardest conclusion: with $200, the cost of learning (failed trades,
API quirks, miscalculated fees) exceeds the capital. We neutralize that risk by measuring
edge ourselves *before* deploying capital — never trusting research or hype on faith.

---

## 2. Core Principles (Financial-Analyst-Engineer)

These are binding. They are restated as operating rules in `CLAUDE.md`.

1. **Honesty about EV over optimism.** Every strategy must pass an explicit, fee-adjusted
   EV/Sharpe verdict before advancing. A losing backtest goes to the trash, not to prod.
2. **Never trust research or hype without verification.** The source research is dated
   2026-06-07 and is full of *specific but second-hand* facts (contract addresses, SDK
   names, fee formulas, dates). Each architecture-critical claim is verified against a
   primary source (Phase 0) before code is built on it. Status tracked in
   `docs/research/claims-verification.md`.
3. **Fees are a first-class, fully-tested module.** Dynamic taker fees, maker rebates,
   gas, on/off-ramp costs. Every backtest/paper/live decision routes through the cost
   model. If the cost model is wrong, the backtest lies.
4. **The backtest → paper → live gate is non-negotiable.** No strategy advances a stage
   without meeting its gate criterion (see roadmap).
5. **Risk limits are encoded in the system, not held in the head.** Max ~25% of bankroll
   per position, 3–5 concurrent positions, drawdown stop, kill-switch.
6. **🔴 Every decision is recorded.** All non-trivial decisions are written as ADRs in
   `docs/decisions/`. This is mandatory — we do not lose ideas or rationale.
7. **Security: keys never leak.** No secrets in git. Read-only third-party tooling only.
   The bot signs/executes with its own audited code, never via an external MCP.
8. **One strategy interface, three execution backends.** The same strategy code runs
   unchanged across backtest, paper, and live. This is what makes the verdicts trustworthy.

---

## 3. Architecture (Approach A — thin own core, vertical slice first)

### 3.1 Stack
- **Python 3.11+**, `asyncio` (not threading)
- `httpx[http2]` (async HTTP), `websockets` (live feeds)
- `pydantic` (strict data/order schemas)
- `polars` for backtest analytics (fast, memory-efficient on 64 GB), `pandas` where ecosystem needs it
- `structlog` (JSON logs)
- `pytest` (tests), `ruff` (lint/format), `mypy` (types)
- Dependency/venv management via **`uv`**
- Secrets via `.env` (never committed; `.env.example` is the template)

### 3.2 Seven layers (thin core, extended by plugins)

| # | Layer (`src/pat/...`) | Responsibility | Why isolated |
|---|---|---|---|
| 1 | `data/` | Historical ingestion (OrderFilled via Polygon RPC + Gamma API), live WebSocket CLOB, Kalshi. Normalize to one schema. | One source of truth feeds both backtest and live. |
| 2 | `venues/` (`polymarket/`, `kalshi/`) | Common interface over each venue's API/CLOB. | Strategies don't know which venue is underneath. |
| 3 | `execution/` | `BacktestBroker` / `PaperBroker` / `LiveBroker` behind one interface. | Same strategy code runs everywhere. Paper is mandatory (Polymarket has no usable testnet). |
| 4 | `costs/` | **Fee & cost model.** Dynamic taker fees, maker rebates, gas, ramp. Fully tested. | The heart of honesty — every decision routes through it. |
| 5 | `strategies/` | Plugins implementing `on_market_data / on_fill / generate_orders`. Market maker first. | New strategy or hybrid = new module, not a rewrite. |
| 6 | `risk/` | Position sizing, drawdown stops, kill-switch. | Capital protection encoded, not improvised. |
| 7 | `analytics/` | PnL attribution, Sharpe, win-rate, automated "EV>0 after fees?" verdict. | This is the research output: numbers, not belief. |

`core/` holds shared `pydantic` types (`Order`, `Fill`, `Market`, `Position`, ...).

### 3.3 Repository structure
```
polyalgotrade/
├── CLAUDE.md                  # operating instructions for the AI engineer
├── pyproject.toml             # uv + dependencies
├── .env.example               # secret template (real .env is gitignored)
├── src/pat/
│   ├── core/                  # shared pydantic types
│   ├── data/                  # layer 1
│   ├── venues/                # layer 2 (polymarket/, kalshi/)
│   ├── execution/             # layer 3 (backtest/paper/live brokers)
│   ├── costs/                 # layer 4 — cost model
│   ├── strategies/            # layer 5 (market_maker.py first)
│   ├── risk/                  # layer 6
│   ├── analytics/             # layer 7
│   └── signals/               # SEAM for the (deferred) intelligence layer — see §4
├── tests/                     # pytest, mirrors src/
├── scripts/                   # one-off: data fetch, backtest runs
├── data/                      # raw/processed data (gitignored)
├── notebooks/                 # exploratory analysis
└── docs/                      # see §6
```

---

## 4. Intelligence & Observability

### 4.1 Resource reality (binding constraint)
- **Claude Max 5x is NOT an API key.** It powers Claude Code / Claude.ai (interactive,
  dev-time). It cannot legally or practically drive a 24/7 trading bot.
- **Dev-time intelligence = Claude + the Claude Code subagents** (run on Max; *not* in the
  trading path). They help write, verify, research.
- **Runtime intelligence = local models on the RTX 4070 Ti Super 16 GB** via Ollama
  (Qwen2.5-14B / Llama-3.1-8B Q4 ≈ 9–10 GB, + embeddings). This is the only viable runtime
  LLM option.

### 4.2 Deterministic vs LLM decision matrix
**~90% of the system is deterministic scripts** (LLMs are too slow/non-deterministic for
the hot path).

| Component | Solution | Reason |
|---|---|---|
| Market making, quoting, fills | **Script** | Determinism & latency critical |
| Backtest, fee-model, risk-manager | **Script** | Pure math |
| Cross-market / combinatorial arb (price compare) | **Script** | Math, latency |
| Copy-trading (watch on-chain → replicate) | **Script** | Deterministic replication |
| Latency-arb | **Script** | An LLM would kill the strategy |
| **News → propensity** (news bot) | Runtime local LLM | Language classification |
| **Resolution-rule comparison** (cross-market) | Batch LLM | Language task |
| **UMA dispute risk score** | Batch LLM | Reads dispute context |
| **Research claims verification** | Dev-time subagents | Reads primary sources |

### 4.3 RAG vs CAG (deferred — seam only)
- **RAG** for the large/changing corpus: history of similar events, fuzzy news→market
  matching. Stack: local embeddings (`nomic-embed-text`/`bge`) + `LanceDB`/`Qdrant`.
- **CAG** for the hot path: the set of *active* markets is bounded (hundreds) and slow to
  change → preload markets + resolution rules into a long-context local model's context,
  avoiding retrieval latency. For the news bot, CAG is smarter than RAG (speed).

**Decision:** Design the `src/pat/signals/` seam now; implement the LLM/RAG/CAG layer only
when we reach the news phase (roadmap Phase 4). Documented in
`docs/architecture/intelligence-layer.md`. We will revisit this topic in depth later.

### 4.4 Logging & observability standard (v1)
Cross-cutting first-class concern, applied **everywhere — even one-off scripts**:
- `structlog` → JSON, a correlation-id per operation, a `mode` field (backtest/paper/live).
- **Append-only "trade journal"** (start with simple file/JSONL; upgrade to SQLite/parquet +
  dashboard later — to be discussed): every *decision* and order logged with full context —
  price, computed fee, **reason**, strategy. Without this we cannot reconstruct *why* the
  bot acted, and it is also the dataset for PnL post-mortems.
- LLM components (when added) log prompt/model/latency/tokens/response/parsed-signal to
  audit the LLM's contribution to PnL.

**Decision:** Start simple (structlog JSON + trade journal). Upgrade to dashboard/SQLite is a
later discussion. Documented in `docs/architecture/logging-observability.md`.

### 4.5 Where it runs
- Deterministic strategies (MM, arb, copy) → 24/7 on a cheap GPU-less VPS (Hetzner ~€5).
- LLM-dependent news strategy → on the desktop (GPU) or deferred until a GPU VPS is
  justified. The €5 VPS cannot run local LLMs.

---

## 5. Validation Roadmap (order of checks)

| Phase | What | Gate to advance |
|---|---|---|
| **0** | Foundation + **verify research claims** (contract addresses, SDK names, fee formulas, KZ access) | Critical facts confirmed by primary source |
| **1** | Data + **fee model** + backtest core + analytics/verdict | Pipeline runs ≥1000 sim trades; fees computed correctly |
| **2** | **Market making** (first wave): backtest on geopolitics (0% fee) + politics (rebates) | Verdict: EV>0 after fees? Sharpe>1? |
| **3** | **Paper** (our "drawn" sim + Kalshi demo): MM live with no money | paper-PnL ≈ backtest (deviation <10%) |
| **4** | Remaining strategies, one by one, through the same pipeline: cross-market/combinatorial → copy-trading → **latency-arb (verify, don't bury)** → news (LLM layer activates) | Each gets its own verdict doc |
| **5** | **Small real capital ($50)**: only strategies with confirmed EV>0 | Execution validation, not income |
| **6** | Scale / hybrid (only if 3 months stably positive) | — |

Each strategy gets a doc in `docs/strategies/` following `_template.md`:
hypothesis → edge thesis → data needed → backtest plan → results → verdict → proceed/kill.

---

## 6. Documentation Structure
```
docs/
├── README.md                      # navigation
├── roadmap.md                     # the phase table above, expanded
├── research/
│   ├── 2026-06-07-original-research.md   # copy of source research (source of truth)
│   └── claims-verification.md            # each claim → status + primary source
├── architecture/
│   ├── overview.md  ·  data-schema.md  ·  fee-cost-model.md
│   ├── execution-brokers.md  ·  intelligence-layer.md  ·  logging-observability.md
├── strategies/
│   ├── _template.md  ·  market-making.md
├── decisions/                     # 🔴 ADRs — every decision (mandatory)
│   ├── _template.md  ·  0001..000N
├── operations/
│   ├── vps-setup.md  ·  security.md  ·  runbook.md  ·  tooling.md
└── superpowers/specs/             # this spec + future specs
```

---

## 7. Subagents (dev-time, Claude Code, in `.claude/agents/`)

Run on Max; **not** in the trading path. Each pinned to a model + `effort: xhigh`.

| Agent | Role | model |
|---|---|---|
| `quant-researcher` | Strategy hypotheses, statistical rigor (no look-ahead bias, sample size, Sharpe), backtest interpretation, verdicts | `claude-opus-4-8` |
| `fee-cost-auditor` | Adversarial honesty guardian: audit fee model vs real schedules, hunt hidden costs (gas, slippage, ramp) | `claude-opus-4-8` |
| `claims-verifier` | Verify research claims against primary sources (docs, GitHub, on-chain) | `claude-sonnet-4-6` |
| `market-data-engineer` | Data pipelines, RPC/WebSocket/Gamma, schema normalization, data quality | `claude-sonnet-4-6` |
| `execution-engineer` | Framework: brokers, backtest engine, order routing | `claude-sonnet-4-6` |
| `risk-manager` | Sizing, drawdown stops, kill-switch, audit strategies for risk-limit compliance | `claude-opus-4-8` |
| `security-reviewer` | Secrets, keys, signing (ERC-1271 / signature types), "never leak a key" | `claude-sonnet-4-6` |

All use `effort: xhigh`.

---

## 8. Tooling (MCP / plugins / skills)

**Framing:** MCP servers connect to *Claude Code* (dev-time research convenience), **never**
to the production bot. The bot executes via its own audited code.

**Documented candidates (read-only data only; connect later, after code review):**
- `JamesANZ/prediction-market-mcp` — read-only Polymarket+PredictIt+Kalshi data
- `guangxiangdebizi/PolyMarket-MCP` — Polymarket markets/positions/history
- `PMXT` (pmxt.dev) — unified Polymarket+Kalshi API + MCP
- `Nayshins/mcp-server-ccxt` — spot prices across 100+ exchanges (latency-arb research)

**Security rule (in CLAUDE.md):** connect only read-only data servers, only after reviewing
their code; **never** an MCP holding trade/private keys (e.g. IQ AI execute-capable servers).

**Future candidates to revisit:** TradingView MCP, news MCPs, research MCPs.

**Skills:** built-in `deep-research` is the workhorse for Phase-0 claims verification.
Existing plugins (`superpowers`, `anthropic-skills`, `commit-commands`) are sufficient.

**Decision:** document candidates in `docs/operations/tooling.md`; connect nothing now
(clean start). Revisit MCP selection later.

---

## 9. Constraints & Reality Check

- **Capital:** $200 total. Treated as infrastructure + tiny live validation, *not* trading
  capital, until an edge is proven (per research).
- **Jurisdiction (KZ):** Kazakhstan is not on Polymarket's or Kalshi's block lists as of the
  research date — **to be re-verified in Phase 0** (the landscape changes weekly; Spain/India/
  Indonesia were blocked in May 2026). Polymarket KYC is optional for retail (≤7-figure).
- **Withdrawal path:** no easy fiat off-ramp to KZT; realistic route is USDC → Binance → P2P
  (≈1–2% conversion loss).
- **Tax:** crypto-trading income is taxable in KZ (10% IIT, 2024 rules) — keep fill records.
- **No Polymarket testnet:** Amoy has no liquidity → our own PaperBroker is mandatory, not
  optional. Kalshi has a full sandbox (`demo-api.kalshi.com`).

## 10. Key Risks (from research, to keep in view)
- Arms race is mature: 14/20 top wallets are bots; spreads compressed ~4.5%→1.2%; only 0.51%
  of wallets ever profited >$1,000. Wintermute/Galaxy adding institutional depth.
- Dynamic taker fees killed crypto latency-arb for small capital (need edge >1.8%).
- UMA dispute risk: even objectively-resolving markets can resolve wrong via token-weighted
  votes (MicroStrategy case). Mitigation: sell winners at $0.95+, don't hold to $1.00 on
  dispute-prone markets.
- Cross-platform resolution divergence: different rulebooks can lose both legs. Read both
  rulebooks before any cross-market position.

## 11. Open Questions (resolved in Phase 0)
- Do `py-clob-client-v2`, the CTF Exchange V2 addresses, and the fee formulas in the research
  actually match Polymarket's live docs/contracts today?
- Is KZ still unblocked on both venues today?
- What is the real measured latency from a chosen VPS region to the Polymarket CLOB?

## 12. Out of Scope (YAGNI for now)
- Latency-arb on crypto with <$2K bankroll (cost structure forbids it).
- A runtime multi-agent LLM system beyond a single news classifier.
- Dashboard / SQLite analytics upgrade (deferred to a later discussion).
- TypeScript/Rust implementations (Python only for now).
- Any real-money execution before Phase 5.
