"""Tests for the pre-registered resolution-grounded P&L methodology (spec §4)."""

from __future__ import annotations

from decimal import Decimal

from pat.analytics.resolution_pnl import (
    AMBIGUOUS,
    FRAME_INCOMPLETE,
    RESOLVED,
    UNKNOWN,
    UNRESOLVED,
    ConditionPnl,
    condition_pnls,
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


# ---------------------------------------------------------------------------
# Task 3: condition_pnls
# ---------------------------------------------------------------------------


def _row(
    cond: str,
    asset: str,
    side: str,
    price: str,
    size: str,
    *,
    idx: int = 0,
    ts: int = 100,
    slug: str = "ev-a",
) -> dict:
    return {
        "conditionId": cond,
        "eventSlug": slug,
        "asset": asset,
        "side": side,
        "price": price,
        "size": size,
        "outcomeIndex": idx,
        "timestamp": ts,
    }


_RES = {
    "0xw": {"status": "resolved", "winning_index": 0},
    "0xl": {"status": "resolved", "winning_index": 1},
    "0xu": {"status": "unresolved", "winning_index": None},
}


def _one(rows: list[dict], res: dict | None = None) -> ConditionPnl:
    out = condition_pnls(rows, res if res is not None else _RES)
    assert len(out) == 1
    return out[0]


def test_buy_and_redeem_win() -> None:
    # buy 10 @ 0.4 of outcome 0; outcome 0 wins -> pnl = -4 + 10 = +6
    c = _one([_row("0xw", "tokA", "BUY", "0.4", "10", idx=0)])
    assert c.status == "resolved"
    assert c.pnl == Decimal("6")


def test_buy_and_lose() -> None:
    # buy 10 @ 0.4 of outcome 0; outcome 1 wins -> pnl = -4
    c = _one([_row("0xl", "tokA", "BUY", "0.4", "10", idx=0)])
    assert c.pnl == Decimal("-4")


def test_roundtrip_before_resolution_is_pure_cashflow() -> None:
    # buy 10 @ 0.4, sell 10 @ 0.7 -> net 0 shares, pnl = +3 (no redemption leg)
    c = _one(
        [
            _row("0xw", "tokA", "BUY", "0.4", "10", ts=100),
            _row("0xw", "tokA", "SELL", "0.7", "10", ts=200),
        ]
    )
    assert c.pnl == Decimal("3")


def test_both_outcome_tokens_one_condition() -> None:
    # buy 10 YES (idx0) @ 0.6 and 10 NO (idx1) @ 0.5; idx0 wins:
    # YES: -6 + 10 = +4; NO: -5 + 0 = -5 -> total -1
    c = _one(
        [
            _row("0xw", "tokY", "BUY", "0.6", "10", idx=0),
            _row("0xw", "tokN", "BUY", "0.5", "10", idx=1),
        ]
    )
    assert c.pnl == Decimal("-1")


def test_negative_net_shares_is_frame_incomplete_even_if_resolved() -> None:
    c = _one([_row("0xw", "tokA", "SELL", "0.7", "5")])
    assert c.status == FRAME_INCOMPLETE


def test_unresolved_exposure_at_last_trade_price() -> None:
    # buy 10 @ 0.4 then 2 @ 0.55 -> net 12, last price 0.55 -> exposure 6.6
    c = _one(
        [
            _row("0xu", "tokA", "BUY", "0.4", "10", ts=100),
            _row("0xu", "tokA", "BUY", "0.55", "2", ts=200),
        ]
    )
    assert c.status == "unresolved"
    assert c.unresolved_exposure == Decimal("6.6")
    assert c.pnl == Decimal("0")


def test_condition_missing_from_resolutions_is_unknown() -> None:
    c = _one([_row("0xmissing", "tokA", "BUY", "0.4", "10")], res={})
    assert c.status == UNKNOWN


def test_zero_size_and_missing_fields_rows_are_skipped() -> None:
    rows = [
        _row("0xw", "tokA", "BUY", "0.4", "0"),          # zero size
        {"conditionId": "", "eventSlug": "x", "asset": "t", "side": "BUY",
         "price": "0.4", "size": "1", "outcomeIndex": 0, "timestamp": 1},  # no cond
        _row("0xw", "tokA", "BUY", "0.4", "10"),
    ]
    out = condition_pnls(rows, _RES)
    assert len(out) == 1
    assert out[0].pnl == Decimal("6")


# ---------------------------------------------------------------------------
# Part 0: review hardening (I1, I2, M1)
# ---------------------------------------------------------------------------


def test_row_missing_required_field_is_skipped() -> None:
    rows = [
        {k: v for k, v in _row("0xw", "tokA", "BUY", "0.4", "10").items() if k != "asset"},
        _row("0xw", "tokA", "BUY", "0.4", "10"),
    ]
    out = condition_pnls(rows, _RES)
    assert len(out) == 1
    assert out[0].pnl == Decimal("6")


def test_unrecognized_side_is_skipped() -> None:
    rows = [_row("0xw", "tokA", "HODL", "0.4", "10"), _row("0xw", "tokA", "BUY", "0.4", "10")]
    out = condition_pnls(rows, _RES)
    assert out[0].pnl == Decimal("6")


def test_resolved_record_without_winner_is_unknown() -> None:
    res = {"0xbad": {"status": "resolved", "winning_index": None}}
    c = _one([_row("0xbad", "tokA", "BUY", "0.4", "10")], res=res)
    assert c.status == UNKNOWN
