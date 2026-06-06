# Intelligence Layer (DEFERRED — seam only)

Status: **not built.** We design the `src/pat/signals/` seam now and implement the LLM/RAG/CAG
layer only at roadmap **Phase 4** (news). We will revisit this topic together before building.
Decision: ADR [`0003`](../decisions/0003-intelligence-layer-deferred.md).

## Resource reality (binding)
- **Claude Max 5x is not an API key.** It powers dev-time work (you + the subagents), *never*
  the trading path.
- **Runtime LLM = local models on the RTX 4070 Ti Super 16 GB** via Ollama
  (Qwen2.5-14B / Llama-3.1-8B Q4 ≈ 9–10 GB + embeddings). The €5 VPS has no GPU, so
  LLM-dependent strategies run on the desktop or wait for a GPU VPS.

## Deterministic vs LLM — the decision matrix
~90% of the system is deterministic scripts. LLMs are too slow/non-deterministic for the hot
path.

| Component | Solution | Reason |
|---|---|---|
| Market making, quoting, fills | **Script** | Determinism & latency critical |
| Backtest, cost model, risk manager | **Script** | Pure math |
| Cross-market / combinatorial arb (price compare) | **Script** | Math, latency |
| Copy-trading (watch on-chain → replicate) | **Script** | Deterministic replication |
| Latency-arb | **Script** | An LLM would kill the strategy |
| **News → propensity** | Runtime, local LLM | Language classification of news |
| **Resolution-rule comparison** (cross-market divergence) | Batch LLM | Language task over rulebooks |
| **UMA dispute risk score** | Batch LLM | Reads dispute context |
| **Research claims verification** | Dev-time subagents | Reads primary sources |

## RAG vs CAG (when we build it)
- **RAG** — large/changing corpus: history of similar events, fuzzy news→market matching.
  Stack: local embeddings (`nomic-embed-text`/`bge`) + a local vector DB (`LanceDB`/`Qdrant`).
- **CAG** — hot path: the set of *active* markets is bounded (hundreds) and slow to change →
  preload markets + resolution rules into a long-context local model's context, skipping
  retrieval latency. For the news bot, CAG is likely smarter than RAG (speed).

## The seam (`src/pat/signals/`)
A `Signal` is a typed, optional input a strategy may consume:
```python
class Signal(Protocol):
    name: str
    async def evaluate(self, market: Market, context) -> SignalOutput  # score + rationale + latency
```
Deterministic strategies ignore signals entirely. When we build the intelligence layer, a
news/dispute signal implements this protocol and a strategy composes it — no change to the
core. LLM calls (when added) are logged per [logging-observability.md](logging-observability.md).

## Open for later discussion
Exact local models, embedding model, vector store, whether the news pipeline is a single
classifier or a small agentic refute-loop, and the desktop-vs-GPU-VPS hosting choice.
