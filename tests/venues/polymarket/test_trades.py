# tests/venues/polymarket/test_trades.py
"""Tests for src/pat/venues/polymarket/trades.py."""
from __future__ import annotations

import httpx

from pat.venues.polymarket.trades import fetch_user_trades, tag_maker_taker

_USER = "0x" + "ab" * 20


# ---------------------------------------------------------------------------
# fetch_user_trades — pagination
# ---------------------------------------------------------------------------

def _page_of(n: int, start_idx: int = 0) -> list[dict]:
    """Build a fake page of *n* trade dicts with distinct transactionHash values."""
    return [
        {
            "transactionHash": f"0xtx{start_idx + i}",
            "asset": "999",
            "size": "1.0",
            "side": "BUY",
            "price": "0.5",
            "timestamp": 1_700_000_000 + start_idx + i,
        }
        for i in range(n)
    ]


def test_fetch_user_trades_paginates_until_empty() -> None:
    """Three-page sequence: 500, 3, [] -> returns 503 trades."""
    pages = [_page_of(500, 0), _page_of(3, 500), []]
    call_count = 0

    def fake_get_page(*, user: str, taker_only: bool, limit: int, offset: int) -> list[dict]:
        nonlocal call_count
        idx = call_count
        call_count += 1
        return pages[idx] if idx < len(pages) else []

    result = fetch_user_trades(_USER, taker_only=False, max_trades=2000, get_page=fake_get_page)
    assert len(result) == 503


def test_fetch_user_trades_respects_max_trades() -> None:
    """With max_trades=400, stops early after the first page (500) is truncated to 400."""
    pages = [_page_of(500, 0), _page_of(3, 500), []]
    call_count = 0

    def fake_get_page(*, user: str, taker_only: bool, limit: int, offset: int) -> list[dict]:
        nonlocal call_count
        idx = call_count
        call_count += 1
        # Respect the limit parameter — API only returns up to limit rows.
        return pages[idx][:limit] if idx < len(pages) else []

    result = fetch_user_trades(_USER, taker_only=False, max_trades=400, get_page=fake_get_page)
    assert len(result) == 400
    # One page call: limit=400 applied, loop exits because len(out) >= max_trades.
    assert call_count == 1


def test_fetch_user_trades_stops_on_http_status_error() -> None:
    """API ceiling: first page ok; second call raises HTTPStatusError -> returns first page."""
    first_page = _page_of(500, 0)
    call_count = 0

    def fake_get_page(*, user: str, taker_only: bool, limit: int, offset: int) -> list[dict]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return first_page
        # Simulate HTTP 400 at the ~3000-row ceiling.
        dummy_request = httpx.Request("GET", "https://data-api.polymarket.com/trades")
        dummy_response = httpx.Response(400, request=dummy_request)
        raise httpx.HTTPStatusError("400", request=dummy_request, response=dummy_response)

    result = fetch_user_trades(_USER, taker_only=False, max_trades=2000, get_page=fake_get_page)
    assert len(result) == 500  # first page intact
    assert call_count == 2     # attempted second page, caught the error


# ---------------------------------------------------------------------------
# tag_maker_taker
# ---------------------------------------------------------------------------

def _trade(tx: str, asset: str, size: str, side: str) -> dict:
    return {"transactionHash": tx, "asset": asset, "size": size, "side": side, "price": "0.5"}


def test_tag_maker_taker_classifies_correctly() -> None:
    """A in taker -> is_maker False; B, C not in taker -> is_maker True."""
    trade_a = _trade("0xtx1", "111", "10.0", "BUY")
    trade_b = _trade("0xtx2", "222", "5.0",  "SELL")
    trade_c = _trade("0xtx3", "333", "2.0",  "BUY")

    all_trades = [trade_a, trade_b, trade_c]
    taker_trades = [trade_a]  # only A is a taker fill

    tagged = tag_maker_taker(all_trades, taker_trades)

    assert len(tagged) == 3
    by_tx = {t["transactionHash"]: t for t in tagged}
    assert by_tx["0xtx1"]["is_maker"] is False  # A: taker
    assert by_tx["0xtx2"]["is_maker"] is True   # B: maker
    assert by_tx["0xtx3"]["is_maker"] is True   # C: maker


def test_tag_maker_taker_preserves_original_fields() -> None:
    """Tagged dicts must retain all original fields unchanged."""
    trade = _trade("0xtx9", "555", "3.0", "BUY")
    tagged = tag_maker_taker([trade], [])  # no taker trades -> is_maker True
    assert tagged[0]["price"] == "0.5"
    assert tagged[0]["is_maker"] is True


def test_tag_maker_taker_empty_inputs() -> None:
    """Empty all_trades returns empty list; empty taker_trades marks everything maker."""
    assert tag_maker_taker([], []) == []
    trade = _trade("0xtx0", "1", "1.0", "BUY")
    tagged = tag_maker_taker([trade], [])
    assert tagged[0]["is_maker"] is True
