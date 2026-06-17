from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Market(StrEnum):
    A = "a"
    HK = "hk"
    US = "us"


class WatchItemCreate(BaseModel):
    market: Market
    symbol: str = Field(min_length=1, max_length=32)
    name: str | None = Field(default=None, max_length=64)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WatchItem(WatchItemCreate):
    id: str


class ProviderStatus(BaseModel):
    status: Literal["ok", "partial", "unavailable", "error"]
    source: str
    updated_at: str
    message: str | None = None


class Quote(BaseModel):
    id: str
    market: Market
    symbol: str
    name: str | None = None
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    previous_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    currency: str
    status: ProviderStatus


class GoldQuote(BaseModel):
    symbol: str
    name: str
    price: float | None = None
    currency: str = "CNY/g"
    status: ProviderStatus


class SectorItem(BaseModel):
    name: str
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    volume: float | None = None
    amount: float | None = None


class SectorResponse(BaseModel):
    market: Market
    status: ProviderStatus
    items: list[SectorItem]


class SymbolSearchResult(BaseModel):
    market: Market
    symbol: str
    name: str
    source: str


class OverviewResponse(BaseModel):
    watchlist: list[WatchItem]
    quotes: list[Quote]
    gold: GoldQuote
    sectors: list[SectorResponse]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
