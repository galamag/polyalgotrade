"""Kalshi fee model — verified against official docs (ADR 0009).

Fee formula (taker): fee = multiplier * price * (1 - price) * contracts
  - Default multiplier is 0.07 (standard series).
  - Per-series multiplier may override the default (e.g. promo/zero-fee series).
  - Rounding is CEIL to the cent for non-direct members (NOT round-half-up).

Maker fee uses multiplier 0.0175 (25 % of the standard 0.07 taker multiplier).
Unlike Polymarket, Kalshi charges makers — the maker rate is NOT zero.

All monetary values are Decimal to avoid float rounding errors.
"""

from decimal import Decimal

from pat.costs.base import ceil_to

# Default fee multipliers (ADR 0009).
TAKER_MULT: Decimal = Decimal("0.07")
MAKER_MULT: Decimal = Decimal("0.0175")  # 25 % of taker; NOT zero

# Rounding unit for non-direct members: fees are CEIL'd to the cent.
CENT: Decimal = Decimal("0.01")


def _validate(price: Decimal, contracts: Decimal) -> None:
    """Domain guard: raise if inputs are out of legal range.

    A fee formula with out-of-range price or negative contracts would silently
    produce a negative or meaningless result — we treat that as a programming
    error rather than returning a negative 'credit'.
    """
    if not (Decimal("0") <= price <= Decimal("1")):
        raise ValueError(f"price must be in [0, 1], got {price}")
    if contracts < Decimal("0"):
        raise ValueError(f"contracts must be >= 0, got {contracts}")


def kalshi_taker_fee(
    price: Decimal,
    contracts: Decimal,
    multiplier: Decimal = TAKER_MULT,
    tick: Decimal = CENT,
) -> Decimal:
    """Compute the taker fee for a Kalshi order.

    Formula: fee = CEIL(multiplier * price * (1 - price) * contracts, tick)

    Args:
        price:      Execution price in [0, 1].
        contracts:  Number of contracts; must be >= 0.
        multiplier: Per-series fee multiplier; defaults to 0.07.
        tick:       Rounding unit; defaults to $0.01 (cent) for non-direct members.

    Returns:
        Fee in USD as Decimal, ceil-rounded to *tick*.

    Raises:
        ValueError: If price is outside [0, 1] or contracts is negative.
    """
    _validate(price, contracts)
    raw = multiplier * price * (Decimal("1") - price) * contracts
    # raw is zero at the price bounds (p=0 or p=1) and when multiplier=0.
    # Guard against a hypothetical negative raw (should be impossible after
    # _validate, but belt-and-suspenders — a fee must never be a credit).
    if raw <= Decimal("0"):
        return Decimal("0")
    return ceil_to(raw, tick)


def kalshi_maker_fee(
    price: Decimal,
    contracts: Decimal,
    multiplier: Decimal = MAKER_MULT,
    tick: Decimal = CENT,
) -> Decimal:
    """Compute the maker fee for a Kalshi order.

    Kalshi charges makers at 0.0175 (25 % of the 0.07 taker multiplier).
    This is NOT zero — unlike Polymarket, where makers pay nothing.

    Args:
        price:      Execution price in [0, 1].
        contracts:  Number of contracts; must be >= 0.
        multiplier: Per-series maker multiplier; defaults to 0.0175.
        tick:       Rounding unit; defaults to $0.01 (cent) for non-direct members.

    Returns:
        Fee in USD as Decimal, ceil-rounded to *tick*.

    Raises:
        ValueError: If price is outside [0, 1] or contracts is negative.
    """
    _validate(price, contracts)
    raw = multiplier * price * (Decimal("1") - price) * contracts
    if raw <= Decimal("0"):
        return Decimal("0")
    return ceil_to(raw, tick)
