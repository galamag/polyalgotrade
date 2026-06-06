# Execution Brokers (`src/pat/execution/`)

One `Broker` protocol, three implementations. Strategies depend only on the protocol, so the
same strategy code is what we backtest, paper-trade, and run live.

## The `Broker` protocol (illustrative)
```python
class Broker(Protocol):
    async def submit(self, order: Order) -> OrderAck: ...
    async def cancel(self, client_id: str) -> None: ...
    async def positions(self) -> list[Position]: ...
    # events delivered to the strategy: on_market_data(book), on_fill(fill)
```
Every `submit` passes through `risk/` (pre-trade limit check) and records to the trade
journal with its `reason`. Fills carry a `fee` computed by `costs/`.

## 1. `BacktestBroker`
- Replays normalized historical events from `data/`. Deterministic.
- **Fill model:** a limit order fills when the replayed book crosses it; model maker/taker
  classification, partial fills, and a configurable slippage assumption. Conservative by
  default (assume we're behind the queue) — optimistic fills are how backtests lie.
- Produces the trade journal that `analytics/` turns into the verdict.

## 2. `PaperBroker` (mandatory — Polymarket has no usable testnet)
- Consumes **live** market data but simulates fills against the *live* book (our own "drawn"
  paper). No real orders, no money.
- Same fill/slippage/cost model as backtest, so paper↔backtest are comparable (Phase-3 gate:
  deviation < 10%).
- **Kalshi side** can additionally use the real `demo-api.kalshi.com` sandbox (claim I4) for
  a higher-fidelity check.

## 3. `LiveBroker`
- Real execution via the Polymarket V2 SDK (`py-clob-client-v2` — claim C4) and Kalshi API.
- Security-critical: signing (ERC-1271 / signature types — research notes signature_type=3 is
  the common failure), key handling. Route changes through `security-reviewer`.
- Rate-limit aware (claim I2); WebSocket for data, never polling.
- Used only from Phase 5, only for verdict-positive strategies, capped at ≤$5/position.

## Why conservative fills matter
The single biggest way a backtest fools you is optimistic fills (assuming you got the good
price). Default to pessimistic assumptions; if a strategy survives pessimistic fills, the
edge is more likely real.
