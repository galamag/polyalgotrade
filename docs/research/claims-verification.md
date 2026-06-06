# Claims Verification (Phase 0 worklist)

The source research (`2026-06-07-original-research.md`) is **second-hand**: specific but
unverified addresses, SDK names, fee formulas, dates. We build on a claim only after a
**primary source** confirms it. This is the binding rule from `CLAUDE.md` §1.2.

**Status legend:** `PENDING` (not checked) · `VERIFIED` (primary source confirms) ·
`REFUTED` (primary source contradicts) · `STALE` (was true, may have changed — recheck) ·
`PARTIAL` (some sub-claims confirmed).

**Primary sources** = official docs (`docs.polymarket.com`, Kalshi API docs), the actual
GitHub repos, on-chain data (Polygonscan), or direct API responses. NOT blog posts / X / VPS
vendors.

> ⚠️ Several research figures come from VPS-vendor blogs (TradoxVPS/QuantVPS) with a
> commercial motive — treat latency numbers as **low-trust** until measured ourselves.

---

## Critical (block Phase 1 code) — must be VERIFIED/REFUTED before the gate

| # | Claim | Why it matters | Primary source to check | Status |
|---|---|---|---|---|
| C1 | CTF Exchange V2 live since 2026-04-28; exchange `0xE111180000d2663C0091e4f400237545B87B996B`, Neg-Risk `0xe2222d279d744050d28e00520010520000310F59`; old exchange disabled | Wrong address = orders fail / funds at risk | Polygonscan + Polymarket docs | PENDING |
| C2 | Collateral is **pUSD** (ERC-20, 1:1 USDC) on Polygon | Funding/settlement path | Polymarket docs + token contract | PENDING |
| C3 | Order struct dropped `nonce/feeRateBps/taker`, added `timestamp/metadata/builder`; EIP-712 domain version `"2"` | Signing/serialization correctness | `Polymarket/ctf-exchange-v2` repo + SDK | PENDING |
| C4 | Required SDK is **`py-clob-client-v2` (v1.0.1+)**; old client broken on prod | Foundation dependency choice | PyPI + `Polymarket/py-clob-client-v2` repo | PENDING |
| C5 | Polymarket **dynamic taker fee** `C × 0.07 × p × (1−p)` on crypto; peak ~1.56–1.80% at p=0.50 | Cost model = the whole game on small capital | Polymarket fee docs / live API `getClobMarketInfo` | PENDING |
| C6 | **Geopolitics taker fee = 0%** (permanent) | The primary MM edge for Phase 2 | Polymarket fee docs / live API per market | PENDING |
| C7 | **Maker rebates** 25% of taker pool (20% crypto), daily in pUSD, min $1 | Secondary MM edge | Polymarket maker-rewards docs | PENDING |
| C8 | Kalshi fee `round(0.07 × price × (1−price), 2)`/contract; maker $0 by rounding | Kalshi-side cost model | Kalshi fee schedule (official) | PENDING |
| C9 | **KZ not blocked** on Polymarket (33-country list) or Kalshi (~52 restricted) **today** | Whether we can use the venues at all | Polymarket ToS/geo page + Kalshi restricted list | PENDING |

## Important (needed during Phase 1–3, not blocking the foundation)

| # | Claim | Why it matters | Source | Status |
|---|---|---|---|---|
| I1 | CLOB endpoints: `clob.polymarket.com`, `wss://ws-subscriptions-clob...`, `wss://ws-live-data...`, `gamma-api.polymarket.com` | Data + execution wiring | Polymarket docs | PENDING |
| I2 | Rate limits: POST/DELETE `/order` 120k/10min; `/orders` batch 2000/10s | Throttle design | Polymarket docs | PENDING |
| I3 | `warproxxx/poly_data` reads `OrderFilled` from the V2 contract via Polygon RPC + Gamma | Our historical-data pipeline basis | The repo | PENDING |
| I4 | Kalshi `demo-api.kalshi.com` is a full fake-money sandbox | Paper-trading the Kalshi side | Kalshi docs | PENDING |
| I5 | 15-min/1-hr crypto markets auto-settle via Chainlink Data Streams | Resolution timing / sniping dead | Polymarket docs | PENDING |
| I6 | Polymarket KYC optional for retail (≤7-figure) | Onboarding from KZ | Polymarket docs / ToS | PENDING |
| I7 | Polygon base fee ≥25 gwei; typical tx ≈ $0.0024 | Gas is negligible, not a bottleneck | Polygonscan gas tracker | PENDING |

## Low-trust / measure-ourselves

| # | Claim | Note | Status |
|---|---|---|---|
| L1 | Latency: Dublin <5 ms, Amsterdam ~10 ms, Helsinki ~25–30 ms to CLOB | VPS-vendor source — **measure with `ping`/`mtr`** before trusting | PENDING |
| L2 | Stats: 0.51% wallets profited >$1k; 14/20 top wallets are bots; spreads 4.5%→1.2%; arb window 2.7 s | Directional, not actionable; don't build on exact numbers | PENDING |
| L3 | "$313 → $437K" (0x8dxd) and other bot P&L figures | Survivorship bias; informative only | PENDING |

## Compliance / personal

| # | Claim | Note | Status |
|---|---|---|---|
| P1 | KZ crypto-trading income taxable at 10% IIT (2024 rules) | Keep fill records; confirm current rate | PENDING |
| P2 | Off-ramp: USDC → Binance → P2P KZT (~1–2% loss) | Confirm a working route before Phase 5 | PENDING |

---

### How to update this file
When you verify a claim: change Status, add the source URL + date checked, and if it
materially affects the design, **write an ADR** in `docs/decisions/`.
