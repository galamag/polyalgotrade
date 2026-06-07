from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class Venue(StrEnum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Liquidity(StrEnum):
    MAKER = "maker"
    TAKER = "taker"


class OrderType(StrEnum):
    GTC = "gtc"
    FOK = "fok"
    FAK = "fak"


class Category(StrEnum):
    CRYPTO = "crypto"
    SPORTS = "sports"
    FINANCE = "finance"
    POLITICS = "politics"
    ECONOMICS = "economics"
    CULTURE = "culture"
    WEATHER = "weather"
    TECH = "tech"
    MENTIONS = "mentions"
    OTHER = "other"
    GEOPOLITICS = "geopolitics"


Mode = Literal["backtest", "paper", "live"]
Price = Decimal


class Market(BaseModel):
    id: str
    venue: Venue
    question: str
    category: Category
    tick_size: Decimal = Decimal("0.01")
    resolution_source: str | None = None
    close_time_ms: int | None = None


class Order(BaseModel):
    client_id: str
    token_id: str
    side: Side
    price: Price = Field(ge=Decimal("0"), le=Decimal("1"))
    size: Decimal = Field(gt=Decimal("0"))
    order_type: OrderType = OrderType.GTC
    mode: Mode = "backtest"
    reason: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def notional(self) -> Decimal:
        return (self.price * self.size).quantize(Decimal("0.01"))


class Fill(BaseModel):
    order_id: str
    token_id: str
    price: Price = Field(ge=Decimal("0"), le=Decimal("1"))
    size: Decimal = Field(gt=Decimal("0"))
    fee: Decimal = Decimal("0")
    liquidity: Liquidity = Liquidity.TAKER
    mode: Mode = "backtest"
    ts: int


class Position(BaseModel):
    token_id: str
    net_size: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
