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
