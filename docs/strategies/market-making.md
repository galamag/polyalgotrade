# Strategy: Market Making (first wave)

- **Status:** **MM SHELVED (2026-06-09).** v1 (ADR 0018): naive symmetric MM gate-failed on real
  0%-fee geopolitics (headline loss mostly a boundary-clamp artifact, fixed). v2 inventory-skew spike
  (ADR 0019): skew reduces toxic inventory but does **not** create +EV → **PIVOT** to wallet-analysis
  / directional. MM revisit only with an order book in paper (ADR 0014). Skew code stays (default 0 =
  v1). Full design: spec `docs/superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md` §2.
- **Roadmap phase:** 2
- **Owner subagent:** quant-researcher (+ fee-cost-auditor, risk-manager)

## 1. Hypothesis
On low-liquidity prediction markets (long-tail politics, geopolitics, niche), HFT market
makers don't fully cover the book, leaving spreads of ~3–8¢. By quoting both sides we earn
the spread and, where applicable, maker rebates — while paying little/no taker fee.

## 2. Edge thesis
- **Source of edge:** spread capture + (sometimes) maker rebate. ⚠️ **Corrected in Phase 0:**
  on **geopolitics the taker fee is 0% (C6 verified) — but the maker-rebate pool is therefore
  also 0**, so a geopolitics MM earns **pure spread, no rebate income**. Rebates (25% non-crypto
  / 20% crypto, C7) only exist where takers actually pay fees — i.e. **politics and other
  categories**, not geopolitics. So the two sub-niches have different economics: geopolitics =
  zero-fee spread capture; politics = spread + daily-batch rebate ($1/day gate).
- **Why it survives competition:** these markets are below the threshold where co-located HFT
  bothers to compete; the research names this the best edge/complexity ratio for small capital.
- **Expected gross edge:** the quoted half-spread per filled round-trip (TBD from data).
- **Expected NET edge after fees:** must be measured — geopolitics (0% taker) is the cleanest
  test; this is the Phase-2 gate.

## 3. Costs
- Geopolitics: 0% taker (verify C6). Politics: maker rebate (verify C7). Gas negligible (I7).
- Breakeven: spread captured must exceed adverse-selection losses + any fee. Route all of this
  through `src/pat/costs/`.

## 4. Data needed
- Categories: geopolitics, long-tail politics (low-liquidity). Crypto excluded initially
  (dynamic taker fee, HFT-dense).
- Window: the post-V2 period (since 2026-04-28) via `OrderFilled` (RPC) + Gamma metadata.
- Order-book depth/spread series to estimate fill probability.

## 5. Backtest plan (v1 — approved 2026-06-07)
- **Quoting (v1, simple fixed-spread):** fair value `fv` = EWMA of recent trades; symmetric
  `bid = fv − half_spread`, `ask = fv + half_spread`, resting MAKER (GTC); fixed size `q`; inventory
  cap ±I_max (at the cap, quote only the inventory-reducing side). Inventory-skew (Avellaneda–
  Stoikov) is v2 — documented, not built (YAGNI).
- **Conservative fill model:** the `BacktestBroker` through-trade rule (strict inequality, MAKER,
  fee=0 on geopolitics) — back-of-queue; adverse selection emerges naturally (a bid fills only on a
  trade strictly below it). **Caveat:** with no historical book this is a *lower bound on fills*;
  the verdict is directional and the real proof is paper (Phase 3, ADR 0014).
- **Inventory mark-to-market (ADR 0012):** value residual inventory at last trade price minus a
  half-spread liquidation haircut. (Resolution-value rejected: an MM flattens before resolution.)
- **Parameter sweep:** `half_spread ∈ {1,2,3,5}¢` × size × I_max; report the honest frontier (many
  configs likely −EV).
- Sample ≥1000 simulated fills (across markets). First fix the parser to `assetId == "0"` and run a
  real geopolitics fetch (ADR 0012).
- Metrics: net PnL, Sharpe, win-rate, max drawdown, **fee/rebate drag**, inventory stats.

## 6. Risk
- Sizing: ≤$5/position in paper/early-live; ≤25% bankroll total; 3–5 concurrent.
- Inventory limits (don't accumulate a one-sided book into a resolving event).
- **Don't hold to resolution** on dispute-prone markets (UMA risk) — flatten / sell winners
  ~$0.95+.
- Kill-switch on drawdown.

## 7. Results
<!-- RESULTS:START -->
| half_spread | n_trades | net_pnl | gross_pnl | fee_drag | inv_value | win_rate | max_dd | sharpe | advance |
|---|---|---|---|---|---|---|---|---|---|
| 0.01 | 339 | -32.4014856737513205263026184 | -187.90633520 | 0 | 155.5048495262486794736973816 | 0.451 | 231.59127546 | -0.112 | False |
| 0.02 | 112 | -25.51291927634503165067674721 | 24.48015867 | 0 | -49.99307794634503165067674721 | 0.527 | 56.02101019 | 0.047 | False |
| 0.03 | 55 | -15.12581122495062236591060213 | 27.31786607 | 0 | -42.44367729495062236591060213 | 0.545 | 29.46910000 | 0.111 | False |
| 0.05 | 28 | -11.46877495102483515310510576 | -12.72875563 | 0 | 1.25998067897516484689489424 | 0.500 | 41.06700000 | -0.102 | False |

**Provenance:** json_path=data/raw/geopolitics_88082000_88090000.json, tokens=680, max_n_trades=339

_Caveats (§8): sharpe is per-fill (relative ranking, not annualized); win_rate ~50% by construction for a two-sided MM (lean on net_pnl incl. inventory MtM); sharpe & max_dd are realized-only; fills are a conservative lower bound (through-trade proxy, no order book — real proof is paper, Phase 3)._

<!-- RESULTS:END -->

## 8. Verdict
- [✗] EV > 0 after fees? **No** (net negative on every config).  [✗] Sharpe > 1.0? **No** (per-fill ≤ 0.63).  [✗] Survives pessimistic fills? **n/a — fails the gate.**
- **Verdict-writing caveats (from the Phase-2 final review — read before filling this in):**
  1. `Sharpe` here is a **per-fill** statistic (mean/stdev of per-fill net contributions) for
     *relative ranking* across the sweep — **not annualized**; do not present it as a conventional
     Sharpe.
  2. `win_rate` is a fill-level stat (buy fills are negative at fill time), so a balanced two-sided
     MM sits near 50% by construction — **not edge evidence**; lean on net PnL (incl. inventory MtM).
  3. Sharpe/drawdown are **realized-only** and ignore the terminal inventory mark — a config ending
     with heavy residual inventory can show +net EV but a realized-only Sharpe; weigh both.
  4. Fills are a **lower bound** (through-trade proxy, no order book) — real proof is paper (Phase 3).
- **Verdict (2026-06-09 · ADR 0018): DO NOT ADVANCE v1.** Real data: 21,748 0%-fee geopolitics
  fills, blocks 88082000–88090000 (~4.4 h), 680 tokens, both V2 exchanges.
  - **Gate-valid run** (n=1335 @ hs=0.01): net −$129, Sharpe 0.33 — but **adversarially shown to be a
    boundary-clamp artifact** (68.5% of fills at the 0.01/0.99 clamp; 80% on near-resolved binaries).
    The "gross +$2041 vs adverse-selection −$2170" framing was an **accounting illusion** — true
    adverse selection ≈ −$61; −$2096 was held-inventory cost-basis, not loss.
  - **Artifact-corrected run** (§7 above: boundary guard 0.10 + market-spread liquidation haircut via
    `costs/`; n=339 @ hs=0.01): net −$32, Sharpe −0.11 — **gate-INVALID (n<1000)**. Removing the clamp
    cut 75% of fills (near-resolved churn).
  - **Neither version advances.** Thesis (MM on 0%-fee geopolitics) **unresolved** — corrected margin
    is thin/noisy and tradeable mid-price geo is too sparse for a gate-valid MM verdict in one window.
- **Cost sign-off (fee-cost-auditor):** SIGN is honest (survives haircut=0); MAGNITUDE is a soft
  lower bound. **I9/C6 downgraded → PARTIAL** — `feesEnabled=false` ≠ 0% on-chain (4.1% of fills
  carried a fee).
- **v2 update (2026-06-09 · ADR 0019): inventory-skew spike = PIVOT.** Skew (γ mid-shift + δ asym
  spread) reduces residual toxic inventory (resid 1223→587, gross −188→−67 at hs=0.01) but does NOT
  move net to ≥0 on the existing data (hs=0.01 ≈ −$43, hs=0.03 ≈ −$15 across all γ/δ). The v1 −$32
  leaned on a lucky favourable residual mark that skew flattens away. 0%-fee geo is informed-flow-
  dominated → passive MM, even skewed, is marginal/negative. **MM shelved** (revisit only with an
  order book in paper).
- **Next (pivot):** top-50 wallet behavioral analysis (what the winners actually do) → then
  directional/news or copy-trading per ADR-0013 catalog.
