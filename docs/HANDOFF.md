# HANDOFF — read this FIRST when resuming

> **New session? Read this file first, then the "Read next" docs in order.** This is the durable,
> git-versioned session handoff (unlike `.remember/remember.md`, which the remember plugin empties
> on start and is not in git). **Update + commit this file at each session end.**

**Last updated:** 2026-06-08 · **Branch:** `main` @ `7e59d4b` (LOCAL — ahead of origin, NOT pushed)

## Where we are
- **Phase 0 ✅** claims verification · **Phase 1 ✅** data + cost model + backtest core.
- **Phase 2 ✅** Market-making **backtest pipeline** — built test-first, merged to `main`.
- **Phase 2b — DATA LAYER BUILT ✅, VERDICT PENDING.** The geopolitics data layer (V2 decoder +
  block-timestamp enrichment + Gamma 0%-fee selection + fetcher topic0/NegRisk + orchestration +
  verdict recording) was built test-first (6 tasks), per-task + holistic adversarially reviewed, and
  **merged to `main`. 123 tests green, ruff + mypy clean.** RPC ready (`.env` `POLYGON_RPC_URL` =
  Alchemy free, 30M CU/mo). **The ONE remaining step is Task 7 — the real-data run that produces the
  actual MM edge verdict** (no verdict yet). See "Next action".
- **Security:** supply-chain hardening done this session (ADR 0017): uv 7-day cooldown
  (`exclude-newer`), npm `ignore-scripts`+`min-release-age`, anti-AI-poisoning rule, portable
  `docs/operations/PACKAGE_SECURITY_PROTOCOL.md`. (npm done; registry MFA/tokens [F] deferred by user.)

## Read next (grounding, in order)
1. `CLAUDE.md` — operating manual (auto-loads).
2. `docs/roadmap.md` — phase gates + "current position".
3. `docs/strategies/market-making.md` — MM v1 design + **§8 verdict-writing caveats**.
4. **`docs/superpowers/specs/2026-06-08-phase2b-data-layer-design.md`** + **`docs/superpowers/plans/2026-06-08-phase2b-data-layer.md`** — Phase-2b spec + plan (Tasks 1-7; **1-6 DONE**, 7 = next).
5. New code: `src/pat/data/polymarket_on_chain.py` (decode + enrich), `src/pat/venues/polymarket/gamma.py` (selection), `scripts/fetch_geopolitics_data.py` (orchestration), `scripts/run_mm_backtest.py --record`.
6. ADRs: **`0016`** (V2 decode), `0009` (fees), `0014` (backtest = lower bound), `0015` (mode), **`0017`** (supply-chain). Claims **I8/I9**.

## Next action — Phase 2b **Task 7** (operational real-data run → THE verdict)
The data layer is built & merged; Task 7 produces the real verdict (plan §"Task 7"). Needs real
network + Alchemy CU + decisions:
1. **NegRisk verify** (`claims-verifier`): confirm `0xe2222…0F59` emits the same `OrderFilled`
   ABI/topic0; record in `claims-verification.md`. If not → use main exchange only.
2. **Probe + grow window:** `uv run python scripts/fetch_geopolitics_data.py --from-block <B> --to-block <B2> --cross-check`
   → read the `geopolitics.*` log counts → grow the window until ≥1000–2000 fills (watch CU; lower
   `POLYGON_MAX_BLOCK_RANGE` if getLogs hits the 10k cap).
3. **Verdict:** `uv run python scripts/run_mm_backtest.py data/raw/geopolitics_<B>_<B2>.json --record docs/strategies/market-making.md`.
4. **Golden fixture:** save one real raw OrderFilled → `tests/data/fixtures/orderfilled_raw_v2.json` + a decode assertion (plan Task 7 Step 4b).
5. **Cost sign-off** (`fee-cost-auditor`): ratify static `GEOPOLITICS=0` + review `inventory_haircut`.
6. **ADR 0018** (the verdict) + fill `market-making.md` §8. Gate: **n≥1000 ∧ net EV>0 ∧ Sharpe>1.0**.
   If volume can't reach 1000 → honest "insufficient data", not "no edge".

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
