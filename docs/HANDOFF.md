# HANDOFF — read this FIRST when resuming

> **New session? Read this file first, then the "Read next" docs in order.** This is the durable,
> git-versioned session handoff (unlike `.remember/remember.md`, which the remember plugin empties
> on start and is not in git). **Update + commit this file at each session end.**

**Last updated:** 2026-06-09 · **Branch:** `main` (Phase-2b verdict committed; check `git log`/`git status` for sync).

## Where we are
- **Phase 0 ✅** claims · **Phase 1 ✅** data + cost model + backtest core · **Phase 2 ✅** MM backtest pipeline.
- **Phase 2b ✅ COMPLETE — v1 MM verdict delivered: DO NOT ADVANCE** (ADR 0018).
  - Real data: **21,748 0%-fee geopolitics fills**, Polygon blocks 88082000–88090000 (~4.4 h,
    2026-06-07), 680 tokens, both V2 exchanges. Data layer battle-tested on real chain data.
  - **Naive symmetric MM is gate-failing.** The first gate-valid run (n=1335) showed net −$129, but
    `quant-researcher` + `fee-cost-auditor` proved it was **mostly a boundary-clamp artifact** (80% of
    fills on near-resolved 0/1 binaries) + an **accounting illusion** (the "−$2170 adverse selection"
    was inventory cost-basis; true adverse selection ≈ −$61). Artifact-corrected run (boundary guard +
    market-spread haircut): net −$32 but **gate-invalid (n=339<1000)**. Neither advances; **thesis
    unresolved** → v2.
  - **Defects found & fixed this session** (all committed, 133 tests green, ruff+mypy clean):
    Gamma live-selection (`closed=false`+pagination — default page returned dead 2024 markets);
    `python scripts/...` path-run import; eth_getLogs **auto-split** on 10k cap + **429 retry/backoff**
    + **RPC-key redaction** in errors; console **log-flood**; `--fast-ts` (block-order, skips per-block
    RPC); MM **boundary guard** (`quote_band`); liquidation **haircut routed through `costs/`**.
- **Claims:** **I10** NegRisk == main `OrderFilled` ABI **VERIFIED**. **I9 downgraded → PARTIAL**:
  `feesEnabled=false` ≠ 0% on-chain (885/21,748 fills carried a fee; flag lied). I8 VERIFIED.
- **Security:** supply-chain hardening (ADR 0017) done earlier; registry MFA/tokens [F] deferred by user.

## Read next (grounding, in order)
1. `CLAUDE.md` — operating manual (auto-loads). 2. `docs/roadmap.md` — phase gates.
3. **`docs/decisions/0018-geopolitics-mm-verdict.md`** — THE verdict + artifacts + fixes + follow-ups.
4. `docs/strategies/market-making.md` — §7 recorded frontier + **§8 verdict** + v2 next-steps.
5. `docs/research/claims-verification.md` — **I9 (PARTIAL, on-chain fee ≠ flag)**, I10, I8.
6. Tooling touched: `scripts/fetch_geopolitics_data.py` (`--fast-ts`, closed=false+paginate),
   `scripts/fetch_polymarket_history.py` (auto-split + 429 retry + redaction),
   `scripts/run_mm_backtest.py` (`--quote-band`), `src/pat/strategies/market_maker.py` (`quote_band`),
   `src/pat/costs/polymarket.py` (`MARKET_HALF_SPREAD` / `liquidation_haircut`).

## Next action — **v2 market maker** (new brainstorm → spec → plan cycle)
The naive symmetric MM is trashed; the thesis (MM on 0%-fee geopolitics) is NOT settled. Per ADR 0018:
1. **Brainstorm v2** (superpowers:brainstorming): **inventory skew** `fv − γ·inventory` (priority 1,
   testable in-harness) + boundary guard (already in); **vol-adaptive spread** (priority 2, testable);
   **order-flow toxicity / VPIN** = **paper-only** (no aggressor side / order book in our stream).
2. **Data:** test v2 on a **larger, multi-window dataset** (≥2–3 independent days) — mid-price geo is
   thin (~339 MM fills / 4.4 h); the boundary guard cuts ~75% of raw fills. Reuse `--fast-ts`.
3. **Compare every v2 result against the v1 verdict** (ADR 0018 numbers) — same gate.

**Open backlog (recorded, not lost):**
- Golden raw-log fixture (plan Task 7 Step 4b) — still pending; needs one tiny raw fetch
  (`fetch_polymarket_history.py --from-block B --to-block B+50`) → `tests/data/fixtures/orderfilled_raw_v2.json` + decode assertion.
- Cost model: route **gas + slippage** line items through `costs/`; thinness/tail-aware haircut if v2 residuals land near 0/1.
- Taker-strategy / live: **verify on-chain fee, not the metadata flag** (I9 PARTIAL).
- Exploratory (not roadmap-committed): top-50 **wallet behavioral analysis** (C1 — maker/taker
  indexed → ~110k CU for 50 wallets' full history); **news-driven directional** "become-the-informed-flow" (§4 intelligence layer, Phase 4, paper-first).

## Non-obvious gotchas (durable)
- 🔴 **Gamma selection MUST use `closed=false` + pagination** — the default `tag_id` page returns ~100
  resolved **2024** markets (Gamma caps ~100/page); their tokens never trade in a recent window → geo=0.
- 🔴 **`feesEnabled=false` (and CLOB `/fee-rate=0`) ≠ 0% on-chain** (I9 PARTIAL). For a maker it's moot;
  a taker/live must read the real on-chain fee.
- 🔴 **Backtest inventory accounting:** "gross spread vs adverse-selection inventory" is misleading —
  the inventory mark is mostly cost-basis. Report **residual-vs-entry** for true adverse selection.
- **RPC:** scripts read `POLYGON_RPC_URL` from env (no python-dotenv) — `export` it or `--rpc-url`. Main
  exchange is dense (~106 OrderFilled/block) → getLogs auto-splits + 429-retries; `--fast-ts` skips the
  per-block timestamp RPC (block order == time order, fine for the backtest's sort). 🔴 **never read `.env`.**
- Backtest = conservative **lower bound** (through-trade, no book) → real proof is **paper (Phase 3)**.
  Sharpe is **per-fill** (relative, not annualized); `win_rate` ~50% by construction — lean on net PnL.

## Working agreements
- Reply in **Russian**; code/identifiers/committed docs in English.
- Workflow: **brainstorm → writing-plans → subagent-driven TDD** (review-gated). Verify before
  claiming pass (show command output). Adversarial sign-offs (quant + fee-cost) before trusting a verdict.
- Commits: **NO `Co-Authored-By` trailer**. Money = `Decimal` (float only for Sharpe). Run via
  `uv run` (`pytest -q` / `ruff check .` / `mypy src`). 🔴 **Never read `.env`/keys** (user hard rule).
- Record EVERY decision/idea as an ADR; never risk real money before a fee-adjusted edge is proven.
