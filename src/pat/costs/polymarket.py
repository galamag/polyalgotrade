"""Polymarket fee model — verified against official docs (ADR 0009).

Fee formula: fee = shares * rate * price * (1 - price)
  - rate varies by category (see TAKER_RATE)
  - geopolitics markets have zero fees
  - makers are never charged; they receive a daily-batch rebate from the taker pool

All monetary values are Decimal to avoid float rounding errors.
"""

from decimal import ROUND_HALF_UP, Decimal

from pat.core.types import Category

# Per-category taker fee rate.  Verified: ADR 0009 / official Polymarket fee schedule.
TAKER_RATE: dict[Category, Decimal] = {
    Category.CRYPTO: Decimal("0.07"),
    Category.SPORTS: Decimal("0.03"),
    Category.FINANCE: Decimal("0.04"),
    Category.POLITICS: Decimal("0.04"),
    Category.TECH: Decimal("0.04"),
    Category.MENTIONS: Decimal("0.04"),
    Category.ECONOMICS: Decimal("0.05"),
    Category.CULTURE: Decimal("0.05"),
    Category.WEATHER: Decimal("0.05"),
    Category.OTHER: Decimal("0.05"),
    Category.GEOPOLITICS: Decimal("0"),
}

# Daily-batch rebate fraction of the taker pool (NOT a per-trade discount).
# Geopolitics pool is zero, so its rebate rate is zero.
# Crypto rebate is 20 %; all other non-zero categories are 25 %.
MAKER_REBATE_RATE: dict[Category, Decimal] = {
    c: (
        Decimal("0")
        if c is Category.GEOPOLITICS
        else Decimal("0.20")
        if c is Category.CRYPTO
        else Decimal("0.25")
    )
    for c in Category
}

_FIVE_DP = Decimal("0.00001")


def polymarket_taker_fee(category: Category, price: Decimal, shares: Decimal) -> Decimal:
    """Compute the taker fee for a Polymarket order.

    Formula: fee = shares * rate * price * (1 - price), rounded to 5 dp.
    A minimum floor of 0.00001 applies whenever the raw fee is strictly positive
    but rounds to zero — prevents tiny orders from appearing free.

    Args:
        category: Market category (determines rate).
        price:    Execution price in [0, 1].
        shares:   Number of shares (outcome tokens).

    Returns:
        Fee in USDC, as Decimal with 5 decimal places.
    """
    rate = TAKER_RATE[category]
    raw = shares * rate * price * (Decimal("1") - price)
    fee = raw.quantize(_FIVE_DP, rounding=ROUND_HALF_UP)
    if raw > 0 and fee < _FIVE_DP:
        return _FIVE_DP
    return fee


def polymarket_maker_fee(category: Category, price: Decimal, shares: Decimal) -> Decimal:  # noqa: ARG001
    """Makers are never charged a fee on Polymarket.

    The rebate (MAKER_REBATE_RATE) is distributed daily from the taker pool
    and is accounted for separately in PnL attribution, not as a negative fee here.
    """
    return Decimal("0")
