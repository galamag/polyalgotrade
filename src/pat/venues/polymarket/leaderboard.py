# src/pat/venues/polymarket/leaderboard.py
"""Keyless data-api leaderboard client — the SAMPLING FRAME for wallet analysis (claim I11).

GET data-api.polymarket.com/v1/leaderboard returns a `proxyWallet` (0x) per ranked trader.
The `pnl` field's exact definition is undocumented (I11 PARTIAL) -> used as a frame only, never
as verdict input. Network isolation: `_leaderboard_get_page` is the ONLY wire-touching function.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import structlog
from pydantic import BaseModel

DATA_API = "https://data-api.polymarket.com"
_REQUEST_TIMEOUT = 30  # seconds — explicit to satisfy ruff S113
_PAGE_MAX = 50  # data-api caps limit at 50

log = structlog.get_logger(__name__)


class LeaderEntry(BaseModel):
    rank: int
    wallet: str  # proxyWallet, lowercased (== on-chain maker/taker, claim I12)
    user_name: str
    vol: Decimal
    pnl: Decimal


def parse_leaderboard(raw: list[dict[str, Any]]) -> list[LeaderEntry]:
    """Extract LeaderEntry rows; skip rows lacking a proxyWallet. Address lowercased."""
    out: list[LeaderEntry] = []
    for row in raw:
        addr = row.get("proxyWallet")
        if not addr:
            continue
        out.append(
            LeaderEntry(
                rank=int(row.get("rank", 0)),
                wallet=str(addr).lower(),
                user_name=str(row.get("userName", "")),
                vol=Decimal(str(row.get("vol", "0"))),
                pnl=Decimal(str(row.get("pnl", "0"))),
            )
        )
    return out


def _leaderboard_get_page(
    *, time_period: str, order_by: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    """Fetch ONE leaderboard page (keyless). ONLY wire-touching function — monkeypatch in tests."""
    params: dict[str, str | int] = {
        "timePeriod": time_period, "orderBy": order_by,
        "limit": limit, "offset": offset, "category": "OVERALL",
    }
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{DATA_API}/v1/leaderboard", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def fetch_leaderboard(
    *,
    time_period: str = "ALL",
    order_by: str = "PNL",
    top_n: int = 50,
    get_page: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[LeaderEntry]:
    """Return the top-N ranked entries (paging the data-api, max 50/page)."""
    fetch = get_page or _leaderboard_get_page
    out: list[LeaderEntry] = []
    offset = 0
    while len(out) < top_n:
        page = fetch(
            time_period=time_period, order_by=order_by,
            limit=min(_PAGE_MAX, top_n - len(out)), offset=offset,
        )
        if not page:
            break
        out.extend(parse_leaderboard(page))
        offset += _PAGE_MAX
    log.info("leaderboard.fetched", n=len(out[:top_n]), time_period=time_period, order_by=order_by)
    return out[:top_n]
