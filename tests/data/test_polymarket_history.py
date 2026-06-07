import json
from decimal import Decimal
from pathlib import Path

from pat.data.polymarket_history import FILL_SCALE, parse_orderfilled

FIX = Path(__file__).parent / "fixtures"


def test_parse_orderfilled_normalizes_units_and_price() -> None:
    events = json.loads((FIX / "orderfilled_sample.json").read_text())
    fills = parse_orderfilled(events)
    assert len(fills) == len(events)
    f = fills[0]
    assert Decimal("0") <= f.price <= Decimal("1")
    assert f.size > 0 and f.ts > 0


def test_fill_scale_constant() -> None:
    assert FILL_SCALE == Decimal("1000000")


def test_parse_orderfilled_price_event0() -> None:
    """Event 0: maker=5_000_000 shares, taker=2_500_000 USDC → price=0.5"""
    events = json.loads((FIX / "orderfilled_sample.json").read_text())
    fills = parse_orderfilled(events)
    assert fills[0].price == Decimal("0.5")
    assert fills[0].size == Decimal("5")


def test_parse_orderfilled_price_event1() -> None:
    """Event 1: maker=3_000_000 shares, taker=2_100_000 USDC → price=0.7"""
    events = json.loads((FIX / "orderfilled_sample.json").read_text())
    fills = parse_orderfilled(events)
    assert fills[1].price == Decimal("0.7")
    assert fills[1].size == Decimal("3")


def test_parse_orderfilled_fee_converted() -> None:
    """Fee should be scaled by FILL_SCALE: 25_000 / 1_000_000 = 0.025"""
    events = json.loads((FIX / "orderfilled_sample.json").read_text())
    fills = parse_orderfilled(events)
    assert fills[0].fee == Decimal("0.025")


def test_parse_orderfilled_token_id_and_order_id() -> None:
    events = json.loads((FIX / "orderfilled_sample.json").read_text())
    fills = parse_orderfilled(events)
    f = fills[0]
    expected_token = "71321045679252212594626385532706912750332728571942532289631379312455583992616"
    assert f.order_id == "0xabc123def456aaa111222333444555666777888999000aaa111bbb222ccc333dd"
    assert f.token_id == expected_token


def test_parse_orderfilled_mode_and_ts() -> None:
    events = json.loads((FIX / "orderfilled_sample.json").read_text())
    fills = parse_orderfilled(events)
    f = fills[0]
    assert f.mode == "backtest"
    assert f.ts == 1717200000000


def test_parse_orderfilled_empty_list() -> None:
    fills = parse_orderfilled([])
    assert fills == []


def test_price_from_taker_collateral_leg() -> None:
    """takerAssetId=='0' → taker is USDC, maker is shares; price = usdc/shares."""
    events = [{
        "makerAssetId": "999", "takerAssetId": "0",
        "makerAmountFilled": 4_000_000, "takerAmountFilled": 3_600_000,  # 4 shares, 3.6 USDC
        "fee": 0, "timestamp": 1, "transactionHash": "0xaa",
    }]
    f = parse_orderfilled(events)[0]
    assert f.price == Decimal("0.9") and f.size == Decimal("4")


def test_price_from_maker_collateral_leg() -> None:
    """makerAssetId=='0' → maker is USDC, taker is shares."""
    events = [{
        "makerAssetId": "0", "takerAssetId": "888",
        "makerAmountFilled": 950_000, "takerAmountFilled": 1_000_000,  # 0.95 USDC, 1 share
        "fee": 0, "timestamp": 1, "transactionHash": "0xbb",
    }]
    f = parse_orderfilled(events)[0]
    assert f.price == Decimal("0.95") and f.size == Decimal("1")


def test_usdc_leg_is_authoritative_not_magnitude() -> None:
    """Corrupt event: USDC leg (maker, assetId 0) has MORE units than the shares leg.

    Correct: USDC=1.5, shares=1.0 → price 1.5 → pydantic rejects (anomaly surfaced).
    Old heuristic would call the larger (1.5) leg 'shares' → price 0.667, hiding it.
    """
    import pytest
    from pydantic import ValidationError

    events = [{
        "makerAssetId": "0", "takerAssetId": "888",
        "makerAmountFilled": 1_500_000, "takerAmountFilled": 1_000_000,  # 1.5 USDC, 1.0 shares
        "fee": 0, "timestamp": 1, "transactionHash": "0xcc",
    }]
    with pytest.raises(ValidationError):
        parse_orderfilled(events)
