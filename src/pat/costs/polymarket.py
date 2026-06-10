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
    The smallest charged fee is 0.00001 USDC; anything smaller rounds to zero.

    Args:
        category: Market category (determines rate).
        price:    Execution price in [0, 1].
        shares:   Number of shares (outcome tokens); must be >= 0.

    Returns:
        Fee in USDC, as Decimal with 5 decimal places.

    Raises:
        ValueError: If price is outside [0, 1] or shares is negative.
    """
    if not (Decimal("0") <= price <= Decimal("1")):
        raise ValueError(f"price must be in [0,1], got {price}")
    if shares < 0:
        raise ValueError(f"shares must be >= 0, got {shares}")
    rate = TAKER_RATE[category]
    raw = shares * rate * price * (Decimal("1") - price)
    return raw.quantize(_FIVE_DP, rounding=ROUND_HALF_UP)


def polymarket_maker_fee(category: Category, price: Decimal, shares: Decimal) -> Decimal:  # noqa: ARG001
    """Makers are never charged a fee on Polymarket.

    The rebate (MAKER_REBATE_RATE) is distributed daily from the taker pool
    and is accounted for separately in PnL attribution, not as a negative fee here.
    """
    return Decimal("0")


# Assumed market half-spread (price units) to cross the book and flatten one residual share at
# liquidation. 1 tick on Polymarket's penny grid. The backtest marks residual MM inventory net of
# this cost. It is INDEPENDENT of the strategy's own quote half-spread — you unwind at the MARKET's
# spread, not at the width you happened to quote (fee-audit fix, ADR 0018).
MARKET_HALF_SPREAD = Decimal("0.01")


def liquidation_haircut(net_shares: Decimal) -> Decimal:
    """Cost (USDC) to cross the book and flatten a residual position.

    ``|net_shares| * MARKET_HALF_SPREAD``. Routed through the cost model (not ad-hoc in the
    backtest runner) so the residual-inventory liquidation cost is auditable and tested.
    """
    return abs(net_shares) * MARKET_HALF_SPREAD


# Conservative per-transaction gas on Polygon (claim I7: $0.002-0.005). CLOB trades cost
# the USER no gas (the operator settles); gas applies to split/merge/redeem transactions.
POLYGON_TX_GAS_USDC = Decimal("0.005")


def gas_cost(n_txs: int) -> Decimal:
    """Gas line item (USDC) for *n_txs* on-chain transactions (split/merge/redeem)."""
    if n_txs < 0:
        raise ValueError(f"n_txs must be >= 0, got {n_txs}")
    return POLYGON_TX_GAS_USDC * n_txs


def depth_vwap(
    levels: list[tuple[Decimal, Decimal]], size: Decimal
) -> Decimal | None:
    """Executable VWAP walking (price, size) levels best-first; None if depth < size.

    Slippage is implicit (VWAP vs top of book) — never a constant. `levels` must be
    best-first (bids descending / asks ascending); the caller normalizes.
    """
    remaining = size
    cost = Decimal("0")
    for price, level_size in levels:
        take = min(remaining, level_size)
        cost += price * take
        remaining -= take
        if remaining == 0:
            return cost / size
    return None
