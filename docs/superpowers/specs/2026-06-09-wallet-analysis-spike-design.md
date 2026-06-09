# Top-Wallet Behavioral Analysis Spike — Design (2026-06-09)

> **Status:** design approved in brainstorm; next = implementation plan (writing-plans).
> **Origin:** the ADR-0019 pivot off shelved market-making. Let the *winners'* on-chain
> behavior pick our next real strategy before we commit to a build.
> **Variant:** Approach 1 (Lean), staged. Approaches 2 (resolution-grounded) and
> 3 (copyability-simulation) are recorded escalations, not built now.

---

## 1. Context & goal

MM is shelved (ADR 0018 v1 + ADR 0019 v2 skew = PIVOT): passive market-making on 0%-fee
geopolitics is informed-flow-dominated. The ADR-0019 recommended pivot is to characterize the
*winners* and let that steer the next strategy.

**Goal of this spike:** classify the top ~50 Polymarket wallets by P&L into behavioral
**archetypes**, contrast them against a control group of ordinary wallets, and emit a
**ranked recommendation of which strategy to build next** (copy-trading C1 vs directional/news
D3 vs revisit-MM-with-book vs structural arb/dispute). This is decision-support, not a build.

**Non-goal:** building copy-trading or any strategy. This spike outputs a *direction*, with a
pre-registered decision rule, and the data to feed whichever strategy wins.

**Cheap-first discipline (same as the MM spikes):** Approach 1 uses only on-chain `OrderFilled`
fills + Gamma metadata (+ a per-wallet `data-api/positions` call for marks). No per-market
resolution fetch, no simulation. If the lean read is ambiguous, escalate (§13).

---

## 2. Pre-registered decision rule (output → next strategy)

For each archetype compute: # wallets, median skill-score, copyability proxy, and the
**contrast vs control**. The recommendation is fixed *before* seeing results:

1. **≥1 archetype is (skill, not luck) AND high copyability** → recommend **C1 copy-trading**
   on that archetype; next step = Approach 3 (lag/cost simulation) to confirm before any build.
2. **Winners predominantly directional-informed** (taker-led, positive round-trip, holds through
   a move) **but NOT copyable** (move too fast for our lag) → recommend **directional/news (D3)**
   — "become the informed flow", not copy them.
3. **Winners predominantly market-makers** (maker-led, fast flip, spread capture) → reinforces
   that the edge is liquidity provision → **revisit MM only with an order book** (consistent with
   ADR 0014/0019), do not chase passively.
4. **Winners predominantly longshot-farmers / resolution-holders whose P&L is luck-dominated**
   (few big bets, fail the consistency screen) → **no cheaply-replicable edge here**; redirect to
   structural strategies (A2 combinatorial arb / D1 UMA-dispute reversion).

A "recommendation" requires the winning archetype's features to **differ materially from the
control group** (§11) — otherwise "winning" is indistinguishable from ordinary trading + luck.

---

## 3. Verified data sources (claims I11/I12, 2026-06-09)

Verified by `claims-verifier` against primary sources (live API, Polygonscan, official docs):

- **Leaderboard (I11, PARTIAL):**
  `GET https://data-api.polymarket.com/v1/leaderboard?timePeriod={DAY|WEEK|MONTH|ALL}&orderBy={PNL|VOL}&limit={1..50}&offset={0..1000}&category=OVERALL`
  → returns per trader: **`proxyWallet` (0x address)**, `userName`, `vol`, `pnl`. Max 50/page,
  1000 total via `offset`. ⚠️ The `pnl` field's exact definition (realized vs unrealized vs MTM)
  is **undocumented** → we use the leaderboard **only as the sampling frame**, never as verdict
  input. (`lb-api.polymarket.com` does NOT serve the leaderboard.)
- **Address mapping (I12, VERIFIED) — the key enabler:** the leaderboard `proxyWallet` is
  **exactly** the address that appears in `OrderFilled` `topics[2]` (maker) / `topics[3]` (taker).
  **No secondary join.** A topic-filtered `eth_getLogs` on that address returns the wallet's
  on-chain trade history directly. (Confirmed on-chain: Theo4's proxy in a live Polygonscan tx.)
  `taker` is sometimes the exchange operator or the zero address (public-order flow); both
  maker and taker are real proxies in user-vs-user matches.
- **Positions (cross-check):**
  `GET https://data-api.polymarket.com/positions?user={proxyWallet}` and `/closed-positions`
  → `avgPrice`, `initialValue`, `currentValue`, `curPrice`, `cashPnl` (unrealized),
  `realizedPnl`, `conditionId`, `asset`. Keys on the **proxy** address. Used for (a) marking
  residual positions and (b) a sanity cross-check of our on-chain P&L proxy — not as the
  behavioral source.
- **Exchanges (all four — V1 is still live):**
  V1 main `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`,
  V1 neg-risk `0xC5d563A36AE78145C45a50134d48A1215220f80a`,
  V2 main `0xE111180000d2663C0091e4f400237545B87B996B`,
  V2 neg-risk `0xe2222d279d744050d28e00520010520000310F59`.
  `eth_getLogs` `address` accepts an array → one pass covers all four.
- **OrderFilled ABIs:** V2 topic0 `0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee`
  (7 data words: `side, tokenId, makerAmt, takerAmt, fee, builder, metadata`), decoded by the
  existing `decode_v2_orderfilled`. **V1 OrderFilled has a different ABI** (8 params, `side`
  ABSENT, `makerAssetId`/`takerAssetId` present) and a **different topic0** (not yet recorded —
  confirm at Task 0 via one Polygonscan event-signature lookup *only if the V1 gate triggers*,
  §6). maker/taker are `topics[2]`/`topics[3]` on V1 too → wallet topic-filtering is identical.

---

## 4. Architecture / pipeline (isolated, testable units)

```
 leaderboard ──► candidate proxyWallets ─┐
                                          ├─► wallet_history ─► decode ─► fills
 control sample (from existing data) ─────┘        │
                                                   ▼
                                   wallet_features (pure) ─► wallet_archetype (pure)
                                                   │                  │
                                          skill screen + copyability  │
                                                   └──────► report + ADR
```

Units (each: one purpose, defined interface, independently testable):

| Unit | Input | Output | Lives in |
|---|---|---|---|
| `leaderboard_client` | timePeriod, orderBy, limit | list[`proxyWallet`, userName, pnl, vol] | `src/pat/venues/polymarket/` |
| `wallet_history` (fetch+merge) | address, block range, exchanges | decoded fills for that wallet | reuse `scripts/fetch_*` + new merge helper |
| `wallet_features` | fills + token→market/category map (+ marks) | feature dict | `src/pat/analytics/wallet_features.py` (new, pure) |
| `wallet_archetype` | feature dict | (label, confidence) | `src/pat/analytics/wallet_archetype.py` (new, pure) |
| `control_sampler` | existing raw fills JSON | 25 median-activity proxyWallets | helper in driver |
| `run_wallet_analysis` | config | report.md + JSONL | `scripts/run_wallet_analysis.py` (new driver) |

Network I/O stays in the existing seams (`_rpc_get_logs`, a new `leaderboard_client`,
an optional `positions` fetch); the pure analytics functions never touch the wire (tested offline).

---

## 5. Step A — candidate selection + control group

- **Candidates:** `timePeriod=ALL, orderBy=PNL, limit=50, offset=0, category=OVERALL` → top-50
  `proxyWallet`. ALL-time chosen as the primary frame (canonical "winners"; the skill screen §9
  + control §11 handle luck). `MONTH` is the recorded V2-native alternative (§13).
- **Control group (survivorship-bias guard):** 25 wallets sampled **deterministically** from our
  existing `data/raw/geopolitics_*.json` — sort distinct proxyWallets by fill count, take the 25
  closest to the **median** fill count (reproducible, no RNG; excludes both the hyper-active top
  decile and one-fill noise). These are "ordinary active traders." Every feature is computed for
  them too.

## 6. Step B — wallet history fetch (4 exchanges, maker∪taker, measure-first V1 gate)

Per wallet, two topic-filtered passes per exchange, merged:
- maker pass: `topics=[topic0, null, <wallet_topic>]`
- taker pass: `topics=[topic0, null, null, <wallet_topic>]`
where `<wallet_topic>` = the proxy address left-padded to 32 bytes
(`"0x" + "0"*24 + addr[2:]`). Dedup the union by `(transactionHash, logIndex)`.

Reuses `_rpc_get_logs` (auto-split on the 10k-log cap, 429 retry/backoff, key redaction).
Per-wallet topic filtering is **sparse** → on Alchemy a huge block range returns in one call
unless >10k logs (then it auto-splits) — so even all-time history is cheap (§16).

**Measure-first V1 gate (pre-registered, user's choice):**
1. First COUNT fills per wallet split by V2 vs V1 (cheap; getLogs returns the list, we count).
   Counting V1 OrderFilled needs the V1 topic0 → confirm it once at Task 0 (Polygonscan).
2. **If V1 > 20% of fills for the *median* top wallet → V1 is material → escalate: write a
   `decode_v1_orderfilled` (different ABI) + dispatch by topic0**, then compute features on V1+V2.
3. **If V1 ≤ 20% → proceed V2-only**, and document the small V1 gap in the report.

This refuses to ship a V2-only-biased verdict, without paying for a V1 decoder blindly.

**Operational (key isolation):** the fetch hits Alchemy with the user's key → 🔴 **the USER runs
the fetch commands**; the AI prepares exact commands and reads back the structlog counters.
**Never read `.env` or any key** (hard rule).

## 7. Step C — P&L proxy + features (deterministic, `Decimal`)

From each fill, derive the wallet's perspective: it is maker or taker; the maker's token side
comes from the asset legs (`makerAssetId==0` → maker BUYS the token; else maker SELLS); the taker
is the opposite. Per fill → `(conditionId, token, side∈{buy,sell}, price=usdc/size, size, block)`.

- **Cashflow:** buy → −price·size USDC (+size tokens); sell → +price·size (−size tokens).
- **P&L proxy** per wallet = Σ realized cashflow + (residual token position × mark). Mark =
  `curPrice` from `data-api/positions` for open positions; their `realizedPnl`/`cashPnl` are kept
  only as a **cross-check**, never as the verdict number.

**Features per wallet** (computed for candidates AND control):
`n_fills`, `n_markets` (distinct conditionId — the skill denominator), `maker_fill_ratio`,
`flip_rate` (fraction of token positions both opened and closed vs held), `median_hold_blocks`
(for flips), `entry_price_mean` (+ distribution), `category_mix` (Gamma category shares),
`turnover_usdc`, `pnl_proxy`, `realized_share`, `top1_market_pnl_share` (luck flag),
`roundtrip_return_median` (for flips: median exit−entry — the lean copyability upper bound).

## 8. Step D — archetype classifier (first-pass deterministic labeler)

A first-pass rule labeler. The report also prints raw feature **distributions** + control
contrast so the thresholds are sanity-checked, not blindly trusted.

| Archetype | First-pass rule |
|---|---|
| Market-maker | `maker_fill_ratio ≥ 0.6` ∧ `flip_rate ≥ 0.6` ∧ `median_hold_blocks` small (init ≤150 blk ≈5 min) ∧ `entry_price_mean ∈ [0.2,0.8]` |
| Directional-informed | `maker_fill_ratio ≤ 0.4` ∧ `roundtrip_return_median > 0` ∧ `median_hold_blocks` larger (init >150 blk) ∧ few markets/period |
| Longshot-farmer | `entry_price_mean ≤ 0.2` ∧ low `flip_rate` (holds) ∧ high `top1_market_pnl_share` |
| Resolution-holder | `entry_price_mean ≥ 0.85` ∧ low `flip_rate` ∧ low round-trip variance |
| Arbitrageur | very high `flip_rate` ∧ `median_hold_blocks ≈ 0` ∧ ~0 net exposure ∧ paired complementary tokens |
| Unclassified | none of the above (counts toward the "can't classify >50%" escalation, §13) |

Exact numeric cutoffs (the small-`median_hold_blocks` etc.) are finalized against the observed
distributions in the plan; the labeler reports each wallet's features alongside its label.

## 9. Step E — skill-vs-luck screen (the core of Approach 1)

A wallet is in the **skill cohort** (eligible to drive a recommendation) only if:
`n_markets ≥ 30` **AND** `top1_market_pnl_share < 0.40` **AND** positive P&L proxy across a
majority of its markets. Otherwise it is **luck-flagged** — kept in the archetype map for color,
excluded from the recommendation. (One jackpot longshot = luck; many small consistent wins = skill.)

## 10. Step F — copyability proxy (lean)

Lean copyability = **zero-lag round-trip return** for flippers: `roundtrip_return_median` and the
holding-time gap. Slow drift (exit hours later at a better price) → copyable with lag; same/next
block → edge gone (arb/MM, not copyable). This is an **upper bound** (zero lag); the lag/taker-cost
erosion is measured only in **Approach 3** (escalation). Hold-to-resolution wallets have no exit
leg → copyability "unknown in lean", flagged for Approach 2/3.

## 11. Step G — survivorship-bias control contrast

Every feature is tabulated candidates vs control. A recommendation (§2) requires the winning
archetype's discriminating features (e.g. `roundtrip_return_median`, `maker_fill_ratio`,
`entry_price_mean`) to differ **materially** from control (concrete bar: the candidate-archetype
median for the discriminating feature falls outside the control group's interquartile range) —
otherwise the "edge" is noise + luck. Report the side-by-side so the contrast is visible, not asserted.

## 12. Step H — outputs

- `docs/research/2026-06-09-wallet-analysis.md` — archetype map (counts + median features per
  archetype), candidate-vs-control table, skill-cohort list, copyability read, and the
  **recommendation** under the §2 rule. Plus provenance (leaderboard query, block ranges, V1/V2
  split, n wallets).
- **ADR 0020** — the recommendation (next strategy) + escalation status + claim refs I11/I12.
- Update `docs/HANDOFF.md` + `docs/roadmap.md`.
- Raw per-wallet features to `logs/wallet_features.jsonl` (reproducible).

## 13. Escalation triggers (pre-registered)

- **Thin spectrum / ambiguous classification:** `< 3` archetypes with `≥ 5` wallets, OR `> 50%`
  of top-50 land Unclassified → **escalate sample to Top-100 + 50 control** before recommending.
- **V1 material:** `V1 > 20%` of median-wallet fills → **build `decode_v1_orderfilled`** (Approach
  stays Lean otherwise).
- **Skill-vs-luck unresolved on lean P&L proxy** → **Approach 2** (fetch Gamma resolutions →
  true realized P&L + a null-model significance test on the shortlist).
- **An archetype looks copyable and we lean toward C1** → **Approach 3** (replay top wallets'
  trades through `BacktestBroker` with our lag + taker fee + slippage → surviving edge) *before*
  any copy-trading build.
- **Frame alternative:** if ALL-time proves too V1-heavy and we don't want the V1 decoder, switch
  the leaderboard frame to `timePeriod=MONTH` (more V2-native, more luck-noise — skill screen guards).

## 14. Code layout / reuse / isolation

- **Reuse:** `_build_getlogs_payload` / `_rpc_get_logs` (topics arg, auto-split, 429-retry),
  `decode_v2_orderfilled`, the Gamma client (token→market→category).
- **New:**
  - `src/pat/venues/polymarket/leaderboard.py` — `fetch_leaderboard(...)` (thin, network-seam isolated).
  - wallet→topic encoder + maker∪taker merge — small helper (in `scripts/` or `wallet_history`).
  - `src/pat/analytics/wallet_features.py` — pure feature extraction (TDD).
  - `src/pat/analytics/wallet_archetype.py` — pure classifier (TDD).
  - `scripts/run_wallet_analysis.py` — orchestration + report (driver, structlog).
  - (escalation only) `decode_v1_orderfilled` in `src/pat/data/polymarket_on_chain.py`.
- Money in `Decimal`; floats only for ratios/scores. structlog + correlation-id in the driver.

## 15. Testing strategy (TDD)

- `wallet_features`: synthetic fill sets → assert each feature (buy/sell direction from asset legs,
  flip vs hold, round-trip return, P&L proxy, top1 share). Offline, no network.
- `wallet_archetype`: hand-crafted feature dicts hitting each archetype + Unclassified.
- `leaderboard_client`: monkeypatch the HTTP seam with a recorded JSON sample → assert parsing of
  `proxyWallet`/`pnl`.
- wallet→topic encoder: assert 32-byte left-pad; maker∪taker dedup by (txHash, logIndex).
- (escalation) `decode_v1_orderfilled`: a recorded V1 raw log → asserted decode.
- All gates: `uv run pytest -q`, `ruff check .`, `mypy src`.

## 16. Cost & operations

- ~50 candidates × 4 exchanges × 2 passes (+25 control on V2 from existing data) ≈ a few hundred
  `eth_getLogs` calls; sparse topic filters → mostly single-call ranges → **negligible CU vs the
  Alchemy budget** (order of hundreds of k CU even all-time). Per-wallet `data-api/positions` =
  ~50 cheap REST calls.
- 🔴 **User runs the Alchemy-backed fetch** (key isolation); AI prepares exact commands + reads
  structlog counters. `data-api` (no key) calls may be run either side.

## 17. Out of scope (YAGNI)

- No copy-trading / directional build (that's the *next* spec, chosen by this spike's output).
- No resolution fetch, no null-model test, no lag simulation (Approaches 2/3 — escalation only).
- No LLM/intelligence layer (CLAUDE.md §4 deferred).
- No EOA↔proxy reverse mapping (not needed — leaderboard gives the proxy, which is the on-chain id).

## 18. Risks & caveats

- **Leaderboard `pnl` is opaque** → used only as the frame; our verdict uses on-chain-derived
  P&L proxy (+ positions cross-check). [I11 PARTIAL]
- **Survivorship bias** → control group + skill screen + "must beat control" gate. Winners may
  still be un-copyable (that's an output, not a failure). The control is V2-geopolitics
  median-activity traders — neutral but **not category-matched** to the all-category candidates;
  a category-matched resample (from a broad V2 fetch) is a recorded future refinement.
- **Lean P&L proxy** marks residuals at `curPrice` (not resolution) → directional/holder P&L is
  approximate; Approach 2 sharpens it if the read is ambiguous.
- **V1 ABI** differs → measure-first gate; V1 topic0 to be confirmed at Task 0 only if triggered.
- **`taker` = operator/zero-address** on some fills → exclude those from the wallet's taker count
  (they are not the wallet's own aggressive trades).
- One leaderboard snapshot = a point in time; record the query timestamp for reproducibility.
