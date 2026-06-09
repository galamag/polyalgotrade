# Approach 2 — Resolution-grounded P&L concentration screen (ADR 0021 Step 1)

**Date:** 2026-06-10 · **Status:** approved by user (design review in session)
**Parent decision:** `docs/decisions/0021-post-wallet-spike-direction.md` (sequenced hybrid)
**Predecessor:** `docs/decisions/0020-wallet-analysis-verdict.md` (lean read INCONCLUSIVE),
`docs/superpowers/specs/2026-06-09-wallet-analysis-spike-design.md` (lean spike spec)

## 1. Goal & deliverable

Compute **TRUE realized P&L including redemption payouts** for the saved 75-wallet dataset
(`data/raw/wallet_trades/`, 50 leaderboard winners + 25 control) by joining each trade's
`conditionId` to its Gamma resolution. Deliverable is a **concentration screen** — per wallet,
is resolution-grounded P&L spread across many independent winning *events* (systematic) or
concentrated in 1–3 bets (single-shot whale)? It is **NOT** a C1/D3 strategy pick.

**Pre-registered kill criterion (ADR 0021, interpretation fixed here BEFORE the run):**
if **< 5 of the 50 winners** show a *diversified profile* (§4), branch (B) closes entirely —
no non-survivorship build, C1 archived via a follow-up ADR. If **≥ 5**, the expensive half of
(B) (entry-ranked sample + persistence) is justified.

**Time-box:** 1–2 sessions. If too few resolved positions survive the frame filters for the
screen to discriminate, the verdict is "inconclusive by frame limit" — recorded, not extended.

Dataset facts (measured 2026-06-10): 75 wallet files; **3626 unique `conditionId`**,
**2119 unique `eventSlug`** across all saved trades. Saved trade rows carry
`conditionId`, `eventSlug`, `outcome`, `outcomeIndex`, `asset`, `side`, `price`, `size`,
`timestamp`, `transactionHash`, `is_maker`.

## 2. User decisions (fixed in design review)

1. **Independence = events, not conditionIds.** One Polymarket *event* contains multiple
   correlated markets (conditionIds); 10 markets inside one event are one bet, not ten.
   The kill criterion's "≥ 10 independent" counts **distinct `eventSlug`**. Both
   `n_conditions` and `n_events` are reported; the gate applies to events.
2. **Unresolved markets are EXCLUDED from the gate.** The gate uses only resolved markets
   (trades + redemption at the actual outcome). Unresolved positions appear as a separate
   disclosed exposure column — no `curPrice` marking inside the gate (lesson B3: no
   hindsight flatter).
3. **Approach: new module** (option 1 of 3). Isolate the pre-registered methodology in new,
   small, testable units; do not touch the lean screen (`run_wallet_analysis.py`,
   ADR 0020 artifact). Rejected: extending the lean pipeline (mixes methodologies, bloats
   files); trusting data-api `/positions` PnL fields (unverifiable black box, §1 honesty).

## 3. Architecture & data flow

```
data/raw/wallet_trades/*.json (75 wallets, exists)     Gamma /markets?condition_ids=...
        │                                                       │
        ├─ scripts/fetch_resolutions.py ───────────────────────┘
        │      → data/raw/resolutions.json   (conditionId → resolution record)
        │
        └─ scripts/run_resolution_screen.py
               → src/pat/analytics/resolution_pnl.py   (pure functions, no network)
               → docs/research/2026-06-10-resolution-screen.md  (report)
               → logs/resolution_features.jsonl + kill-criterion verdict
```

Everything is **keyless** (Gamma + saved files, $0, 0 CU) except the separate on-chain
spot-check (§7), which has a fixed micro CU budget.

### Components

- **`src/pat/venues/polymarket/gamma.py`** — add `fetch_markets_by_condition_ids(
  condition_ids, *, batch_size=20, get_page=None)`: the ONLY new wire-touching function,
  same injectable-seam pattern as `_gamma_get_events`. Queries `GET {GAMMA}/markets` with
  repeated `condition_ids` params, `batch_size` per request (empirically tuned at
  implementation; on 4xx fall back to smaller batches, ultimately per-id). 3626 ids ≈ 180
  requests at batch 20.
- **`scripts/fetch_resolutions.py`** — collect unique `conditionId` across the 75 wallet
  files → fetch via the gamma seam → write a single `data/raw/resolutions.json` keyed by
  conditionId. **Idempotent:** entries already recorded as *resolved* are never re-fetched
  (a resolution is a permanent fact); *unresolved/unknown* entries are re-fetched only with
  `--refresh`. structlog JSON + corr_id, as in all scripts.
- **`src/pat/analytics/resolution_pnl.py`** — the pre-registered methodology (§4) + the
  kill screen. Pure functions, `Decimal` money, no network, fully unit-tested.
- **`scripts/run_resolution_screen.py`** — driver: load 75 wallets' trades + resolutions →
  per-wallet metrics → winners-vs-control table → verdict line against the pre-registered
  gate → report + `logs/resolution_features.jsonl`.
- **Carried fixes (ride along, separate commits):**
  - **S5:** `n_tokens` counted by `conditionId` in `wallet_features.py` — add optional
    `condition_id: str | None = None` to `WalletFill`, populate in
    `wallet_fills_from_trades`, count unique `condition_id` when present else `token_id`.
  - **I13 trust step:** `scripts/spot_check_trades.py` (§7).

## 4. P&L methodology & kill screen (pre-registered — frozen before the run)

Per wallet, per **asset** (outcome token), from the saved wallet-perspective rows:

```
net_shares(asset) = Σ size[side=BUY] − Σ size[side=SELL]
cashflow(asset)   = Σ price·size[side=SELL] − Σ price·size[side=BUY]
```

Classification per `conditionId` (resolution record from `resolutions.json`):

- **RESOLVED** — strictly: parsed `outcomePrices` contains exactly one `"1"` and all other
  entries `"0"`; `winning_index` = index of the `"1"`.
  `redemption(asset) = max(net_shares, 0) × 1[outcomeIndex(asset) == winning_index]`
  `resolution_pnl(conditionId) = Σ_assets (cashflow(asset) + redemption(asset))`
- **FRAME-INCOMPLETE** — any asset of the condition has `net_shares < 0` (sold more than
  visibly bought → the cost basis lies outside the recent-2000 window). **Excluded from
  the gate**, counted in a disclosed `n_frame_incomplete` column. No fabricated basis.
- **UNRESOLVED / AMBIGUOUS / UNKNOWN** — not resolved yet; or resolved but not strictly
  binary (e.g. 50/50 refunds); or conditionId missing from Gamma. All **excluded from the
  gate**, each with its own disclosed counter (`n_unresolved`, `n_ambiguous`, `n_unknown`).

Event aggregation (user decision #1): `event_pnl(eventSlug) = Σ resolution_pnl(conditionId)`
over that event's gate-eligible (RESOLVED, not frame-incomplete) conditions.

Per-wallet metrics:

```
total_resolution_pnl = Σ event_pnl                    (gate-eligible events only)
n_events_resolved    = count(events with ≥1 gate-eligible condition)
n_events_positive    = count(events with event_pnl > 0)
top1_share           = max|event_pnl| / Σ|event_pnl|   (abs-based; 0 if no events)
unresolved_exposure  = Σ max(net_shares, 0) · last_trade_price over assets of UNRESOLVED
                       conditions only (disclosure column, NOT in the gate; last_trade_price
                       = price of the wallet's last saved trade in that asset)
```

**Diversified profile** (kill-criterion unit):

```
diversified := total_resolution_pnl > 0
            ∧ n_events_positive ≥ 10
            ∧ top1_share < 0.5
```

**Kill verdict:** `n_diversified` among the **50 winners** `< 5` → **KILL branch (B)**
(no non-survivorship build; archive C1 via follow-up ADR). `≥ 5` → expensive half justified.
The 25 control wallets get the same metrics **as report contrast only** — they are not part
of the gate.

These formulas are frozen as of this spec's commit; the run may not alter them. Any
post-run change of definition would be a new, separately-justified ADR.

## 5. Error handling

- Gamma batch failure (4xx/5xx): retry with smaller batch; final fallback per-id; a
  conditionId that still fails → recorded as `unknown` (excluded + counted).
- `outcomePrices` arrives as a JSON-encoded string (known Gamma quirk — same as
  `clobTokenIds`): parse defensively via the `_coerce_*` pattern.
- Missing fields in a trade row → skip the row with a structlog warning + counter (do not
  silently drop).
- Money is `Decimal` end-to-end; floats only in ratios (`top1_share`).

## 6. Testing (TDD)

Mirror `tests/` layout; no network in tests (monkeypatch the seams):

- `resolution_pnl`: net_shares/cashflow on mixed BUY/SELL; redemption win/lose; clamp at
  `net_shares < 0` → frame-incomplete; strict-binary winner parse (incl. ambiguous 50/50 →
  AMBIGUOUS); event aggregation across multiple conditionIds; `top1_share` abs-basis;
  `diversified` boundary cases (exactly 10 events, top1 exactly 0.5 → NOT diversified);
  kill verdict at exactly 4 and exactly 5 diversified.
- `gamma.fetch_markets_by_condition_ids`: batching math, fallback on injected 4xx,
  `outcomePrices`-as-string payloads.
- `fetch_resolutions`: idempotency (resolved entries not re-fetched; unresolved re-fetched
  only with `--refresh`).
- `run_resolution_screen`: report rendering + verdict line on synthetic fixtures.
- S5: `n_tokens` by conditionId when `condition_id` present, by `token_id` otherwise.

## 7. On-chain spot-check (I13 trust step, separate script)

`scripts/spot_check_trades.py`: take 2 wallets (1 winner, 1 control), sample ~30 saved
trades, fetch each trade's **transaction receipt by `transactionHash`** (point lookups —
NOT range `getLogs`; fixed budget ≈ 30 receipts, negligible CU ≈ < $0.01), decode the
`OrderFilled` logs and compare price/size/side/asset against the data-api rows. Output: a
match-rate line + mismatch details. Requires `POLYGON_RPC_URL` (user runs it; the AI never
reads `.env`). Claim I13 upgraded in `docs/research/claims-verification.md` on success.

## 8. Out of scope (YAGNI)

- No non-survivorship sample, no persistence testing (Step 3, conditional on the gate).
- No C1/D3 selection, no copy-trading replay (Approach 3).
- No changes to the lean screen (`run_wallet_analysis.py` stays the ADR 0020 artifact).
- No `curPrice` marks anywhere inside the gate.
- No A2 scanner work in this spec (ADR 0021 Step 2 — its own spec).
