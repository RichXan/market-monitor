import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import (
    GoldQuote,
    Market,
    ProviderStatus,
    Quote,
    SectorConstituent,
    SectorDetailResponse,
    SectorItem,
    SectorResponse,
    SymbolSearchResult,
    WatchItemCreate,
)
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
            items=[SectorItem(name=f"{market.value}-active", change_percent=1.23)],
            status=ProviderStatus(
                status="unavailable",
                source="fake-sector",
                updated_at="2026-06-17T00:00:00+00:00",
                message="strict mode unavailable",
            ),
        )

    def get_sector_details(self, market, sector_name, limit=12):
        return SectorDetailResponse(
            market=market,
            sector_name=sector_name,
            items=[
                SectorConstituent(
                    symbol="600519",
                    name="贵州茅台",
                    price=1500.0,
                    change_percent=0.67,
                    volume=1200000,
                    source="fake-detail",
                )
            ],
            status=ProviderStatus(
                status="ok",
                source="fake-detail",
                updated_at="2026-06-17T00:00:00+00:00",
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


class SlowSectorProvider(FakeProvider):
    def get_sectors(self, market):
        time.sleep(0.2)
        return super().get_sectors(market)


class CountingProvider(FakeProvider):
    def __init__(self) -> None:
        self.quote_calls = 0
        self.gold_calls = 0
        self.sector_calls = 0
        self.sector_detail_calls = 0

    def get_quotes(self, items):
        self.quote_calls += 1
        return super().get_quotes(items)

    def get_gold_quote(self):
        self.gold_calls += 1
        return super().get_gold_quote()

    def get_sectors(self, market):
        self.sector_calls += 1
        return super().get_sectors(market)

    def get_sector_details(self, market, sector_name, limit=12):
        self.sector_detail_calls += 1
        return super().get_sector_details(market, sector_name, limit=limit)


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
    services = {item["name"]: item for item in response.json()["services"]}
    assert {"FastAPI", "Cache", "Quotes", "Gold", "Sectors"}.issubset(services)
    assert services["Gold"]["source"] == "fake-gold"


def test_market_status_endpoint(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/market-status")

    assert response.status_code == 200
    assert {item["market"] for item in response.json()} == {"a", "hk", "us"}
    assert all(item["label"] for item in response.json())
    assert all(item["timezone"] for item in response.json())


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


def test_sector_details_endpoint(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/sector-details", params={"market": "a", "sector": "白酒"})

    assert response.status_code == 200
    assert response.json()["sector_name"] == "白酒"
    assert response.json()["items"][0]["symbol"] == "600519"
    assert response.json()["items"][0]["source"] == "fake-detail"


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


def test_background_refresh_preloads_json_cache(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")
    provider = CountingProvider()
    cache = FakeJsonCache()

    app = create_app(store=store, provider=provider, cache=cache, background_refresh_seconds=0.01)
    with TestClient(app):
        deadline = time.time() + 1
        while time.time() < deadline:
            has_quotes = any(key.startswith("quotes:") for key in cache.values)
            has_gold = "gold:Au99.99" in cache.values
            has_sectors = all(f"sectors:{market.value}" in cache.values for market in [Market.A, Market.HK, Market.US])
            has_details = any(key.startswith("sector-details:") for key in cache.values)
            if has_quotes and has_gold and has_sectors and has_details:
                break
            time.sleep(0.02)

    assert provider.quote_calls >= 1
    assert provider.gold_calls >= 1
    assert provider.sector_calls >= 3
    assert provider.sector_detail_calls >= 1
    assert any(key.startswith("quotes:") for key in cache.values)
    assert "gold:Au99.99" in cache.values
    assert all(f"sectors:{market.value}" in cache.values for market in [Market.A, Market.HK, Market.US])
    assert any(key.startswith("sector-details:") for key in cache.values)


def test_background_refresh_reports_timeout_in_health(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.json")
    provider = SlowSectorProvider()
    cache = FakeJsonCache()
    fast_provider = FakeProvider()
    for market in [Market.A, Market.HK, Market.US]:
        cache.set_json(f"sectors:{market.value}", fast_provider.get_sectors(market).model_dump(mode="json"), 60)

    app = create_app(
        store=store,
        provider=provider,
        cache=cache,
        background_refresh_seconds=0.5,
        background_provider_timeout_seconds=0.01,
    )
    with TestClient(app) as client:
        background_service = None
        deadline = time.time() + 1
        while time.time() < deadline:
            response = client.get("/api/health")
            services = {item["name"]: item for item in response.json()["services"]}
            background_service = services["Background refresh"]
            if background_service["status"] == "error":
                break
            time.sleep(0.02)

    assert background_service is not None
    assert background_service["status"] == "error"
    assert "timed out" in background_service["message"]


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
