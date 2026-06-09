# src/pat/analytics/wallet_archetype.py
"""First-pass deterministic archetype labeler (spec §8). Thresholds are initial; the report
prints raw feature distributions so they can be sanity-checked, not blindly trusted.

Order matters: arbitrageur (instant flip) is checked before market-maker; resolution-holder /
longshot-farmer (price extremes) before the mid-price MM band.
"""

from __future__ import annotations

from decimal import Decimal

from pat.analytics.wallet_features import WalletFeatures

ARBITRAGEUR = "arbitrageur"
MARKET_MAKER = "market-maker"
DIRECTIONAL_INFORMED = "directional-informed"
LONGSHOT_FARMER = "longshot-farmer"
RESOLUTION_HOLDER = "resolution-holder"
UNCLASSIFIED = "unclassified"

_MM_HOLD_MAX = 150          # blocks (~5 min on Polygon) — fast flip
_DIRECTIONAL_HOLD_MIN = 150  # holds through a move


def classify(f: WalletFeatures) -> tuple[str, float]:
    """Return (archetype, confidence in [0,1]). Confidence is a coarse rule-margin proxy."""
    # Arbitrageur: near-instant flips, both-sided.
    if f.flip_rate >= 0.9 and f.median_hold_blocks <= 2:
        return ARBITRAGEUR, 0.8
    # Price-extreme holders (check before the mid-price MM band).
    if f.entry_price_mean <= Decimal("0.2") and f.flip_rate <= 0.3:
        return LONGSHOT_FARMER, 0.7
    if f.entry_price_mean >= Decimal("0.85") and f.flip_rate <= 0.3:
        return RESOLUTION_HOLDER, 0.7
    # Market-maker: maker-led, fast two-sided flip in the mid band.
    if (
        f.maker_fill_ratio >= 0.6
        and f.flip_rate >= 0.6
        and f.median_hold_blocks <= _MM_HOLD_MAX
        and Decimal("0.2") <= f.entry_price_mean <= Decimal("0.8")
    ):
        return MARKET_MAKER, 0.8
    # Directional-informed: taker-led, positive round-trip, holds through the move.
    if (
        f.maker_fill_ratio <= 0.4
        and f.roundtrip_return_median > Decimal("0")
        and f.median_hold_blocks >= _DIRECTIONAL_HOLD_MIN
    ):
        return DIRECTIONAL_INFORMED, 0.7
    return UNCLASSIFIED, 0.0
