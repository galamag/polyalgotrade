# A2 Combinatorial-Arb Feasibility Scanner (v1, structural) — Design

**Date:** 2026-06-10 · **Status:** approved by user (design review in session)
**Parent decision:** `docs/decisions/0021-post-wallet-spike-direction.md` (Step 2 — starts early,
accrues calendar data) · **Catalog:** ADR 0013 / spec 2026-06-07 (A2; A1 rides along)

## 1. Goal & verdict question

Measure, on live Polymarket markets, the **frequency and magnitude of structural price-sum
violations** — net of fees, gas, and book-depth slippage — to decide whether A2 deserves a deep
design or gets shelved ("already swept by faster bots" is a valid, cheap negative verdict).
The scanner **accrues calendar data**: arb-window frequency cannot be bought retroactively, so it
starts early and runs whenever the user's PC is on (later: VPS, unchanged).

**Read-only.** No orders, no keys, $0 (Gamma + CLOB public endpoints).

## 2. User decisions (fixed in design review)

1. **Scope v1 = STRUCTURAL only:** negRisk events (Σ of the K mutually-exclusive outcomes' YES
   prices must equal 1) + **A1** (single market: YES+NO must equal $1). Mutual exclusivity is
   guaranteed by the event structure itself → zero definition-risk, zero relation-mapping.
   **Logical pairs across events (e.g. Trump ≤ Republican) are v2** — they carry the
   definition-risk the catalog warns about and would contaminate the verdict.
2. **Price source = CLOB `POST /books` batch** (full order books, keyless): gives DEPTH →
   honest executable size + slippage from the real book, not a constant. Gamma
   `bestBid`/`bestAsk` rejected (top-of-book only, staleness pollutes the calendar stats).
3. **Runtime = long-running loop**: one process, scan every `--interval` seconds (default 120),
   append-only JSONL snapshots, graceful Ctrl+C. Coverage gaps (PC off) are honest — visible as
   timestamp gaps in the data. Approach: polling REST (WebSocket real-time is v2 if v1 says
   "windows exist but are shorter than the interval").

## 3. Architecture & data flow

```
Gamma /events?closed=false  (negRisk events + top-volume binaries)      [universe refresh]
        │   every --interval seconds (default 120)
        ▼
CLOB POST /books  (batch over all universe tokens; --max-books hard bound)
        │
        ▼
src/pat/analytics/arb_scan.py   (pure functions, no network)
  negRisk Σ-violations · A1 YES+NO · size-grid executable edge
        │                                   ▲
        │                  src/pat/costs/  (taker fees + gas_cost + depth_vwap)
        ▼
data/raw/arb_scans/YYYY-MM-DD.jsonl   (append-only; daily files; gitignored/regenerable)
```

### Components

- **`src/pat/costs/polymarket.py`** (prerequisite, +2 primitives — forced backlog item):
  - `POLYGON_TX_GAS_USDC = Decimal("0.005")` — conservative per-tx gas (claim I7: $0.002–0.005).
    CLOB trades cost the USER no gas (operator settles); gas applies only to split/merge/redeem
    transactions.
  - `gas_cost(n_txs: int) -> Decimal` — `n_txs * POLYGON_TX_GAS_USDC`.
  - `depth_vwap(levels: list[tuple[Decimal, Decimal]], size: Decimal) -> Decimal | None` —
    executable VWAP walking (price, size) levels best-first; `None` if total depth < size.
    Slippage is therefore implicit (VWAP vs top), never a constant.
- **`src/pat/venues/polymarket/books.py`** (new module — the ONLY new wire seam):
  `fetch_books(token_ids, *, batch_size, get_page=None)` posting to CLOB `POST /books`
  (`[{"token_id": ...}, ...]`); batch size tuned empirically at implementation (I14 lesson:
  verify endpoint behavior on real ids before trusting); split-on-failure like
  `fetch_markets_by_condition_ids`; returns `token_id -> {bids: [(p,s)...], asks: [(p,s)...]}`.
- **`src/pat/analytics/arb_scan.py`** — the §4 math; pure, fully unit-tested.
- **`scripts/run_arb_scanner.py`** — the loop driver: refresh universe (every M scans, default
  every 10th, to limit Gamma load), fetch books, scan, append snapshot, structlog
  (corr_id per scan, `mode="paper"`-style field = `"scan"`), `--interval 120`,
  `--max-books` (default 1500 — hard request bound per scan), `--out-dir data/raw/arb_scans`,
  graceful KeyboardInterrupt.

### Universe (bounded)

- All **active negRisk events** (Gamma `/events?closed=false`, `negRisk == true`) → all their
  markets' YES tokens (+ NO tokens for the A1 check on the same markets).
- Plus **top-volume active binary markets** (by Gamma `volume24hr`) up to the `--max-books`
  budget — A1 windows live in the long tail, but the budget keeps the scan bounded; the cap and
  the actually-scanned count are logged per scan (no silent truncation).

## 4. Violation math (PRE-REGISTERED — frozen at this spec's commit)

For a negRisk event with K mutually-exclusive outcomes, on the size grid
**s ∈ {10, 50, 100, 500} shares**, all per-leg prices from `depth_vwap` at size s
(leg dropped → grid point is not executable if ANY leg lacks depth):

- **Buy-all-YES:** `cost(s) = Σᵢ depth_vwap(asksᵢ, s) · s`; exactly one outcome pays $1 →
  `net(s) = s − cost(s) − Σᵢ fee(legᵢ) − gas_cost(1)`  (1 tx: redeem at resolution).
- **Sell-all-YES (split-and-sell):** execution = split $1 → YESᵢ+NOᵢ on EACH of the K markets
  (cost s·K, K split txs), sell all K YES legs, hold the NOs (exactly K−1 pay $1 at resolution)
  → per-share economics collapse to `Σ bids − 1`:
  `net(s) = Σᵢ depth_vwap(bidsᵢ, s) · s − s − Σᵢ fee(legᵢ) − gas_cost(K + 1)`
  (K splits + 1 redeem; conservative — the NegRisk adapter may batch, we don't assume it).
- **A1 buy-side (K=2, one market):** YES_ask + NO_ask < 1 → buy both + merge:
  `net(s) = s − [vwap(asks_YES, s) + vwap(asks_NO, s)]·s − fees − gas_cost(1)` (merge tx).
- **A1 sell-side:** YES_bid + NO_bid > 1 → split + sell both:
  `net(s) = [vwap(bids_YES, s) + vwap(bids_NO, s)]·s − s − fees − gas_cost(1)` (split tx).
- **Fees — conservative because of I9 (`feesEnabled` lies):** every leg is charged the
  CATEGORY taker rate via `polymarket_taker_fee` (price = that leg's VWAP) REGARDLESS of the
  market's `feesEnabled` flag; geopolitics = 0% by category. No "maybe there's no fee."
- **Violation record:** computed per scan per event/market; `best_net = max over grid of net(s)`
  and `best_size = argmax`; a violation is reported when `best_net > 0`.
- **Window (frequency unit):** the same violation key `(event_slug | market, type)` observed in
  CONSECUTIVE scans counts as ONE window (it ends when a scan no longer reports it; a gap in
  scanning ends it too). Frequency statistics count windows, not scan-rows.

## 5. Pre-registered feasibility verdict gate (fixed BEFORE the run)

**A2 advances to deep design ONLY if, over ≥ 10 scanning-days, the scanner records ≥ 5 DISTINCT
net-positive windows with `best_net ≥ $1`** (after fees + gas + depth slippage, at executable
size). Otherwise A2 is shelved via ADR ("swept clean" — valid negative verdict).

- A *scanning-day* = a calendar day with ≥ 4 hours of scan coverage (timestamps prove it).
- **Claim ceiling (recorded honestly):** polling at 120 s cannot see windows shorter than the
  interval → measured frequency is a LOWER BOUND. "Not seen" ≠ "doesn't exist" — but windows
  invisible at 120 s are unreachable for our execution speed anyway, so the gate remains
  decision-valid for OUR strategy. The verdict ADR must restate this ceiling.
- These thresholds may not be altered after data starts accruing; any change = a new,
  separately-justified ADR before a fresh observation period.

## 6. Error handling

- One books-batch failure → skip THIS scan with `log.warning` (next scan in `--interval`);
  no retry storms. HTTP 429 → exponential backoff within the batch helper.
- Universe refresh failure → reuse the previous universe (log it); first-ever refresh failure →
  exit with a clear error.
- Malformed book payload (missing sides) → token skipped + counted (`n_bad_books` in snapshot).
- Snapshot write is per-scan append — a crash loses at most the current scan.

## 7. Snapshot schema (JSONL, one line per scan)

```
{ts, scan_duration_s, n_events, n_markets, n_books, n_bad_books, universe_truncated: bool,
 violations: [{key, type: buy_all|sell_all|a1_buy|a1_sell, event_slug, condition_ids,
               grid: {"10": net, "50": net, ...}, best_size, best_net,
               legs: [{token_id, top, vwap}]}]}
```
Daily files `data/raw/arb_scans/YYYY-MM-DD.jsonl` (gitignored; regenerable only forward in time —
THIS is the calendar asset, back it up when it matters).

## 8. Testing (TDD)

- `depth_vwap`: exact VWAP across levels; boundary = size exactly equals total depth;
  insufficient depth → None; empty book → None.
- `gas_cost`: trivial arithmetic + Decimal type.
- Every §4 formula: hand-computed fixtures per type (buy_all with K=3, sell_all, a1_buy,
  a1_sell), incl. fee-per-leg at VWAP price, grid point dropped when a leg lacks depth,
  `best_net`/`best_size` selection, no-violation case (net ≤ 0 at all sizes).
- Window dedup: same key across consecutive scans → 1 window; gap → 2 windows.
- `books.fetch_books`: batching math + split-on-failure (mirror test_gamma_markets pattern).
- Driver: one fake-clock loop iteration writes a valid snapshot line; Ctrl+C path exits cleanly;
  universe-refresh failure reuses previous universe. No network in tests (seams injected).

## 9. Out of scope (YAGNI)

- No order placement, no execution path, no keys.
- No cross-event logical relations (v2, separate spec — definition-risk needs its own design).
- No WebSocket (v2 trigger: v1 shows windows exist but die inside the polling interval).
- No dashboard; analysis of accrued JSONL is a later, separate step (the verdict run).
- No VPS setup (the loop is VPS-ready as-is).
