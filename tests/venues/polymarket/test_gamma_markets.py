"""Tests for gamma.fetch_markets_by_condition_ids — batching + fallback, no network."""

from __future__ import annotations

import httpx

from pat.venues.polymarket.gamma import fetch_markets_by_condition_ids


def _mk(cid: str) -> dict:
    return {"conditionId": cid, "closed": True, "outcomePrices": '["1", "0"]'}


def _http_error() -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://gamma-api.polymarket.com/markets")
    return httpx.HTTPStatusError(
        "400", request=req, response=httpx.Response(400, request=req)
    )


def test_batches_and_collects_all() -> None:
    calls: list[list[str]] = []

    def fake(chunk: list[str]) -> list[dict]:
        calls.append(list(chunk))
        return [_mk(c) for c in chunk]

    ids = [f"0x{i:02d}" for i in range(45)]
    out = fetch_markets_by_condition_ids(ids, batch_size=20, get_page=fake)
    assert [len(c) for c in calls] == [20, 20, 5]
    assert {m["conditionId"] for m in out} == set(ids)


def test_failed_batch_splits_and_single_failure_is_skipped() -> None:
    ids = [f"0x{i:02d}" for i in range(10)]
    bad = ids[3]

    def fake(chunk: list[str]) -> list[dict]:
        if bad in chunk:
            raise _http_error()
        return [_mk(c) for c in chunk]

    out = fetch_markets_by_condition_ids(ids, batch_size=10, get_page=fake)
    got = {m["conditionId"] for m in out}
    assert bad not in got
    assert len(got) == 9


def test_empty_input_no_calls() -> None:
    def fake(chunk: list[str]) -> list[dict]:  # pragma: no cover - must not run
        raise AssertionError("should not be called")

    assert fetch_markets_by_condition_ids([], get_page=fake) == []
