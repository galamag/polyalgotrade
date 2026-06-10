"""Tests for gamma.fetch_active_events — no-tag pagination, no network."""

from __future__ import annotations

from pat.venues.polymarket.gamma import _GAMMA_PAGE_SIZE, fetch_active_events

_N = _GAMMA_PAGE_SIZE  # alias so pages are exactly "full" size


def test_paginates_and_dedups() -> None:
    # Two full pages + one overlapping id + one empty page to stop.
    page0 = [{"id": i, "slug": f"s{i}"} for i in range(_N)]          # ids 0.._N-1
    page1 = [{"id": i, "slug": f"s{i}"} for i in range(_N - 1, 2 * _N - 1)]  # overlap on _N-1
    pages = [page0, page1, []]
    calls: list[dict] = []

    def fake(*, closed: bool | None, limit: int, offset: int) -> list[dict]:
        calls.append({"closed": closed, "limit": limit, "offset": offset})
        idx = offset // limit
        return pages[idx] if idx < len(pages) else []

    out = fetch_active_events(get_page=fake)
    expected_ids = list(range(2 * _N - 1))  # 0..(2N-2), deduped
    assert [e["id"] for e in out] == expected_ids
    assert all(c["closed"] is False for c in calls)
    assert calls[0]["offset"] == 0


def test_stops_on_short_page() -> None:
    def fake(*, closed: bool | None, limit: int, offset: int) -> list[dict]:
        assert offset == 0
        return [{"id": 1}]  # short page -> stop

    out = fetch_active_events(get_page=fake)
    assert len(out) == 1
