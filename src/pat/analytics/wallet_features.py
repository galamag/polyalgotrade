"""Per-wallet behavioral features from decoded OrderFilled events (lean, on-chain only).

`derive_wallet_fills` projects each decoded event onto the wallet's perspective (BUY/SELL,
price, size, cashflow). `compute_wallet_features` (next task) aggregates them. Money = Decimal.
"""

from __future__ import annotations

from decimal import Decimal
from statistics import median

from pydantic import BaseModel

from pat.core.types import Side
from pat.data.polymarket_history import price_and_size


class WalletFill(BaseModel):
    token_id: str
    side: Side
    price: Decimal
    size: Decimal
    block: int
    is_maker: bool
    cashflow: Decimal  # BUY -> negative (USDC out); SELL -> positive (USDC in)


def derive_wallet_fills(events: list[dict[str, object]], wallet: str) -> list[WalletFill]:
    """Project decoded events onto *wallet*'s perspective. Skips events not involving the wallet.

    side==0 (BUY order): maker gives USDC -> maker BUYS the token; taker SELLS.
    side==1 (SELL order): maker gives shares -> maker SELLS the token; taker BUYS.
    """
    w = wallet.lower()
    out: list[WalletFill] = []
    for ev in events:
        maker = str(ev.get("maker", "")).lower()
        taker = str(ev.get("taker", "")).lower()
        is_maker = maker == w
        is_taker = taker == w
        if not (is_maker or is_taker):
            continue
        side_int = int(str(ev["side"]))
        maker_buys = side_int == 0
        wallet_buys = maker_buys if is_maker else (not maker_buys)
        price, size = price_and_size(ev)
        if size == 0:
            continue
        side = Side.BUY if wallet_buys else Side.SELL
        cashflow = (-price * size) if wallet_buys else (price * size)
        out.append(
            WalletFill(
                token_id=str(ev["tokenId"]), side=side, price=price, size=size,
                block=int(str(ev["blockNumber"])), is_maker=is_maker, cashflow=cashflow,
            )
        )
    return out


class WalletFeatures(BaseModel):
    wallet: str
    n_fills: int
    n_tokens: int
    maker_fill_ratio: float
    flip_rate: float
    median_hold_blocks: int
    entry_price_mean: Decimal
    turnover_usdc: Decimal
    pnl_proxy: Decimal
    realized_share: float
    top1_token_pnl_share: float
    positive_token_fraction: float
    roundtrip_return_median: Decimal


def _vwap(prices_sizes: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Size-weighted average price; 0 if no size."""
    tot = sum((s for _, s in prices_sizes), Decimal("0"))
    if tot == 0:
        return Decimal("0")
    return sum((p * s for p, s in prices_sizes), Decimal("0")) / tot


def compute_wallet_features(
    wallet: str, fills: list[WalletFill], marks: dict[str, Decimal]
) -> WalletFeatures:
    """Aggregate per-wallet behavioral features. `marks` = token_id -> current mark price.

    pnl_proxy per token = realized cashflow + residual_position * mark (mark falls back to the
    token's last trade price if absent). top1_token_pnl_share / positive_token_fraction use the
    per-token pnl. roundtrip_return_median / median_hold_blocks use only flipped tokens.
    """
    if not fills:
        return WalletFeatures(
            wallet=wallet, n_fills=0, n_tokens=0, maker_fill_ratio=0.0, flip_rate=0.0,
            median_hold_blocks=0, entry_price_mean=Decimal("0"), turnover_usdc=Decimal("0"),
            pnl_proxy=Decimal("0"), realized_share=0.0, top1_token_pnl_share=0.0,
            positive_token_fraction=0.0, roundtrip_return_median=Decimal("0"),
        )

    by_token: dict[str, list[WalletFill]] = {}
    for fl in fills:
        by_token.setdefault(fl.token_id, []).append(fl)

    buys_all: list[tuple[Decimal, Decimal]] = []
    hold_gaps: list[int] = []
    roundtrips: list[Decimal] = []
    token_pnl: dict[str, Decimal] = {}
    realized_total = Decimal("0")
    unrealized_total = Decimal("0")
    turnover = Decimal("0")
    flips = 0

    for token, tfills in by_token.items():
        tfills.sort(key=lambda f: f.block)
        buys = [(f.price, f.size) for f in tfills if f.side is Side.BUY]
        sells = [(f.price, f.size) for f in tfills if f.side is Side.SELL]
        buys_all.extend(buys)
        turnover += sum((f.price * f.size for f in tfills), Decimal("0"))
        realized_cash = sum((f.cashflow for f in tfills), Decimal("0"))
        net_size = sum((f.size if f.side is Side.BUY else -f.size for f in tfills), Decimal("0"))
        last_price = tfills[-1].price
        mark = marks.get(token, last_price)
        residual_value = net_size * mark
        token_pnl[token] = realized_cash + residual_value
        realized_total += realized_cash
        unrealized_total += residual_value
        if buys and sells:
            flips += 1
            entry_block = next(f.block for f in tfills if f.side is Side.BUY)
            exit_block = next(f.block for f in tfills if f.side is Side.SELL)
            hold_gaps.append(exit_block - entry_block)
            roundtrips.append(_vwap(sells) - _vwap(buys))

    n_tokens = len(by_token)
    pnl_proxy = realized_total + unrealized_total
    positive = [v for v in token_pnl.values() if v > 0]
    pos_total = sum(positive, Decimal("0"))
    top1_share = float(max(positive) / pos_total) if pos_total > 0 else 0.0
    realized_share = float(realized_total / pnl_proxy) if pnl_proxy != 0 else 0.0

    return WalletFeatures(
        wallet=wallet,
        n_fills=len(fills),
        n_tokens=n_tokens,
        maker_fill_ratio=sum(1 for f in fills if f.is_maker) / len(fills),
        flip_rate=flips / n_tokens,
        median_hold_blocks=int(median(hold_gaps)) if hold_gaps else 0,
        entry_price_mean=_vwap(buys_all),
        turnover_usdc=turnover,
        pnl_proxy=pnl_proxy,
        realized_share=max(0.0, min(1.0, realized_share)),
        top1_token_pnl_share=top1_share,
        positive_token_fraction=len(positive) / n_tokens,
        roundtrip_return_median=median(roundtrips) if roundtrips else Decimal("0"),
    )


_SKILL_MIN_TOKENS = 30          # >= ~15 binary markets — "many independent bets"
_SKILL_MAX_TOP1_SHARE = 0.40    # no single bet dominates the P&L
_SKILL_MIN_POSITIVE_FRAC = 0.50  # positive across a majority of tokens
_COPY_MIN_HOLD_BLOCKS = 3       # below this, the move is too fast to follow with our lag


def is_skill_cohort(f: WalletFeatures) -> bool:
    """True if the wallet's P&L looks like repeatable skill, not one lucky jackpot (spec §9)."""
    return (
        f.n_tokens >= _SKILL_MIN_TOKENS
        and f.top1_token_pnl_share < _SKILL_MAX_TOP1_SHARE
        and f.positive_token_fraction > _SKILL_MIN_POSITIVE_FRAC
    )


def copyability_proxy(f: WalletFeatures) -> Decimal:
    """Lean zero-lag copyability = round-trip edge, but 0 if the flip is too fast to follow (§10)."""
    if f.median_hold_blocks < _COPY_MIN_HOLD_BLOCKS:
        return Decimal("0")
    return max(Decimal("0"), f.roundtrip_return_median)
