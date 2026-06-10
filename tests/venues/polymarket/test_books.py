"""Tests for books.fetch_books — batching, normalization, split-on-failure. No network."""

from __future__ import annotations

from decimal import Decimal

import httpx

from pat.venues.polymarket.books import fetch_books


def _raw_book(token: str) -> dict:
    return {
        "asset_id": token,
        "bids": [{"price": "0.40", "size": "10"}, {"price": "0.50", "size": "5"}],
        "asks": [{"price": "0.70", "size": "1"}, {"price": "0.60", "size": "2"}],
    }


def _http_error() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://clob.polymarket.com/books")
    return httpx.HTTPStatusError(
        "400", request=req, response=httpx.Response(400, request=req)
    )


def test_batches_normalizes_and_sorts() -> None:
    calls: list[list[str]] = []

    def fake(chunk: list[str]) -> list[dict]:
        calls.append(list(chunk))
        return [_raw_book(t) for t in chunk]

    ids = [f"tok{i}" for i in range(5)]
    out = fetch_books(ids, batch_size=2, get_page=fake)
    assert [len(c) for c in calls] == [2, 2, 1]
    assert set(out) == set(ids)
    book = out["tok0"]
    # bids sorted DESC, asks sorted ASC, Decimal tuples
    assert book["bids"] == [
        (Decimal("0.50"), Decimal("5")), (Decimal("0.40"), Decimal("10"))
    ]
    assert book["asks"] == [
        (Decimal("0.60"), Decimal("2")), (Decimal("0.70"), Decimal("1"))
    ]


def test_failed_batch_splits_and_single_failure_is_skipped() -> None:
    ids = [f"tok{i}" for i in range(6)]
    bad = ids[2]

    def fake(chunk: list[str]) -> list[dict]:
        if bad in chunk:
            raise _http_error()
        return [_raw_book(t) for t in chunk]

    out = fetch_books(ids, batch_size=6, get_page=fake)
    assert bad not in out
    assert len(out) == 5


def test_malformed_book_is_skipped() -> None:
    def fake(chunk: list[str]) -> list[dict]:
        return [{"asset_id": chunk[0]}]  # no bids/asks keys

    out = fetch_books(["tokX"], get_page=fake)
    assert out == {}
