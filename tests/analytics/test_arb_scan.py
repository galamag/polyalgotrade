"""Tests for the FROZEN spec §4 arb math (2026-06-10-a2-arb-scanner-design.md)."""

from __future__ import annotations

from decimal import Decimal

from pat.analytics.arb_scan import (
    MarketRef,
    NegRiskTarget,
    scan_negrisk_event,
)
from pat.core.types import Category


def _ref(cid: str, yes: str, no: str, cat: Category = Category.GEOPOLITICS) -> MarketRef:
    return MarketRef(condition_id=cid, yes_token=yes, no_token=no, category=cat)


def _book(bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> dict:
    return {
        "bids": [(Decimal(p), Decimal(s)) for p, s in bids],
        "asks": [(Decimal(p), Decimal(s)) for p, s in asks],
    }


def _target2() -> NegRiskTarget:
    return NegRiskTarget(
        event_slug="ev-k2",
        markets=[_ref("0xc1", "y1", "n1"), _ref("0xc2", "y2", "n2")],
    )


def test_buy_all_violation_zero_fee() -> None:
    # asks sum to 0.95/share, geopolitics (0 fee), deep books
    books = {
        "y1": _book([], [("0.40", "600")]),
        "y2": _book([], [("0.55", "600")]),
    }
    out = scan_negrisk_event(_target2(), books)
    v = next(x for x in out if x.type == "buy_all")
    # net(s) = s*0.05 - gas(1): best at s=500: 25 - 0.005 = 24.995
    assert v.best_size == Decimal("500")
    assert v.best_net == Decimal("24.995")
    assert v.grid["10"] == Decimal("0.495")
    assert v.key == "ev-k2"
    assert [leg.token_id for leg in v.legs] == ["y1", "y2"]


def test_sell_all_violation_uses_k_plus_1_gas() -> None:
    # bids sum to 1.05/share; K=2 -> gas_cost(3) = 0.015
    books = {
        "y1": _book([("0.60", "600")], []),
        "y2": _book([("0.45", "600")], []),
    }
    out = scan_negrisk_event(_target2(), books)
    v = next(x for x in out if x.type == "sell_all")
    assert v.best_size == Decimal("500")
    assert v.best_net == Decimal("24.985")  # 25 - 0.015


def test_fees_reduce_net_for_fee_category() -> None:
    target = NegRiskTarget(
        event_slug="ev-pol",
        markets=[
            _ref("0xc1", "y1", "n1", Category.POLITICS),
            _ref("0xc2", "y2", "n2", Category.POLITICS),
        ],
    )
    books = {
        "y1": _book([], [("0.30", "100")]),
        "y2": _book([], [("0.65", "100")]),
    }
    out = scan_negrisk_event(target, books)
    v = next(x for x in out if x.type == "buy_all")
    # s=10: gross 0.5; fees 10*0.04*(0.3*0.7) + 10*0.04*(0.65*0.35) = 0.084+0.091=0.175
    assert v.grid["10"] == Decimal("0.5") - Decimal("0.175") - Decimal("0.005")


def test_no_violation_when_sum_at_or_above_one() -> None:
    books = {
        "y1": _book([], [("0.50", "600")]),
        "y2": _book([], [("0.52", "600")]),
    }
    assert scan_negrisk_event(_target2(), books) == []


def test_grid_point_dropped_when_leg_lacks_depth() -> None:
    books = {
        "y1": _book([], [("0.40", "100")]),  # depth only to s=100
        "y2": _book([], [("0.55", "600")]),
    }
    out = scan_negrisk_event(_target2(), books)
    v = next(x for x in out if x.type == "buy_all")
    assert v.grid["500"] is None
    assert v.best_size == Decimal("100")


def test_missing_book_means_no_violation() -> None:
    books = {"y1": _book([], [("0.40", "600")])}  # y2 absent entirely
    assert scan_negrisk_event(_target2(), books) == []


def test_single_market_event_is_skipped() -> None:
    t = NegRiskTarget(event_slug="ev-1", markets=[_ref("0xc1", "y1", "n1")])
    assert scan_negrisk_event(t, {"y1": _book([], [("0.4", "600")])}) == []
