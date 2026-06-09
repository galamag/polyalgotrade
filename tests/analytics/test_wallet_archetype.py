# tests/analytics/test_wallet_archetype.py
from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_archetype import (
    ARBITRAGEUR,
    DIRECTIONAL_HOLDER,
    DIRECTIONAL_INFORMED,
    LONGSHOT_FARMER,
    MARKET_MAKER,
    RESOLUTION_HOLDER,
    UNCLASSIFIED,
    classify,
)
from pat.analytics.wallet_features import WalletFeatures


def _f(**kw: object) -> WalletFeatures:
    base: dict[str, object] = dict(
        wallet="0xw", n_fills=100, n_tokens=40, maker_fill_ratio=0.5, flip_rate=0.5,
        median_hold_blocks=200, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("1000"),
        pnl_proxy=Decimal("10"), realized_share=0.8, top1_token_pnl_share=0.2,
        positive_token_fraction=0.6, roundtrip_return_median=Decimal("0.0"),
    )
    base.update(kw)
    return WalletFeatures(**base)  # type: ignore[arg-type]


def test_classify_market_maker() -> None:
    f = _f(maker_fill_ratio=0.8, flip_rate=0.9, median_hold_blocks=50,
           entry_price_mean=Decimal("0.5"))
    assert classify(f)[0] == MARKET_MAKER


def test_classify_directional_informed() -> None:
    f = _f(maker_fill_ratio=0.2, flip_rate=0.6, median_hold_blocks=400,
           roundtrip_return_median=Decimal("0.08"))
    assert classify(f)[0] == DIRECTIONAL_INFORMED


def test_classify_longshot_farmer() -> None:
    f = _f(entry_price_mean=Decimal("0.12"), flip_rate=0.1, top1_token_pnl_share=0.7)
    assert classify(f)[0] == LONGSHOT_FARMER


def test_classify_resolution_holder() -> None:
    f = _f(entry_price_mean=Decimal("0.95"), flip_rate=0.1)
    assert classify(f)[0] == RESOLUTION_HOLDER


def test_classify_arbitrageur() -> None:
    f = _f(flip_rate=0.95, median_hold_blocks=0, maker_fill_ratio=0.5)
    assert classify(f)[0] == ARBITRAGEUR


def test_classify_unclassified_when_nothing_fits() -> None:
    f = _f(maker_fill_ratio=0.5, flip_rate=0.3, median_hold_blocks=200,
           entry_price_mean=Decimal("0.5"), top1_token_pnl_share=0.2)
    assert classify(f)[0] == UNCLASSIFIED


def test_classify_directional_holder() -> None:
    # BUY-dominant (buy_fill_fraction=0.9), rarely sells (flip_rate=0.0), mid-range entry.
    f = _f(flip_rate=0.0, buy_fill_fraction=0.9, entry_price_mean=Decimal("0.5"))
    assert classify(f)[0] == DIRECTIONAL_HOLDER


def test_classify_resolution_holder_not_stolen_by_directional_holder() -> None:
    # entry_price_mean=0.95 fails the <0.85 upper bound -> resolution-holder wins first.
    f = _f(flip_rate=0.1, buy_fill_fraction=0.9, entry_price_mean=Decimal("0.95"))
    assert classify(f)[0] == RESOLUTION_HOLDER
