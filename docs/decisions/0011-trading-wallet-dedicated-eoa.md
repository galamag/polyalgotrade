# ADR 0011 — Trading wallet: a dedicated EOA for the bot (personal account is email-embedded)

- **Date:** 2026-06-07
- **Status:** Accepted (provisional direction) — open investigation for Phase 3
- **Deciders:** user + AI engineer

## Context
The user's personal Polymarket account was created via **Gmail/email**, so it uses an
**embedded (custodial-style) wallet**, not a self-custody MetaMask EOA. The research flagged
that V2 uses deterministic deposit wallets + **ERC-1271 signatures (signature_type 3)** — the
embedded-wallet case. For **programmatic** order signing the bot's SDK needs either a raw EOA
private key or a supported embedded-key/session-signing path. Email-embedded wallets often do
**not** expose a raw exportable key.

## Options considered
1. **Dedicated EOA for the bot** (raw private key in `.env`), funded with only the active
   bankroll; the personal email account stays separate; move funds between them via on-chain
   transfer.
2. **Reuse the personal email-embedded account** for the bot — depends on whether the key is
   exportable or the SDK supports email/session signing.
3. Decide later.

## Decision
**Provisional: Option 1 — a dedicated EOA for the bot.** It matches the security rule (a
dedicated trading wallet, never the personal main account — `docs/operations/security.md`) and
gives the SDK a clean key to sign with. **Open investigation (Phase 3):** confirm whether the
`polymarket-client` SDK can sign for an embedded/email wallet (ERC-1271 / signature_type 3) and
whether the embedded key is exportable — if a clean supported path exists, revisit.

## Rationale
Separating the bot's wallet from the personal account is safer (bounded bankroll, no exposure
of the personal account's key) and avoids the most common V2 onboarding failure
(`signature_type` mismatch → "insufficient balance"). This is a Phase-3 concern; it does **not**
block Phase 1 (data + cost model + backtest) or Phase 2 (backtest MM).

## Consequences
- Before Phase 5 (live), create a dedicated EOA, fund it via Freedom Bank → Binance → on-chain
  transfer (the ~free ramp; ADR-tracked in `claims-verification.md` P2), and validate signing
  with ≤$1 orders through `security-reviewer`.
- The signing path (ERC-1271 vs EOA `signature_type`) must be settled in the `venues/polymarket/`
  adapter; this is the research's known footgun.
- Funds currently on the personal email account can be moved to the bot EOA via crypto transfer
  when needed.
