# Fear / Volatility / Sentiment Signals — future data-trading possibilities (survey)

- **Date:** 2026-06-07
- **Status:** Idea capture — **NOT built, NOT a decision.** A menu of *candidate, experimental*
  external signals (the user's framing: **"all of this is an experiment"**) to evaluate later, when
  we reach data-driven / news trading.
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

## OSINT / alternative-data signals (most experimental, lowest signal-to-noise)

### Pentagon Pizza Index
An open-source-intelligence folk-indicator: a spike in late-night **pizza deliveries near the
Pentagon** (and the White House / CIA HQ) is claimed to precede major geopolitical events (staff
working late during a crisis). Modern trackers (e.g. `@PenPizzaReport` on X since Aug 2024;
dashboards like *pizzint.watch*) monitor **Google Maps "Popular Times" live busyness** of pizzerias
within 2–3 miles of those buildings, polling every ~10 min for anomalies. Notable 2026 spikes were
reported (e.g. a claimed ~1,250% surge on 2026-01-05 ahead of a Venezuela operation).

- **Why it's on our list:** it is a **geopolitics** early-warning proxy — directly the domain of our
  first strategy (B1) and of dispute/news plays (D1/D3). Notably, third parties (*Pizzint Watch*)
  **already tie this signal to Polymarket**, so the angle demonstrably exists — though that same
  project ships a meme-coin ($PPW), so treat the surrounding ecosystem with skepticism.
- **API:** **none official.** The underlying data is Google Maps Popular Times / live busyness, which
  Google does **not** expose via the official Places API. Access = (a) unofficial scrapers
  (`populartimes`, `LivePopularTimes`, `gmaps-live-popular-times` — fragile, **ToS gray area**), or
  (b) paid third-parties (Outscraper, SerpApi, BestTime.app).
- **Honest read:** the **noisiest, most novelty** signal here. Heavy false positives (a Nationals
  game lets out, a normal Friday rush), data gaps/lag, correlation≠causation; the Pentagon officially
  dismisses it. **Experiment-only** — at most a low-weight feature in a geopolitics-event regime
  model, never a standalone edge, and only if we can source the busyness data legally and reliably.

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

## API status (quick reference — "do they have an API?")

| Signal | API status |
|---|---|
| **Crypto Fear & Greed** (alternative.me) | ✅ **Free official REST** — `api.alternative.me/fng/?limit=0` |
| **GDELT** | ✅ **Free official** DOC 2.0 API (near-real-time) |
| **CNN Fear & Greed** | ⚠️ No official API; **unofficial JSON endpoint** `production.dataviz.cnn.io/index/fearandgreed/graphdata/{date}` (+ feargreedchart.com / RapidAPI mirrors) |
| **GPR** (geopolitical risk) | ⚠️ No API — **free file download** (xlsx/csv) on the site; monthly |
| **EPU** (policy uncertainty) | ⚠️ No API — **free file download**; daily/monthly |
| **VIX / VVIX / MOVE / SKEW** | ⚠️ No single free API; **delayed** via Yahoo/stooq (unofficial), real-time **licensed** (CBOE/brokers) |
| **Pentagon Pizza Index** | ❌ **No API.** Google Popular-Times data → scrape (ToS gray) or paid 3rd-party (Outscraper / SerpApi / BestTime) |

**Takeaway:** the only **free, official, ready-to-wire** APIs are **Crypto Fear & Greed** and
**GDELT** — and they happen to map to our nearest strategies (B3, B1). Everything else is an
unofficial endpoint, a file download, or a scrape. Pentagon Pizza is both the hardest to source and
the noisiest.

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
- Pentagon pizza theory — https://en.wikipedia.org/wiki/Pentagon_pizza_theory ; tracker dashboards https://www.pizzint.watch/ , https://flowingdata.com/2026/01/23/pentagon-pizza-dashboard-to-track-activities/
- Google Popular Times (no official API) scrapers — https://github.com/m-wrzr/populartimes , https://github.com/GrocerCheck/LivePopularTimes
- CNN F&G unofficial endpoint — https://production.dataviz.cnn.io/index/fearandgreed/graphdata/ (see https://github.com/whit3rabbit/fear-greed-data)
