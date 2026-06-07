# ADR 0007 — Polymarket V2 on-chain facts (addresses, pUSD, order struct)

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** AI engineer (Phase-0 verification) — pending user awareness

## Context
Phase 0 verified the research's Polymarket-V2 claims (C1, C2, C3) against primary sources
(official docs, the `Polymarket/ctf-exchange-v2` repo, Polygonscan). The research was directionally
right but wrong on several specifics that would have caused bugs.

## Decision
Build the Polymarket adapter on these **verified** facts (not the research wording):

- **Exchange addresses (confirmed, active on Polygon):**
  - CTFExchangeV2 `0xE111180000d2663C0091e4f400237545B87B996B`
  - NegRiskCtfExchangeV2 `0xe2222d279d744050d28e00520010520000310F59`
- **Old V1 `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` is NOT disabled** — still live on-chain
  (repo archived 2026-05-11, contract active). Code must target V2 **explicitly**.
- **Deploy date ~2026-03-31 / 04-03**, not 2026-04-28 → "post-V2" data windows start ~late March.
- **Collateral pUSD** ERC-20 (proxy `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`), backed by
  **USDC.e** (bridged), 1:1 via onramp/offramp (`0x93070a847efEf7…5B8ee`). Funding must wrap
  USDC.e→pUSD; pUSD ≠ raw USDC.
- **Order struct (V2, exact):** `salt, maker, signer, tokenId, makerAmount, takerAmount, side,
  signatureType, timestamp, metadata, builder, signature`. **EIP-712 domain version `"2"`.**
  `nonce`/`feeRateBps`/`taker` removed (nonce → hash-based OrderStatus; fee applied at match).

## Rationale
Wrong addresses or a wrong signing struct = rejected orders or lost funds (`CLAUDE.md` §1.2,
§5). The research's order-field list omitted `salt/signer/signatureType`, which are required —
signing on the research wording would have produced invalid signatures.

## Consequences
- The signing path (`venues/polymarket/`) is security-critical → `security-reviewer` gate; test
  with ≤$1 orders.
- Addresses are config constants, sourced from the official contracts page, never hard-typed
  from memory.
- Open follow-up (I5): confirm on-chain whether 15-min crypto markets settle via UMA or Chainlink.
