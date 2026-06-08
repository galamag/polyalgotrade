"""Polymarket Gamma / CLOB selection of genuinely 0%-fee geopolitics token ids.

Per claim I9: GET gamma /events?tag_id=100265 -> events[].markets[].clobTokenIds. The
TRUE 0%-fee selector is per-market `feesEnabled == false` (NOT the tag -- some geopolitics
markets carry politics_fees 4%). Optional cross-check: clob /fee-rate?token_id= base_fee==0.

Network isolation: `_gamma_get_events` and `_clob_get_fee_rate` are the only functions
that touch the wire. Monkeypatch them (or pass get_fee_rate=) in tests.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import structlog

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
GEOPOLITICS_TAG_ID = 100265

_REQUEST_TIMEOUT = 30  # seconds -- explicit to satisfy ruff S113

log = structlog.get_logger(__name__)


def _coerce_token_ids(raw: Any) -> list[str]:
    """clobTokenIds is sometimes a real list, sometimes a JSON-encoded string."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [str(t) for t in raw]


def _gamma_get_events(
    tag_id: int = GEOPOLITICS_TAG_ID, *, limit: int = 500, offset: int = 0
) -> list[dict[str, Any]]:
    """Fetch geopolitics events from Gamma. ONLY wire-touching Gamma function."""
    params = {"tag_id": tag_id, "limit": limit, "offset": offset}
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{GAMMA}/events", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def _clob_get_fee_rate(token_id: str) -> int:
    """Return base_fee (bps) for a CLOB token. ONLY wire-touching CLOB function."""
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{CLOB}/fee-rate", params={"token_id": token_id})
        response.raise_for_status()
        body = response.json()
    return int(body.get("base_fee", 0))


def select_geopolitics_tokens(
    events: list[dict[str, Any]],
    *,
    cross_check: bool = False,
    get_fee_rate: Callable[[str], int] | None = None,
) -> set[str]:
    """Return the set of token_ids on markets with feesEnabled == False (the 0%-fee set).

    If cross_check, additionally drop any token whose CLOB base_fee != 0. get_fee_rate
    defaults to the module seam, resolved at CALL time so monkeypatching
    `gamma._clob_get_fee_rate` works.
    """
    tokens: set[str] = set()
    for event in events:
        for market in event.get("markets", []):
            if market.get("feesEnabled") is False:
                tokens.update(_coerce_token_ids(market.get("clobTokenIds", [])))
    if cross_check:
        gr = get_fee_rate or _clob_get_fee_rate
        tokens = {t for t in tokens if gr(t) == 0}
    log.info("gamma.geopolitics_selected", tokens=len(tokens), cross_check=cross_check)
    return tokens
