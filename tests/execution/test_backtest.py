"""Tests for BacktestBroker — TDD (write first, implement second).

Conservative fill rule: a resting order fills ONLY when the replayed trade
stream actually trades *through* its price.  Fees route through pat.costs.
"""

from decimal import Decimal

import pytest

from pat.core.types import Category, Market, Order, Side, Venue
from pat.execution.backtest import BacktestBroker


def _mkt(cat: Category) -> Market:
    return Market(id="m", venue=Venue.POLYMARKET, question="q", category=cat)


# ---------------------------------------------------------------------------
# Core through-trade fill rule
# ---------------------------------------------------------------------------


def test_resting_buy_fills_only_when_price_trades_through() -> None:
    """A resting BUY at 0.40 must NOT fill on a trade at 0.41 (above our bid).
    It MUST fill when a trade at 0.39 happens (through our bid).
    Fill is classified MAKER because we were resting.
    """
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="quote",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.41"), size=Decimal("50"))  # above our bid -> NO fill
    assert b.fills == []
    b.on_trade(price=Decimal("0.39"), size=Decimal("50"))  # trades through -> fill as MAKER
    assert len(b.fills) == 1
    assert b.fills[0].liquidity.value == "maker"


def test_resting_sell_fills_when_trade_at_or_above_ask() -> None:
    """A resting SELL at 0.60 must NOT fill on a trade at 0.59 (below our ask).
    It MUST fill when a trade at 0.61 happens (through our ask).
    """
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.SELL,
        price=Decimal("0.60"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.59"), size=Decimal("50"))  # below our ask -> NO fill
    assert b.fills == []
    b.on_trade(price=Decimal("0.61"), size=Decimal("50"))  # through -> fill
    assert len(b.fills) == 1


def test_resting_buy_at_exact_price_does_not_fill() -> None:
    """Trade at exactly the resting price does NOT trade through — no fill.

    The through-trade rule requires strict inequality: trade_price < order.price
    for BUY, trade_price > order.price for SELL.  This is the conservative
    interpretation: equality means we're at the front of the queue, but we
    model back-of-queue, so no fill.
    """
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.40"), size=Decimal("50"))  # at our price -> back-of-queue, NO fill
    assert b.fills == []


def test_resting_sell_at_exact_price_does_not_fill() -> None:
    """Trade at exactly the resting SELL price does NOT trade through — no fill."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.SELL,
        price=Decimal("0.60"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.60"), size=Decimal("50"))  # at our price -> back-of-queue, NO fill
    assert b.fills == []


# ---------------------------------------------------------------------------
# Fee routing
# ---------------------------------------------------------------------------


def test_fill_fee_routes_through_cost_model_geopolitics_zero() -> None:
    """Maker fee for GEOPOLITICS is always 0 — enforced via polymarket_maker_fee."""
    b = BacktestBroker(market=_mkt(Category.GEOPOLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.50"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.49"), size=Decimal("100"))
    assert b.fills[0].fee == Decimal("0")


def test_fill_fee_is_zero_for_maker_regardless_of_category() -> None:
    """polymarket_maker_fee always returns 0 — makers are never charged on Polymarket."""
    b = BacktestBroker(market=_mkt(Category.CRYPTO))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.50"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.49"), size=Decimal("100"))
    assert b.fills[0].fee == Decimal("0")


# ---------------------------------------------------------------------------
# Partial fills and trade-size sharing
# ---------------------------------------------------------------------------


def test_partial_fill_limited_by_trade_size() -> None:
    """A single trade of size 3 can only partially fill an order of size 10.
    The second trade fills the rest.
    """
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.39"), size=Decimal("3"))  # only 3 available
    assert b.fills[0].size == Decimal("3")
    b.on_trade(price=Decimal("0.39"), size=Decimal("100"))  # rest fills
    assert sum(f.size for f in b.fills) == Decimal("10")


def test_single_trade_shared_across_multiple_orders() -> None:
    """A large trade's size is shared across eligible resting orders in insertion order.

    Order A: BUY 5 @ 0.40, Order B: BUY 8 @ 0.35.
    Trade: price=0.30, size=6.
    Both orders are eligible (0.30 < 0.40 and 0.30 < 0.35).
    A was submitted first, so A fills 5 (exhausted), B fills 1 (6 - 5).
    """
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    a = Order(
        client_id="A",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("5"),
        reason="q",
        mode="backtest",
    )
    bk = Order(
        client_id="B",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.35"),
        size=Decimal("8"),
        reason="q",
        mode="backtest",
    )
    b.submit(a)
    b.submit(bk)
    b.on_trade(price=Decimal("0.30"), size=Decimal("6"))
    fills_by_order = {f.order_id: f.size for f in b.fills}
    assert fills_by_order["A"] == Decimal("5")
    assert fills_by_order["B"] == Decimal("1")


def test_fully_filled_order_removed_from_book() -> None:
    """Once an order is fully filled it should not fill again on subsequent trades."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("5"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.39"), size=Decimal("100"))  # fills completely
    assert sum(f.size for f in b.fills) == Decimal("5")
    count_after_first = len(b.fills)
    b.on_trade(price=Decimal("0.39"), size=Decimal("100"))  # no resting order left
    assert len(b.fills) == count_after_first  # no new fills


# ---------------------------------------------------------------------------
# Fill metadata
# ---------------------------------------------------------------------------


def test_fill_price_is_resting_order_price_not_trade_price() -> None:
    """Fill price must be the resting order's limit price, not the through-trade price.
    This is standard limit-order semantics — we get our quoted price.
    """
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.35"), size=Decimal("50"))  # well below our bid
    assert b.fills[0].price == Decimal("0.40")


def test_fill_order_id_matches_client_id() -> None:
    """fill.order_id must equal the originating order's client_id."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="my-order-id",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.39"), size=Decimal("50"))
    assert b.fills[0].order_id == "my-order-id"


def test_fill_mode_is_backtest() -> None:
    """Fill mode must be 'backtest'."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.39"), size=Decimal("50"))
    assert b.fills[0].mode == "backtest"


def test_ts_is_monotonically_increasing() -> None:
    """Each fill must carry a strictly increasing ts counter."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    for i in range(3):
        o = Order(
            client_id=str(i),
            token_id="t",
            side=Side.BUY,
            price=Decimal("0.40"),
            size=Decimal("1"),
            reason="q",
            mode="backtest",
        )
        b.submit(o)
        b.on_trade(price=Decimal("0.39"), size=Decimal("1"))
    ts_values = [f.ts for f in b.fills]
    assert ts_values == sorted(ts_values)
    assert len(set(ts_values)) == len(ts_values)  # strictly increasing (no duplicates)


# ---------------------------------------------------------------------------
# positions()
# ---------------------------------------------------------------------------


def test_positions_net_buy_minus_sell() -> None:
    """positions() must aggregate net size per token_id (BUY positive, SELL negative)."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    buy = Order(
        client_id="b1",
        token_id="tok",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="q",
        mode="backtest",
    )
    sell = Order(
        client_id="s1",
        token_id="tok",
        side=Side.SELL,
        price=Decimal("0.60"),
        size=Decimal("3"),
        reason="q",
        mode="backtest",
    )
    b.submit(buy)
    b.on_trade(price=Decimal("0.39"), size=Decimal("100"))  # buy fills: 10 shares
    b.submit(sell)
    b.on_trade(price=Decimal("0.61"), size=Decimal("100"))  # sell fills: 3 shares
    positions = b.positions()
    assert len(positions) == 1
    assert positions[0].token_id == "tok"
    assert positions[0].net_size == Decimal("7")  # 10 - 3


def test_positions_empty_before_any_fills() -> None:
    """positions() returns an empty list when nothing has been filled yet."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    assert b.positions() == []


# ---------------------------------------------------------------------------
# Journal integration (optional TradeJournal)
# ---------------------------------------------------------------------------


def test_journal_records_order_and_fill(tmp_path: pytest.fixture) -> None:  # type: ignore[valid-type]
    """When a journal is supplied, submit and fill both write JSONL records."""
    import json
    from pathlib import Path

    from pat.logging import TradeJournal

    journal = TradeJournal(
        path=Path(tmp_path) / "journal.jsonl",
        mode="backtest",
        corr_id="test-corr",
    )
    b = BacktestBroker(market=_mkt(Category.POLITICS), journal=journal)
    o = Order(
        client_id="1",
        token_id="t",
        side=Side.BUY,
        price=Decimal("0.40"),
        size=Decimal("10"),
        reason="quote",
        mode="backtest",
    )
    b.submit(o)
    b.on_trade(price=Decimal("0.39"), size=Decimal("50"))

    lines = [
        json.loads(ln)
        for ln in (Path(tmp_path) / "journal.jsonl").read_text().splitlines()
        if ln.strip()
    ]
    events = [ln["event"] for ln in lines]
    assert "order" in events
    assert "fill" in events


def test_cancel_removes_resting_order() -> None:
    """A cancelled order does not fill on a subsequent through-trade."""
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(client_id="x", token_id="t", side=Side.BUY, price=Decimal("0.40"),
              size=Decimal("10"), reason="q", mode="backtest")
    b.submit(o)
    b.cancel("x")
    b.on_trade(price=Decimal("0.30"), size=Decimal("50"))
    assert b.fills == []


def test_cancel_unknown_id_is_noop() -> None:
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    b.cancel("nope")  # must not raise


def test_on_trade_returns_new_fills() -> None:
    b = BacktestBroker(market=_mkt(Category.GEOPOLITICS))
    o = Order(client_id="x", token_id="t", side=Side.BUY, price=Decimal("0.40"),
              size=Decimal("10"), reason="q", mode="backtest")
    b.submit(o)
    produced = b.on_trade(price=Decimal("0.39"), size=Decimal("50"))
    assert len(produced) == 1 and produced[0].order_id == "x"


def test_on_trade_returns_empty_when_no_fill() -> None:
    b = BacktestBroker(market=_mkt(Category.POLITICS))
    o = Order(client_id="x", token_id="t", side=Side.BUY, price=Decimal("0.40"),
              size=Decimal("10"), reason="q", mode="backtest")
    b.submit(o)
    assert b.on_trade(price=Decimal("0.41"), size=Decimal("50")) == []
