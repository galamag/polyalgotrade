# ADR 0010 — Resolution is two-tier (Chainlink for short crypto, UMA for the rest)

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** AI engineer (Phase-0 loose-end verification, I5)

## Context
Phase-0's first pass marked I5 `CANNOT_CONFIRM` (docs seemed to describe only UMA). A focused
follow-up found the research was actually right, with nuance: Polymarket runs a **two-tier
oracle** (confirmed by the official Polymarket↔Chainlink partnership announcement + the live
`/crypto/15M` category).

## Decision (facts to build on)
- **Short-dated crypto price markets** (5-min / 15-min / 1-hr / 4-hr) resolve via **Chainlink
  Data Streams + Automation**: on-chain, near-instant, **no UMA propose/dispute window**.
- **All other markets** (politics, geopolitics, sports, culture, …) resolve via the **UMA
  Optimistic Oracle**: propose → 2h challenge → dispute → token-weighted vote.
- The **Chainlink resolver/adapter address is NOT in the official contracts registry** (docs
  list only the UMA adapter `0x6A9D…4F74` and OO `0xCB18…5130`). It must be traced on-chain when
  needed.

## Rationale
The resolution mechanism determines dispute risk and resolution timing — core to strategy and
risk design. The research's "Chainlink auto-settle" was correct for short crypto; our first
verifier under-read the docs. This corrects the record honestly.

## Consequences
- **Dispute-avoidance rule is scoped:** "sell winners ~$0.95+, don't hold to $1.00 (UMA
  token-vote risk)" (`CLAUDE.md` §6) applies to **UMA markets only**. Short-dated crypto markets
  carry **no UMA dispute risk** — holding to resolution there is safe from token-vote games.
- The `risk-manager` must classify a market by resolution type (Chainlink vs UMA) before
  applying dispute rules.
- **Deferred (not Phase 1):** to build an on-chain resolution monitor / sniping feature for short
  crypto, first trace the Chainlink Automation caller of `ConditionResolution` on the
  ConditionalTokens contract (`0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`) for a resolved
  15-min market. Not required for Phase-1 market-making code.
- Still consistent with prior gates: short crypto remains fee category Crypto (0.07; ADR 0009),
  and latency-arb on crypto stays barred below $2K (ADR 0006).
