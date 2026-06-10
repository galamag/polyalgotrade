"""CLOB batch order books (POST /books) — the arb scanner's price source.

Network isolation: `_clob_post_books` is the ONLY wire-touching function; inject
`get_page` in tests. Books are normalized to Decimal (price, size) tuples sorted
best-first: bids DESCENDING, asks ASCENDING (what costs.depth_vwap expects).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import structlog

from pat.venues.polymarket.gamma import CLOB

_REQUEST_TIMEOUT = 30  # seconds

log = structlog.get_logger(__name__)

Book = dict[str, list[tuple[Decimal, Decimal]]]  # {"bids": [...], "asks": [...]}


def _clob_post_books(token_ids: list[str]) -> list[dict[str, Any]]:
    """POST /books for a batch of token ids. ONLY wire-touching function."""
    payload = [{"token_id": t} for t in token_ids]
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.post(f"{CLOB}/books", json=payload)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def _normalize_levels(raw: Any, *, descending: bool) -> list[tuple[Decimal, Decimal]]:
    levels = [
        (Decimal(str(lv["price"])), Decimal(str(lv["size"])))
        for lv in (raw or [])
    ]
    return sorted(levels, key=lambda pv: pv[0], reverse=descending)


def fetch_books(
    token_ids: list[str],
    *,
    batch_size: int = 100,
    get_page: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> dict[str, Book]:
    """Fetch + normalize order books for every token, `batch_size` ids per request.

    A failed batch (HTTPStatusError) splits in half; a single id that still fails is
    skipped with a warning (caller treats the missing book as zero depth). Books
    without both `bids` and `asks` keys are skipped + counted (`books.malformed`).
    Network-level errors propagate (infrastructure failure, not a bad token).
    """
    fetch = get_page or _clob_post_books
    raw_out: list[dict[str, Any]] = []

    def _fetch_chunk(chunk: list[str]) -> None:
        try:
            raw_out.extend(fetch(chunk))
        except httpx.HTTPStatusError as exc:
            if len(chunk) == 1:
                log.warning(
                    "books.fetch_failed", token_id=chunk[0],
                    status=exc.response.status_code,
                )
                return
            mid = len(chunk) // 2
            _fetch_chunk(chunk[:mid])
            _fetch_chunk(chunk[mid:])

    for i in range(0, len(token_ids), batch_size):
        _fetch_chunk(token_ids[i : i + batch_size])

    out: dict[str, Book] = {}
    malformed = 0
    for raw in raw_out:
        token = str(raw.get("asset_id", ""))
        if not token or "bids" not in raw or "asks" not in raw:
            malformed += 1
            continue
        out[token] = {
            "bids": _normalize_levels(raw["bids"], descending=True),
            "asks": _normalize_levels(raw["asks"], descending=False),
        }
    if malformed:
        log.warning("books.malformed", count=malformed)
    log.info("books.fetched", requested=len(token_ids), received=len(out))
    return out
