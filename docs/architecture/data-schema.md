# Data Schema (`src/pat/core/`)

The single vocabulary every layer speaks. Implemented as `pydantic` models so bad data fails
loudly at the boundary. Names are illustrative — finalize in Phase 1.

> Source-of-truth claims behind these fields (pUSD, V2 order struct, tick sizes) are tracked
> in [../research/claims-verification.md](../research/claims-verification.md) (C2, C3). Do not
> hard-code an address/format until its claim is VERIFIED.

## Core types

- **`Venue`** — enum: `POLYMARKET`, `KALSHI`.
- **`Market`** — `id`, `venue`, `question`, `category` (e.g. `geopolitics`/`politics`/`crypto`
  — drives the fee tier), `outcomes`, `tick_size`, `resolution_source`, `close_time`,
  `resolution_rule_text` (kept verbatim — needed for cross-market divergence checks).
- **`Token`/`Outcome`** — the tradable YES/NO leg: `token_id`, `market_id`, `side`.
- **`OrderBookLevel`** / **`OrderBook`** — `[(price, size)]` bids/asks + timestamp.
- **`Order`** — `client_id`, `token_id`, `side` (BUY/SELL), `price`, `size`, `order_type`
  (GTC/FOK/FAK), `mode` (backtest/paper/live), `reason` (free text — *why* this order).
- **`Fill`** — `order_id`, `token_id`, `price`, `size`, `fee` (computed by `costs/`), `ts`,
  `liquidity` (MAKER/TAKER), `mode`.
- **`Position`** — `token_id`, `net_size`, `avg_price`, `realized_pnl`, `unrealized_pnl`.
- **`Trade journal record`** — see [logging-observability.md](logging-observability.md);
  superset of `Order`/`Fill` plus correlation-id, strategy, and computed fee/EV context.

## Normalization rules
- Prices are decimals in `[0,1]` (probability), not cents. Convert venue-native units at the
  adapter boundary.
- Timestamps are UTC epoch milliseconds.
- Every record carries `venue` and `mode`; nothing downstream guesses.
- Polymarket and Kalshi differences (e.g. contract vs share, settlement) are absorbed in
  `venues/`, never leaked into strategies or analytics.

## Historical data sources (Phase 1)
- `OrderFilled` events from the CTF Exchange V2 contract via Polygon JSON-RPC, merged with
  Gamma API metadata (the `warproxxx/poly_data` approach — claim I3).
- CLOB historical timeseries (`GET /prices-history`) for price series.
- Stored under `data/` (gitignored): `raw/` (as-fetched) and `processed/` (normalized parquet).
