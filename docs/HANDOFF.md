# HANDOFF — read this FIRST when resuming

> **New session? Read this file first, then the "Read next" docs in order.** This is the durable,
> git-versioned session handoff (unlike `.remember/remember.md`, which the remember plugin empties
> on start and is not in git). **Update + commit this file at each session end.**

**Last updated:** 2026-06-09 · **Branch:** `main` (wallet-analysis verdict ADR 0020 committed; check `git log`/`git status` for sync).

## Where we are
- **Phase 0 ✅** claims · **Phase 1 ✅** data + cost model + backtest core · **Phase 2 ✅** MM backtest pipeline.
- **Phase 2b ✅ COMPLETE — v1 MM verdict delivered: DO NOT ADVANCE** (ADR 0018).
  - Real data: **21,748 0%-fee geopolitics fills**, Polygon blocks 88082000–88090000 (~4.4 h,
    2026-06-07), 680 tokens, both V2 exchanges. Data layer battle-tested on real chain data.
  - **Naive symmetric MM is gate-failing.** The first gate-valid run (n=1335) showed net −$129, but
    `quant-researcher` + `fee-cost-auditor` proved it was **mostly a boundary-clamp artifact** (80% of
    fills on near-resolved 0/1 binaries) + an **accounting illusion** (the "−$2170 adverse selection"
    was inventory cost-basis; true adverse selection ≈ −$61). Artifact-corrected run (boundary guard +
    market-spread haircut): net −$32 but **gate-invalid (n=339<1000)**.
  - **v2 inventory-skew spike (ADR 0019) → PIVOT.** γ mid-shift + δ asym-spread reduce toxic inventory
    (resid 1223→587, gross −188→−67 at hs=0.01) but do NOT move net to ≥0 (hs=0.01 ≈ −$43, hs=0.03 ≈
    −$15 across all γ/δ); the v1 −$32 leaned on a lucky residual mark that skew flattens away. 0%-fee
    geo = informed flow → **MM SHELVED** (revisit only with an order book in paper). Skew code stays
    (default 0 = v1); 144 tests green.
  - **Defects found & fixed this session** (all committed, 133 tests green, ruff+mypy clean):
    Gamma live-selection (`closed=false`+pagination — default page returned dead 2024 markets);
    `python scripts/...` path-run import; eth_getLogs **auto-split** on 10k cap + **429 retry/backoff**
    + **RPC-key redaction** in errors; console **log-flood**; `--fast-ts` (block-order, skips per-block
    RPC); MM **boundary guard** (`quote_band`); liquidation **haircut routed through `costs/`**.
- **Claims:** **I10** NegRisk == main `OrderFilled` ABI **VERIFIED**. **I9 downgraded → PARTIAL**:
  `feesEnabled=false` ≠ 0% on-chain (885/21,748 fills carried a fee; flag lied). I8 VERIFIED.
- **Security:** supply-chain hardening (ADR 0017) done earlier; registry MFA/tokens [F] deferred by user.
- **Wallet-analysis spike (lean) ✅ done — INCONCLUSIVE** (ADR 0020), the pivot target off MM. Built a
  **keyless** acquisition (`data-api/trades`, claim I13 — after on-chain getLogs **exploded** on
  hyper-active wallets: 1M CU, 0 wallets done → pivot). Classified top-50-by-PnL + 25 control →
  40/50 "directional-holder" (maker-led, buy-and-hold). BUT this **FAILS §2/B1 + §9/S1 gates**, is
  **survivorship-tautological** (all-time-PnL frame selects directional bets that *won*) and
  **artifact-laden** (recent-2000 window; redemptions absent from /trades → 33/50 `pnl_proxy<0`, proxy
  falsified by its own frame). `quant-researcher`: GO-WITH-CHANGES → verdict is **INCONCLUSIVE →
  Approach 2** (NOT "build D3"). 194 tests green; keyless pipeline + 75-wallet dataset reusable.

## Read next (grounding, in order)
1. `CLAUDE.md` — operating manual (auto-loads). 2. `docs/roadmap.md` — phase gates.
3. **`docs/decisions/0020-wallet-analysis-verdict.md`** — LATEST verdict (lean wallet read INCONCLUSIVE
   → Approach 2). Then `0019` (MM skew pivot) + `0018` (MM v1). Report: `docs/research/2026-06-09-wallet-analysis.md`.
4. `docs/strategies/market-making.md` — §7 recorded frontier + **§8 verdict** (MM shelved).
5. `docs/research/claims-verification.md` — **I13 (/trades), I11/I12 (leaderboard+proxy)**, I9, I10, I8.
6. Tooling touched: `scripts/fetch_geopolitics_data.py` (`--fast-ts`, closed=false+paginate),
   `scripts/fetch_polymarket_history.py` (auto-split + 429 retry + redaction),
   `scripts/run_mm_backtest.py` (`--quote-band`), `src/pat/strategies/market_maker.py` (`quote_band`),
   `src/pat/costs/polymarket.py` (`MARKET_HALF_SPREAD` / `liquidation_haircut`).

## Next action — **Approach 2: resolution-grounded P&L** (ADR 0020); C1 & D3 both open
The lean (trade-only) wallet read can't judge the winners — their edge is the **resolution payout**,
invisible to `/trades` (redemptions aren't trades), and the all-time-PnL frame is survivorship-biased.
Before picking C1 (copy-trading) vs D3 (directional/news):
1. **Approach 2 — resolution-grounded P&L:** join each saved trade's `conditionId` → Gamma resolution
   (winning outcome) → compute TRUE realized P&L incl. redemption payouts; re-screen skill vs luck.
   Reuses the saved 75-wallet dataset (`data/raw/wallet_trades/`) + the analytics pipeline.
2. **Non-survivorship sample:** rank candidates **at entry** (wallets active in a past market set),
   not by all-time outcome, so directional *losers* are visible.
3. **Then** decide C1 vs D3; if C1 → **Approach 3** (replay with our lag + taker fee + slippage).
Reuse (keyless): `pat.venues.polymarket.trades` (`fetch_user_trades`, `tag_maker_taker`),
`pat.venues.polymarket.leaderboard`, `pat.analytics.wallet_features`/`wallet_archetype`/`wallet_control`,
`scripts/fetch_wallet_trades.py` + `scripts/run_wallet_analysis.py`. (On-chain `fetch_wallet_histories.py`
stays as the deferred narrow spot-check; never use it for full active-wallet history — getLogs explodes.)

**Open backlog (recorded, not lost):**
- Golden raw-log fixture (plan Task 7 Step 4b) — still pending; needs one tiny raw fetch
  (`fetch_polymarket_history.py --from-block B --to-block B+50`) → `tests/data/fixtures/orderfilled_raw_v2.json` + decode assertion.
- Cost model: route **gas + slippage** line items through `costs/`; thinness/tail-aware haircut if v2 residuals land near 0/1.
- Taker-strategy / live: **verify on-chain fee, not the metadata flag** (I9 PARTIAL).
- **MM revisit** only with an order-book recorder in paper (ADR 0014) — not the no-book backtest.
- **news-driven directional** "become-the-informed-flow" (§4 intelligence layer, Phase 4, paper-first)
  — a candidate after the wallet analysis points a direction.

## Non-obvious gotchas (durable)
- 🔴 **Gamma selection MUST use `closed=false` + pagination** — the default `tag_id` page returns ~100
  resolved **2024** markets (Gamma caps ~100/page); their tokens never trade in a recent window → geo=0.
- 🔴 **`feesEnabled=false` (and CLOB `/fee-rate=0`) ≠ 0% on-chain** (I9 PARTIAL). For a maker it's moot;
  a taker/live must read the real on-chain fee.
- 🔴 **Backtest inventory accounting:** do NOT call `inventory_value` "adverse selection" — it is mostly
  cost-basis. `net_pnl` (= gross + inv − fee) is the honest top line; report the gross/inv split +
  residual-share count to see *why* net moved. (A "residual-vs-entry" figure is the debunked illusion.)
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
