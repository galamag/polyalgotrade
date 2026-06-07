# Phase 2 — Strategy Catalog & Market-Making Design (spec)

- **Date:** 2026-06-07
- **Status:** Living document. Catalog + verification order = **approved** by user.
  Market-making deep design (Section 2) = *in progress* (brainstorm continues).
- **Related:** ADR [0013](../../decisions/0013-phase2-strategy-catalog.md) (catalog & order),
  ADR [0014](../../decisions/0014-orderbook-data-and-informed-crossvenue-mm.md) (book data +
  informed cross-venue MM), ADR [0012](../../decisions/0012-phase1-analytics-limitations.md)
  (Phase-2 entry prerequisites), `docs/strategies/market-making.md` (per-strategy verdict doc).

## Goal

Produce a **catalog** of candidate strategies spanning the risk spectrum (risk-free → risky),
each tagged with its edge source, risk, and — critically — whether we can honestly **backtest it
on the data we actually have today**. Then verify them **one at a time** down a fixed order,
starting with market making (roadmap-fixed first wave).

PnL accounting subtracts **market fees only**. KZ income tax is *not* part of any strategy's EV —
it is an income tax computed monthly / at fiat off-ramp, tracked at the bankroll level
(CLAUDE.md §6), never inside a per-trade or per-strategy calculation.

## The hard constraint that shapes everything: data reality

What we have on hand:

- ✅ **On-chain `OrderFilled`** (Polygon RPC) — *executed trades* (prints): price, size, fee,
  timestamp. ⚠️ **Maker/taker addresses** (which would enable copy-trading attribution, C1): the
  canonical CTF Exchange `OrderFilled` signature *appears* to include `address maker, address taker`,
  but our parser/fixture don't capture them and this is **not primary-source verified** — confirm via
  `claims-verifier` before C1 (logged PENDING as claim `I8` in `claims-verification.md`). C1 needs a
  parser **extension** (or, if the event omits them, an alternative attribution source).
- ✅ **Gamma API** — market metadata.
- ❌ **No historical order book** (apparent — ⚠️ to-verify). Polymarket runs an off-chain CLOB; the book is visible only in
  **real time** via WebSocket. There is **no known official/free way to retrieve the book as it looked
  at a past timestamp** (confirm via `claims-verifier`). Gamma `prices-history` gives a derived mid/last timeseries, *not* depth.

Order-book history availability, by venue (⚠️ = architecture-critical, verify via
`claims-verifier` before building the data layer — not on faith, CLAUDE.md §1 principle 2):

| Venue | Real-time book | Historical book |
|---|---|---|
| **Polymarket** | ✅ WS (`wss://ws-subscriptions-clob.polymarket.com`) | ❌ Not retrievable retroactively. Must **self-record** from now forward. ⚠️ |
| **Binance** | ✅ WS depth + REST snapshot | ✅ Free dumps at `data.binance.vision` (trades, aggTrades, klines; bookTicker/bookDepth esp. futures). High-fidelity L2 → self-record diff-depth+snapshot, or paid Tardis/Kaiko *(vendor coverage assumed, unverified)*. ⚠️ exact coverage unverified |
| **Bybit** | ✅ WS orderbook | ⚠️ `public.bybit.com` (trades/klines); historical depth thinner than Binance; Tardis/Kaiko *assumed* to cover *(unverified)*. ⚠️ |

**Consequences for backtesting:**

1. A **high-fidelity** MM backtest on Polymarket from history **appears impossible** with current public sources (no known historical-book endpoint, ⚠️ to-verify) — no book means no
   queue position / depth. We use the **conservative through-trade proxy** already in
   `BacktestBroker` (a resting quote fills only when a trade goes *through* its price; strict
   inequality; classified MAKER). This is a **lower bound**, honest but pessimistic.
2. The **real** MM validation is **paper trading (Phase 3) against the live book.**
3. Therefore we should build a **`live book recorder`** early (WS book → disk). It (a) feeds paper
   trading and (b) accumulates a Polymarket book dataset for *future* backtests "from now forward."
   This is the right investment instead of chasing a history that does not exist.

## Section 1 — The Catalog (approved)

"Backtest now?" = can we test it honestly on current data (on-chain trades + Gamma; maker/taker addresses pending verification, claim I8).

### Tier 0 — structural arbitrage (theoretically risk-free, but execution-gated)

| # | Strategy | Edge | Risk | Backtest now? |
|---|---|---|---|---|
| A1 | YES+NO < \$1.00 (one market) | \$1 at resolution − fees | ~no directional; **execution + fee** gated | ⚠️ Can *measure* gap size/frequency in history; executability ~no (spreads ~1.2%, ~2.7s window — *L2, low-trust/directional*; sub-100ms needed) |
| A2 | Combinatorial arb (related markets, e.g. Trump ≤ Republican) | logical mispricing | leg-risk, capital lock-up, **definition-risk** (related markets may resolve on different criteria) | ⚠️ Partial (needs synchronized price series + manual/LLM relation mapping) |

### Tier 1 — market making (low–medium risk)

| # | Strategy | Edge | Risk | Backtest now? |
|---|---|---|---|---|
| **B1** | **MM geopolitics (0% taker fee)** | **pure spread** | inventory, adverse selection, event resolution | ✅ through-trade proxy ← **#1, deep-designed this phase** |
| B2 | MM long-tail politics (+25% maker rebate) | spread + daily rebate | same as B1 + thinner liquidity | ✅ same proxy (rebate = separate daily batch, $1/day gate) |
| B3 | Informed cross-venue crypto MM (Binance/Bybit signal) | spread + 20% crypto rebate, protected by faster fair-value | **high competition** (HFT/Wintermute), model-risk | ❌ needs the **Polymarket crypto book** (no history; self-record) → **paper-first**. See Section 3 |

### Tier 2 — signal / follow (medium risk)

| # | Strategy | Edge | Risk | Backtest now? |
|---|---|---|---|---|
| C1 | Copy-trading top wallets | their edge − your lag | lag/slippage, edge decay, you are taker | ⚠️ **likely fit** — on-chain address attribution, *pending* `OrderFilled` ABI verification (I8) + parser extension to capture addresses |
| C2 | Cross-venue basis Polymarket↔Kalshi | price gap for the same event | basis (events defined/resolved differently), 2-venue ops, settlement timing | ❌ needs Kalshi price history (new data) |

### Tier 3 — event-driven (high risk)

| # | Strategy | Edge | Risk | Backtest now? |
|---|---|---|---|---|
| D1 | UMA dispute reversion | mispricing during dispute chaos | **tail** — token-vote can resolve "wrong" (MicroStrategy case, ~\$60M — *second-hand research, unverified*) | ⚠️ price series around labeled dispute events |
| D2 | Latency-arb Binance→crypto 15-min (taker) | spot lead | high, fee-dominated | ❌ research: **dead** (dynamic fee 1.75% @ p=0.5 (exact) > 1–2% edge) — **verify-then-likely-bury**; needs Binance tick history |
| D3 | News-event trading | react faster than market | speed, false signals | ❌ Phase 4 (intelligence layer / local LLM) |

### Enabler (not a strategy)

- **`live book recorder`** — persists the Polymarket WS book to disk. Required for paper trading;
  accumulates a future backtest dataset. See the data-reality section above.

## Section 1b — Verification order (approved)

```
B1  →  B2  →  C1  →  A2  →  D1  →  C2  →  B3  →  D2  →  D3
```

Rationale: roadmap-fixed first (MM), then **what is backtestable now and cheap** (copy-trading,
combinatorial, dispute), then **what needs new data/infra** (Kalshi cross-venue, informed crypto
MM), and finally **"verify-then-likely-bury"** (latency-arb) and **Phase-4** (news). Each strategy
gets its own `docs/strategies/<name>.md` verdict before advancing, and must pass the gate
(n_trades ≥ 1000 ∧ net EV > 0 after fees ∧ Sharpe > 1.0; CLAUDE.md §6).

## Section 3 — The "interesting twist": informed cross-venue crypto MM (B3)

**This records an idea so it is not lost (CLAUDE.md §6). It is deferred, not built.**

**Core observation.** A Polymarket crypto binary ("BTC > \$X at time T") is a **derivative of
spot.** Its fair price = the risk-neutral probability that spot closes above the strike at T =
`f(spot, time-to-expiry, volatility)`. Spot is **price-discovered fastest** on Binance/Bybit
(deepest books, most volume). The Polymarket binary therefore **reprices with a lag.**

**What simultaneously watching the crypto book/trades (Binance/Bybit) + Polymarket gives, in
theory:**

1. **Lead-lag signal** — Binance → implied fair probability → compare to the Polymarket quote → a
   divergence beyond a threshold is a signal. This is the basis of latency-arb.
2. **Better fair-value for MM** — knowing spot in real time lets a maker quote smarter and avoid
   being **picked off** on a stale quote (reduced adverse selection).
3. **Volatility estimate** — Binance order flow yields realized/implied vol, the key input to the
   binary's time-value. Polymarket does not expose vol directly.
4. **Microstructure** — book imbalance and aggressor flow on Binance hint at short-term spot
   direction.

**Why the naive version is dead:** "grab stale quotes" = **taker** → pays the dynamic crypto taker
fee, which is **exactly 1.75% at p=0.5** (verified, ADR 0009) and exceeds the typical 1–2% edge;
plus a speed race against HFT (per second-hand research, Wintermute *reportedly* began two-sided
liquidity ~2026-05-29 — *unverified*). Fee-dominated. *(The fee math is verified; the edge size and
competition context are second-hand.)*

**The reframe that makes it interesting (maker, not taker):** use the spot/vol signal to do
**informed market making** — *post* two-sided quotes around the Binance-derived fair value and
skew them to avoid being picked off. This needs **no sub-100ms race** (we are not crossing to
take; we are providing liquidity); it needs only to not get adversely selected. It converts a
"dead latency-arb" into a "smarter MM," and it fits our MM-first roadmap and modest latency
budget.

**Caveat / why it is not first.** Crypto markets on Polymarket are the **most competitive**
(HFT-dense, Wintermute) → the thinnest MM edge. Start MM where HFT does not bother
(geopolitics/long-tail politics). B3 is an **advanced** catalog item.

**Data path for B3.** Binance/Bybit spot + vol (historical *believed* available — *unverified*, confirm via `claims-verifier`) + Polymarket crypto
book (must be **self-recorded** live). Hence B3 is **paper-first**: validate against the live book
once the recorder exists, rather than a non-existent historical book.

## Section 2 — Market-making deep design (B1, geopolitics) [approved]

**Status:** approved by user 2026-06-07. Locked choices: v1 = **simple fixed-spread**; inventory
MtM = **last − haircut**; backtest = **parameter sweep**. Mirrored into
`docs/strategies/market-making.md`.

### Edge
On low-liquidity geopolitics markets HFT does not fully cover the book, leaving wide spreads
(research: ~2–8¢ — *unverified, directional*). Quoting both sides captures the spread. Geopolitics
taker fee = 0% **and** the rebate pool = 0, so **edge = pure spread − adverse selection − inventory
risk**. This is the cleanest MM test: no fee or rebate confounds the verdict.

### Adverse selection is the real enemy (not fees)
Spread capture is gross profit; adverse selection is what kills it — we get filled exactly when we
are on the wrong side of an informed move (a resting bid fills as the market sells *through* it,
then keeps falling). The backtest MUST model this or it reports fake "pure-spread" profit. The
existing through-trade fill model does it naturally: a bid fills only on a trade strictly below it
(the market moving down through us), so we are systematically filled into adverse moves.

### Quoting mechanics (v1 — simple fixed spread)
- **Fair value `fv`** = EWMA of recent trades (no book → trade-derived proxy for mid).
- Symmetric quote: `bid = fv − half_spread`, `ask = fv + half_spread`; both resting **MAKER** (GTC).
- Fixed size `q` per side, capped. **Inventory cap ±I_max**: at the cap, quote only the
  inventory-reducing side.
- Requote when `fv` moves beyond a threshold.
- *Deferred to v2 (documented, not built):* inventory-skewed quoting (Avellaneda–Stoikov). Pursue
  only if the simple version shows promise — if even the simple baseline is −EV, added complexity is
  unjustified (YAGNI).

### Fill model (backtest) + honest caveat
`BacktestBroker` through-trade rule (strict inequality, MAKER-classified, fee=0 on geopolitics) is
conservative (back-of-queue) and produces adverse selection naturally. **Caveat:** with no
historical book this is a **lower bound on fills** (we miss fills we would get in reality). The MM
backtest verdict is therefore a *directional lower bound*; the real validation is **paper trading on
the live book** (Phase 3, ADR 0014).

### Inventory mark-to-market (ADR 0012 prerequisite) — last − haircut
At window end, residual inventory is valued at the **last trade price minus a half-spread liquidation
haircut** (the cost of crossing to flatten). Realistic for an MM that flattens *before* resolution,
and keeps the verdict honest (an MM almost always ends a window holding inventory). Rejected:
resolution-value (0/1) mis-states a strategy that does not hold to resolution; last/mid with no
haircut is mildly optimistic.

### Fee / rebate
Geopolitics: 0 taker / 0 rebate = pure spread. B2 (politics) later adds the maker rebate as a
**separate daily-batch credit** ($1/day gate) in analytics — never in the strategy or per-trade.

### Risk (`risk/` layer)
≤$5/position (paper/early-live); ≤25% bankroll total; 3–5 concurrent markets; inventory cap ±I_max;
**flatten before resolution** (geopolitics resolves via UMA → dispute risk; sell winners ≥$0.95);
kill-switch on drawdown.

### Strategy interface (CLAUDE.md principle 8)
A `Strategy` plugin (`on_event(...) -> list[OrderAction]`, post/cancel) runs unchanged across
`BacktestBroker` / `PaperBroker` / `LiveBroker`. The strategy is pure decision logic; the broker
owns fills. This is what makes the verdict trustworthy.

### Backtest plan
- Data: OrderFilled for **geopolitics** markets (Gamma category filter) since 2026-04-28; real
  fetch — but **first** fix the parser to use `assetId == "0"` (ADR 0012).
- Replay the per-market trade stream → strategy quotes → collect ≥1000 fills (across markets).
- Metrics (with inventory MtM): net PnL, Sharpe, win-rate, max drawdown, inventory stats.
- **Parameter sweep:** `half_spread ∈ {1,2,3,5}¢` × size × `I_max`; report the honest frontier (many
  configs likely −EV). Pick the optimum from data, do not guess.
- Verdict gate: **n_trades ≥ 1000 ∧ net EV > 0 (after fees) ∧ Sharpe > 1.0**. Fail → iterate
  (B2 politics, or v2 inventory-skew) or trash per roadmap triggers.

### Prerequisites folded into the plan as first tasks (ADR 0012)
1. **Inventory mark-to-market** in `analytics/metrics.py` (today `gross_pnl` is realized cash-flow
   only — the single most important analytics gap).
2. **Parser fix** — derive price/size from the USDC leg via `assetId == "0"` + validate on a real
   fetched sample.

*(Claim I8 — OrderFilled maker/taker addresses — is NOT needed for MM, only for C1 copy-trading, so
MM is unblocked.)*
