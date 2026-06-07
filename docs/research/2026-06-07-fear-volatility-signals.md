# Fear / Volatility / Sentiment Signals — future data-trading possibilities (survey)

- **Date:** 2026-06-07
- **Status:** Idea capture — **NOT built, NOT a decision.** A menu of *candidate* external signals to
  evaluate later, when we reach data-driven / news trading.
- **Belongs to:** the `src/pat/signals/` seam (deferred intelligence layer, ADR 0003) and **roadmap
  Phase 4** (cross-market → … → news). Revisit before building.
- **Why recorded now:** the user's thesis — *fear/panic regimes are exactly when prediction markets
  misprice* (overreaction, thin liquidity, wide spreads) → short-lived inefficiencies worth closing.
  We capture the option so it is not lost (CLAUDE.md §6).

## The thesis (why a fear index could help us)
A "fear" spike does two tradeable things to a prediction market:
1. **Spreads widen, liquidity thins** → changes MM economics (B1/B2): more half-spread to capture,
   but more adverse selection and inventory risk. A vol-**regime filter** could gate *when* and *how
   aggressively* to quote (or to step back).
2. **Crowds overreact** → markets overshoot fundamentals → **mean-reversion / fade** and
   **dispute-reversion (D1)** opportunities once the panic clears.

So a fear/vol index is most useful to us as a **regime signal** (when to lean in / out), not as a
standalone edge. *(Correlation with volatility ≠ a fee-beating edge — see caveats.)*

## Candidate signals (survey)

| Signal | Measures | Cadence | Data / API | Cost | Most relevant to |
|---|---|---|---|---|---|
| **VIX** (CBOE) | Implied vol of S&P 500 options, 30-day — the canonical "fear gauge"; spikes on crashes | intraday/daily | CBOE / brokers; real-time often **licensed**, delayed is free | free (delayed) | macro/politics/finance regime; B3 cross-asset |
| **VVIX / MOVE / SKEW** | Vol-of-vol; bond-market (rate) vol; tail-risk ("black swan") | daily | CBOE / ICE | mixed | tail-risk regimes; macro markets |
| **CNN Fear & Greed** | 0–100 composite of 7 stock indicators (momentum, breadth, put/call, junk-bond demand, vol, safe-haven, price strength) | daily | CNN page / MacroMicro (**no official API** → scrape) | free (scrape) | equity/macro sentiment regime |
| **Crypto Fear & Greed (alternative.me)** | 0–100 composite (volatility, momentum/volume, social, dominance, trends) | daily | `GET api.alternative.me/fng/?limit=0` (full history); PyPI wrapper `fear-and-greed-crypto` | **free** | **B3 informed crypto MM**; crypto-binary regime |
| **Geopolitical Risk (GPR) Index** (Caldara & Iacoviello, Fed) | Geopolitical-tension word counts in 10 major newspapers; country variants | **monthly** (daily series may exist on site — ⚠️ verify) | matteoiacoviello.com/gpr.htm; policyuncertainty.com | **free** | **B1 geopolitics MM** regime backdrop |
| **GDELT** (Global Events, Language & Tone) | Real-time global news tone/sentiment; 40+ tone dictionaries; events since 2015 | **near-real-time** | GDELT DOC 2.0 API | **free** | **B1 geopolitics**, **D3 news**; custom conflict/uncertainty signals |
| **Economic Policy Uncertainty (EPU)** | News coverage of economic+policy uncertainty; country–day, 28-day smoothed | daily | policyuncertainty.com | **free** | politics/economics markets |
| **Put/Call ratio** | Options-based fear/greed | daily | CBOE | free (delayed) | macro regime input |

## Mapping to our strategy catalog
- **B1 / B2 — Market making (geopolitics, long-tail politics):** GPR / GDELT geopolitical tone +
  EPU as a **regime gate** — a spike in geopolitical news tone predicts volatility *in exactly the
  markets we quote*. Use it to widen spreads, cut size, or pause quoting during shocks.
- **B3 — Informed cross-venue crypto MM:** **Crypto Fear & Greed (free API)** + VIX as inputs to
  the crypto-binary **fair value & volatility** estimate (complements the Binance/Bybit spot
  signal). Most directly actionable of the lot — free, daily, crypto-native.
- **D1 — UMA dispute reversion:** fear spikes amplify overreaction → larger reversion edges; a
  fear index could **size/time** the fade.
- **D3 — News-event trading (Phase 4):** GDELT is a natural backbone (real-time tone) for the
  intelligence layer; pairs with the local-LLM news→propensity idea.

## Honesty caveats (CLAUDE.md §1, §1.2)
- **Candidate, not edge.** These are signals to *evaluate*, not validated edges. A fear index
  correlating with volatility does **not** imply a tradeable, fee-beating edge. Each must pass its
  own backtest gate (n≥1000, net EV>0, Sharpe>1.0) before it matters.
- **Cadence limits use.** Daily/monthly indices (VIX-daily, CNN F&G, GPR, EPU) are **regime**
  signals only — useless for intra-hour timing. GDELT and exchange vol feeds are the only
  near-real-time options.
- **No look-ahead.** Index publication lag (e.g. GPR ~monthly, EPU 28-day smoothed) must be aligned
  to the *as-of-known* timestamp in any backtest, or the result is fiction.
- **Verify data before building (architecture-critical).** Licensing/cadence/coverage of each
  source (esp. real-time VIX, CNN F&G scraping legality, GPR daily availability) must go through
  `claims-verifier` before any pipeline is written. None of the API facts above are primary-verified
  yet — they are search-derived.
- **Stay deterministic.** If/when adopted, these enter the `signals/` seam as *inputs to
  deterministic rules*, not as a black box.

## Next step (no action now)
Revisit at **Phase 4**. The cheapest, most on-thesis first experiment would be **Crypto Fear &
Greed (free alternative.me API) as a regime input to B3**, and **GDELT geopolitical tone as a B1
regime gate** — both free and aligned with strategies already in our catalog. Until then: parked.

## Sources
- CNN Fear & Greed — https://www.cnn.com/markets/fear-and-greed
- Crypto Fear & Greed (alternative.me) — https://alternative.me/crypto/fear-and-greed-index/ ; API https://alternative.me/crypto/api/
- Geopolitical Risk Index — https://www.matteoiacoviello.com/gpr.htm ; https://www.policyuncertainty.com/gpr.html
- GDELT narrative uncertainty / EPU — https://blog.gdeltproject.org/a-simple-narrative-measure-of-economic-uncertainty-and-economic-policy-uncertainty/
