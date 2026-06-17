import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import GoldQuote, Market, ProviderStatus, Quote, SectorResponse, SymbolSearchResult, WatchItemCreate
from app.store import WatchlistStore


class FakeProvider:
    def search_symbols(self, market, query, limit=8):
        if market == Market.A and query == "贵州":
            return [
                SymbolSearchResult(
                    market=Market.A,
                    symbol="600519",
                    name="贵州茅台",
                    source="fake-search",
                )
            ]
        if market == Market.A and query == "五粮液":
            return [
                SymbolSearchResult(
                    market=Market.A,
                    symbol="000858",
                    name="五粮液",
                    source="fake-search",
                )
            ]
        if market == Market.A and query == "友邦吊顶":
            return [
                SymbolSearchResult(
                    market=Market.A,
                    symbol="002718",
                    name="友邦吊顶",
                    source="fake-search",
                )
            ]
        return []

    def get_quotes(self, items):
        return [
            Quote(
                id=items[0].id,
                market=items[0].market,
                symbol=items[0].symbol,
                name=items[0].name or "贵州茅台",
                price=1500.0,
                change=10.0,
                change_percent=0.67,
                currency="CNY",
                status=ProviderStatus(
                    status="ok",
                    source="fake",
                    updated_at="2026-06-17T00:00:00+00:00",
                ),
            )
        ]

    def get_gold_quote(self):
        return GoldQuote(
            symbol="Au99.99",
            name="上海金 Au99.99",
            price=756.2,
            status=ProviderStatus(
                status="ok",
                source="fake-gold",
                updated_at="2026-06-17T00:00:00+00:00",
            ),
        )

    def get_sectors(self, market):
        return SectorResponse(
            market=market,
            items=[],
            status=ProviderStatus(
                status="unavailable",
                source="fake-sector",
                updated_at="2026-06-17T00:00:00+00:00",
                message="strict mode unavailable",
            ),
        )


class SlowOverviewProvider(FakeProvider):
    def get_quotes(self, items):
        time.sleep(0.15)
        return super().get_quotes(items)

    def get_gold_quote(self):
        time.sleep(0.15)
        return super().get_gold_quote()

    def get_sectors(self, market):
        time.sleep(0.15)
        return super().get_sectors(market)


class CountingProvider(FakeProvider):
    def __init__(self) -> None:
        self.quote_calls = 0

    def get_quotes(self, items):
        self.quote_calls += 1
        return super().get_quotes(items)


class FakeJsonCache:
    def __init__(self) -> None:
        self.values = {}
        self.set_calls = []

    def get_json(self, key):
        return self.values.get(key)

    def set_json(self, key, value, ttl_seconds):
        self.values[key] = value
        self.set_calls.append((key, ttl_seconds))


def make_client(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")
    return TestClient(create_app(store=store, provider=FakeProvider()))


def test_health_endpoint(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_watchlist_crud_endpoints(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/watchlist",
        json={"market": "us", "symbol": "tsla", "name": "Tesla"},
    )
    listed = client.get("/api/watchlist")
    deleted = client.delete(f"/api/watchlist/{created.json()['id']}")

    assert created.status_code == 200
    assert created.json()["symbol"] == "TSLA"
    assert any(item["symbol"] == "TSLA" for item in listed.json())
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}


def test_watchlist_add_resolves_name_like_a_share_symbol(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/watchlist",
        json={"market": "a", "symbol": "五粮液"},
    )

    assert created.status_code == 200
    assert created.json()["symbol"] == "000858"
    assert created.json()["name"] == "五粮液"


def test_watchlist_list_repairs_existing_name_like_a_share_symbols(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")
    store.add_item(WatchItemCreate(market=Market.A, symbol="五粮液"))
    store.add_item(WatchItemCreate(market=Market.A, symbol="友邦吊顶"))
    client = TestClient(create_app(store=store, provider=FakeProvider()))

    listed = client.get("/api/watchlist")

    assert listed.status_code == 200
    symbols = {item["symbol"] for item in listed.json()}
    assert "000858" in symbols
    assert "002718" in symbols
    assert "五粮液" not in symbols
    assert "友邦吊顶" not in symbols


def test_quote_gold_sector_and_overview_endpoints(tmp_path):
    client = make_client(tmp_path)

    quotes = client.get("/api/quotes")
    gold = client.get("/api/gold")
    sectors = client.get("/api/sectors", params={"market": "us"})
    overview = client.get("/api/overview")

    assert quotes.status_code == 200
    assert quotes.json()[0]["price"] == 1500.0
    assert gold.json()["symbol"] == "Au99.99"
    assert sectors.json()["status"]["status"] == "unavailable"
    assert set(overview.json()) == {"watchlist", "quotes", "gold", "sectors"}
    assert len(overview.json()["sectors"]) == 3


def test_quotes_endpoint_uses_json_cache(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")
    provider = CountingProvider()
    cache = FakeJsonCache()
    client = TestClient(create_app(store=store, provider=provider, cache=cache))

    first = client.get("/api/quotes")
    second = client.get("/api/quotes")

    assert first.status_code == 200
    assert second.status_code == 200
    assert provider.quote_calls == 1
    assert second.json() == first.json()
    assert cache.set_calls


def test_symbol_search_endpoint(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/search-symbols", params={"market": "a", "q": "贵州"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "market": "a",
            "symbol": "600519",
            "name": "贵州茅台",
            "source": "本地自选",
        }
    ]


def test_symbol_search_endpoint_uses_watchlist_name_fallback(tmp_path):
    client = make_client(tmp_path)

    a_response = client.get("/api/search-symbols", params={"market": "a", "q": "平安"})
    hk_response = client.get("/api/search-symbols", params={"market": "hk", "q": "腾讯"})

    assert a_response.status_code == 200
    assert a_response.json()[0] == {
        "market": "a",
        "symbol": "000001",
        "name": "平安银行",
        "source": "本地自选",
    }
    assert hk_response.status_code == 200
    assert hk_response.json()[0] == {
        "market": "hk",
        "symbol": "00700",
        "name": "腾讯控股",
        "source": "本地自选",
    }


def test_overview_fetches_panels_concurrently(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")
    client = TestClient(create_app(store=store, provider=SlowOverviewProvider()))

    start = time.perf_counter()
    response = client.get("/api/overview")
    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed < 0.45
