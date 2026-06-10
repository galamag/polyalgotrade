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


_GAMMA_PAGE_SIZE = 100  # Gamma caps /events at ~100 per page regardless of `limit`
_GAMMA_MAX_PAGES = 50  # safety bound (50 * 100 = 5000 events)


def _gamma_get_events(
    tag_id: int = GEOPOLITICS_TAG_ID,
    *,
    closed: bool | None = None,
    limit: int = _GAMMA_PAGE_SIZE,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch one page of geopolitics events from Gamma. ONLY wire-touching Gamma function.

    Pass ``closed=False`` to select LIVE markets — without it Gamma's default page returns
    mostly old, resolved markets whose tokens never appear in a recent on-chain window.
    """
    params: dict[str, Any] = {"tag_id": tag_id, "limit": limit, "offset": offset}
    if closed is not None:
        params["closed"] = "true" if closed else "false"
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{GAMMA}/events", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def _gamma_get_all_events(
    tag_id: int = GEOPOLITICS_TAG_ID,
    *,
    closed: bool | None = None,
    get_page: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Page through Gamma (which caps ~100 events/page) collecting every event for the tag.

    Dedups by event ``id``; stops on an empty page, a short (< page-size) page, or a page
    that adds no new events. ``get_page`` is injectable for tests; bounded by _GAMMA_MAX_PAGES.
    """
    fetch = get_page or _gamma_get_events
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for page in range(_GAMMA_MAX_PAGES):
        events = fetch(
            tag_id, closed=closed, limit=_GAMMA_PAGE_SIZE, offset=page * _GAMMA_PAGE_SIZE
        )
        if not events:
            break
        new = 0
        for ev in events:
            eid = ev.get("id")
            key = eid if eid is not None else id(ev)
            if key in seen:
                continue
            seen.add(key)
            out.append(ev)
            new += 1
        if new == 0 or len(events) < _GAMMA_PAGE_SIZE:
            break
    log.info("gamma.events_fetched", events=len(out), closed=closed)
    return out


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


def _gamma_get_markets(condition_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch /markets for a batch of condition ids. ONLY wire-touching /markets function."""
    params: list[tuple[str, str | int | float | bool | None]] = [
        ("condition_ids", c) for c in condition_ids
    ]
    params.append(("limit", str(len(condition_ids))))
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        response = client.get(f"{GAMMA}/markets", params=params)
        response.raise_for_status()
        body: list[dict[str, Any]] = response.json()
    return body


def fetch_markets_by_condition_ids(
    condition_ids: list[str],
    *,
    batch_size: int = 20,
    get_page: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch Gamma market dicts for every conditionId, `batch_size` ids per request.

    A failed batch (HTTPStatusError) is split in half and retried; a single id that
    still fails is skipped with a warning (the caller records it as unknown).
    Network-level errors (ConnectError, TimeoutException) propagate to the caller —
    they signal infrastructure failure, not a bad condition id, and are not split-retried.
    """
    fetch = get_page or _gamma_get_markets
    out: list[dict[str, Any]] = []

    def _fetch_chunk(chunk: list[str]) -> None:
        try:
            out.extend(fetch(chunk))
        except httpx.HTTPStatusError as exc:
            if len(chunk) == 1:
                log.warning(
                    "gamma.market_fetch_failed",
                    condition_id=chunk[0],
                    status=exc.response.status_code,
                )
                return
            mid = len(chunk) // 2
            _fetch_chunk(chunk[:mid])
            _fetch_chunk(chunk[mid:])

    for i in range(0, len(condition_ids), batch_size):
        _fetch_chunk(condition_ids[i : i + batch_size])
    log.info(
        "gamma.markets_fetched", requested=len(condition_ids), received=len(out)
    )
    return out
