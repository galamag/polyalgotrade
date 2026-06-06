# ADR 0003 — Intelligence layer (LLM/RAG/CAG) deferred to Phase 4

- **Date:** 2026-06-07
- **Status:** Accepted
- **Deciders:** user + AI engineer

## Context
The user asked where a multi-agent / different-LLM system with RAG+CAG fits, vs where a plain
deterministic script suffices. Resources: RTX 4070 Ti Super 16 GB, 64 GB RAM, **no cloud LLM
API** — only a Claude Max 5x subscription (interactive, not an API key).

## Options considered
1. **Design the seam now, build later** — add `src/pat/signals/` interface; implement
   local-LLM + RAG/CAG at Phase 4 (news).
2. **Build the local-LLM infra now** (Ollama + embeddings + vector DB), parallel to the core.
3. **No runtime LLM ever** — deterministic strategies only; drop the news niche.

## Decision
**Option 1.** Document the deterministic-vs-LLM matrix and the RAG/CAG plan; build only the
`signals/` seam now; defer the implementation to Phase 4. Revisit the topic together first.

## Rationale
- The first wave is market making, which is fully deterministic — an LLM there adds latency,
  non-determinism, and failure modes for no benefit.
- Claude Max cannot drive a 24/7 bot; runtime LLM must be local on the desktop GPU, which the
  €5 VPS can't host — another reason to defer until the news phase justifies it.
- ~90% of the system is deterministic; LLMs are genuinely useful only for news→propensity
  (runtime), resolution-rule comparison and dispute scoring (batch), and dev-time claims
  verification (the subagents).

## Consequences
- Positive: focus stays on MM; no premature infra; clean seam keeps the door open.
- Negative/risks: the news strategy is delayed — acceptable per roadmap.
- Follow-ups: revisit local-model/embedding/vector-store choices and desktop-vs-GPU-VPS
  hosting before Phase 4; matrix lives in `docs/architecture/intelligence-layer.md`.
