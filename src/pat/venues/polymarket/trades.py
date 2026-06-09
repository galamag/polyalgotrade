# src/pat/venues/polymarket/trades.py
"""Keyless data-api /trades client for per-wallet trade history (claim I13).

Network isolation: `_trades_get_page` is the ONLY wire-touching function — monkeypatch it in
tests. `fetch_user_trades` paginates with a graceful stop at the ~3000-row API ceiling (HTTP
400). `tag_maker_taker` classifies each trade as maker/taker by diffing the all-trades and
taker-only responses.

/trades endpoint contract (verified 2026-06-09):
  GET https://data-api.polymarket.com/trades
  Params: user (proxyWallet), limit (<=500), offset, takerOnly (bool), side (BUY/SELL).
  Newest-first. No maker/taker field in the response — inferred via takerOnly diff.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import structlog

_DATA_API = "https://data-api.polymarket.com"
_REQUEST_TIMEOUT = 30  # seconds — explicit to satisfy ruff S113

log = structlog.get_logger(__name__)


def _trades_get_page(
    *,
    user: str,
    taker_only: bool,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Fetch ONE page from /trades (keyless). ONLY wire-touching function — monkeypatch in tests."""
    params: dict[str, str | int] = {
        "user": user,
        "takerOnly": "true" if taker_only else "false",
        "limit": limit,
        "offset": offset,
    }
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{_DATA_API}/trades", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def fetch_user_trades(
    user: str,
    *,
    taker_only: bool,
    max_trades: int = 2000,
    page_limit: int = 500,
    get_page: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Paginate /trades for *user*, accumulating until empty page, max_trades, or API ceiling.

    The data-api returns HTTP 400 when the offset exceeds ~3000 rows. We catch
    `httpx.HTTPStatusError` and stop with what we have — this is the documented ceiling, not
    a transient error. `get_page` is the injectable seam (defaults to `_trades_get_page`).
    """
    fetch = get_page or _trades_get_page
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < max_trades:
        limit = min(page_limit, max_trades - len(out))
        try:
            page = fetch(user=user, taker_only=taker_only, limit=limit, offset=offset)
        except httpx.HTTPStatusError as exc:
            log.warning(
                "trades.fetch.ceiling",
                user=user,
                offset=offset,
                status=exc.response.status_code,
                fetched_so_far=len(out),
            )
            break
        if not page:
            break
        out.extend(page)
        offset += page_limit

    result = out[:max_trades]
    log.info("trades.fetched", user=user, taker_only=taker_only, n=len(result))
    return result


def tag_maker_taker(
    all_trades: list[dict[str, Any]],
    taker_trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Annotate each trade in *all_trades* with `is_maker` (bool).

    `all_trades` = takerOnly=false (maker+taker combined).
    `taker_trades` = takerOnly=true (taker-only subset).
    A trade is a maker fill iff its key is present in all_trades but NOT in taker_trades.
    Key = (transactionHash, asset, size, side) — unique enough across fills in a single tx.
    """

    def _key(t: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(t["transactionHash"]),
            str(t["asset"]),
            str(t["size"]),
            str(t["side"]),
        )

    taker_keys: set[tuple[str, str, str, str]] = {_key(t) for t in taker_trades}
    return [{**t, "is_maker": _key(t) not in taker_keys} for t in all_trades]
