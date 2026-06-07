"""Tests for analytics.metrics — EV/Sharpe verdict gate (CLAUDE.md §6).

TDD: these tests were written before the implementation.

Conservative honesty rule (fee audit H4):
  net_pnl = gross_pnl - fee_drag
  No maker-rebate income is added here; rebates are a daily-batch credit
  with a $1/day gate, modelled separately later.  Phase 1 default: zero rebate.
"""

from decimal import Decimal

from pat.analytics.metrics import Result, Verdict, summarize


def test_net_pnl_is_after_fees() -> None:
    """Net PnL must equal gross PnL minus total fees — no rebate sneaking in."""
    fills = [
        {"side": "buy", "price": "0.40", "size": "10", "fee": "0.02"},
        {"side": "sell", "price": "0.50", "size": "10", "fee": "0.02"},
    ]
    r = summarize(fills)
    # gross = sells(0.50*10=5.00) - buys(0.40*10=4.00) = 1.00
    # net   = 1.00 - 0.04 = 0.96
    assert r.net_pnl == Decimal("0.96") and r.fee_drag == Decimal("0.04")
    assert r.gross_pnl == Decimal("1.00") and r.n_trades == 2


def test_verdict_trashes_low_sharpe() -> None:
    """Sharpe <= 1.0 must produce advance=False with 'sharpe' in reason."""
    v = Verdict.from_metrics(sharpe=0.4, net_pnl=Decimal("5"), n_trades=1200)
    assert v.advance is False and "sharpe" in v.reason.lower()


def test_verdict_requires_min_sample() -> None:
    """n_trades < 1000 must produce advance=False with 'sample' in reason."""
    v = Verdict.from_metrics(sharpe=2.0, net_pnl=Decimal("50"), n_trades=200)
    assert v.advance is False and "sample" in v.reason.lower()


def test_verdict_trashes_negative_ev() -> None:
    """net_pnl <= 0 must produce advance=False with 'ev' or 'negative' in reason."""
    v = Verdict.from_metrics(sharpe=2.0, net_pnl=Decimal("-1"), n_trades=1500)
    assert v.advance is False and ("ev" in v.reason.lower() or "negative" in v.reason.lower())


def test_verdict_advances_when_all_gates_met() -> None:
    """All three gates met: n_trades>=1000, net_pnl>0, sharpe>1.0 -> advance=True."""
    v = Verdict.from_metrics(sharpe=1.5, net_pnl=Decimal("100"), n_trades=1200)
    assert v.advance is True


# ---------------------------------------------------------------------------
# Additional correctness tests
# ---------------------------------------------------------------------------


def test_sharpe_zero_for_single_trade() -> None:
    """Sharpe must be 0.0 when there are fewer than 2 trades (no stdev)."""
    fills = [{"side": "buy", "price": "0.50", "size": "5", "fee": "0.01"}]
    r = summarize(fills)
    assert r.sharpe == 0.0


def test_sharpe_zero_when_all_trades_identical() -> None:
    """Sharpe must be 0.0 when stdev of per-trade contributions is zero."""
    fills = [
        {"side": "buy", "price": "0.50", "size": "1", "fee": "0.00"},
        {"side": "buy", "price": "0.50", "size": "1", "fee": "0.00"},
    ]
    r = summarize(fills)
    assert r.sharpe == 0.0


def test_gross_pnl_pure_buys() -> None:
    """Gross PnL for only buys is negative (capital outflow, no sells to offset)."""
    fills = [{"side": "buy", "price": "0.30", "size": "10", "fee": "0.01"}]
    r = summarize(fills)
    assert r.gross_pnl == Decimal("-3.00")
    assert r.fee_drag == Decimal("0.01")
    assert r.net_pnl == Decimal("-3.01")


def test_gross_pnl_pure_sells() -> None:
    """Gross PnL for only sells is positive (cash inflow)."""
    fills = [{"side": "sell", "price": "0.80", "size": "5", "fee": "0.00"}]
    r = summarize(fills)
    assert r.gross_pnl == Decimal("4.00")
    assert r.net_pnl == Decimal("4.00")


def test_max_drawdown_nonnegative() -> None:
    """max_drawdown must always be >= 0."""
    fills = [
        {"side": "buy", "price": "0.40", "size": "10", "fee": "0.02"},
        {"side": "sell", "price": "0.50", "size": "10", "fee": "0.02"},
    ]
    r = summarize(fills)
    assert r.max_drawdown >= Decimal("0")


def test_result_is_dataclass() -> None:
    """Result must be a dataclass with the expected fields."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(Result)}
    assert "gross_pnl" in fields
    assert "fee_drag" in fields
    assert "net_pnl" in fields
    assert "n_trades" in fields
    assert "sharpe" in fields
    assert "win_rate" in fields
    assert "max_drawdown" in fields


def test_verdict_reason_sample_beats_ev_and_sharpe() -> None:
    """Gate priority: sample < 1000 takes precedence over EV and Sharpe failures."""
    # n_trades=500 fails sample; net_pnl<0 would also fail EV; sharpe<1 would fail sharpe
    v = Verdict.from_metrics(sharpe=0.3, net_pnl=Decimal("-10"), n_trades=500)
    assert v.advance is False
    assert "sample" in v.reason.lower()


def test_verdict_reason_ev_beats_sharpe() -> None:
    """Gate priority: negative EV takes precedence over low Sharpe."""
    # n_trades>=1000 OK; net_pnl<=0 fails EV; sharpe<=1.0 would also fail
    v = Verdict.from_metrics(sharpe=0.8, net_pnl=Decimal("0"), n_trades=1500)
    assert v.advance is False
    assert "ev" in v.reason.lower() or "negative" in v.reason.lower()


def test_verdict_reason_sharpe_last() -> None:
    """When only Sharpe fails, reason mentions 'sharpe'."""
    v = Verdict.from_metrics(sharpe=0.9, net_pnl=Decimal("10"), n_trades=1100)
    assert v.advance is False
    assert "sharpe" in v.reason.lower()


def test_decimal_string_inputs_accepted() -> None:
    """summarize() must accept string values for price, size, fee."""
    fills = [
        {"side": "buy", "price": "0.45", "size": "20", "fee": "0.05"},
        {"side": "sell", "price": "0.55", "size": "20", "fee": "0.05"},
    ]
    r = summarize(fills)
    # gross = 0.55*20 - 0.45*20 = 11.00 - 9.00 = 2.00
    # net   = 2.00 - 0.10 = 1.90
    assert r.gross_pnl == Decimal("2.00")
    assert r.net_pnl == Decimal("1.90")
    assert r.fee_drag == Decimal("0.10")


# ---------------------------------------------------------------------------
# Inventory mark-to-market (ADR 0012)
# ---------------------------------------------------------------------------


def test_long_inventory_marked_at_last_minus_haircut() -> None:
    """Open long valued at net_size*mark - |net_size|*haircut, added to net_pnl."""
    fills = [{"side": "buy", "price": "0.40", "size": "10", "fee": "0.00", "token_id": "t"}]
    r = summarize(fills, marks={"t": Decimal("0.50")}, inventory_haircut=Decimal("0.01"))
    # gross (realized) = -4.00 ; inventory_value = 10*0.50 - 10*0.01 = 4.90
    # net = gross + inventory_value - fee = -4.00 + 4.90 - 0.00 = 0.90
    assert r.inventory_value == Decimal("4.90")
    assert r.net_pnl == Decimal("0.90")


def test_short_inventory_marked() -> None:
    """Open short is a liability: net_size negative; closing costs the haircut too."""
    fills = [{"side": "sell", "price": "0.60", "size": "10", "fee": "0.00", "token_id": "t"}]
    r = summarize(fills, marks={"t": Decimal("0.50")}, inventory_haircut=Decimal("0.01"))
    # gross = +6.00 ; inventory_value = -10*0.50 - 10*0.01 = -5.10 ; net = 6.00 - 5.10 = 0.90
    assert r.inventory_value == Decimal("-5.10")
    assert r.net_pnl == Decimal("0.90")


def test_balanced_inventory_has_zero_value() -> None:
    """A flat book (net 0) contributes no inventory value."""
    fills = [
        {"side": "buy", "price": "0.40", "size": "10", "fee": "0.00", "token_id": "t"},
        {"side": "sell", "price": "0.50", "size": "10", "fee": "0.00", "token_id": "t"},
    ]
    r = summarize(fills, marks={"t": Decimal("0.45")}, inventory_haircut=Decimal("0.01"))
    assert r.inventory_value == Decimal("0")
    assert r.net_pnl == Decimal("1.00")  # realized only


def test_no_marks_is_realized_only_and_backward_compatible() -> None:
    """Without marks, inventory_value is 0 and net_pnl is the legacy realized number."""
    fills = [{"side": "buy", "price": "0.40", "size": "10", "fee": "0.02"}]
    r = summarize(fills)
    assert r.inventory_value == Decimal("0")
    assert r.net_pnl == Decimal("-4.02")


def test_marks_without_token_id_raises() -> None:
    """If marks are supplied, every fill must carry token_id."""
    import pytest

    fills = [{"side": "buy", "price": "0.40", "size": "10", "fee": "0.00"}]
    with pytest.raises(ValueError, match="token_id"):
        summarize(fills, marks={"t": Decimal("0.50")})
