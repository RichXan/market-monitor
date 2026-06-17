import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.cache import InMemoryJsonCache, JsonCache, RedisJsonCache
from app.models import GoldQuote, Market, OverviewResponse, Quote, SectorResponse, SymbolSearchResult, WatchItem, WatchItemCreate
from app.providers import MarketDataProvider
from app.store import WatchlistStore, make_watch_id, normalize_symbol_for_market


ModelT = TypeVar("ModelT", bound=BaseModel)


def merge_symbol_results(results: list[SymbolSearchResult], limit: int) -> list[SymbolSearchResult]:
    seen: set[tuple[Market, str]] = set()
    merged: list[SymbolSearchResult] = []
    for item in results:
        key = (item.market, item.symbol)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged


def default_data_path() -> Path:
    root = Path(os.environ.get("MARKET_MONITOR_DATA", "data"))
    return root / "watchlist.json"


def default_cache() -> JsonCache:
    redis_url = os.environ.get("MARKET_MONITOR_REDIS_URL") or os.environ.get("REDIS_URL")
    if redis_url:
        return RedisJsonCache(redis_url)
    return InMemoryJsonCache()


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def cache_models(
    cache: JsonCache,
    key: str,
    ttl_seconds: int,
    model: type[ModelT],
    loader: Callable[[], list[ModelT]],
) -> list[ModelT]:
    cached = cache.get_json(key)
    if cached is not None:
        return [model.model_validate(item) for item in cached]
    value = loader()
    cache.set_json(key, [item.model_dump(mode="json") for item in value], ttl_seconds)
    return value


def cache_model(
    cache: JsonCache,
    key: str,
    ttl_seconds: int,
    model: type[ModelT],
    loader: Callable[[], ModelT],
) -> ModelT:
    cached = cache.get_json(key)
    if cached is not None:
        return model.model_validate(cached)
    value = loader()
    cache.set_json(key, value.model_dump(mode="json"), ttl_seconds)
    return value


def watchlist_cache_key(items: list[WatchItem]) -> str:
    raw = json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"quotes:{digest}"


def is_valid_market_symbol(market: Market, symbol: str) -> bool:
    normalized = normalize_symbol_for_market(market, symbol)
    if market == Market.A:
        return normalized.isdigit() and len(normalized) == 6
    if market == Market.HK:
        return normalized.isdigit() and len(normalized) == 5
    return normalized.isascii() and any(char.isalpha() for char in normalized)


def create_app(
    store: WatchlistStore | None = None,
    provider: MarketDataProvider | None = None,
    cache: JsonCache | None = None,
) -> FastAPI:
    app = FastAPI(title="Market Monitor API")
    watchlist_store = store or WatchlistStore(default_data_path())
    market_provider = provider or MarketDataProvider()
    market_cache = cache or default_cache()
    quote_cache_ttl = env_int("MARKET_MONITOR_QUOTE_CACHE_TTL_SECONDS", 15)
    gold_cache_ttl = env_int("MARKET_MONITOR_GOLD_CACHE_TTL_SECONDS", 15)
    sector_cache_ttl = env_int("MARKET_MONITOR_SECTOR_CACHE_TTL_SECONDS", 60)

    def resolve_watch_payload(payload: WatchItemCreate) -> WatchItemCreate:
        if is_valid_market_symbol(payload.market, payload.symbol):
            return payload
        query = payload.name or payload.symbol
        matches = market_provider.search_symbols(payload.market, query, limit=1)
        if not matches:
            return payload
        match = matches[0]
        return WatchItemCreate(market=match.market, symbol=match.symbol, name=match.name)

    def resolved_watchlist() -> list[WatchItem]:
        items = watchlist_store.list_items()
        changed = False
        resolved: list[WatchItem] = []
        seen: set[str] = set()

        for item in items:
            next_payload = resolve_watch_payload(WatchItemCreate(market=item.market, symbol=item.symbol, name=item.name))
            next_item = WatchItem(
                id=make_watch_id(next_payload.market, next_payload.symbol),
                market=next_payload.market,
                symbol=normalize_symbol_for_market(next_payload.market, next_payload.symbol),
                name=next_payload.name,
            )
            if next_item.id != item.id or next_item.name != item.name:
                changed = True
            if next_item.id in seen:
                changed = True
                continue
            seen.add(next_item.id)
            resolved.append(next_item)

        if changed:
            watchlist_store.replace_items(resolved)
        return resolved

    def cached_quotes(items: list[WatchItem]) -> list[Quote]:
        return cache_models(
            market_cache,
            watchlist_cache_key(items),
            quote_cache_ttl,
            Quote,
            lambda: market_provider.get_quotes(items),
        )

    def cached_gold() -> GoldQuote:
        return cache_model(
            market_cache,
            "gold:Au99.99",
            gold_cache_ttl,
            GoldQuote,
            market_provider.get_gold_quote,
        )

    def cached_sectors(market: Market) -> SectorResponse:
        return cache_model(
            market_cache,
            f"sectors:{market.value}",
            sector_cache_ttl,
            SectorResponse,
            lambda: market_provider.get_sectors(market),
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/watchlist", response_model=list[WatchItem])
    def list_watchlist() -> list[WatchItem]:
        return resolved_watchlist()

    @app.post("/api/watchlist", response_model=WatchItem)
    def add_watch_item(payload: WatchItemCreate) -> WatchItem:
        return watchlist_store.add_item(resolve_watch_payload(payload))

    @app.delete("/api/watchlist/{item_id}")
    def delete_watch_item(item_id: str) -> dict[str, bool]:
        return {"deleted": watchlist_store.delete_item(item_id)}

    @app.get("/api/quotes", response_model=list[Quote])
    def get_quotes() -> list[Quote]:
        return cached_quotes(resolved_watchlist())

    @app.get("/api/gold", response_model=GoldQuote)
    def get_gold() -> GoldQuote:
        return cached_gold()

    @app.get("/api/sectors", response_model=SectorResponse)
    def get_sectors(market: Market) -> SectorResponse:
        return cached_sectors(market)

    @app.get("/api/search-symbols", response_model=list[SymbolSearchResult])
    def search_symbols(
        market: Market,
        q: str = Query(min_length=1, max_length=64),
        limit: int = Query(default=8, ge=1, le=20),
    ) -> list[SymbolSearchResult]:
        query = q.strip()
        query_upper = query.upper()
        local_matches = [
            SymbolSearchResult(
                market=item.market,
                symbol=item.symbol,
                name=item.name or item.symbol,
                source="本地自选",
            )
            for item in resolved_watchlist()
            if item.market == market
            and (
                query_upper in item.symbol.upper()
                or (item.name is not None and (query in item.name or query_upper in item.name.upper()))
            )
        ]
        provider_matches = market_provider.search_symbols(market, query, limit=limit)
        return merge_symbol_results([*local_matches, *provider_matches], limit)

    @app.get("/api/overview", response_model=OverviewResponse)
    def get_overview() -> OverviewResponse:
        watchlist = resolved_watchlist()
        with ThreadPoolExecutor(max_workers=5) as executor:
            quotes_future = executor.submit(cached_quotes, watchlist)
            gold_future = executor.submit(cached_gold)
            sector_futures = [
                executor.submit(cached_sectors, Market.A),
                executor.submit(cached_sectors, Market.HK),
                executor.submit(cached_sectors, Market.US),
            ]
        return OverviewResponse(
            watchlist=watchlist,
            quotes=quotes_future.result(),
            gold=gold_future.result(),
            sectors=[future.result() for future in sector_futures],
        )

    return app


app = create_app()
