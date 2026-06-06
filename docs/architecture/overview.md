# Architecture Overview

Approach **A**: a thin, well-understood core that we own, extended by strategy plugins.
Built as a **vertical slice** (market making) first, then widened. Rationale and
alternatives: ADR [`0001`](../decisions/0001-architecture-approach-A.md).

## Principle: one strategy interface, three execution backends
A `Strategy` reacts to market data and emits orders. It is handed a `Broker`. The *same*
strategy code runs against three brokers — this is what makes a backtest verdict
trustworthy as a prediction of live behavior.

```
            ┌─────────────────────────────────────────────┐
            │                 Strategy                     │
            │  on_market_data() · on_fill() · gen_orders() │
            └───────────────┬─────────────────────────────┘
                            │ Order / cancel        ▲ Fill / book
                            ▼                        │
            ┌───────────────────────────────────────┴─────┐
            │   Broker (one interface)                     │
            │   Backtest  ·  Paper  ·  Live                │
            └───────────────┬─────────────────────────────┘
        passes every order's│cost through
                            ▼
                     costs/ (fee model)  ──► every PnL number is net-of-fee
```

## The seven layers

1. **`data/`** — historical ingestion (`OrderFilled` via Polygon RPC + Gamma API) and live
   WebSocket feeds, both normalized into the same `core/` types. One source of truth for
   backtest and live.
2. **`venues/`** — adapters (`polymarket/`, `kalshi/`) presenting a common interface over
   each venue's quirks (auth, order serialization, settlement).
3. **`execution/`** — `BacktestBroker` / `PaperBroker` / `LiveBroker` behind one `Broker`
   protocol. See [execution-brokers.md](execution-brokers.md).
4. **`costs/`** — the fee & cost model. Every order's cost is computed here; no ad-hoc fee
   math anywhere else. See [fee-cost-model.md](fee-cost-model.md).
5. **`strategies/`** — plugins implementing the `Strategy` protocol. `market_maker.py` first.
   A hybrid is just another plugin composing signals.
6. **`risk/`** — pre-trade checks: position sizing (≤25% bankroll, 3–5 positions), drawdown
   stop, kill-switch. The broker refuses orders that violate limits.
7. **`analytics/`** — consumes the trade journal → PnL attribution, Sharpe, win-rate, and the
   automated **verdict** ("EV>0 after fees? Sharpe>1?").

`core/` holds the shared `pydantic` types every layer speaks. `signals/` is the (currently
empty) seam for the deferred intelligence layer ([intelligence-layer.md](intelligence-layer.md)).

## Data flow (backtest example)
`data/` replays normalized events → `BacktestBroker` feeds them to the `Strategy` → strategy
emits orders → broker simulates fills using `costs/` (fee) + a slippage model → fills logged
to the trade journal → `analytics/` produces the verdict. The live flow is identical except
the broker is `LiveBroker` and events come from the WebSocket.

## Design constraints
- `asyncio` single event loop; no blocking calls in the hot path.
- Small, single-purpose modules with explicit interfaces (`Protocol`/ABC) between layers, so
  each can be tested in isolation and swapped.
