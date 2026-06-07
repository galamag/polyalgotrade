# Phase 0 Verdict — Claims Verification

- **Date:** 2026-06-07
- **Method:** 6 parallel `claims-verifier` subagents → official docs / GitHub / PyPI /
  Polygonscan. Full detail + sources: [`claims-verification.md`](claims-verification.md).

## Gate result: ✅ PASS — Phase 1 unblocked
No Critical claim (C1–C9) remains `PENDING`. The core architecture **holds**: V2 exists with
real, active addresses; the fee regime is real and documented; Kazakhstan is open on both
venues; a maintained SDK and a working historical-data pipeline exist. **But** verification
caught several specifics that would have caused bugs — exactly the point of Phase 0.

## Critical claims

| # | Claim | Verdict | What changed |
|---|---|---|---|
| C1 | V2 addresses / launch / V1 disabled | PARTIAL | Addresses ✅; launch ~Mar 31 (not Apr 28); **V1 still live** — target V2 explicitly |
| C2 | pUSD collateral | PARTIAL | ✅ real; backed by **USDC.e**; model USDC.e→pUSD onramp |
| C3 | Order struct / EIP-712 v2 | PARTIAL | ✅ ver "2" + exact struct; research field list was **incomplete** (salt/signer/signatureType) |
| C4 | SDK `py-clob-client-v2` | PARTIAL | **Use `polymarket-client` (py-sdk)** instead — research was a generation stale |
| C5 | Crypto taker fee | PARTIAL | ✅ formula; peak **1.75%** (not 1.56–1.80%); full category table obtained |
| C6 | Geopolitics 0% | ✅ VERIFIED | True; **but rebate pool also 0** → geopolitics MM = pure spread |
| C7 | Maker rebates | ✅ VERIFIED | 25%/20%, daily pUSD, $1 min; daily-batch credit (gate matters on small bankroll) |
| C8 | Kalshi fee | PARTIAL | **CEIL** rounding (not round); **maker fee 0.0175** (not $0) |
| C9 | KZ venue access | ✅ VERIFIED | KZ absent from both block lists; **mutable — recheck before Phase 5** |

## What this means for Phase 1
1. **Cost model** (`src/pat/costs/`) encodes the verified Polymarket category table + Kalshi
   **ceil + maker-fee** corrections (ADR 0009). Unit-test the boundary prices and the
   geopolitics zero-rate path.
2. **SDK dependency** = `polymarket-client` (ADR 0008), isolated behind the venue adapter.
3. **Contract constants** = the verified V2 addresses + pUSD onramp (ADR 0007); signing uses the
   exact order struct + domain version "2" (security-critical).
4. **Data pipeline** follows `warproxxx/poly_data` (V2 `OrderFilled` + Gamma keyset); budget a
   paid RPC; "post-V2" window starts ~late March 2026.
5. **Endpoints** config includes `/ws/user` + `data-api.polymarket.com`; rate limiter honors
   burst + sustained tiers.

## Strategy-relevant nuance (for the quant-researcher)
- **Geopolitics MM earns pure spread** (zero taker fee *and* zero rebate). The "0% fee + 25%
  rebate" mental model from the research is wrong for geopolitics — rebates need a non-zero
  taker pool, which geopolitics doesn't have. Re-examine the Phase-2 MM edge thesis with this.

## Open items (do NOT block Phase 1, but track)
- **I5 (CANNOT_CONFIRM) ⚠️** — crypto-market settlement: docs show **only UMA** (2h challenge),
  not Chainlink auto-settle. **Phase-1 on-chain task:** find the `reportPayouts()` caller for a
  resolved 15-min crypto market. **Do not build sniping/timing logic on the Chainlink claim.**
- **I6 (PENDING)** — Polymarket KYC threshold for KZ onboarding: verify before paper→live.
- **L1 (PENDING)** — VPS→CLOB latency: measure from a real VPS (deferred to VPS setup).
- **P1/P2 (PENDING)** — KZ tax rate + off-ramp route: confirm before funding (Phase 5).

## Decisions written
ADR 0007 (V2 on-chain facts), 0008 (SDK = polymarket-client), 0009 (fee-model corrections).
