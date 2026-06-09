"""Control-group sampler: median-activity wallets from existing decoded fills (spec §5, §11).

Survivorship-bias guard -- "ordinary active traders". Deterministic (no RNG): rank distinct
wallets by fill count and take the n closest to the median count. The zero address and a
caller-supplied exclude set (the winners) are dropped.
"""

from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any

_ZERO = "0x" + "00" * 20


def sample_control_wallets(
    events: list[dict[str, Any]], *, n: int = 25, exclude: set[str] | None = None
) -> list[str]:
    """Return n median-activity proxyWallets appearing as maker/taker in *events*."""
    drop = {a.lower() for a in (exclude or set())} | {_ZERO}
    counts: Counter[str] = Counter()
    for ev in events:
        for role in ("maker", "taker"):
            addr = str(ev.get(role, "")).lower()
            if addr and addr not in drop:
                counts[addr] += 1
    if not counts:
        return []
    med = median(counts.values())
    # Sort by closeness to the median fill count (ties -> higher activity first, then address).
    ranked = sorted(counts.items(), key=lambda kv: (abs(kv[1] - med), -kv[1], kv[0]))
    return [addr for addr, _ in ranked[:n]]
