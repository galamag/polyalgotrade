"""Tests for the pre-registered resolution-grounded P&L methodology (spec §4)."""

from __future__ import annotations

from pat.analytics.resolution_pnl import (
    AMBIGUOUS,
    RESOLVED,
    UNRESOLVED,
    parse_resolution,
)


def test_resolved_strict_binary_winner_index() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc1", "closed": True, "outcomePrices": '["0", "1"]'}
    )
    assert rec == {"conditionId": "0xc1", "status": RESOLVED, "winning_index": 1}


def test_open_market_is_unresolved() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc2", "closed": False, "outcomePrices": '["0.7", "0.3"]'}
    )
    assert rec["status"] == UNRESOLVED
    assert rec["winning_index"] is None


def test_closed_5050_refund_is_ambiguous() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc3", "closed": True, "outcomePrices": '["0.5", "0.5"]'}
    )
    assert rec["status"] == AMBIGUOUS
    assert rec["winning_index"] is None


def test_outcome_prices_as_real_list_also_parses() -> None:
    rec = parse_resolution(
        {"conditionId": "0xc4", "closed": True, "outcomePrices": ["1", "0"]}
    )
    assert rec["status"] == RESOLVED
    assert rec["winning_index"] == 0


def test_closed_without_prices_is_unresolved() -> None:
    rec = parse_resolution({"conditionId": "0xc5", "closed": True})
    assert rec["status"] == UNRESOLVED
