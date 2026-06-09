# v2 Market Maker — Inventory-Skew Spike (design)

**Date:** 2026-06-09 · **Status:** approved (brainstorm) → writing-plans next
**Owner subagent:** quant-researcher (+ fee-cost-auditor on any verdict)

## Goal
Cheaply test **one hypothesis**: does **inventory skew** move the v1 market maker from −EV toward
+EV on 0%-fee geopolitics? Add two composable skew knobs to `MarketMaker`, sweep them on the
**existing** dataset (0 CU), and decide **greenlight vs pivot** by a trend criterion.

## Context (why)
v1 verdict (ADR 0018): naive symmetric MM gate-fails. The headline −$129 was mostly a boundary-clamp
artifact; the **corrected** run (boundary guard + market haircut) was **net −$32 @ hs=0.01 but
gate-invalid (n=339<1000)**. The v1 bot is "blind" to trends → toxic inventory (true adverse
selection ≈ −$61). Inventory skew is the ADR-0018 priority-1 fix. This spike isolates whether skew
*works* before investing in a larger multi-window dataset.

## Non-goals (YAGNI)
- **Not** paper-bound and **not** gate-valid (n stays ~hundreds on one window). Directional only.
- **No** new data fetch (reuse `data/raw/geopolitics_88082000_88090000.json`, 21,748 fills).
- **No** vol-adaptive spread, **no** order-flow toxicity (deferred; toxicity is paper-only — no
  aggressor/book in our stream).

## Design

### 1. Strategy change — `src/pat/strategies/market_maker.py`
Two new keyword params, **default 0 = exactly v1** (backward compatible; existing tests untouched):
- `gamma` (γ) — **mid-shift** (reservation-price lean, simplified Avellaneda–Stoikov).
- `skew_delta` (δ) — **asymmetric spread** (widen the inventory-building side).

In `on_trade`, after the fv (EWMA) update, the cancels, and the existing `quote_band` boundary guard:
```
inv_frac = clamp(inventory / inventory_cap, -1, +1)        # bounded; cap logic keeps |inv|<=cap
fv_eff   = fv - gamma * inv_frac                            # long -> shift down; short -> up
bid_off  = half_spread + skew_delta * max(0, inv_frac)      # long  -> deeper bid (buy less)
ask_off  = half_spread + skew_delta * max(0, -inv_frac)     # short -> deeper ask (sell less)
bid_px   = clamp(fv_eff - bid_off)                          # clamp = existing [tick, 1-tick]
ask_px   = clamp(fv_eff + ask_off)
```
γ=δ=0 ⇒ `fv_eff=fv`, `bid_off=ask_off=half_spread` ⇒ identical prices to v1. The inventory-cap
quoting rule (at the cap, quote only the reducing side) and `quote_band` stand-aside are unchanged.

**Effect:** when long, mid-shift lowers BOTH quotes (ask fills sooner = sell down inventory; bid
retreats); asym-spread deepens only the bid (stop buying). They are complementary — tested separately
and combined (clean attribution **away from the cap**, see caveats).

**Postcondition (BLOCKER):** `bid_px < ask_px` must hold for EVERY config — enforce a ≥1-tick gap
after `_clamp` (if skew + clamp collapse/cross them near the band edges, widen symmetrically to keep
≥1 tick). Unit-test across the grid, including band-edge `fv`. Without this, skew can re-create the
v1 clamp artifact one band-width inward. The `quote_band` guard keys off **raw `fv`** (not `fv_eff`)
— do not switch it.
**Attribution caveats:** (a) at the inventory cap the one-sided rule already suppresses the
building-side quote, so `skew_delta` is **inert at the cap** — high-δ rows partly travel the γ/cap
path; (b) a mid-shift `γ·inv_frac` below ~½ tick rounds back to v1 prices via `_clamp` (sub-tick
dead-zone) — hence the widened γ grid + the `resid_shares` column to see when the shift actually bites.

### 2. Runner — `scripts/run_mm_backtest.py`
- Extract the per-config evaluation into a helper `_evaluate_config(streams, market, *, half_spread,
  gamma, skew_delta, size, inventory_cap, alpha, quote_band) -> dict` (builds a `BacktestBroker` +
  `MarketMaker` per token, `run_replay`, collects fills + last-price marks, `summarize(...,
  inventory_haircut=MARKET_HALF_SPREAD)`, `Verdict.from_metrics`; also computes `residual_abs_shares = Σ_token |Σ signed fill size|`). Returns
  `{"result", "verdict", "residual_abs_shares"}`; the runner derives `net_pnl_per_fill =
  net_pnl/n_trades` (0 if n=0).
- Refactor the existing **`run_sweep`** to call `_evaluate_config` per `half_spread` with
  `gamma=0, skew_delta=0` — **same signature, same return shape** (its tests stay green).
- Add **`run_skew_sweep(streams, market, configs, *, size, inventory_cap, alpha, quote_band=Decimal("0.10"))
  -> list[dict]`** where `configs` is a list of `{"half_spread", "gamma", "skew_delta"}`; each row is
  `{**config, "result", "verdict"}`.

### 3. Spike script — `scripts/run_skew_spike.py` (thin `__main__`)
- Arg: `json_path` (default `data/raw/geopolitics_88082000_88090000.json`).
- Load → `parse_orderfilled` → `streams_from_fills` (no token filter; data already geo).
- First print corrected-v1 **n-per-hs** (free: `run_sweep`, γ=δ=0) to confirm the max-n half-spread
  (expected 0.01: ADR 0018 had n=339 vs 112/55/28 at wider hs).
- Build the grid at **two half-spreads** — the max-n tight one (0.01) **and** one wider (0.03):
  δ is *added* to `half_spread`, so skew interacts with spread by construction; a single hs would
  measure skew only where it most dominates. γ/δ are widened so the mid-shift clears the 0.01 tick at
  moderate inventory (sub-tick shifts quantize back to v1 prices via `_clamp`):
  - γ-trend (δ=0): γ ∈ {0, 0.02, 0.04, 0.06, 0.10}
  - δ-trend (γ=0): δ ∈ {0.02, 0.04, 0.06, 0.10}
  - combo: (γ,δ) ∈ {(0.02,0.02), (0.04,0.04), (0.06,0.06)}
  (≈24 configs across the 2 half-spreads — still 0 CU, local compute.)
- `run_skew_sweep` → print **labelled tables per hs** (γ-trend / δ-trend / combo), columns
  `gamma | skew_delta | n_trades | net_pnl | gross_pnl | inv_value | net/fill | resid_shares |
  sharpe`. Configure structlog at INFO. One `TradeJournal` `verdict` event per config.

### 4. Reported metrics + decision criterion
**Per config report** (all cheap — on `Result` or derived in the runner): `half_spread, gamma,
skew_delta, n_trades, net_pnl, gross_pnl, inventory_value, net_pnl_per_fill (=net/n), |residual net
shares|, sharpe`. **`net_pnl` is the decision metric** — it already nets residual inventory MtM minus
the `MARKET_HALF_SPREAD` haircut (cost-model-clean, ADR 0018). The gross/inventory_value split +
residual-share count show *why* net moved (more spread captured vs simply ending flatter). **Do NOT
report a "residual-vs-entry adverse-selection" figure** — that is the debunked accounting illusion
(ADR 0018 #2); `net_pnl` is the honest top line.

**Greenlight = fund a ≥2–3-window gate-valid v2 test** (explicitly NOT "skew works") **iff** `net_pnl`
shows a clear upward trend as γ / δ / the combo diagonal increases AND reaches ≥ 0 **at both swept
half-spreads** — a *trend*, not a lucky point (minor non-monotonic noise OK if unambiguous). Pair the
trend with `n_trades` + `net_pnl_per_fill` so a "trend" that is really *skew throttling volume*
(fewer-but-cleaner fills) is visible and not mistaken for per-fill edge.

**Strongest claim a greenlight supports:** *"On one 4.4h Iran/Israel window, skew moves net-of-fee PnL
toward/across zero and reduces residual toxic inventory as predicted — enough to justify spending data
CU on a multi-window gate-valid test. It does NOT establish +EV, regime-generalisation, or anything
paper-ready."* **`fee-cost-auditor` signs off on the net_pnl gross/inventory_value/haircut
decomposition BEFORE any greenlight** (it caught the haircut mis-spec in v1). **Otherwise → honest
pivot** (per ADR-0018 alternatives: wallet-analysis / directional). Either way, record the outcome as
**ADR 0019** (v2-skew spike verdict).

## Data flow
`geopolitics_*.json` → `parse_orderfilled` → `streams_from_fills` → `run_skew_sweep(grid)` →
tables per hs → human reads the trend → ADR 0019 (greenlight/pivot). No network; deterministic.

## Testing
- `tests/strategies/test_market_maker.py`:
  - γ>0, long inventory ⇒ both quotes lower than v1; short ⇒ both higher.
  - δ>0, long ⇒ bid deeper, ask unchanged; short ⇒ ask deeper, bid unchanged.
  - γ=δ=0 ⇒ identical prices to the no-skew baseline.
  - `inv_frac` clamped (inventory > cap ⇒ shift bounded at γ).
  - **no-cross invariant:** `bid_px < ask_px` (≥1 tick) across the full γ×δ grid at several inventory
    levels, including band-edge `fv` where `_clamp` would otherwise collapse them.
- `tests/scripts/test_mm_backtest.py`:
  - `run_skew_sweep` with all-zero configs reproduces `run_sweep` exactly (equivalence).
  - `run_skew_sweep` respects configs (a γ>0 config differs from the γ=0 row).
- Spike script: smoke `--help` (thin `__main__`, no unit test of the table text).
- Gates: `uv run --extra dev pytest -q && ruff check . && mypy src`.

## Files
- Modify: `src/pat/strategies/market_maker.py` (γ, δ + skew math).
- Modify: `scripts/run_mm_backtest.py` (`_evaluate_config`, refactor `run_sweep`, add `run_skew_sweep`).
- Create: `scripts/run_skew_spike.py` (grid + tables per hs).
- Modify: `tests/strategies/test_market_maker.py`, `tests/scripts/test_mm_backtest.py`.
- After the run: create `docs/decisions/0019-v2-skew-spike-verdict.md`; update `market-making.md`.

## Risks / caveats
- **Small n (~hundreds, one 4.4h window, one Iran/Israel regime):** the spike is *directional*; a
  greenlight must be confirmed gate-valid on ≥2–3 windows before paper. The trend criterion guards
  against reading noise as edge.
- **The γ-points are correlated (one window ≈ one experiment, not n=5):** a smooth trend shows the
  response surface is smooth on THIS regime, not that the edge generalises. This is exactly why a
  greenlight only *funds* a multi-window test and never claims +EV (see §4 claim ceiling).
- **Skew interacts with spread by construction** (δ is added to `half_spread`): hence ≥2 half-spreads.
  If skew helps at one hs but hurts at the other, that is a crucial honest finding a single-hs grid
  would hide.
- **Skew changes the fill count** (mid-shift fills the reducing side more) — compare *trends*, not a
  single n. Report n per config so thin rows are visible.
- **Through-trade fill is still a pessimistic lower bound** (no benign at-touch fills; ADR 0014) —
  skew's real benefit (queue position, not standing in front of informed flow) is only fully
  measurable in paper.
- **Structural doubt stands:** 0%-fee = informed-flow signal; even skewed MM may be marginal. The
  spike is explicitly a go/pivot decision, not a commitment to MM.
