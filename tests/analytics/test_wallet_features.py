# tests/analytics/test_wallet_features.py
from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_features import WalletFill, derive_wallet_fills, wallet_fills_from_trades
from pat.core.types import Side

W = "0x" + "11" * 20  # the wallet under analysis
OTHER = "0x" + "22" * 20


def _ev(*, side: int, token: str, maker_amt: int, taker_amt: int,
        maker: str, taker: str, block: int) -> dict:
    """A decoded-event dict shaped like decode_v2_orderfilled output (6-dp amounts)."""
    maker_asset, taker_asset = ("0", token) if side == 0 else (token, "0")
    return {
        "makerAssetId": maker_asset, "takerAssetId": taker_asset,
        "makerAmountFilled": maker_amt, "takerAmountFilled": taker_amt,
        "maker": maker, "taker": taker, "side": side, "tokenId": token,
        "blockNumber": block, "transactionHash": "0xtx",
    }


def test_derive_wallet_buy_as_maker() -> None:
    # side=0 BUY: maker gives USDC 2.5 for shares 5 -> price 0.5; wallet is maker -> BUY.
    ev = _ev(side=0, token="7", maker_amt=2_500_000, taker_amt=5_000_000,
             maker=W, taker=OTHER, block=100)
    fills = derive_wallet_fills([ev], W)
    assert fills == [WalletFill(token_id="7", side=Side.BUY, price=Decimal("0.5"),
                                size=Decimal("5"), block=100, is_maker=True,
                                cashflow=Decimal("-2.5"))]


def test_derive_wallet_buy_as_taker_when_other_is_maker_seller() -> None:
    # side=1 SELL means the MAKER sells; the wallet is taker -> wallet BUYS. shares 5, USDC 2.5.
    ev = _ev(side=1, token="7", maker_amt=5_000_000, taker_amt=2_500_000,
             maker=OTHER, taker=W, block=101)
    fills = derive_wallet_fills([ev], W)
    assert fills[0].side is Side.BUY
    assert fills[0].is_maker is False
    assert fills[0].cashflow == Decimal("-2.5")  # bought -> USDC out


def test_derive_wallet_skips_events_where_wallet_is_neither_leg() -> None:
    ev = _ev(side=0, token="7", maker_amt=1_000_000, taker_amt=2_000_000,
             maker=OTHER, taker="0x" + "33" * 20, block=102)
    assert derive_wallet_fills([ev], W) == []


# ---- Task 4 additions ----
from pat.analytics.wallet_features import (  # noqa: E402
    WalletFeatures,
    compute_wallet_features,
    is_skill_cohort,
)


def _wf(token: str, side: Side, price: str, size: str, block: int) -> WalletFill:
    p, s = Decimal(price), Decimal(size)
    cash = (-p * s) if side is Side.BUY else (p * s)
    return WalletFill(token_id=token, side=side, price=p, size=s, block=block,
                      is_maker=False, cashflow=cash)


def test_features_flip_roundtrip_and_pnl() -> None:
    # Token A: buy 10@0.40 (block 1), sell 10@0.60 (block 51) -> flipped, +2.0 realized.
    fills = [
        _wf("A", Side.BUY, "0.40", "10", 1),
        _wf("A", Side.SELL, "0.60", "10", 51),
    ]
    f = compute_wallet_features("0xw", fills, marks={})
    assert f.n_fills == 2
    assert f.n_tokens == 1
    assert f.flip_rate == 1.0
    assert f.median_hold_blocks == 50
    assert f.roundtrip_return_median == Decimal("0.20")
    assert f.pnl_proxy == Decimal("2.0")          # +6.0 - 4.0, residual 0
    assert f.realized_share == 1.0


def test_features_held_position_marked_at_curprice() -> None:
    # Buy 10@0.30, never sold; mark 0.50 -> residual value 5.0, cost 3.0 -> pnl +2.0.
    fills = [_wf("B", Side.BUY, "0.30", "10", 5)]
    f = compute_wallet_features("0xw", fills, marks={"B": Decimal("0.50")})
    assert f.flip_rate == 0.0
    assert f.entry_price_mean == Decimal("0.30")
    assert f.pnl_proxy == Decimal("2.0")          # -3.0 cashflow + 5.0 residual
    assert f.realized_share == 0.0                # all pnl is unrealized
    assert f.maker_fill_ratio == 0.0


def test_features_top1_token_share_flags_concentration() -> None:
    # Token X: +9 pnl; Token Y: +1 pnl -> top1 share 0.9 (both positive, abs-based same).
    fills = [
        _wf("X", Side.BUY, "0.10", "10", 1), _wf("X", Side.SELL, "1.00", "10", 2),
        _wf("Y", Side.BUY, "0.50", "2", 1), _wf("Y", Side.SELL, "1.00", "2", 2),
    ]
    f = compute_wallet_features("0xw", fills, marks={})
    assert f.n_tokens == 2
    assert f.top1_token_pnl_share == 0.9


# ---- Post-build review corrections (B2, B3, S2) ----

def test_top1_share_abs_based_dominant_loss_flags() -> None:
    # Token A: +9 pnl; Token B: -50 pnl -> abs-based top1 = 50 / (9 + 50) = 50/59.
    # buy 10@0.10, sell 10@1.0 -> +9; buy 100@1.0, sell 100@0.5 -> -50
    fills = [
        _wf("A", Side.BUY, "0.10", "10", 1),
        _wf("A", Side.SELL, "1.00", "10", 2),
        _wf("B", Side.BUY, "1.00", "100", 3),
        _wf("B", Side.SELL, "0.50", "100", 4),
    ]
    f = compute_wallet_features("0xw", fills, marks={})
    assert f.n_tokens == 2
    expected = 50 / 59
    assert abs(f.top1_token_pnl_share - expected) < 1e-9


def test_sliver_sell_not_flipped() -> None:
    # Buy 10, sell 1: min/max = 0.1 < 0.5 -> NOT a flip -> flip_rate 0.0
    fills = [
        _wf("A", Side.BUY, "0.40", "10", 1),
        _wf("A", Side.SELL, "0.60", "1", 50),
    ]
    f = compute_wallet_features("0xw", fills, marks={})
    assert f.flip_rate == 0.0
    assert f.median_hold_blocks == 0


def test_net_negative_wallet_not_skill_cohort() -> None:
    # pnl_proxy < 0 -> is_skill_cohort False regardless of other features.
    f = WalletFeatures(
        wallet="0xw", n_fills=200, n_tokens=50, maker_fill_ratio=0.5, flip_rate=0.5,
        median_hold_blocks=200, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("1000"),
        pnl_proxy=Decimal("-1"),  # net loss
        realized_share=0.8, top1_token_pnl_share=0.2, positive_token_fraction=0.6,
        roundtrip_return_median=Decimal("0.05"),
    )
    assert is_skill_cohort(f) is False


def test_mostly_unrealized_pnl_not_skill_cohort() -> None:
    # realized_share = 0.1 < 0.30 -> is_skill_cohort False (B3 guard).
    f = WalletFeatures(
        wallet="0xw", n_fills=200, n_tokens=50, maker_fill_ratio=0.5, flip_rate=0.5,
        median_hold_blocks=200, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("1000"),
        pnl_proxy=Decimal("10"), realized_share=0.1,  # mostly unrealized
        top1_token_pnl_share=0.2, positive_token_fraction=0.6,
        roundtrip_return_median=Decimal("0.05"),
    )
    assert is_skill_cohort(f) is False


# ---- wallet_fills_from_trades (data-api path) ----

def _api_trade(
    *,
    asset: str,
    side: str,
    price: str,
    size: str,
    timestamp: int,
    is_maker: bool = False,
) -> dict[str, object]:
    return {
        "transactionHash": "0xtx",
        "asset": asset,
        "side": side,
        "price": price,
        "size": size,
        "timestamp": timestamp,
        "is_maker": is_maker,
    }


def test_wallet_fills_from_trades_buy_negative_cashflow() -> None:
    """BUY trade -> negative cashflow; block == timestamp; is_maker passed through."""
    trade = _api_trade(asset="111", side="BUY", price="0.40", size="10", timestamp=1_700_000_100,
                       is_maker=True)
    fills = wallet_fills_from_trades([trade])
    assert len(fills) == 1
    f = fills[0]
    assert f.token_id == "111"
    assert f.side is Side.BUY
    assert f.price == Decimal("0.40")
    assert f.size == Decimal("10")
    assert f.block == 1_700_000_100
    assert f.is_maker is True
    assert f.cashflow == Decimal("-4.0")  # -0.40 * 10


def test_wallet_fills_from_trades_sell_positive_cashflow() -> None:
    """SELL trade -> positive cashflow."""
    trade = _api_trade(asset="222", side="SELL", price="0.60", size="5", timestamp=1_700_000_200)
    fills = wallet_fills_from_trades([trade])
    assert len(fills) == 1
    f = fills[0]
    assert f.side is Side.SELL
    assert f.cashflow == Decimal("3.0")  # +0.60 * 5
    assert f.is_maker is False  # default


def test_wallet_fills_from_trades_skips_zero_size() -> None:
    """Trades with size == 0 must be silently skipped."""
    zero = _api_trade(asset="333", side="BUY", price="0.50", size="0", timestamp=1_700_000_300)
    good = _api_trade(asset="444", side="BUY", price="0.50", size="2", timestamp=1_700_000_400)
    fills = wallet_fills_from_trades([zero, good])
    assert len(fills) == 1
    assert fills[0].token_id == "444"


def test_compute_wallet_features_buy_fill_fraction() -> None:
    """2 BUY fills + 1 SELL fill -> buy_fill_fraction == 2/3 (~0.667)."""
    fills = [
        _wf("A", Side.BUY, "0.40", "10", 1),
        _wf("A", Side.BUY, "0.45", "5", 2),
        _wf("A", Side.SELL, "0.60", "8", 50),
    ]
    f = compute_wallet_features("0xw", fills, marks={})
    assert abs(f.buy_fill_fraction - 2 / 3) < 1e-9


# ---- S5: n_tokens counts markets (conditionId), not assets ----

def test_s5_n_tokens_counts_markets_by_condition_id() -> None:
    trades = [
        {"asset": "tokYES", "side": "BUY", "price": "0.6", "size": "10",
         "timestamp": 100, "is_maker": False, "conditionId": "0xc1"},
        {"asset": "tokNO", "side": "BUY", "price": "0.5", "size": "10",
         "timestamp": 200, "is_maker": False, "conditionId": "0xc1"},
    ]
    fills = wallet_fills_from_trades(trades)
    assert all(f.condition_id == "0xc1" for f in fills)
    f = compute_wallet_features("0xw", fills, {})
    assert f.n_tokens == 1  # one MARKET, even though two assets


def test_s5_flip_rate_denominator_stays_per_token_group() -> None:
    # tokA is flipped (balanced buy+sell), tokB is buy-only; same condition.
    trades = [
        {"asset": "tokA", "side": "BUY", "price": "0.4", "size": "10",
         "timestamp": 100, "is_maker": False, "conditionId": "0xc1"},
        {"asset": "tokA", "side": "SELL", "price": "0.6", "size": "10",
         "timestamp": 200, "is_maker": False, "conditionId": "0xc1"},
        {"asset": "tokB", "side": "BUY", "price": "0.5", "size": "10",
         "timestamp": 300, "is_maker": False, "conditionId": "0xc1"},
    ]
    f = compute_wallet_features("0xw", wallet_fills_from_trades(trades), {})
    assert f.n_tokens == 1          # market breadth (S5)
    assert f.flip_rate == 0.5       # flips / token groups — UNCHANGED denominator


def test_s5_on_chain_fills_without_condition_fall_back_to_token_id() -> None:
    fills = [
        WalletFill(token_id="a", side=Side.BUY, price=Decimal("0.4"), size=Decimal("1"),
                   block=1, is_maker=False, cashflow=Decimal("-0.4")),
        WalletFill(token_id="b", side=Side.BUY, price=Decimal("0.4"), size=Decimal("1"),
                   block=2, is_maker=False, cashflow=Decimal("-0.4")),
    ]
    f = compute_wallet_features("0xw", fills, {})
    assert f.n_tokens == 2
