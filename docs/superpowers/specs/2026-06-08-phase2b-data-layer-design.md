# Phase 2b — Geopolitics MM Data Layer & Real Verdict (spec)

- **Date:** 2026-06-08
- **Status:** Approved by user (brainstorm complete). Ready for writing-plans.
- **Related:** ADR [0016](../../decisions/0016-v2-orderfilled-abi-and-raw-log-decode.md) (V2
  OrderFilled decode recipe — THE source for the decoder), ADR
  [0009](../../decisions/0009-fee-model-corrections.md) (fee math), ADR
  [0014](../../decisions/0014-orderbook-data-and-informed-crossvenue-mm.md) (backtest = lower bound),
  ADR [0015](../../decisions/0015-execution-mode-stamped-by-broker.md) (mode), claims
  [I8/I9](../../research/claims-verification.md), `docs/strategies/market-making.md` §7-8 (verdict
  doc + caveats), `docs/roadmap.md` (Phase 2b gate). Prior context map produced by the
  `phase2b-context-map` workflow (7-subsystem read).

## Goal & success criteria

Build the **data layer** that feeds the existing market-making backtest with **real on-chain
Polymarket trades** from genuinely 0%-fee geopolitics markets, and produce the first **real,
fee-adjusted MM edge verdict**.

**Verdict gate** (already implemented in `Verdict.from_metrics`, CLAUDE.md §6): advance iff
`n_trades >= 1000` **and** `net_pnl > 0` **and** `sharpe > 1.0`. A failing gate sends the MM
strategy to the trash, not to production.

### The framing insight (why "0%-fee" matters here)
On geopolitics `feesEnabled=false` markets the backtest charges **0 fees on both sides**: Polymarket
makers are *never* charged (`polymarket_maker_fee ≡ 0`), the geopolitics taker rate is 0, and
maker-rebate income is deliberately **excluded** from `net_pnl` (metrics.py H4 honesty rule; the
geopolitics rebate pool is 0 anyway). The `BacktestBroker` produces **maker fills only**. Therefore
this verdict measures **pure spread capture minus adverse selection** — the cost model does not
meaningfully fire. That is intentional: it is the cleanest, most honest *lower-bound* test of "does
the MM have an edge at all," before we ever model rebates or fee-bearing markets.

## Decisions made during brainstorming

1. **Scope = clean 0%-fee verdict only** (minimal data layer, static cost model = 0, fast go/no-go).
   Maker-rebate income and fee-bearing markets are a **later, separate phase** — explicitly out of
   scope here.
2. **Iterative data window + both exchanges.** Start with a small recent window (~7-14 days) over
   **both** the main CTF Exchange V2 and NegRisk V2; measure geo-fill density; grow the window toward
   ~1500-2000 fills. NegRisk emitting the same `OrderFilled` ABI must be **verified** first.
3. **maker/taker saved in raw, schema untouched.** The decoder keeps `maker`/`taker` (+ `side`,
   `tokenId`, `blockNumber`) in the saved decoded-JSON for future copy-trading (C1), but the `Fill`
   pydantic schema is **not** extended now.
4. **Architecture A — modular library + thin orchestration** (aligns with ADR 0016, reusable for
   Phase 3/4 live).

## Architecture & components

The integration boundary is a **decoded-events JSON file**: `run_mm_backtest.py` already does
`json.load → parse_orderfilled → streams_from_fills → run_sweep → verdict`. The new data layer
*produces* that file (geopolitics-only, timestamped); the backtest path is reused **unchanged**.

### New module `src/pat/data/polymarket_on_chain.py` (pure logic + 1 network seam)
```python
TOPIC0_ORDERFILLED = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"

def decode_v2_orderfilled(log: dict) -> dict | None
    # Pure. If topics[0] != TOPIC0_ORDERFILLED -> None (skip non-OrderFilled events).
    # maker = "0x" + topics[2][-40:];  taker = "0x" + topics[3][-40:]
    # data = bytes.fromhex(log["data"][2:]); 7 x 32-byte words at range(0,224,32):
    #   side, tokenId, makerAmountFilled, takerAmountFilled, fee, builder, metadata
    # V2->V1 bridge: side==0 (BUY) -> makerAssetId="0", takerAssetId=str(tokenId)
    #                side==1 (SELL) -> makerAssetId=str(tokenId), takerAssetId="0"
    # Returns dict with EXACTLY the keys parse_orderfilled reads:
    #   makerAssetId, takerAssetId, makerAmountFilled, takerAmountFilled, fee  (RAW 6-dp ints),
    #   transactionHash
    # plus extras (NOT read by the parser, preserved for copy-trading / provenance):
    #   blockNumber:int, maker, taker, side, tokenId
    # NB: does NOT set "timestamp" (enrich_timestamps owns that).

def _rpc_get_block_timestamp(rpc_url: str, block_number: int) -> int   # NETWORK SEAM, epoch SECONDS

def enrich_timestamps(events: list[dict], rpc_url: str,
                      get_ts: Callable = _rpc_get_block_timestamp) -> list[dict]
    # Dedup unique blockNumbers -> one eth_getBlockByNumber per block (cache).
    # Sets event["timestamp"] = seconds * 1000  (epoch MILLISECONDS, what parse_orderfilled expects).
```
No `web3`/`eth-abi` dependency (ADR 0016 rejected the SDK path) — hand-roll with
`bytes.fromhex` + `int.from_bytes(..., "big")`.

### New module `src/pat/venues/polymarket/gamma.py` (pure logic + 2 network seams)
```python
GAMMA = "https://gamma-api.polymarket.com"
GEOPOLITICS_TAG_ID = 100265

def _gamma_get_events(tag_id: int = GEOPOLITICS_TAG_ID, *, limit: int = 500,
                      offset: int = 0) -> list[dict]          # NETWORK SEAM (paginate ~35-40 events)
def _clob_get_fee_rate(token_id: str) -> int                  # NETWORK SEAM -> base_fee (bps)

def select_geopolitics_tokens(events: list[dict], *, cross_check: bool = False) -> set[str]
    # From events[].markets[] keep markets with feesEnabled == false (the TRUE 0%-fee selector —
    # NOT the tag; some geopolitics-tagged markets carry politics_fees 4%). Collect clobTokenIds
    # (decimal strings) into a set. If cross_check: additionally drop any token whose
    # _clob_get_fee_rate(token_id) base_fee != 0.
```

### Extend `scripts/fetch_polymarket_history.py`
- Add `topics=[TOPIC0_ORDERFILLED]` to the `eth_getLogs` params (currently address-only, returns
  *all* events from the contract).
- Query **two** addresses: `EXCHANGE_V2 = 0xE111180000d2663C0091e4f400237545B87B996B` and
  `NEGRISK_V2 = 0xe2222d279d744050d28e00520010520000310F59`.

### New orchestration `scripts/fetch_geopolitics_data.py`
Produces the geopolitics-only decoded JSON. See data flow below. Also serves as the **density probe**
for the iterative window (it logs the geo-fill count).

### Reused UNCHANGED
`parse_orderfilled`, `streams_from_fills` (its `token_ids` arg is the geopolitics filter hook),
`run_sweep`, `Verdict.from_metrics`, the cost model. `run_mm_backtest.py` gains only an optional
`--record` flag (verdict writer, §"Cost / verdict / journal").

## Data flow (ordered for CU economy)

```
Gamma /events?tag_id=100265&limit=500 → markets[feesEnabled=false].clobTokenIds → geo_token_set: set[str]
        │ (optional /fee-rate cross-check base_fee==0)
        ▼
eth_getLogs [EXCHANGE_V2, NEGRISK_V2], topics=[TOPIC0], [from,to] (paged ≤10k/call) → ALL raw OrderFilled logs
        ▼ decode_v2_orderfilled  (non-OrderFilled topic -> None; malformed -> quarantine)
decoded events (+ maker/taker/side/tokenId/blockNumber)
        ▼ FILTER to geo_token_set            ← BEFORE timestamps (this is the CU saving)
geo-only decoded events
        ▼ enrich_timestamps  (eth_getBlockByNumber per UNIQUE block, x1000 -> ms)
geo-only + timestamp(ms)  →  write data/raw/geopolitics_{from}_{to}.json   (includes maker/taker)
        ▼  (run_mm_backtest, EXISTING path, unchanged)
parse_orderfilled → list[Fill] → streams_from_fills(token_ids=geo_set) → run_sweep → Result/Verdict
        ▼
print frontier + record verdict in market-making.md §7-8 + JSONL journal
```

**Why this order:** `eth_getLogs` cannot filter by `tokenId` (it lives in `data`, not `topics`), so
we must pull *all* exchange OrderFilled in the window and filter afterward. But the expensive
per-block timestamp RPC (`eth_getBlockByNumber`, ~20 CU each on Alchemy) runs **only over the
geo-filtered fills**, not the whole exchange volume — this is what keeps the iterative window cheap
within the 30M CU/mo free tier.

## Verified facts & constraints (obey exactly)

- **V2 `OrderFilled` event** (ADR 0016 / I8): `OrderFilled(bytes32 indexed orderHash, address indexed
  maker, address indexed taker, uint8 side, uint256 tokenId, uint256 makerAmountFilled, uint256
  takerAmountFilled, uint256 fee, bytes32 builder, bytes32 metadata)`. 3 indexed params.
- **topic0** = `0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee`.
- **Raw layout:** topics[1]=orderHash; topics[2]=maker (last 40 hex); topics[3]=taker; data = 7×32B
  words at offsets `range(0,224,32)`: side(0=BUY,1=SELL), tokenId, makerAmountFilled,
  takerAmountFilled, fee, builder(~0), metadata(~0).
- **Scaling:** amounts & fee are 6-dp fixed point; `FILL_SCALE = Decimal("1000000")`. The **decoder
  passes RAW ints**; `parse_orderfilled` divides. Never pre-scale in the decoder.
- **USDC leg** is `assetId == "0"`; `price = usdc/shares`; `token_id` = the non-"0" asset id. The
  side→assetId bridge is what makes price come out right for V2 logs.
- **Timestamp:** `eth_getLogs` returns no timestamp; `eth_getBlockByNumber` returns epoch **seconds**;
  `parse_orderfilled` expects epoch **milliseconds**. The data layer multiplies by 1000
  (`enrich_timestamps`); the parser does no scaling.
- **Gamma (I9):** `GET https://gamma-api.polymarket.com/events?tag_id=100265&limit=500[&offset=]`;
  `events[].markets[].clobTokenIds = [YES_id, NO_id]` (decimal strings). The **0%-fee selector is
  per-market `feesEnabled==false`** (≡ `feeType==null`), **NOT** the tag. Cross-check a token via
  `clob.polymarket.com/fee-rate?token_id=<id>` → `base_fee` (bps) == 0. ~35-40 events (1-2 pages).
- **Fee facts (ADR 0009):** taker = `shares*rate*price*(1-price)` rounded 5-dp; geopolitics rate = 0
  AND rebate pool = 0; makers never charged; crypto peak exactly 1.75% at p=0.5 (derive, never
  hard-code).
- **Verdict gate** (metrics.py, checked in order): `n_trades>=1000`, `net_pnl>0`, `sharpe>1.0`.
  `net_pnl = gross_pnl + inventory_value - fee_drag` (no rebate income).
- **Verdict-writing caveats** (MM doc §8): sharpe is **per-fill** (relative ranking, not annualized);
  win_rate ~50% by construction for a two-sided MM (lean on net_pnl incl. inventory MtM); sharpe &
  max_drawdown are realized-only; fills are a conservative **lower bound** (through-trade proxy, no
  historical order book — real proof is paper, Phase 3, ADR 0014).
- **V2 deploy** ~2026-03-31 → usable windows start late March 2026.
- **Conventions:** money is `Decimal` everywhere (only `sharpe` is float); all network I/O behind a
  **single monkeypatchable seam** per fetcher + a "no real network" test; ruff `S` (bandit) active on
  `src` (httpx needs explicit timeout, no asserts, no hardcoded secrets); mypy strict on `src`
  (full annotations); sync `httpx.Client` is acceptable for these batch scripts; read/write files
  with `encoding="utf-8"`; env vars read via `os.environ.get` (no python-dotenv) — user exports
  `POLYGON_RPC_URL` or passes `--rpc-url`.

## Error handling & edge cases

- **Quarantine malformed events.** `parse_orderfilled` raises `pydantic.ValidationError` on price>1
  or size<=0 (intentional anomaly surfacing). The orchestration validates decoded events first
  (has "0" leg, price∈[0,1], size>0); failures go to a quarantine log with a **count + warning**,
  not a crash. The parser stays strict.
- **NegRisk address + ABI verification.** The NegRisk V2 address `0xe2222d279d744050d28e00520010520000310F59`
  came from a secondary read, not a primary source (CLAUDE.md §1 principle 2) — verify the **address**
  *and* that it emits the same `OrderFilled` ABI before use: probe a small sample, assert
  `topics[0]==TOPIC0` and a clean 7-word decode with valid price. Match → use it; mismatch/empty →
  fall back to the main exchange only + flag. Record the outcome as a `claims-verification.md` entry
  (route via `claims-verifier`).
- **`eth_getLogs` 10k-result cap.** Page by `POLYGON_MAX_BLOCK_RANGE` (default 1000); on a
  ">10k results" error, halve the range adaptively.
- **date→block.** CLI takes `from_block`/`to_block`; a light `resolve_window(days_back)` helper uses
  `eth_blockNumber` + ~2 s/block (exact boundaries aren't critical for a research fetch; the
  iterative approach self-corrects).
- **token_id format match.** Gamma `clobTokenIds` (decimal strings) must exactly equal `str(tokenId)`
  from the decoder — verify empirically against real data (assert + a one-time check) so the
  `streams_from_fills` filter actually matches.
- **Empty window / 0 geo fills** → clean log, no crash (the density probe surfaces this).

## Cost model, verdict recording, journal

- **Cost model = static `Category.GEOPOLITICS = 0`** (per decision 1). Guard that markets are truly
  0%-fee: `feesEnabled==false` in Gamma selection + optional `/fee-rate base_fee==0` cross-check.
  Per CLAUDE.md §3 the "static vs live per-market fee" decision is **ratified by `fee-cost-auditor`**
  before the verdict is trusted (a distinct task-7 step). Also surface to the auditor that
  `inventory_haircut` is a raw `Decimal` in `metrics.py` **not** routed through `src/pat/costs/` —
  confirm it is a correct liquidation proxy, not a hidden-cost gap.
- **Verdict recording.** `run_mm_backtest --record` writes the frontier into
  `docs/strategies/market-making.md` §7 (table: half_spread, net_pnl, gross_pnl, fee_drag,
  inventory_value, sharpe, win_rate, max_drawdown, n_trades, verdict) + a §8 verdict line, **with the
  §8 caveats** and data provenance (block window, token count, total fills).
- **Journal.** Add a `TradeJournal` JSONL for the run (fetch + backtest), `corr_id`, `mode="backtest"`:
  records for gamma selection (n tokens), fetch (n logs / n geo / unique blocks / quarantined), and
  each verdict row. (`run_mm_backtest` has no journal today — we add one consciously per the
  logging-observability standard.)

## Testing strategy

Mirror existing patterns: pytest mirroring `src/`, committed JSON fixtures + inline literals + small
deterministic generators, `monkeypatch` on network seams, `tmp_path` for output, **no** conftest /
factory libs, all money `Decimal`.

- `tests/data/test_polymarket_on_chain.py` — `decode_v2_orderfilled` (golden raw-log → expected dict,
  both BUY/SELL bridge branches; non-OrderFilled topic → None; malformed → handled);
  `enrich_timestamps` (monkeypatched `get_ts`: N events / M unique blocks → exactly M calls; assert
  ×1000 ms).
- **New golden fixture** `tests/data/fixtures/orderfilled_raw_v2.json` — a real raw `eth_getLogs`
  OrderFilled entry (hex topics/data) → assert `parse_orderfilled(decode_v2_orderfilled(log))`
  yields the correct `Fill` (closes the ADR-0016 follow-up "regenerate fixtures from real V2 logs").
- `tests/venues/polymarket/test_gamma.py` — `select_geopolitics_tokens` (feesEnabled true/false mix →
  only false-fee tokens; `cross_check` path with monkeypatched fee-rate).
- `tests/scripts/test_fetch_geopolitics_data.py` — full orchestration with ALL seams monkeypatched →
  expected geo-only JSON; "no real network" test; quarantine count; CU-saving order (timestamps only
  for geo fills).
- Extend `tests/scripts/test_fetch_mocked.py` for the topic0 filter + two addresses.
- End-to-end offline: monkeypatched seams → `fetch_geopolitics_data` → `run_mm_backtest` → a `Verdict`
  is produced.

## Task breakdown (TDD, subagent-driven, review-gated)

1. `decode_v2_orderfilled` + golden raw-log fixture (test-first) — the core decoder.
2. `enrich_timestamps` + block-timestamp seam + dedup cache.
3. `gamma.select_geopolitics_tokens` + seams (+ cross-check).
4. Extend `fetch_polymarket_history` (topic0 + NegRisk address) + NegRisk-ABI verification probe +
   `claims-verification.md` entry (via `claims-verifier`).
5. `fetch_geopolitics_data` orchestration (+ quarantine + journal + CU-saving order).
6. `run_mm_backtest --record` (verdict → market-making.md §7-8) + journal.
7. **Real-data run** (iterative window) → record the actual verdict; route the cost-model sign-off via
   `fee-cost-auditor`; write the ADR(s).

## Open risks (carried into implementation)

- **n≥1000 feasibility** — the binding empirical unknown. Only ~35-40 geopolitics events exist and the
  through-trade fill rule is a conservative lower bound. Task 7 answers it; the iterative window +
  NegRisk inclusion are the mitigations. If the sample starves, the verdict is "insufficient data,"
  not "no edge."
- **NegRisk ABI sameness** — verified in task 4 before use.
- **token_id string-format match** (Gamma vs on-chain) — verified on real data.
- **date→block precision** — acceptable for a research fetch.

## Non-goals (explicit YAGNI)

- Maker-rebate income modeling and fee-bearing markets (a later phase).
- Extending the `Fill` schema with maker/taker/tokenId fields (saved in raw JSON only).
- Live trading / signing / wallet keys (Phase 3/4; supply-chain & key isolation gated there per
  ADR 0017).
- A historical order book or any non-lower-bound fill model (Phase 3 paper is the real proof).
- Per-market live fee plumbing into the cost model (only relevant once we test fee-bearing markets).
