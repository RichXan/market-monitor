from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed
from dataclasses import dataclass
from functools import cached_property
from time import monotonic
from typing import Any, Callable, Iterable

import pandas as pd

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
    WatchItem,
    utc_now_iso,
)
from app.store import normalize_symbol_for_market


@dataclass(frozen=True)
class MarketFrameResult:
    source: str
    frame: pd.DataFrame | None = None
    error: Exception | None = None


US_SECTOR_ETFS: list[tuple[str, str]] = [
    ("Technology", "XLK"),
    ("Financials", "XLF"),
    ("Health Care", "XLV"),
    ("Energy", "XLE"),
    ("Consumer Discretionary", "XLY"),
    ("Consumer Staples", "XLP"),
    ("Industrials", "XLI"),
    ("Materials", "XLB"),
    ("Utilities", "XLU"),
    ("Real Estate", "XLRE"),
    ("Communication Services", "XLC"),
]

HK_SECTOR_LABELS: dict[str, str] = {
    "Basic Materials": "原材料",
    "Communication Services": "通信服务",
    "Consumer Cyclical": "非必需消费",
    "Consumer Defensive": "必需消费",
    "Energy": "能源",
    "Financial Services": "金融服务",
    "Healthcare": "医疗保健",
    "Industrials": "工业",
    "Real Estate": "房地产",
    "Technology": "科技",
    "Utilities": "公用事业",
}


def _status(
    status: str,
    source: str,
    message: str | None = None,
    updated_at: str | None = None,
) -> ProviderStatus:
    return ProviderStatus(
        status=status, source=source, message=message, updated_at=updated_at or utc_now_iso()
    )


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _first_present(row: pd.Series, names: Iterable[str]) -> Any:
    for name in names:
        if name in row and not pd.isna(row[name]):
            return row[name]
    return None


def _compact_text(value: Any) -> str:
    return "".join(str(value).split())


class MarketDataProvider:
    def __init__(
        self,
        ak_module: Any | None = None,
        yf_module: Any | None = None,
        cache_ttl_seconds: int = 30,
        call_timeout_seconds: float = 1.5,
        sector_timeout_seconds: float = 10,
    ) -> None:
        self._ak_module = ak_module
        self._yf_module = yf_module
        self.cache_ttl_seconds = cache_ttl_seconds
        self.call_timeout_seconds = call_timeout_seconds
        self.sector_timeout_seconds = sector_timeout_seconds
        self._cache: dict[str, tuple[float, Any]] = {}

    @cached_property
    def ak(self) -> Any:
        if self._ak_module is not None:
            return self._ak_module
        import akshare as ak

        return ak

    @cached_property
    def yf(self) -> Any:
        if self._yf_module is not None:
            return self._yf_module
        import yfinance as yf

        return yf

    def get_quotes(self, items: list[WatchItem]) -> list[Quote]:
        quotes: list[Quote] = []
        frames: dict[Market, MarketFrameResult] = {}
        needed_markets = {item.market for item in items if item.market in {Market.A, Market.HK}}
        if needed_markets:
            with ThreadPoolExecutor(max_workers=len(needed_markets)) as executor:
                futures = {executor.submit(self._load_market_frame, market): market for market in needed_markets}
                for future in as_completed(futures):
                    frames[futures[future]] = future.result()

        for item in items:
            if item.market == Market.US:
                quotes.append(self._quote_from_yfinance(item))
            elif item.market == Market.A:
                quotes.append(self._quote_from_frame(item, frames[Market.A], "CNY"))
            elif item.market == Market.HK:
                quotes.append(self._quote_from_frame(item, frames[Market.HK], "HKD"))
        return quotes

    def search_symbols(self, market: Market, query: str, limit: int = 8) -> list[SymbolSearchResult]:
        normalized_query = query.strip()
        if not normalized_query:
            return []
        if market == Market.US:
            return self._search_us_symbols(normalized_query, limit)
        if market == Market.A:
            results = self._search_a_code_name_symbols(normalized_query, limit)
            if results:
                return results
        return self._search_symbols_from_market_frame(market, normalized_query, limit)

    def get_gold_quote(self, symbol: str = "Au99.99") -> GoldQuote:
        try:
            frame = self._call_provider(
                lambda: self.ak.spot_quotations_sge(symbol=symbol),
                "AKShare / Shanghai Gold Exchange",
            )
            if frame.empty:
                return GoldQuote(
                    symbol=symbol,
                    name=f"上海金 {symbol}",
                    status=_status(
                        "unavailable",
                        "AKShare / Shanghai Gold Exchange",
                        "Shanghai Gold Exchange returned no rows.",
                    ),
                )
            row = frame.iloc[-1]
            return GoldQuote(
                symbol=symbol,
                name=f"上海金 {symbol}",
                price=_float(_first_present(row, ["现价", "最新价", "price"])),
                status=_status(
                    "ok",
                    "AKShare / Shanghai Gold Exchange",
                    updated_at=str(_first_present(row, ["更新时间", "时间"]) or utc_now_iso()),
                ),
            )
        except Exception as exc:
            return GoldQuote(
                symbol=symbol,
                name=f"上海金 {symbol}",
                status=_status("error", "AKShare / Shanghai Gold Exchange", str(exc)),
            )

    def get_sectors(self, market: Market) -> SectorResponse:
        if market == Market.HK:
            return self._cached("sectors:hk", self._get_hk_sector_activity)
        if market == Market.US:
            return self._get_us_sector_etfs()
        return self._cached("sectors:a", self._get_a_share_sectors)

    def get_sector_details(self, market: Market, sector_name: str, limit: int = 12) -> SectorDetailResponse:
        if market == Market.US:
            return self._get_us_sector_details(sector_name, limit)
        if market == Market.HK:
            return self._get_hk_sector_details(sector_name, limit)
        return self._get_a_sector_details(sector_name, limit)

    def _get_a_share_sectors(self) -> SectorResponse:
        errors: list[str] = []
        loaders: list[tuple[str, Callable[[], pd.DataFrame]]] = [
            ("AKShare / Eastmoney sector boards", self._load_eastmoney_a_sector_frame),
            ("AKShare / Sina sector boards", lambda: self.ak.stock_sector_spot()),
        ]

        for source, loader in loaders:
            try:
                frame = self._call_provider(loader, source, timeout_seconds=self.sector_timeout_seconds)
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                continue

            items = self._frame_to_sector_items(frame)
            if not items:
                errors.append(f"{source}: empty response")
                continue
            items.sort(key=lambda item: item.change_percent if item.change_percent is not None else -9999, reverse=True)
            return SectorResponse(
                market=Market.A,
                items=items[:16],
                status=_status(
                    "ok",
                    source,
                    "; ".join(errors) if errors else None,
                ),
            )

        return SectorResponse(
            market=Market.A,
            items=[],
            status=_status(
                "unavailable",
                "AKShare / Eastmoney + Sina sector boards",
                f"A-share sector ranking source is temporarily unavailable: {'; '.join(errors) or 'No rows returned.'}",
            ),
        )

    def _load_eastmoney_a_sector_frame(self) -> pd.DataFrame:
        industry = self.ak.stock_board_industry_name_em()
        concept = self.ak.stock_board_concept_name_em()
        return pd.concat([industry, concept], ignore_index=True)

    def _load_market_frame(self, market: Market) -> MarketFrameResult:
        return self._cached(f"quote-frame:{market.value}", lambda: self._fetch_market_frame(market))

    def _fetch_market_frame(self, market: Market) -> MarketFrameResult:
        if market == Market.A:
            return self._first_market_frame(
                [
                    ("AKShare / Eastmoney A-share", lambda: self.ak.stock_zh_a_spot_em()),
                    ("AKShare / Sina A-share fallback", lambda: self.ak.stock_zh_a_spot()),
                ]
            )
        if market == Market.HK:
            return self._first_market_frame(
                [
                    ("AKShare / Eastmoney HK", lambda: self.ak.stock_hk_spot_em()),
                    ("AKShare / HK fallback", lambda: self.ak.stock_hk_spot()),
                ]
            )
        return MarketFrameResult(source="AKShare", frame=pd.DataFrame())

    def _first_market_frame(self, loaders: list[tuple[str, Callable[[], pd.DataFrame]]]) -> MarketFrameResult:
        errors: list[str] = []
        for source, loader in loaders:
            try:
                frame = self._call_provider(loader, source)
                if not frame.empty:
                    return MarketFrameResult(source=source, frame=frame)
                errors.append(f"{source}: empty response")
            except Exception as exc:
                errors.append(f"{source}: {exc}")
        return MarketFrameResult(
            source=loaders[-1][0],
            error=RuntimeError("; ".join(errors) or "No quote rows returned."),
        )

    def _cached(self, key: str, loader: Callable[[], Any]) -> Any:
        now = monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        value = loader()
        self._cache[key] = (now, value)
        return value

    def _call_provider(
        self,
        loader: Callable[[], pd.DataFrame],
        source: str,
        timeout_seconds: float | None = None,
    ) -> pd.DataFrame:
        return self._call_with_timeout(loader, source, timeout_seconds)

    def _call_with_timeout(
        self,
        loader: Callable[[], Any],
        source: str,
        timeout_seconds: float | None = None,
    ) -> Any:
        timeout = timeout_seconds if timeout_seconds is not None else self.call_timeout_seconds
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(loader)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise TimeoutError(f"{source} timed out after {timeout:g}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _get_hk_sector_activity(self) -> SectorResponse:
        source = "yfinance / Yahoo Finance HK active stocks"
        try:
            items = self._call_with_timeout(
                self._load_hk_sector_activity_items,
                source,
                timeout_seconds=max(self.sector_timeout_seconds, 12),
            )
        except Exception as exc:
            return SectorResponse(
                market=Market.HK,
                items=[],
                status=_status("unavailable", source, f"Hong Kong active sector data is unavailable: {exc}"),
            )

        if not items:
            return SectorResponse(
                market=Market.HK,
                items=[],
                status=_status("unavailable", source, "Yahoo Finance returned no usable Hong Kong sector rows."),
            )
        return SectorResponse(
            market=Market.HK,
            items=items[:16],
            status=_status(
                "ok",
                source,
                "Hong Kong sector activity is aggregated from Yahoo Finance active stock screeners.",
            ),
        )

    def _load_hk_sector_activity_items(self) -> list[SectorItem]:
        quotes = self._load_hk_active_quotes()
        if not quotes:
            return []

        quotes = quotes[:30]
        sector_by_symbol: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(quotes))) as executor:
            futures = {executor.submit(self._sector_for_hk_quote, quote): quote for quote in quotes}
            for future in as_completed(futures):
                quote = futures[future]
                symbol = str(quote.get("symbol") or "")
                try:
                    sector = future.result()
                except Exception:
                    sector = self._infer_hk_sector_from_quote(quote)
                if symbol and sector:
                    sector_by_symbol[symbol] = sector

        return self._aggregate_hk_sector_quotes(quotes, sector_by_symbol)

    def _load_hk_active_quotes(self) -> list[dict[str, Any]]:
        errors: list[str] = []
        quotes_by_symbol: dict[str, dict[str, Any]] = {}
        for query in ["most_actives_hk", "day_gainers_hk"]:
            try:
                data = self.yf.screen(query, count=40)
            except Exception as exc:
                errors.append(f"{query}: {exc}")
                continue

            for quote in data.get("quotes", []) if isinstance(data, dict) else []:
                symbol = str(quote.get("symbol") or "")
                if not symbol.endswith(".HK"):
                    continue
                existing = quotes_by_symbol.get(symbol)
                if existing is None:
                    quotes_by_symbol[symbol] = quote
                    continue
                current_volume = _float(quote.get("regularMarketVolume")) or 0
                existing_volume = _float(existing.get("regularMarketVolume")) or 0
                if current_volume > existing_volume:
                    quotes_by_symbol[symbol] = quote

        if not quotes_by_symbol and errors:
            raise RuntimeError("; ".join(errors))
        quotes = list(quotes_by_symbol.values())
        quotes.sort(key=lambda quote: _float(quote.get("regularMarketVolume")) or 0, reverse=True)
        return quotes

    def _sector_for_hk_quote(self, quote: dict[str, Any]) -> str | None:
        direct_sector = quote.get("sector") or quote.get("industry")
        if direct_sector:
            return str(direct_sector)

        symbol = str(quote.get("symbol") or "")
        if not symbol:
            return self._infer_hk_sector_from_quote(quote)
        info = self.yf.Ticker(symbol).info
        sector = info.get("sector") or info.get("industry")
        if sector:
            return str(sector)
        return self._infer_hk_sector_from_quote(quote)

    def _aggregate_hk_sector_quotes(
        self,
        quotes: list[dict[str, Any]],
        sector_by_symbol: dict[str, str],
    ) -> list[SectorItem]:
        groups: dict[str, dict[str, float]] = {}
        for quote in quotes:
            symbol = str(quote.get("symbol") or "")
            sector = sector_by_symbol.get(symbol) or self._infer_hk_sector_from_quote(quote)
            if not sector:
                continue

            name = HK_SECTOR_LABELS.get(sector, sector)
            group = groups.setdefault(
                name,
                {"weighted_change": 0.0, "weight": 0.0, "volume": 0.0, "amount": 0.0, "count": 0.0},
            )
            price = _float(quote.get("regularMarketPrice"))
            change_percent = _float(quote.get("regularMarketChangePercent"))
            volume = _float(quote.get("regularMarketVolume")) or 0.0
            amount = (price or 0.0) * volume
            weight = amount or volume or 1.0
            if change_percent is not None:
                group["weighted_change"] += change_percent * weight
                group["weight"] += weight
            group["volume"] += volume
            group["amount"] += amount
            group["count"] += 1

        items = [
            SectorItem(
                name=name,
                change_percent=round(group["weighted_change"] / group["weight"], 2) if group["weight"] else None,
                volume=group["volume"] or None,
                amount=group["amount"] or None,
            )
            for name, group in groups.items()
        ]
        items.sort(key=lambda item: item.amount or item.volume or 0, reverse=True)
        return items

    def _infer_hk_sector_from_quote(self, quote: dict[str, Any]) -> str | None:
        name = " ".join(
            str(quote.get(key) or "") for key in ["shortName", "longName", "symbol"]
        ).upper()
        keyword_sectors = [
            ("Financial Services", ["BANK", "HSBC", "INSURANCE", "AIA", "FINANC", "SECURITIES"]),
            ("Technology", ["TECH", "SEMICONDUCTOR", "SOFTWARE", "ELECTRONIC", "XIAOMI", "SENSETIME"]),
            ("Communication Services", ["TENCENT", "TELECOM", "MOBILE", "MEDIA", "ENTERTAINMENT"]),
            ("Real Estate", ["PROPERTY", "REAL ESTATE", "LAND", "GARDEN", "DEVELOPMENT"]),
            ("Energy", ["ENERGY", "OIL", "PETRO", "GAS", "COAL"]),
            ("Healthcare", ["PHARMA", "BIO", "HEALTH", "MEDICAL"]),
            ("Basic Materials", ["MATERIAL", "ALUMINUM", "STEEL", "CEMENT", "BUILDING"]),
            ("Consumer Cyclical", ["AUTO", "RETAIL", "HOTEL", "TRAVEL", "MEITUAN", "BABA"]),
            ("Industrials", ["INDUSTRIAL", "ENGINEERING", "CONSTRUCTION", "MACHINERY"]),
            ("Utilities", ["POWER", "UTILITY", "WATER", "ELECTRIC"]),
        ]
        for sector, keywords in keyword_sectors:
            if any(keyword in name for keyword in keywords):
                return sector
        return None

    def _get_us_sector_etfs(self) -> SectorResponse:
        items: list[SectorItem] = []
        errors: list[str] = []
        for name, symbol in US_SECTOR_ETFS:
            try:
                ticker = self.yf.Ticker(symbol)
                info = ticker.fast_info
                price = _float(info.get("lastPrice"))
                previous_close = _float(info.get("previousClose"))
                change = None
                change_percent = None
                if price is not None and previous_close not in (None, 0):
                    change = round(price - previous_close, 2)
                    change_percent = round((change / previous_close) * 100, 2)
                items.append(
                    SectorItem(
                        name=name,
                        price=price,
                        change=change,
                        change_percent=change_percent,
                        volume=_float(info.get("lastVolume") or info.get("volume")),
                    )
                )
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")

        items = [item for item in items if item.change_percent is not None]
        items.sort(key=lambda item: item.change_percent if item.change_percent is not None else -9999, reverse=True)
        if items:
            return SectorResponse(
                market=Market.US,
                items=items,
                status=_status(
                    "ok",
                    "yfinance / Yahoo Finance sector ETFs",
                    "US sector activity is represented by liquid sector ETF proxies.",
                ),
            )
        return SectorResponse(
            market=Market.US,
            items=[],
            status=_status(
                "unavailable",
                "yfinance / Yahoo Finance sector ETFs",
                "; ".join(errors) or "Yahoo Finance sector ETF proxy data is unavailable.",
            ),
        )

    def _get_us_sector_details(self, sector_name: str, limit: int) -> SectorDetailResponse:
        symbols = {name: symbol for name, symbol in US_SECTOR_ETFS}
        symbol = symbols.get(sector_name)
        if symbol is None:
            return SectorDetailResponse(
                market=Market.US,
                sector_name=sector_name,
                items=[],
                status=_status(
                    "unavailable",
                    "yfinance / Yahoo Finance sector ETFs",
                    f"No ETF proxy is configured for {sector_name}.",
                ),
            )

        quote = self._quote_from_yfinance(
            WatchItem(id=f"us:{symbol}", market=Market.US, symbol=symbol, name=f"{sector_name} ETF")
        )
        item = SectorConstituent(
            symbol=symbol,
            name=f"{sector_name} ETF",
            price=quote.price,
            change_percent=quote.change_percent,
            volume=quote.volume,
            amount=quote.amount,
            currency=quote.currency,
            source=quote.status.source,
        )
        return SectorDetailResponse(
            market=Market.US,
            sector_name=sector_name,
            items=[item][:limit],
            status=_status(
                quote.status.status if quote.status.status in {"ok", "partial", "unavailable", "error"} else "ok",
                "yfinance / Yahoo Finance sector ETFs",
                "US sector constituents are represented by the liquid sector ETF proxy.",
            ),
        )

    def _get_hk_sector_details(self, sector_name: str, limit: int) -> SectorDetailResponse:
        source = "yfinance / Yahoo Finance HK active stocks"
        try:
            quotes = self._load_hk_active_quotes()
        except Exception as exc:
            return SectorDetailResponse(
                market=Market.HK,
                sector_name=sector_name,
                items=[],
                status=_status("unavailable", source, str(exc)),
            )

        items: list[SectorConstituent] = []
        for quote in quotes:
            try:
                raw_sector = self._sector_for_hk_quote(quote)
            except Exception:
                raw_sector = self._infer_hk_sector_from_quote(quote)
            sector = HK_SECTOR_LABELS.get(raw_sector or "", raw_sector or "")
            if sector != sector_name:
                continue
            symbol = str(quote.get("symbol") or "")
            items.append(
                SectorConstituent(
                    symbol=symbol,
                    name=str(quote.get("shortName") or quote.get("longName") or symbol),
                    price=_float(quote.get("regularMarketPrice")),
                    change_percent=_float(quote.get("regularMarketChangePercent")),
                    volume=_float(quote.get("regularMarketVolume")),
                    amount=(_float(quote.get("regularMarketPrice")) or 0) * (_float(quote.get("regularMarketVolume")) or 0) or None,
                    currency="HKD",
                    source=source,
                )
            )
            if len(items) >= limit:
                break

        return SectorDetailResponse(
            market=Market.HK,
            sector_name=sector_name,
            items=items,
            status=_status(
                "ok" if items else "unavailable",
                source,
                None if items else f"No active Hong Kong stock rows matched {sector_name}.",
            ),
        )

    def _get_a_sector_details(self, sector_name: str, limit: int) -> SectorDetailResponse:
        errors: list[str] = []
        loaders: list[tuple[str, Callable[[], pd.DataFrame]]] = [
            ("AKShare / Eastmoney industry constituents", lambda: self.ak.stock_board_industry_cons_em(symbol=sector_name)),
            ("AKShare / Eastmoney concept constituents", lambda: self.ak.stock_board_concept_cons_em(symbol=sector_name)),
        ]

        for source, loader in loaders:
            try:
                frame = self._call_provider(loader, source, timeout_seconds=self.sector_timeout_seconds)
            except Exception as exc:
                errors.append(f"{source}: {exc}")
                continue

            items = self._frame_to_sector_constituents(frame, source)
            if items:
                items.sort(key=lambda item: item.change_percent if item.change_percent is not None else -9999, reverse=True)
                return SectorDetailResponse(
                    market=Market.A,
                    sector_name=sector_name,
                    items=items[:limit],
                    status=_status("ok", source, "; ".join(errors) if errors else None),
                )
            errors.append(f"{source}: empty response")

        return SectorDetailResponse(
            market=Market.A,
            sector_name=sector_name,
            items=[],
            status=_status(
                "unavailable",
                "AKShare / Eastmoney sector constituents",
                f"A-share sector constituents are unavailable: {'; '.join(errors) or 'No rows returned.'}",
            ),
        )

    def _quote_from_frame(
        self,
        item: WatchItem,
        result: MarketFrameResult,
        currency: str,
    ) -> Quote:
        if result.error is not None:
            fallback = self._quote_from_yahoo_fallback(item)
            if fallback is not None and fallback.status.status == "ok":
                return fallback
            return self._unavailable_quote(item, currency, result.source, str(result.error), "error")

        frame = result.frame.copy() if result.frame is not None else pd.DataFrame()
        code_column = self._code_column(frame)
        if frame.empty or code_column is None:
            fallback = self._quote_from_yahoo_fallback(item)
            if fallback is not None and fallback.status.status == "ok":
                return fallback
            return self._unavailable_quote(item, currency, result.source, "No quote rows returned.")

        wanted = normalize_symbol_for_market(item.market, item.symbol)
        codes = frame[code_column].astype(str).str.upper().str.replace(r"^(SH|SZ|BJ|HK)", "", regex=True)
        if item.market == Market.HK:
            codes = codes.str.zfill(5)
        matched = frame[codes == wanted]
        if matched.empty:
            fallback = self._quote_from_yahoo_fallback(item)
            if fallback is not None and fallback.status.status == "ok":
                return fallback
            return self._unavailable_quote(item, currency, result.source, f"No quote row found for {wanted}.")

        row = matched.iloc[0]
        name = str(_first_present(row, ["名称", "name", "中文名称"]) or item.name or item.symbol)
        return Quote(
            id=item.id,
            market=item.market,
            symbol=item.symbol,
            name=name,
            price=_float(_first_present(row, ["最新价", "现价", "price"])),
            change=_float(_first_present(row, ["涨跌额", "change"])),
            change_percent=_float(_first_present(row, ["涨跌幅", "changePercent"])),
            open=_float(_first_present(row, ["今开", "开盘价", "open"])),
            high=_float(_first_present(row, ["最高", "最高价", "high"])),
            low=_float(_first_present(row, ["最低", "最低价", "low"])),
            previous_close=_float(_first_present(row, ["昨收", "昨收价", "previousClose"])),
            volume=_float(_first_present(row, ["成交量", "volume"])),
            amount=_float(_first_present(row, ["成交额", "amount"])),
            currency=currency,
            status=_status("ok", result.source),
        )

    def _code_column(self, frame: pd.DataFrame) -> str | None:
        for column in ["代码", "symbol", "code", "股票代码"]:
            if column in frame.columns:
                return column
        return None

    def _name_column(self, frame: pd.DataFrame) -> str | None:
        for column in ["名称", "name", "股票名称", "中文名称", "shortName", "longName"]:
            if column in frame.columns:
                return column
        return None

    def _search_a_code_name_symbols(self, query: str, limit: int) -> list[SymbolSearchResult]:
        try:
            frame = self._cached(
                "symbol-search:a-code-name",
                lambda: self._call_provider(
                    self.ak.stock_info_a_code_name,
                    "AKShare / A-share code names",
                    timeout_seconds=max(self.call_timeout_seconds, 30),
                ),
            )
        except Exception:
            return []
        return self._search_symbols_in_frame(
            Market.A,
            frame,
            query,
            limit,
            "AKShare / A-share code names",
        )

    def _search_symbols_from_market_frame(
        self,
        market: Market,
        query: str,
        limit: int,
    ) -> list[SymbolSearchResult]:
        result = self._load_market_frame(market)
        if result.error is not None or result.frame is None or result.frame.empty:
            return []

        frame = result.frame.copy()
        code_column = self._code_column(frame)
        name_column = self._name_column(frame)
        if code_column is None or name_column is None:
            return []

        return self._search_symbols_in_frame(market, frame, query, limit, result.source)

    def _search_symbols_in_frame(
        self,
        market: Market,
        frame: pd.DataFrame,
        query: str,
        limit: int,
        source: str,
    ) -> list[SymbolSearchResult]:
        code_column = self._code_column(frame)
        name_column = self._name_column(frame)
        if frame.empty or code_column is None or name_column is None:
            return []

        query_upper = query.upper()
        compact_query = _compact_text(query)
        compact_query_upper = compact_query.upper()
        normalized_symbol_query = normalize_symbol_for_market(market, query)
        scored: list[tuple[int, int, SymbolSearchResult]] = []
        for index, row in frame.iterrows():
            raw_code = str(row[code_column]).upper()
            symbol = raw_code.replace("SH", "").replace("SZ", "").replace("BJ", "").replace("HK", "")
            symbol = normalize_symbol_for_market(market, symbol)
            name = _compact_text(row[name_column])
            name_upper = name.upper()
            if normalized_symbol_query == symbol:
                score = 0
            elif name.startswith(query) or name_upper.startswith(query_upper) or name.startswith(compact_query) or name_upper.startswith(compact_query_upper):
                score = 1
            elif query in name or query_upper in name_upper or compact_query in name or compact_query_upper in name_upper:
                score = 2
            elif query_upper in symbol:
                score = 3
            else:
                continue
            scored.append(
                (
                    score,
                    int(index),
                    SymbolSearchResult(market=market, symbol=symbol, name=name, source=source),
                )
            )

        scored.sort(key=lambda item: (item[0], item[1]))
        return [item for _, _, item in scored[:limit]]

    def _search_us_symbols(self, query: str, limit: int) -> list[SymbolSearchResult]:
        try:
            search = self.yf.Search(
                query,
                max_results=limit,
                news_count=0,
                lists_count=0,
                include_cb=False,
                include_nav_links=False,
                include_research=False,
                include_cultural_assets=False,
                recommended=0,
            )
        except Exception:
            return []

        results: list[SymbolSearchResult] = []
        for quote in getattr(search, "quotes", []) or []:
            symbol = str(quote.get("symbol") or "").upper()
            if not symbol or "." in symbol:
                continue
            quote_type = str(quote.get("quoteType") or "").upper()
            if quote_type and quote_type not in {"EQUITY", "ETF"}:
                continue
            name = str(quote.get("shortname") or quote.get("longname") or symbol)
            results.append(
                SymbolSearchResult(
                    market=Market.US,
                    symbol=symbol,
                    name=name,
                    source="yfinance / Yahoo Finance search",
                )
            )
            if len(results) >= limit:
                break
        return results

    def _quote_from_yfinance(
        self,
        item: WatchItem,
        ticker_symbol: str | None = None,
        source: str = "yfinance / Yahoo Finance",
    ) -> Quote:
        try:
            ticker = self.yf.Ticker(ticker_symbol or item.symbol)
            info = ticker.fast_info
            price = _float(info.get("lastPrice"))
            previous_close = _float(info.get("previousClose"))
            change = None
            change_percent = None
            if price is not None and previous_close not in (None, 0):
                change = round(price - previous_close, 2)
                change_percent = round((change / previous_close) * 100, 2)
            return Quote(
                id=item.id,
                market=item.market,
                symbol=item.symbol,
                name=item.name or item.symbol,
                price=price,
                change=change,
                change_percent=change_percent,
                open=_float(info.get("open")),
                high=_float(info.get("dayHigh")),
                low=_float(info.get("dayLow")),
                previous_close=previous_close,
                volume=_float(info.get("lastVolume") or info.get("volume")),
                currency=str(info.get("currency") or "USD"),
                status=_status("ok", source),
            )
        except Exception as exc:
            return self._unavailable_quote(item, "USD", source, str(exc), "error")

    def _quote_from_yahoo_fallback(self, item: WatchItem) -> Quote | None:
        ticker_symbol = self._yahoo_symbol_for_market(item)
        if ticker_symbol is None:
            return None
        return self._quote_from_yfinance(
            item,
            ticker_symbol=ticker_symbol,
            source="yfinance / Yahoo Finance fallback",
        )

    def _yahoo_symbol_for_market(self, item: WatchItem) -> str | None:
        symbol = normalize_symbol_for_market(item.market, item.symbol)
        if item.market == Market.HK and symbol.isdigit():
            return f"{int(symbol):04d}.HK"
        if item.market == Market.A and symbol.isdigit():
            if symbol.startswith("6"):
                return f"{symbol}.SS"
            if symbol.startswith(("0", "3")):
                return f"{symbol}.SZ"
            if symbol.startswith(("4", "8", "9")):
                return f"{symbol}.BJ"
        return None

    def _unavailable_quote(
        self,
        item: WatchItem,
        currency: str,
        source: str,
        message: str,
        status: str = "unavailable",
    ) -> Quote:
        return Quote(
            id=item.id,
            market=item.market,
            symbol=item.symbol,
            name=item.name or item.symbol,
            currency=currency,
            status=_status(status, source, message),
        )

    def _frame_to_sector_items(self, frame: pd.DataFrame) -> list[SectorItem]:
        items: list[SectorItem] = []
        if frame.empty:
            return items
        for _, row in frame.iterrows():
            name = _first_present(row, ["板块名称", "板块", "名称", "行业", "行业名称", "name"])
            if name is None:
                continue
            items.append(
                SectorItem(
                    name=str(name),
                    price=_float(_first_present(row, ["最新价", "现价", "平均价格", "行业指数", "price"])),
                    change=_float(_first_present(row, ["涨跌额", "change"])),
                    change_percent=_float(_first_present(row, ["涨跌幅", "行业-涨跌幅", "changePercent"])),
                    volume=_float(_first_present(row, ["成交量", "总成交量", "volume"])),
                    amount=_float(_first_present(row, ["成交额", "总成交额", "amount"])),
                )
            )
        return items

    def _frame_to_sector_constituents(self, frame: pd.DataFrame, source: str) -> list[SectorConstituent]:
        items: list[SectorConstituent] = []
        if frame.empty:
            return items
        for _, row in frame.iterrows():
            symbol = _first_present(row, ["代码", "symbol", "code", "股票代码"])
            name = _first_present(row, ["名称", "name", "股票名称", "中文名称"])
            if symbol is None or name is None:
                continue
            items.append(
                SectorConstituent(
                    symbol=normalize_symbol_for_market(Market.A, str(symbol)),
                    name=str(name),
                    price=_float(_first_present(row, ["最新价", "现价", "price"])),
                    change_percent=_float(_first_present(row, ["涨跌幅", "changePercent"])),
                    volume=_float(_first_present(row, ["成交量", "volume"])),
                    amount=_float(_first_present(row, ["成交额", "amount"])),
                    currency="CNY",
                    source=source,
                )
            )
        return items
