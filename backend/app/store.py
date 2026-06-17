import json
from pathlib import Path

from app.models import Market, WatchItem, WatchItemCreate


DEFAULT_WATCHLIST: list[WatchItemCreate] = [
    WatchItemCreate(market=Market.A, symbol="600519", name="贵州茅台"),
    WatchItemCreate(market=Market.A, symbol="000001", name="平安银行"),
    WatchItemCreate(market=Market.HK, symbol="00700", name="腾讯控股"),
    WatchItemCreate(market=Market.HK, symbol="09988", name="阿里巴巴-W"),
    WatchItemCreate(market=Market.US, symbol="AAPL", name="Apple"),
    WatchItemCreate(market=Market.US, symbol="MSFT", name="Microsoft"),
    WatchItemCreate(market=Market.US, symbol="NVDA", name="NVIDIA"),
    WatchItemCreate(market=Market.CRYPTO, symbol="BTC-USD", name="Bitcoin"),
    WatchItemCreate(market=Market.CRYPTO, symbol="ETH-USD", name="Ethereum"),
]

REQUIRED_DEFAULT_WATCHLIST: list[WatchItemCreate] = [
    WatchItemCreate(market=Market.CRYPTO, symbol="BTC-USD", name="Bitcoin"),
    WatchItemCreate(market=Market.CRYPTO, symbol="ETH-USD", name="Ethereum"),
]


def normalize_symbol_for_market(market: Market, symbol: str) -> str:
    normalized = symbol.strip().upper()
    if market == Market.HK and normalized.isdigit():
        return normalized.zfill(5)
    return normalized


def make_watch_id(market: Market, symbol: str) -> str:
    return f"{market.value}:{normalize_symbol_for_market(market, symbol)}"


class WatchlistStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write([self._from_create(item) for item in DEFAULT_WATCHLIST])

    def list_items(self) -> list[WatchItem]:
        return self._read_with_required_defaults()

    def add_item(self, payload: WatchItemCreate) -> WatchItem:
        normalized = WatchItemCreate(
            market=payload.market,
            symbol=normalize_symbol_for_market(payload.market, payload.symbol),
            name=payload.name,
        )
        existing_items = self._read()
        item_id = make_watch_id(normalized.market, normalized.symbol)
        for item in existing_items:
            if item.id == item_id:
                return item
        created = self._from_create(normalized)
        self._write([*existing_items, created])
        return created

    def delete_item(self, item_id: str) -> bool:
        existing_items = self._read()
        next_items = [item for item in existing_items if item.id != item_id]
        if len(next_items) == len(existing_items):
            return False
        self._write(next_items)
        return True

    def replace_items(self, items: list[WatchItem]) -> None:
        self._write(items)

    def _from_create(self, payload: WatchItemCreate) -> WatchItem:
        symbol = normalize_symbol_for_market(payload.market, payload.symbol)
        return WatchItem(
            id=make_watch_id(payload.market, symbol),
            market=payload.market,
            symbol=symbol,
            name=payload.name,
        )

    def _read(self) -> list[WatchItem]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [WatchItem.model_validate(item) for item in raw]

    def _read_with_required_defaults(self) -> list[WatchItem]:
        items = self._read()
        existing = {item.id for item in items}
        additions = [
            self._from_create(payload)
            for payload in REQUIRED_DEFAULT_WATCHLIST
            if make_watch_id(payload.market, payload.symbol) not in existing
        ]
        if additions:
            items = [*items, *additions]
            self._write(items)
        return items

    def _write(self, items: list[WatchItem]) -> None:
        self.path.write_text(
            json.dumps(
                [item.model_dump(mode="json") for item in items],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
