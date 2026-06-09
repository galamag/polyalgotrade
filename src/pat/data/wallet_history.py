"""Per-wallet on-chain history helpers: address->topic encoding and maker-taker merge.

Polymarket V2/V1 OrderFilled index maker at topics[2] and taker at topics[3] (claims I8/I12).
To get a wallet's full activity we run TWO topic-filtered eth_getLogs passes (maker, then taker)
and merge them, deduping by (transactionHash, logIndex). Pure: no network here.
"""

from __future__ import annotations

from typing import Any


def wallet_to_topic(address: str) -> str:
    """Left-pad a 20-byte address to a 32-byte topic (lowercased), as eth_getLogs expects."""
    raw = address.lower().removeprefix("0x")
    return "0x" + raw.rjust(64, "0")


def merge_maker_taker(
    maker_logs: list[dict[str, Any]], taker_logs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union the two passes, deduping by (transactionHash, logIndex)."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in (*maker_logs, *taker_logs):
        key = (str(entry.get("transactionHash")), str(entry.get("logIndex")))
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out
