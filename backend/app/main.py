import asyncio
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from datetime import datetime, time
from pathlib import Path
from typing import Callable, TypeVar
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.cache import InMemoryJsonCache, JsonCache, RedisJsonCache
from app.models import (
    GoldQuote,
    HealthResponse,
    HealthService,
    IndexQuote,
    Market,
    MarketStatus,
    OverviewResponse,
    Quote,
    SectorDetailResponse,
    SectorResponse,
    SymbolSearchResult,
    WatchItem,
    WatchItemCreate,
    utc_now_iso,
)
from app.providers import MarketDataProvider
from app.store import WatchlistStore, make_watch_id, normalize_symbol_for_market


ModelT = TypeVar("ModelT", bound=BaseModel)
MARKETS = [Market.A, Market.HK, Market.US]


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


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def set_cached_models(cache: JsonCache, key: str, ttl_seconds: int, value: list[ModelT]) -> list[ModelT]:
    cache.set_json(key, [item.model_dump(mode="json") for item in value], ttl_seconds)
    return value


def set_cached_model(cache: JsonCache, key: str, ttl_seconds: int, value: ModelT) -> ModelT:
    cache.set_json(key, value.model_dump(mode="json"), ttl_seconds)
    return value


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
    return set_cached_models(cache, key, ttl_seconds, value)


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
    return set_cached_model(cache, key, ttl_seconds, value)


def watchlist_cache_key(items: list[WatchItem]) -> str:
    raw = json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"quotes:{digest}"


def sector_details_cache_key(market: Market, sector_name: str, limit: int) -> str:
    safe_sector = hashlib.sha256(sector_name.encode("utf-8")).hexdigest()
    return f"sector-details:{market.value}:{safe_sector}:{limit}"


def is_valid_market_symbol(market: Market, symbol: str) -> bool:
    normalized = normalize_symbol_for_market(market, symbol)
    if market == Market.A:
        return normalized.isdigit() and len(normalized) == 6
    if market == Market.HK:
        return normalized.isdigit() and len(normalized) == 5
    return normalized.isascii() and any(char.isalpha() for char in normalized)


def session_state(now: datetime, sessions: list[tuple[time, time]]) -> str:
    if now.weekday() >= 5:
        return "closed"
    current = now.time()
    if any(start <= current <= end for start, end in sessions):
        return "trading"
    first_start = sessions[0][0]
    last_end = sessions[-1][1]
    if current < first_start:
        return "pre_market"
    if any(sessions[index][1] < current < sessions[index + 1][0] for index in range(len(sessions) - 1)):
        return "break"
    if current > last_end:
        return "after_hours"
    return "closed"


def market_statuses(now_utc: datetime | None = None) -> list[MarketStatus]:
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    configs = [
        (
            Market.A,
            "Asia/Shanghai",
            "09:30-11:30 / 13:00-15:00",
            [(time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))],
        ),
        (
            Market.HK,
            "Asia/Hong_Kong",
            "09:30-12:00 / 13:00-16:00",
            [(time(9, 30), time(12, 0)), (time(13, 0), time(16, 0))],
        ),
        (
            Market.US,
            "America/New_York",
            "04:00-09:30 盘前 / 09:30-16:00 正常 / 16:00-20:00 盘后",
            [(time(9, 30), time(16, 0))],
        ),
        (
            Market.CRYPTO,
            "UTC",
            "24/7",
            [(time(0, 0), time(23, 59, 59))],
        ),
    ]
    labels = {
        "trading": "交易中",
        "break": "午间休市",
        "pre_market": "盘前",
        "after_hours": "盘后",
        "closed": "休市",
    }
    statuses: list[MarketStatus] = []
    for market, timezone, session, sessions in configs:
        local_now = now_utc.astimezone(ZoneInfo(timezone))
        if market == Market.CRYPTO:
            state = "trading"
            label = "24/7"
        elif market == Market.US and local_now.weekday() < 5:
            current = local_now.time()
            if time(4, 0) <= current < time(9, 30):
                state = "pre_market"
            elif time(16, 0) < current <= time(20, 0):
                state = "after_hours"
            else:
                state = session_state(local_now, sessions)
            label = labels[state]
        else:
            state = session_state(local_now, sessions)
            label = labels[state]
        statuses.append(
            MarketStatus(
                market=market,
                state=state,
                label=label,
                timezone=timezone,
                session=session,
                updated_at=now_utc.isoformat(),
            )
        )
    return statuses


def aggregate_status(statuses: list[str]) -> str:
    if any(status == "error" for status in statuses):
        return "error"
    if any(status in {"partial", "unavailable"} for status in statuses):
        return "partial"
    return "ok"


def create_app(
    store: WatchlistStore | None = None,
    provider: MarketDataProvider | None = None,
    cache: JsonCache | None = None,
    background_refresh_seconds: float | None = None,
    background_provider_timeout_seconds: float | None = None,
) -> FastAPI:
    watchlist_store = store or WatchlistStore(default_data_path())
    market_provider = provider or MarketDataProvider()
    market_cache = cache or default_cache()
    quote_cache_ttl = env_int("MARKET_MONITOR_QUOTE_CACHE_TTL_SECONDS", 15)
    index_cache_ttl = env_int("MARKET_MONITOR_INDEX_CACHE_TTL_SECONDS", 15)
    gold_cache_ttl = env_int("MARKET_MONITOR_GOLD_CACHE_TTL_SECONDS", 15)
    sector_cache_ttl = env_int("MARKET_MONITOR_SECTOR_CACHE_TTL_SECONDS", 60)
    sector_detail_refresh_count = env_int("MARKET_MONITOR_BACKGROUND_SECTOR_DETAIL_COUNT", 3)
    refresh_interval_seconds = (
        env_float("MARKET_MONITOR_BACKGROUND_REFRESH_SECONDS", 60.0)
        if background_refresh_seconds is None
        else background_refresh_seconds
    )
    refresh_call_timeout_seconds = (
        env_float("MARKET_MONITOR_BACKGROUND_PROVIDER_TIMEOUT_SECONDS", 30.0)
        if background_provider_timeout_seconds is None
        else background_provider_timeout_seconds
    )
    refresh_state = {
        "status": "partial" if refresh_interval_seconds > 0 else "unavailable",
        "source": f"{refresh_interval_seconds:g}s interval" if refresh_interval_seconds > 0 else "disabled",
        "updated_at": utc_now_iso(),
        "message": "Waiting for first refresh" if refresh_interval_seconds > 0 else "Background refresh disabled",
    }

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

    def refresh_quotes_cache(items: list[WatchItem]) -> list[Quote]:
        return set_cached_models(
            market_cache,
            watchlist_cache_key(items),
            quote_cache_ttl,
            market_provider.get_quotes(items),
        )

    def cached_indexes() -> list[IndexQuote]:
        return cache_models(
            market_cache,
            "indexes:global",
            index_cache_ttl,
            IndexQuote,
            market_provider.get_index_quotes,
        )

    def refresh_index_cache() -> list[IndexQuote]:
        return set_cached_models(
            market_cache,
            "indexes:global",
            index_cache_ttl,
            market_provider.get_index_quotes(),
        )

    def cached_gold() -> GoldQuote:
        return cache_model(
            market_cache,
            "gold:Au99.99",
            gold_cache_ttl,
            GoldQuote,
            market_provider.get_gold_quote,
        )

    def refresh_gold_cache() -> GoldQuote:
        return set_cached_model(
            market_cache,
            "gold:Au99.99",
            gold_cache_ttl,
            market_provider.get_gold_quote(),
        )

    def cached_sectors(market: Market) -> SectorResponse:
        return cache_model(
            market_cache,
            f"sectors:{market.value}",
            sector_cache_ttl,
            SectorResponse,
            lambda: market_provider.get_sectors(market),
        )

    def refresh_sector_cache(market: Market) -> SectorResponse:
        return set_cached_model(
            market_cache,
            f"sectors:{market.value}",
            sector_cache_ttl,
            market_provider.get_sectors(market),
        )

    def cached_sector_details(market: Market, sector_name: str, limit: int) -> SectorDetailResponse:
        return cache_model(
            market_cache,
            sector_details_cache_key(market, sector_name, limit),
            sector_cache_ttl,
            SectorDetailResponse,
            lambda: market_provider.get_sector_details(market, sector_name, limit=limit),
        )

    def refresh_sector_details_cache(market: Market, sector_name: str, limit: int) -> SectorDetailResponse:
        return set_cached_model(
            market_cache,
            sector_details_cache_key(market, sector_name, limit),
            sector_cache_ttl,
            market_provider.get_sector_details(market, sector_name, limit=limit),
        )

    def health_service_from_cached_raw(
        name: str,
        raw: object | None,
        model: type[ModelT],
        empty_message: str,
    ) -> HealthService:
        if raw is None:
            return HealthService(
                name=name,
                status="partial",
                source=type(market_cache).__name__,
                updated_at=utc_now_iso(),
                message=empty_message,
            )
        try:
            values = [model.model_validate(item) for item in raw] if isinstance(raw, list) else [model.model_validate(raw)]
        except Exception as exc:
            return HealthService(
                name=name,
                status="error",
                source=type(market_cache).__name__,
                updated_at=utc_now_iso(),
                message=f"Cached {name.lower()} data is invalid: {exc}",
            )
        statuses = [item.status for item in values if hasattr(item, "status")]
        return HealthService(
            name=name,
            status=aggregate_status([status.status for status in statuses]),
            source=" / ".join(sorted({status.source for status in statuses})) or type(market_cache).__name__,
            updated_at=max((status.updated_at for status in statuses), default=utc_now_iso()),
        )

    def quote_health_service() -> HealthService:
        items = watchlist_store.list_items()
        return health_service_from_cached_raw(
            "Quotes",
            market_cache.get_json(watchlist_cache_key(items)),
            Quote,
            "No cached quote data yet. The background refresher or /api/quotes will populate it.",
        )

    def sectors_health_service() -> HealthService:
        raws = [market_cache.get_json(f"sectors:{market.value}") for market in MARKETS]
        missing = [market.value for market, raw in zip(MARKETS, raws) if raw is None]
        if missing:
            return HealthService(
                name="Sectors",
                status="partial",
                source=type(market_cache).__name__,
                updated_at=utc_now_iso(),
                message=f"No cached sector data yet for: {', '.join(missing)}.",
            )
        try:
            sectors = [SectorResponse.model_validate(raw) for raw in raws]
        except Exception as exc:
            return HealthService(
                name="Sectors",
                status="error",
                source=type(market_cache).__name__,
                updated_at=utc_now_iso(),
                message=f"Cached sectors data is invalid: {exc}",
            )
        statuses = [sector.status for sector in sectors]
        return HealthService(
            name="Sectors",
            status=aggregate_status([status.status for status in statuses]),
            source=" / ".join(sorted({status.source for status in statuses})) or type(market_cache).__name__,
            updated_at=max((status.updated_at for status in statuses), default=utc_now_iso()),
        )

    async def refresh_market_cache_once() -> tuple[str, str]:
        watchlist = await refresh_call("watchlist", resolved_watchlist)
        initial_results = await asyncio.gather(
            refresh_call("quotes", refresh_quotes_cache, watchlist),
            refresh_call("indexes", refresh_index_cache),
            refresh_call("gold", refresh_gold_cache),
            *(refresh_call(f"{market.value} sectors", refresh_sector_cache, market) for market in MARKETS),
            return_exceptions=True,
        )
        core_errors = [result for result in initial_results if isinstance(result, Exception)]
        if core_errors:
            messages = "; ".join(str(error) for error in core_errors[:3])
            raise RuntimeError(messages)

        sector_responses = [result for result in initial_results[3:] if isinstance(result, SectorResponse)]
        detail_limit = max(0, sector_detail_refresh_count)
        detail_tasks = [
            refresh_call(f"{response.market.value} {item.name} sector details", refresh_sector_details_cache, response.market, item.name, 12)
            for response in sector_responses
            for item in response.items[:detail_limit]
        ]
        detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True) if detail_tasks else []
        detail_errors = [result for result in detail_results if isinstance(result, Exception)]
        index_result = initial_results[1]
        counts = {
            "quotes": len(watchlist),
            "indexes": len(index_result) if isinstance(index_result, list) else 0,
            "sectors": len(sector_responses),
            "sector_details": sum(1 for result in detail_results if not isinstance(result, Exception)),
        }
        message = (
            f"Cached {counts['quotes']} quotes, "
            f"{counts['indexes']} index panels, "
            f"{counts['sectors']} sector panels, "
            f"{counts['sector_details']} sector detail panels"
        )
        if detail_errors:
            messages = "; ".join(str(error) for error in detail_errors[:3])
            return "partial", f"{message}; sector detail preload partial: {messages}"
        return "ok", message

    async def refresh_call(label: str, func: Callable, *args):
        try:
            call = asyncio.to_thread(func, *args)
            if refresh_call_timeout_seconds <= 0:
                return await call
            return await asyncio.wait_for(call, timeout=refresh_call_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"{label} timed out after {refresh_call_timeout_seconds:g}s") from exc

    async def background_refresh_loop() -> None:
        while True:
            try:
                status, message = await refresh_market_cache_once()
                refresh_state.update(
                    status=status,
                    updated_at=utc_now_iso(),
                    message=message,
                )
            except Exception as exc:
                refresh_state.update(status="error", updated_at=utc_now_iso(), message=str(exc))
            await asyncio.sleep(refresh_interval_seconds)

    refresh_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal refresh_task
        if refresh_interval_seconds > 0:
            refresh_task = asyncio.create_task(background_refresh_loop())
        try:
            yield
        finally:
            if refresh_task is not None:
                refresh_task.cancel()
                with suppress(asyncio.CancelledError):
                    await refresh_task

    app = FastAPI(title="Market Monitor API", lifespan=lifespan)

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

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        services = [
            HealthService(
                name="FastAPI",
                status="ok",
                source="local api",
                updated_at=utc_now_iso(),
            ),
            HealthService(
                name="Cache",
                status="ok",
                source=type(market_cache).__name__,
                updated_at=utc_now_iso(),
            ),
            HealthService(
                name="Background refresh",
                status=refresh_state["status"],
                source=refresh_state["source"],
                updated_at=refresh_state["updated_at"],
                message=refresh_state["message"],
            ),
        ]
        services.append(quote_health_service())
        services.append(
            health_service_from_cached_raw(
                "Gold",
                market_cache.get_json("gold:Au99.99"),
                GoldQuote,
                "No cached gold data yet. The background refresher or /api/gold will populate it.",
            )
        )
        services.append(
            health_service_from_cached_raw(
                "Indexes",
                market_cache.get_json("indexes:global"),
                IndexQuote,
                "No cached index data yet. The background refresher or /api/indexes will populate it.",
            )
        )
        services.append(sectors_health_service())
        return HealthResponse(status="ok", services=services)

    @app.get("/api/market-status", response_model=list[MarketStatus])
    def get_market_status() -> list[MarketStatus]:
        return market_statuses()

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

    @app.get("/api/indexes", response_model=list[IndexQuote])
    def get_indexes() -> list[IndexQuote]:
        return cached_indexes()

    @app.get("/api/gold", response_model=GoldQuote)
    def get_gold() -> GoldQuote:
        return cached_gold()

    @app.get("/api/sectors", response_model=SectorResponse)
    def get_sectors(market: Market) -> SectorResponse:
        return cached_sectors(market)

    @app.get("/api/sector-details", response_model=SectorDetailResponse)
    def get_sector_details(
        market: Market,
        sector: str = Query(min_length=1, max_length=64),
        limit: int = Query(default=12, ge=1, le=30),
    ) -> SectorDetailResponse:
        return cached_sector_details(market, sector.strip(), limit)

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
