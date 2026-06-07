# ADR 0014 — Order-book data reality + informed cross-venue crypto MM (idea parked)

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer (Phase-2 brainstorm)

## Context
Two linked findings from the Phase-2 brainstorm, both stemming from one question: *where do we get
order-book data, and what could watching a crypto exchange's book alongside Polymarket give us?*

1. **No historical Polymarket order book (apparent — ⚠️ to-verify).** Polymarket runs an off-chain
   CLOB; the book is visible only in **real time** (WebSocket). No *known* official/free endpoint
   returns a *past* book state. Gamma `prices-history` is a derived mid/last series, not depth. By
   contrast, crypto venues *reportedly* publish historical trade/depth data (Binance
   `data.binance.vision`, Bybit `public.bybit.com`, paid Tardis/Kaiko) — extent **unverified**.
   ⚠️ Exact endpoint behaviour and free-dump coverage are **architecture-critical and not yet
   primary-verified** — route through `claims-verifier` before building the data layer (CLAUDE.md
   §1 principle 2).
2. **A Polymarket crypto binary is a derivative of spot.** Its fair price =
   `P(spot > strike at expiry) = f(spot, time, volatility)`. Spot is discovered fastest on
   Binance/Bybit, so the Polymarket binary reprices with a lag → there is a real lead-lag signal.

## Options considered
**(a) Sourcing the order book for MM backtests:**
1. Try to obtain historical Polymarket book — *not available* (rejected: does not exist).
2. Through-trade proxy on historical trades only — honest but pessimistic lower bound.
3. Build a **`live book recorder`** now + validate MM in **paper** against the live book.

**(b) Using the cross-venue spot signal:**
1. Naive latency-arb (taker: grab stale Polymarket quotes) — fee-dominated, dead.
2. **Informed market making** (maker: post quotes around a Binance-derived fair value, skew to
   avoid being picked off) — no sub-100ms race needed.
3. Ignore the cross-venue signal entirely.

## Decision
- **(a)** Use **option 2 + 3 together**: the through-trade proxy is the *backtest* lower bound now;
  the **real MM validation is paper trading against the live book**; and we will build a
  **`live book recorder`** (WS book → disk) early so paper has data and we accumulate a Polymarket
  book dataset for future "from-now-forward" backtests.
- **(b)** **Park option 2** (informed cross-venue crypto MM) as catalog item **B3** — recorded, not
  built. The naive taker latency-arb (option 1) stays as catalog item **D2** ("verify-then-likely-
  bury"), per CLAUDE.md "don't bury the dead — verify."

## Rationale
- Chasing a non-existent historical Polymarket book is wasted effort; recording it live is the
  correct, durable investment (serves paper + future backtests). Matches CLAUDE.md §0 gating
  (backtest is a lower bound; paper is the real proof).
- Naive crypto latency-arb is fee-dominated: the dynamic crypto taker fee is **1.75% at p=0.5**
  (exact, ADR 0009) vs a typical 1–2% edge, against HFT (per second-hand research, Wintermute
  *reportedly* began two-sided liquidity ~2026-05-29 — *unverified*). The **maker reframe** (informed
  MM) is the part worth keeping — it needs no latency race, only adverse-selection avoidance.
- Crypto markets on Polymarket are the most HFT-competitive (thinnest MM edge), so B3 is an
  *advanced* item, not the first MM target. Geopolitics/long-tail politics come first (ADR 0013).

## Consequences
- Positive: the most consequential idea ("watch both books → informed MM") is preserved; the data
  strategy is explicit; no time wasted on unavailable history.
- Negative / risks: the `live book recorder` is new data-layer work (effort + storage); B3's edge
  is uncertain and faces the strongest competition; backtest fidelity for all MM is capped by the
  proxy until the recorder accrues data.
- Follow-ups: (1) `claims-verifier` to confirm Polymarket has no historical book endpoint and to
  map Binance/Bybit free-dump coverage before the data layer is built; (2) schedule the
  `live book recorder` in the data-layer plan; (3) B3 and D2 carry their own future
  `docs/strategies/<name>.md` verdicts; (4) verify the V2 `OrderFilled` ABI carries maker/taker
  addresses (`claims-verifier`, claim I8 — PENDING), then extend the parser to capture them (also
  enables C1 copy-trading). Full detail: spec
  `docs/superpowers/specs/2026-06-07-phase2-strategy-catalog-design.md` (Section 3).
