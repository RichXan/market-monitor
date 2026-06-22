import json

from app.models import Market, WatchItemCreate
from app.store import WatchlistStore


def test_store_seeds_default_watchlist_when_file_is_missing(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")

    items = store.list_items()

    assert [item.symbol for item in items] == [
        "600519",
        "000001",
        "00700",
        "09988",
        "AAPL",
        "MSFT",
        "NVDA",
        "BTC-USD",
        "ETH-USD",
    ]
    assert [item.market for item in items] == [
        Market.A,
        Market.A,
        Market.HK,
        Market.HK,
        Market.US,
        Market.US,
        Market.US,
        Market.CRYPTO,
        Market.CRYPTO,
    ]


def test_store_adds_and_persists_watch_item(tmp_path):
    path = tmp_path / "watchlist.json"
    store = WatchlistStore(path)

    created = store.add_item(
        WatchItemCreate(market=Market.US, symbol="tsla", name="Tesla")
    )
    reloaded = WatchlistStore(path)

    assert created.symbol == "TSLA"
    assert created.name == "Tesla"
    assert any(item.symbol == "TSLA" for item in reloaded.list_items())


def test_store_adds_crypto_defaults_to_existing_watchlist(tmp_path):
    path = tmp_path / "watchlist.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "us:AAPL",
                    "market": "us",
                    "symbol": "AAPL",
                    "name": "Apple",
                }
            ]
        ),
        encoding="utf-8",
    )
    store = WatchlistStore(path)

    items = store.list_items()
    reloaded = WatchlistStore(path).list_items()

    assert [item.symbol for item in items] == ["AAPL", "BTC-USD", "ETH-USD"]
    assert [item.market for item in items] == [Market.US, Market.CRYPTO, Market.CRYPTO]
    assert [item.symbol for item in reloaded] == ["AAPL", "BTC-USD", "ETH-USD"]


def test_store_prevents_duplicate_market_symbol_pairs(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")

    first = store.add_item(WatchItemCreate(market=Market.US, symbol="aapl"))
    second = store.add_item(WatchItemCreate(market=Market.US, symbol="AAPL"))

    assert first.id == second.id
    assert [item.symbol for item in store.list_items()].count("AAPL") == 1


def test_store_normalizes_a_share_exchange_suffixes(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")

    first = store.add_item(WatchItemCreate(market=Market.A, symbol="513300.SH", name="纳指ETF"))
    second = store.add_item(WatchItemCreate(market=Market.A, symbol="513300"))

    assert first.id == "a:513300"
    assert first.symbol == "513300"
    assert second.id == first.id
    assert [item.symbol for item in store.list_items()].count("513300") == 1


def test_store_deletes_watch_item(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")
    created = store.add_item(WatchItemCreate(market=Market.HK, symbol="00005"))

    removed = store.delete_item(created.id)

    assert removed is True
    assert created.id not in {item.id for item in store.list_items()}
