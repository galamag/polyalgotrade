# tests/analytics/test_wallet_screen.py
from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_features import WalletFeatures, copyability_proxy, is_skill_cohort


def _f(**kw: object) -> WalletFeatures:
    base: dict[str, object] = dict(
        wallet="0xw", n_fills=100, n_tokens=40, maker_fill_ratio=0.5, flip_rate=0.5,
        median_hold_blocks=200, entry_price_mean=Decimal("0.5"), turnover_usdc=Decimal("1000"),
        pnl_proxy=Decimal("10"), realized_share=0.8, top1_token_pnl_share=0.2,
        positive_token_fraction=0.6, roundtrip_return_median=Decimal("0.05"),
    )
    base.update(kw)
    return WalletFeatures(**base)  # type: ignore[arg-type]


def test_skill_cohort_requires_breadth_low_concentration_and_consistency() -> None:
    assert is_skill_cohort(_f(n_tokens=40, top1_token_pnl_share=0.2,
                              positive_token_fraction=0.6)) is True


def test_luck_flagged_when_one_token_dominates() -> None:
    assert is_skill_cohort(_f(top1_token_pnl_share=0.7)) is False


def test_luck_flagged_when_too_few_independent_bets() -> None:
    assert is_skill_cohort(_f(n_tokens=10)) is False


def test_copyability_is_roundtrip_return_when_drift_is_slow() -> None:
    # Positive round-trip with a non-trivial hold gap -> copyable (returns the round-trip edge).
    assert copyability_proxy(_f(roundtrip_return_median=Decimal("0.05"),
                               median_hold_blocks=300)) == Decimal("0.05")


def test_copyability_zero_when_flip_is_instant_arb() -> None:
    # Instant flip (<=2 blocks) -> edge gone before we can follow -> 0.
    assert copyability_proxy(_f(roundtrip_return_median=Decimal("0.05"),
                               median_hold_blocks=1)) == Decimal("0")
