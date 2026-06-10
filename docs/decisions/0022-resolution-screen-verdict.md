# ADR 0022 — Resolution-grounded concentration screen: PASS (kill criterion cleared)

- **Date:** 2026-06-10
- **Status:** Accepted
- **Deciders:** AI engineer + `quant-researcher` adversarial sign-off (GO-WITH-CHANGES, caveats
  incorporated below); pre-registered criteria fixed in ADR 0021 + spec **before** the run

## Context
ADR 0021 Step 1: join the saved 75-wallet trades dataset (`data/raw/wallet_trades/`, 50 winners +
25 control) to Gamma resolutions and compute TRUE realized P&L including redemption payouts —
a **concentration screen** with a pre-registered kill criterion deciding whether the expensive
half of branch (B) (non-survivorship sample + persistence test) is worth building. Methodology
frozen in `specs/2026-06-10-approach2-resolution-pnl-design.md` §4; implementation built
subagent-driven TDD (233 tests green; per-task spec+quality reviews; final whole-build review
READY).

**Operational discovery (recorded as claim I14):** Gamma `/markets?condition_ids=` returns only
NON-closed markets by default — the first fetch saw 246/3625 ids (all open). Fix: two-pass fetch
(`closed=true`, then leftovers open). Final coverage: **3358 resolved / 246 unresolved /
8 ambiguous / 13 unknown** of 3625 conditionIds. Whole step keyless, $0, 0 CU.

## Decision
**The kill criterion is CLEARED: n_diversified = 14 of 50 winners ≥ 5 → branch (B)'s expensive
half is justified.** Per pre-registered ADR 0021 Step 3: build the **non-survivorship sample**
(entry-ranked, losers visible) + **persistence test**; C1 (copy-trading) stays open pending that
+ Approach 3 (lag/fee replay). The A2 feasibility scanner (ADR 0021 Step 2) still starts early
regardless — it accrues calendar data.

`quant-researcher` verdict: **GO-WITH-CHANGES** — PASS is real, reproducible (recomputed from raw
trades: 0 mismatches; full re-run → same 14), robust (P&L floor ≥$1k → 13; ≥$100k → 10;
**≥$1M → 7**, all ≥ 5; dropping unresolved-heavy wallets → 12), and free of goalpost drift.

## Evidence
Report: `docs/research/2026-06-10-resolution-screen.md`; per-wallet metrics:
`logs/resolution_features.jsonl` (regenerable; data/ and logs/ are gitignored by design).

- Winners median resolution P&L **$137,498** vs control median **$0.05** — redemption payouts,
  invisible to the lean trade-only proxy (ADR 0020: 33/50 computed negative), dominate the
  winners' true P&L. The lean read's blindness is now *measured*, not assumed.
- Standouts: `0xd38b71f3…` +$2.52M over **174 positive events**, top1 2.5%; `0x006cc834…`
  +$4.52M over 111 events (top1 3%); `0xc2e78…` +$10.28M over 34 events (top1 14%).
- Median in-window resolved events per winner: 11.5 (recent-2000 cap is thin but sufficient);
  rows skipped 2 of ~150K.

## 🔴 Binding caveats (required by quant sign-off — over-claims forbidden)
1. **The diversified flag is a STRUCTURE detector, not a skill/edge detector.** It fires on
   **28% of random control wallets (7/25)** — at trivial P&L ($0.05–$9.91). The 14 winners
   differ from diversified controls by P&L *magnitude*, which is the survivorship-selected
   variable. PASS = "≥5 survivors made their money spread across many markets, not in 1–3 whale
   bets" — nothing more.
2. **18/50 winners have NEGATIVE recent-window resolution P&L** (30 positive / 2 zero / 18
   negative) despite being all-time leaders. Diversified ≠ in-window profitable; the window is a
   slice, not a lifetime. **Persistence is exactly the open question Step 3 must answer.** (Note:
   among the 22 winners with spread-out structure, the only pass/fail separator was the sign of
   the in-window total — the gate discriminated on precisely the pre-registered margin.)
3. **Forbidden inference:** "≥5 diversified ⇒ a copyable systematic edge exists." The
   copyability prior (the winners' edge lives at *entry*; a copier enters later, as taker —
   ADR 0021) is untouched by this screen and remains the live risk Approach 3 must size.

## Consequences
- **Positive:** the decision the spike was bought for is made — the expensive half of (B) is
  funded by evidence, not hope. The dataset, resolutions join, and screen are reusable for the
  non-survivorship build. Cost of the whole step: $0 (keyless).
- **Negative / honest:** still survivorship-framed; nothing here is an edge claim. The
  non-survivorship build is a real acquisition effort (size unknown) — time-box it at design.
- **Process:** the pre-registered-gate discipline worked — the goalposts were set in ADR 0021
  and survived an adversarial audit unchanged.

## Follow-ups
1. **Step 3 design (next):** non-survivorship sample — rank wallets **at entry** (active in a
   past market window), fetch their trades keyless, resolution-ground their P&L, test
   persistence (split-window). Brainstorm → spec → plan, per workflow.
2. **Step 2 (parallel, per ADR 0021):** A2 combinatorial-arb feasibility scanner — prerequisite
   gas+slippage line items through `src/pat/costs/`.
3. **I13 spot-check still pending** (user runs `scripts/spot_check_trades.py` with
   `POLYGON_RPC_URL`; ~$0.0003 of CU) — upgrades trust in the /trades source; does not change
   this verdict.
4. Carried: category-matched control (S3); golden raw-log fixture; MM revisit gated on order
   book (ADR 0014).
