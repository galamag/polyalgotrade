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
    condition_id: str | None = None  # market id (S5); None on the on-chain path


def wallet_fills_from_trades(trades: list[dict[str, object]]) -> list[WalletFill]:
    """Map tagged data-api /trades (each with an `is_maker` flag) onto WalletFill.

    `side` is already the wallet's perspective (BUY=wallet bought). We store the epoch-SECONDS
    `timestamp` in `block` (a monotonic time/order key reused by compute_wallet_features for
    hold-gap math; seconds, not blocks — note the unit shift for the data-api path).

    Skips trades where size <= 0.
    """
    out: list[WalletFill] = []
    for t in trades:
        size = Decimal(str(t["size"]))
        if size <= 0:
            continue
        price = Decimal(str(t["price"]))
        side = Side.BUY if str(t["side"]).upper() == "BUY" else Side.SELL
        cashflow = (-price * size) if side is Side.BUY else (price * size)
        out.append(
            WalletFill(
                token_id=str(t["asset"]),
                side=side,
                price=price,
                size=size,
                block=int(str(t["timestamp"])),
                is_maker=bool(t.get("is_maker", False)),
                cashflow=cashflow,
                condition_id=(str(t["conditionId"]) if t.get("conditionId") else None),
            )
        )
    return out


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
    buy_fill_fraction: float = 0.0


def _vwap(prices_sizes: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Size-weighted average price; 0 if no size."""
    tot = sum((s for _, s in prices_sizes), Decimal("0"))
    if tot == 0:
        return Decimal("0")
    return sum((p * s for p, s in prices_sizes), Decimal("0")) / tot


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def compute_wallet_features(
    wallet: str, fills: list[WalletFill], marks: dict[str, Decimal]
) -> WalletFeatures:
    """Aggregate per-wallet behavioral features. `marks` = token_id -> current mark price.

    pnl_proxy per token = clean realized P&L (matched round-trips) + unrealized (residual *
    mark). top1_token_pnl_share uses abs(pnl) so a dominant loss also flags concentration.
    realized_share = realized_total / pnl_proxy (clamped [0,1]).
    A token is "flipped" only if min(buy_size,sell_size)/max(buy_size,sell_size) >= 0.5
    (substantial two-sidedness). Hold span = last_sell_block - first_buy_block.
    n_tokens counts unique markets (condition_id or token_id fallback, S5); flip_rate
    and positive_token_fraction keep per-token-group denominators.
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

        buy_size = sum((s for _, s in buys), Decimal("0"))
        sell_size = sum((s for _, s in sells), Decimal("0"))
        buy_vwap = _vwap(buys)
        sell_vwap = _vwap(sells)

        # Clean realized/unrealized split (B3)
        matched = min(buy_size, sell_size)
        realized_pnl_token = matched * (sell_vwap - buy_vwap) if (buys and sells) else Decimal("0")

        residual_size = buy_size - sell_size
        last_price = tfills[-1].price
        mark = marks.get(token, last_price)
        unrealized_pnl_token = residual_size * (mark - buy_vwap)

        token_pnl[token] = realized_pnl_token + unrealized_pnl_token
        realized_total += realized_pnl_token
        unrealized_total += unrealized_pnl_token

        # Robust flip: substantial two-sidedness required (S2)
        if buys and sells:
            min_sz = min(buy_size, sell_size)
            max_sz = max(buy_size, sell_size)
            is_flip = (min_sz / max_sz) >= Decimal("0.5") if max_sz > 0 else False
        else:
            is_flip = False

        if is_flip:
            flips += 1
            buy_blocks = [f.block for f in tfills if f.side is Side.BUY]
            sell_blocks = [f.block for f in tfills if f.side is Side.SELL]
            first_buy_block = min(buy_blocks)
            last_sell_block = max(sell_blocks)
            hold_gaps.append(last_sell_block - first_buy_block)
            roundtrips.append(sell_vwap - buy_vwap)

    # S5: breadth = unique MARKETS (conditionId when present, token_id fallback).
    n_tokens = len({f.condition_id or f.token_id for f in fills})
    n_token_groups = len(by_token)
    pnl_proxy = realized_total + unrealized_total

    # Loss-aware top1_token_pnl_share (B2): uses abs(pnl) so dominant loss also flags
    abs_pnls = [abs(v) for v in token_pnl.values()]
    abs_total = sum(abs_pnls, Decimal("0"))
    top1_share = float(max(abs_pnls) / abs_total) if abs_total > 0 else 0.0

    realized_share = _clamp01(float(realized_total / pnl_proxy)) if pnl_proxy != 0 else 0.0
    positive = [v for v in token_pnl.values() if v > 0]

    return WalletFeatures(
        wallet=wallet,
        n_fills=len(fills),
        n_tokens=n_tokens,
        maker_fill_ratio=sum(1 for f in fills if f.is_maker) / len(fills),
        flip_rate=flips / n_token_groups,
        median_hold_blocks=int(median(hold_gaps)) if hold_gaps else 0,
        entry_price_mean=_vwap(buys_all),
        turnover_usdc=turnover,
        pnl_proxy=pnl_proxy,
        realized_share=realized_share,
        top1_token_pnl_share=top1_share,
        positive_token_fraction=len(positive) / n_token_groups,
        roundtrip_return_median=median(roundtrips) if roundtrips else Decimal("0"),
        buy_fill_fraction=sum(1 for f in fills if f.side is Side.BUY) / len(fills),
    )


_SKILL_MIN_TOKENS = 30          # >= ~15 binary markets — "many independent bets"
_SKILL_MAX_TOP1_SHARE = 0.40    # no single bet dominates the P&L (abs-based)
_SKILL_MIN_POSITIVE_FRAC = 0.50  # positive across a majority of tokens
_SKILL_MIN_REALIZED_SHARE = 0.30  # exclude mostly-unrealized (hindsight-marked) P&L (B3)
_COPY_MIN_HOLD_BLOCKS = 3       # below this, the move is too fast to follow with our lag


def is_skill_cohort(f: WalletFeatures) -> bool:
    """True if the wallet's P&L looks like repeatable skill, not a lucky jackpot (spec §9, B2, B3).

    Requires: net profit, realized_share >= 0.30 (not mostly unrealized), breadth >= 30 tokens,
    abs-concentration < 0.40, and majority of tokens positive.
    """
    return (
        f.pnl_proxy > 0
        and f.realized_share >= _SKILL_MIN_REALIZED_SHARE
        and f.n_tokens >= _SKILL_MIN_TOKENS
        and f.top1_token_pnl_share < _SKILL_MAX_TOP1_SHARE
        and f.positive_token_fraction > _SKILL_MIN_POSITIVE_FRAC
    )


def copyability_proxy(f: WalletFeatures) -> Decimal:
    """Lean zero-lag copyability = round-trip edge, 0 if flip is too fast to follow (§10)."""
    if f.median_hold_blocks < _COPY_MIN_HOLD_BLOCKS:
        return Decimal("0")
    return max(Decimal("0"), f.roundtrip_return_median)
