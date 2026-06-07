# HANDOFF — read this FIRST when resuming

> **New session? Read this file first, then the "Read next" docs in order.** This is the durable,
> git-versioned session handoff (unlike `.remember/remember.md`, which the remember plugin empties
> on start and is not in git). **Update + commit this file at each session end.**

**Last updated:** 2026-06-08 · **Branch:** `main` @ `c0e7809` (pushed; origin in sync)

## Where we are
- **Phase 0 ✅** claims verification · **Phase 1 ✅** data + cost model + backtest core.
- **Phase 2 ✅** Market-making **backtest pipeline** — built test-first (8 tasks), adversarially
  reviewed, merged to `main`, pushed. 104 tests green, ruff + mypy clean.
- **Phase 2b — IN PROGRESS, GATED.** Data gates VERIFIED (I8 OrderFilled ABI + I9 Gamma; ADR 0016).
  RPC ready (`.env` `POLYGON_RPC_URL` = Alchemy free, 30M CU/mo). **No MM edge verdict yet** — that
  is the Phase-2b goal. Tracker task #28.

## Read next (grounding, in order)
1. `CLAUDE.md` — operating manual (auto-loads).
2. `docs/roadmap.md` — phase gates + "current position".
3. `docs/strategies/market-making.md` — MM v1 design + **§8 verdict-writing caveats**.
4. `docs/superpowers/plans/2026-06-07-phase2-market-making.md` — the built pipeline (Tasks 1–8).
5. ADRs: `0012` (entry prereqs), `0013`/`0014` (catalog / book data), `0015` (mode seam),
   **`0016`** (V2 OrderFilled decode recipe).
6. `docs/research/claims-verification.md` — claims **I8** (OrderFilled ABI) + **I9** (Gamma geopolitics).

## Next action — Phase 2b (brainstorm → writing-plans → subagent-driven)
Build the data layer to produce a REAL MM verdict:
1. **Gamma client** — `GET /events?tag_id=100265` → `markets[].clobTokenIds` + per-market
   `feesEnabled`; select `feesEnabled=false` (the true 0%-fee geopolitics markets).
2. **On-chain decoder** — `decode_v2_orderfilled` (ADR 0016 recipe) + `eth_getBlockByNumber`
   block-timestamp batch fetch + fetch `OrderFilled` (topic0 `0xd543adfd…`) for the window.
3. **Wire** — decode → existing parser → per-token streams (filtered to 0%-fee tokens) →
   `scripts/run_mm_backtest.py::run_sweep` → record the verdict in `docs/strategies/market-making.md`
   §7-8. Gate: **n≥1000 ∧ net EV>0 ∧ Sharpe>1.0**.
4. **Cost-model decision** — keep static `Category→rate` vs read live per-market Gamma fee
   (route via the `fee-cost-auditor` subagent).

## Non-obvious gotchas (durable)
- 🔴 **geopolitics 0%-fee = `feesEnabled=false` per market, NOT the tag** — some geopolitics-tagged
  markets carry `politics_fees` (4%). Cross-check a token via `clob.polymarket.com/fee-rate?token_id=`.
- V2 `OrderFilled` = `side` + `tokenId` (NOT `makerAssetId`/`takerAssetId`, which are V1). The
  adapter bridges V2→parser, so the parser is unchanged. maker/taker addresses ARE present (copy-
  trading C1 also unblocked).
- `eth_getLogs` returns no timestamp → `eth_getBlockByNumber` per **unique** block (dedup; 20 CU).
  Watch Alchemy's getLogs ≤10k-result cap → narrow the block range if it errors. V2 start maybe
  ~2026-03-31 (unverified — detect empirically by the first OrderFilled block).
- Backtest = conservative **lower bound** (through-trade proxy, no order book); real proof is paper
  (Phase 3). Sharpe is **per-fill** (relative ranking, not annualized); `win_rate` ~50% by
  construction for a two-sided MM — lean on net PnL incl. inventory MtM.

## Working agreements
- Reply in **Russian**; code/identifiers/committed docs in English.
- Workflow: **brainstorm → writing-plans → subagent-driven TDD** (review-gated). Verify before
  claiming pass (show command output).
- Commits: **NO `Co-Authored-By` trailer**. Money = `Decimal` (float only for Sharpe). Run via
  `uv run` (`pytest -q` / `ruff check .` / `mypy src`).
- Record every non-trivial decision as an ADR (`docs/decisions/`). No MCP until cross-market/data-driven.
- Record EVERY decision/idea; never risk real money before a fee-adjusted edge is proven.
