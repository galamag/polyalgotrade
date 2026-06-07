"""Parse decoded Polymarket CTF Exchange V2 `OrderFilled` events into normalized Fill records.

On-chain amounts use 6-decimal fixed point (divide by FILL_SCALE to get human units).
USDC amounts and share counts are both expressed this way in the raw event.

Price convention:
  - The collateral (USDC) leg is authoritatively identified by assetId == "0".
  - The other leg is shares.  price = usdc / shares.
  - Falls back to the magnitude heuristic only for rare token/token swaps (neither leg is "0").

This module is a pure transform: no network, no I/O. Feed it decoded event dicts
(as produced by eth_getLogs + ABI decode, or a pre-saved JSON fixture) and receive
a list of `pat.core.types.Fill`.

Data-quality boundary
---------------------
- Pydantic validates price in [0,1] and size > 0 on Fill construction; bad data raises.
- Zero-share events (division-by-zero guard) produce price=0 and are passed through;
  callers may filter them.
- `fee` is stored in USDC (human units), not shares.
"""

from __future__ import annotations

from decimal import Decimal

import structlog

from pat.core.types import Fill, Liquidity

log = structlog.get_logger(__name__)

FILL_SCALE = Decimal("1000000")  # 6-dp fixed-point on-chain amounts


def _price_and_size(ev: dict[str, object]) -> tuple[Decimal, Decimal]:
    """Return (price, shares) from a raw OrderFilled event dict.

    The collateral (USDC) leg is authoritatively the one with assetId == "0".
    The other leg is shares.  price = usdc / shares.  If neither leg is
    collateral (rare token/token swap), fall back to the magnitude heuristic.
    """
    maker_id = str(ev.get("makerAssetId", ""))
    taker_id = str(ev.get("takerAssetId", ""))
    maker_amt = Decimal(str(ev["makerAmountFilled"])) / FILL_SCALE
    taker_amt = Decimal(str(ev["takerAmountFilled"])) / FILL_SCALE

    if taker_id == "0":
        usdc, shares = taker_amt, maker_amt
    elif maker_id == "0":
        usdc, shares = maker_amt, taker_amt
    else:
        # Neither leg is USDC collateral — fall back to magnitude (larger = shares).
        log.warning("orderfilled.no_collateral_leg", maker_id=maker_id, taker_id=taker_id)
        if taker_amt >= maker_amt:
            shares, usdc = taker_amt, maker_amt
        else:
            shares, usdc = maker_amt, taker_amt

    price = (usdc / shares) if shares else Decimal("0")
    return price, shares


def parse_orderfilled(events: list[dict[str, object]]) -> list[Fill]:
    """Convert a list of decoded OrderFilled event dicts into normalized Fill records.

    Parameters
    ----------
    events:
        List of decoded event dicts, each containing at minimum:
        - makerAssetId (str | int): ERC-1155 token ID for the maker leg
        - takerAssetId (str | int): ERC-1155 token ID for the taker leg
        - makerAmountFilled (int): raw on-chain amount (6-dp fixed-point)
        - takerAmountFilled (int): raw on-chain amount (6-dp fixed-point)
        - fee (int): raw on-chain fee amount (6-dp fixed-point)
        - timestamp (int): UTC epoch milliseconds
        - transactionHash (str): hex tx hash used as order_id

    Returns
    -------
    list[Fill]:
        Normalized fills; price in [0,1], size > 0, fee in USDC, mode="backtest".
        Raises pydantic.ValidationError if any record violates the schema.
    """
    out: list[Fill] = []
    for i, ev in enumerate(events):
        price, size = _price_and_size(ev)
        fee_raw = Decimal(str(ev.get("fee", "0"))) / FILL_SCALE

        # token_id: prefer the non-zero asset ID (shares leg); USDC leg is "0"
        maker_asset = str(ev.get("makerAssetId", ""))
        taker_asset = str(ev.get("takerAssetId", ""))
        token_id = maker_asset if maker_asset not in ("", "0") else taker_asset

        order_id = str(ev.get("transactionHash", "unknown"))
        ts = int(str(ev["timestamp"]))

        fill = Fill(
            order_id=order_id,
            token_id=token_id,
            price=price,
            size=size,
            fee=fee_raw,
            liquidity=Liquidity.TAKER,
            mode="backtest",
            ts=ts,
        )
        log.debug(
            "orderfilled.parsed",
            index=i,
            order_id=order_id,
            price=str(price),
            size=str(size),
            fee=str(fee_raw),
            ts=ts,
        )
        out.append(fill)

    log.info("orderfilled.batch_parsed", count=len(out))
    return out
