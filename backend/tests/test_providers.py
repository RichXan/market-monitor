import time
from threading import Lock

import pandas as pd

from app.models import IndexQuote, Market, ProviderStatus, WatchItem
from app.providers import MarketDataProvider


class FakeFastInfo(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        currency = "USD"
        last_volume = 55000000
        market_cap = 3_200_000_000_000
        if symbol.endswith(".HK"):
            currency = "HKD"
        if symbol.endswith((".SS", ".SZ")):
            currency = "CNY"
        last_price = 192.4
        previous_close = 190.0
        if symbol == "XLK":
            last_price = 210.0
            previous_close = 200.0
        if symbol == "XLF":
            last_price = 49.0
            previous_close = 50.0
        if symbol == "XLV":
            last_price = 101.0
            previous_close = 100.0
        if symbol == "BTC-USD":
            last_price = 65000.0
            previous_close = 64000.0
            last_volume = 3575000000
            market_cap = 1_280_000_000_000
        if symbol == "000001.SS":
            last_price = 3100.0
            previous_close = 3080.0
        if symbol == "^HSI":
            currency = "HKD"
            last_price = 18000.0
            previous_close = 18100.0
        if symbol == "^GSPC":
            last_price = 4900.0
            previous_close = 4880.0
        if symbol.startswith("XL") and symbol not in {"XLK", "XLF", "XLV"}:
            last_price = 100.0
            previous_close = 100.0
        self.fast_info = FakeFastInfo(
            {
                "lastPrice": last_price,
                "previousClose": previous_close,
                "dayHigh": last_price + 1,
                "dayLow": last_price - 1,
                "open": previous_close,
                "lastVolume": last_volume,
                "currency": currency,
            }
        )
        hk_info = {
            "0700.HK": ("Communication Services", "Internet Content & Information"),
            "0005.HK": ("Financial Services", "Banks - Diversified"),
            "3323.HK": ("Basic Materials", "Building Materials"),
            "1810.HK": ("Technology", "Consumer Electronics"),
        }
        sector, industry = hk_info.get(symbol, ("Technology", "Software - Application"))
        self.info = {
            "sector": sector,
            "industry": industry,
            "shortName": symbol,
            "averageVolume": 50_000_000,
            "trailingPE": 29.48,
            "marketCap": market_cap,
        }


class FakeSearch:
    def __init__(self, query: str) -> None:
        if query.lower().startswith("apple"):
            self.quotes = [
                {
                    "symbol": "AAPL",
                    "shortname": "Apple Inc.",
                    "longname": "Apple Inc.",
                    "quoteType": "EQUITY",
                    "exchange": "NMS",
                }
            ]
        else:
            self.quotes = []


class FakeYFinance:
    def Ticker(self, symbol: str, session=None) -> FakeTicker:
        return FakeTicker(symbol)

    def Search(self, query: str, **kwargs) -> FakeSearch:
        return FakeSearch(query)

    def screen(self, query: str, count: int = 25):
        assert query in {"most_actives_hk", "day_gainers_hk"}
        quotes = [
            {
                "symbol": "0700.HK",
                "regularMarketPrice": 445.0,
                "regularMarketChangePercent": 2.0,
                "regularMarketVolume": 100_000_000,
            },
            {
                "symbol": "0005.HK",
                "regularMarketPrice": 148.0,
                "regularMarketChangePercent": -1.0,
                "regularMarketVolume": 60_000_000,
            },
            {
                "symbol": "3323.HK",
                "regularMarketPrice": 6.5,
                "regularMarketChangePercent": 6.0,
                "regularMarketVolume": 20_000_000,
            },
            {
                "symbol": "1810.HK",
                "regularMarketPrice": 25.3,
                "regularMarketChangePercent": 3.0,
                "regularMarketVolume": 30_000_000,
            },
        ]
        return {"quotes": quotes[:count]}


class SlowConcurrentYFinance(FakeYFinance):
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.lock = Lock()

    def Ticker(self, symbol: str) -> FakeTicker:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            return FakeTicker(symbol)
        finally:
            with self.lock:
                self.active -= 1


class FailingYFinance:
    def Ticker(self, symbol: str, session=None):
        raise ConnectionError("Yahoo failed")

    def screen(self, query: str, count: int = 25):
        raise ConnectionError(f"{query} failed")


class ProxyAwareYFinance(FakeYFinance):
    def __init__(self) -> None:
        self.sessions = []

    def Ticker(self, symbol: str, session=None) -> FakeTicker:
        self.sessions.append(session)
        return FakeTicker(symbol)


class SlowYFinance(FakeYFinance):
    def Ticker(self, symbol: str, session=None) -> FakeTicker:
        time.sleep(0.2)
        return FakeTicker(symbol)


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FailingGoogleFallbackProvider(MarketDataProvider):
    def _index_quote_from_google_finance(self, market, symbol, name, currency, quote_path):
        return IndexQuote(
            market=market,
            symbol=symbol,
            name=name,
            currency=currency,
            status=ProviderStatus(status="error", source="disabled fallback", updated_at="2026-06-17T00:00:00+00:00"),
        )


class GoogleIndexFallbackProvider(MarketDataProvider):
    def _load_google_finance_quote_html(self, quote_path: str) -> str:
        assert quote_path == ".INX:INDEXSP"
        return '<div data-last-price="7420.1" data-last-normal-market-timestamp="1781729434"></div>'


class FakeAKShare:
    def stock_info_a_code_name(self):
        return pd.DataFrame(
            [
                {"code": "600519", "name": "贵州茅台"},
                {"code": "000858", "name": "五 粮 液"},
                {"code": "002718", "name": "友邦吊顶"},
            ]
        )

    def stock_zh_a_spot_em(self):
        return pd.DataFrame(
            [
                {
                    "代码": "600519",
                    "名称": "贵州茅台",
                    "最新价": 1500.5,
                    "涨跌额": 12.0,
                    "涨跌幅": 0.81,
                    "今开": 1488.0,
                    "最高": 1508.0,
                    "最低": 1480.0,
                    "昨收": 1488.5,
                    "成交量": 1200000,
                    "成交额": 1800000000,
                    "量比": 1.12,
                    "市盈率-动态": 24.2,
                    "总市值": 1800000000000,
                }
            ]
        )

    def stock_hk_spot_em(self):
        return pd.DataFrame(
            [
                {
                    "代码": "00700",
                    "名称": "腾讯控股",
                    "最新价": 410.2,
                    "涨跌额": -2.4,
                    "涨跌幅": -0.58,
                    "今开": 411.0,
                    "最高": 414.0,
                    "最低": 408.0,
                    "昨收": 412.6,
                    "成交量": 22000000,
                    "成交额": 9020000000,
                    "量比": 0.96,
                    "市盈率": 18.7,
                    "总市值": 3900000000000,
                }
            ]
        )

    def stock_zh_index_spot_em(self):
        return pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "上证指数",
                    "最新价": 4108.08,
                    "涨跌额": 15.36,
                    "涨跌幅": 0.38,
                    "今开": 4092.72,
                    "最高": 4110.0,
                    "最低": 4080.0,
                    "昨收": 4092.72,
                    "成交量": 310000000,
                }
            ]
        )

    def stock_hk_index_spot_em(self):
        return pd.DataFrame(
            [
                {
                    "代码": "HSI",
                    "名称": "恒生指数",
                    "最新价": 24312.16,
                    "涨跌额": -181.79,
                    "涨跌幅": -0.74,
                    "今开": 24500.0,
                    "最高": 24600.0,
                    "最低": 24250.0,
                    "昨收": 24493.95,
                    "成交量": 0,
                }
            ]
        )

    def spot_quotations_sge(self, symbol: str):
        assert symbol == "Au99.99"
        return pd.DataFrame(
            [
                {"品种": "Au99.99", "时间": "09:00:00", "现价": 755.0, "更新时间": "2026-06-17 09:01:00"},
                {"品种": "Au99.99", "时间": "09:01:00", "现价": 756.2, "更新时间": "2026-06-17 09:02:00"},
            ]
        )

    def stock_board_industry_name_em(self):
        return pd.DataFrame(
            [
                {"板块名称": "半导体", "最新价": 1020.5, "涨跌额": 20.5, "涨跌幅": 2.05, "成交额": 8800000000},
                {"板块名称": "银行", "最新价": 980.0, "涨跌额": -4.0, "涨跌幅": -0.41, "成交额": 2300000000},
            ]
        )

    def stock_board_concept_name_em(self):
        return pd.DataFrame(
            [
                {"板块名称": "机器人概念", "最新价": 1200.0, "涨跌额": 36.0, "涨跌幅": 3.1, "成交额": 7300000000}
            ]
        )

    def stock_board_industry_cons_em(self, symbol: str):
        if symbol != "半导体":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {"代码": "688981", "名称": "中芯国际", "最新价": 88.2, "涨跌幅": 4.5, "成交量": 30000000},
                {"代码": "603986", "名称": "兆易创新", "最新价": 120.5, "涨跌幅": 2.1, "成交量": 12000000},
            ]
        )

    def stock_board_concept_cons_em(self, symbol: str):
        if symbol != "机器人概念":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {"代码": "300024", "名称": "机器人", "最新价": 18.2, "涨跌幅": 3.8, "成交量": 45000000}
            ]
        )


class CountingAKShare(FakeAKShare):
    def __init__(self) -> None:
        self.a_calls = 0

    def stock_zh_a_spot_em(self):
        self.a_calls += 1
        return super().stock_zh_a_spot_em()


class FallbackAKShare(FakeAKShare):
    def stock_zh_a_spot_em(self):
        raise ConnectionError("primary A failed")

    def stock_hk_spot_em(self):
        raise ConnectionError("primary HK failed")

    def stock_zh_a_spot(self):
        return pd.DataFrame(
            [
                {
                    "代码": "sh600519",
                    "名称": "贵州茅台",
                    "最新价": 1510.0,
                    "涨跌额": 9.5,
                    "涨跌幅": 0.63,
                }
            ]
        )

    def stock_hk_spot(self):
        return pd.DataFrame(
            [
                {
                    "symbol": "00700",
                    "name": "腾讯控股",
                    "最新价": 411.0,
                    "涨跌额": 1.8,
                    "涨跌幅": 0.44,
                }
            ]
        )


class SlowAKShare(FakeAKShare):
    def stock_zh_a_spot_em(self):
        time.sleep(0.2)
        return super().stock_zh_a_spot_em()

    def stock_zh_a_spot(self):
        time.sleep(0.2)
        return super().stock_zh_a_spot_em()


class SlowIndexAKShare(FakeAKShare):
    def stock_zh_index_spot_em(self):
        time.sleep(0.2)
        return super().stock_zh_index_spot_em()

    def stock_hk_index_spot_em(self):
        time.sleep(0.2)
        return super().stock_hk_index_spot_em()


class FailingAKShare(FakeAKShare):
    def stock_zh_a_spot_em(self):
        raise ConnectionError("primary A failed")

    def stock_zh_a_spot(self):
        raise ConnectionError("fallback A failed")

    def stock_hk_spot_em(self):
        raise ConnectionError("primary HK failed")

    def stock_hk_spot(self):
        raise ConnectionError("fallback HK failed")


class HKSectorFallbackAKShare(FakeAKShare):
    def stock_hk_spot_em(self):
        return pd.DataFrame(
            [
                {
                    "代码": "00700",
                    "名称": "腾讯控股",
                    "最新价": 440.0,
                    "涨跌幅": 2.5,
                    "成交量": 100000000,
                },
                {
                    "代码": "00941",
                    "名称": "中国移动",
                    "最新价": 84.5,
                    "涨跌幅": 1.5,
                    "成交量": 80000000,
                },
                {
                    "代码": "09988",
                    "名称": "阿里巴巴-W",
                    "最新价": 105.0,
                    "涨跌幅": 3.0,
                    "成交量": 50000000,
                },
                {
                    "代码": "00005",
                    "名称": "汇丰控股",
                    "最新价": 93.0,
                    "涨跌幅": -1.0,
                    "成交量": 90000000,
                },
            ]
        )


class FailingIndexAKShare(FakeAKShare):
    def stock_zh_index_spot_em(self):
        raise ConnectionError("A index failed")

    def stock_hk_index_spot_em(self):
        raise ConnectionError("HK index failed")


class FailingBoardAKShare(FakeAKShare):
    def stock_board_industry_name_em(self):
        raise ConnectionError("industry board disconnected")

    def stock_board_concept_name_em(self):
        raise TimeoutError("concept board timeout")

    def stock_sector_spot(self):
        return pd.DataFrame(
            [
                {
                    "板块": "玻璃行业",
                    "平均价格": 22.44,
                    "涨跌额": 0.88,
                    "涨跌幅": 4.12,
                    "总成交量": 1101457968,
                    "总成交额": 25653582227,
                },
                {
                    "板块": "电力行业",
                    "平均价格": 9.82,
                    "涨跌额": -0.08,
                    "涨跌幅": -0.84,
                    "总成交量": 5379355216,
                    "总成交额": 52403880343,
                },
            ]
        )


class FailingAllBoardAKShare(FailingBoardAKShare):
    def stock_sector_spot(self):
        raise ConnectionError("sina board disconnected")


class SinaDetailFallbackAKShare(FakeAKShare):
    def stock_board_industry_cons_em(self, symbol: str):
        raise ConnectionError("industry constituents disconnected")

    def stock_board_concept_cons_em(self, symbol: str):
        raise TimeoutError("concept constituents timeout")

    def stock_sector_spot(self, indicator=None):
        assert indicator in (None, "新浪行业")
        return pd.DataFrame(
            [
                {"板块": "有色金属", "label": "new_ysjs"},
                {"板块": "电器行业", "label": "new_dqhy"},
            ]
        )

    def stock_sector_detail(self, sector: str):
        assert sector == "new_ysjs"
        return pd.DataFrame(
            [
                {
                    "symbol": "sh600111",
                    "code": "600111",
                    "name": "北方稀土",
                    "trade": 54.15,
                    "changepercent": 5.35,
                    "volume": 246385960,
                    "amount": 13073459531,
                },
                {
                    "symbol": "sz000807",
                    "code": "000807",
                    "name": "云铝股份",
                    "trade": 17.8,
                    "changepercent": 2.48,
                    "volume": 129300000,
                    "amount": 2319000000,
                },
            ]
        )


class SlowDualMarketAKShare(FakeAKShare):
    def stock_zh_a_spot_em(self):
        time.sleep(0.2)
        return super().stock_zh_a_spot_em()

    def stock_hk_spot_em(self):
        time.sleep(0.2)
        return super().stock_hk_spot_em()


def test_provider_normalizes_quotes_from_akshare_and_yfinance():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())
    items = [
        WatchItem(id="a:600519", market=Market.A, symbol="600519", name=None),
        WatchItem(id="hk:00700", market=Market.HK, symbol="00700", name=None),
        WatchItem(id="us:AAPL", market=Market.US, symbol="AAPL", name="Apple"),
        WatchItem(id="crypto:BTC-USD", market=Market.CRYPTO, symbol="BTC-USD", name="Bitcoin"),
    ]

    quotes = provider.get_quotes(items)

    assert [quote.symbol for quote in quotes] == ["600519", "00700", "AAPL", "BTC-USD"]
    assert quotes[0].name == "贵州茅台"
    assert quotes[0].price == 1500.5
    assert quotes[0].currency == "CNY"
    assert quotes[0].volume_ratio == 1.12
    assert quotes[0].pe_ratio == 24.2
    assert quotes[0].market_cap == 1800000000000
    assert quotes[1].change_percent == -0.58
    assert quotes[1].currency == "HKD"
    assert quotes[1].volume_ratio == 0.96
    assert quotes[1].pe_ratio == 18.7
    assert quotes[1].market_cap == 3900000000000
    assert quotes[2].price == 192.4
    assert quotes[2].change == 2.4
    assert quotes[2].change_percent == 1.26
    assert quotes[2].volume == 55000000
    assert quotes[2].amount == 10582000000
    assert quotes[2].volume_ratio == 1.1
    assert quotes[2].pe_ratio == 29.48
    assert quotes[2].market_cap == 3200000000000
    assert quotes[2].currency == "USD"
    assert quotes[3].market == Market.CRYPTO
    assert quotes[3].price == 65000.0
    assert quotes[3].change_percent == 1.56
    assert quotes[3].amount == 3575000000
    assert quotes[3].volume == 55000
    assert quotes[3].market_cap == 1280000000000
    assert quotes[3].volume_ratio is None
    assert quotes[3].pe_ratio is None


def test_provider_normalizes_gold_quote():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    quote = provider.get_gold_quote()

    assert quote.symbol == "Au99.99"
    assert quote.name == "上海金 Au99.99"
    assert quote.price == 756.2
    assert quote.status.status == "ok"
    assert quote.status.source == "AKShare / Shanghai Gold Exchange"


def test_provider_returns_market_index_quotes():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    indexes = provider.get_index_quotes()

    assert [(item.market, item.symbol, item.name) for item in indexes] == [
        (Market.A, "000001.SS", "上证指数"),
        (Market.HK, "^HSI", "恒生指数"),
        (Market.US, "^GSPC", "标普500"),
    ]
    assert indexes[0].price == 4108.08
    assert indexes[0].change_percent == 0.38
    assert indexes[0].currency == "CNY"
    assert indexes[1].price == 24312.16
    assert indexes[1].change_percent == -0.74
    assert indexes[1].currency == "HKD"
    assert indexes[2].change == 20.0
    assert indexes[2].currency == "USD"


def test_provider_prefers_akshare_for_a_and_hk_index_quotes():
    provider = FailingGoogleFallbackProvider(ak_module=FakeAKShare(), yf_module=FailingYFinance())

    indexes = provider.get_index_quotes()

    assert indexes[0].price == 4108.08
    assert indexes[0].status.source == "AKShare / Eastmoney A-share indexes"
    assert indexes[1].price == 24312.16
    assert indexes[1].status.source == "AKShare / Eastmoney HK indexes"
    assert indexes[2].status.status == "error"


def test_provider_falls_back_to_google_finance_for_us_index_quote():
    provider = GoogleIndexFallbackProvider(ak_module=FakeAKShare(), yf_module=FailingYFinance())

    indexes = provider.get_index_quotes()

    assert indexes[2].market == Market.US
    assert indexes[2].price == 7420.1
    assert indexes[2].currency == "USD"
    assert indexes[2].status.source == "Google Finance index fallback"


def test_provider_searches_a_hk_and_us_symbols_by_name():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    a_results = provider.search_symbols(Market.A, "贵州")
    a_name_results = provider.search_symbols(Market.A, "五粮液")
    hk_results = provider.search_symbols(Market.HK, "腾讯")
    us_results = provider.search_symbols(Market.US, "Apple")
    crypto_results = provider.search_symbols(Market.CRYPTO, "bitcoin")

    assert [(item.market, item.symbol, item.name) for item in a_results] == [
        (Market.A, "600519", "贵州茅台")
    ]
    assert [(item.market, item.symbol, item.name) for item in a_name_results] == [
        (Market.A, "000858", "五粮液")
    ]
    assert [(item.market, item.symbol, item.name) for item in hk_results] == [
        (Market.HK, "00700", "腾讯控股")
    ]
    assert [(item.market, item.symbol, item.name) for item in us_results] == [
        (Market.US, "AAPL", "Apple Inc.")
    ]
    assert [(item.market, item.symbol, item.name) for item in crypto_results] == [
        (Market.CRYPTO, "BTC-USD", "Bitcoin")
    ]


def test_provider_sorts_a_share_sector_rows_by_change_percent():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    response = provider.get_sectors(Market.A)

    assert response.status.status == "ok"
    assert [item.name for item in response.items] == ["机器人概念", "半导体", "银行"]


def test_provider_falls_back_to_sina_when_eastmoney_a_share_sector_source_fails():
    provider = MarketDataProvider(ak_module=FailingBoardAKShare(), yf_module=FakeYFinance())

    response = provider.get_sectors(Market.A)

    assert response.status.status == "ok"
    assert response.status.source == "AKShare / Sina sector boards"
    assert [item.name for item in response.items] == ["玻璃行业", "电力行业"]
    assert response.items[0].change_percent == 4.12
    assert response.items[0].amount == 25653582227


def test_provider_returns_unavailable_when_all_a_share_sector_sources_fail():
    provider = MarketDataProvider(ak_module=FailingAllBoardAKShare(), yf_module=FakeYFinance())

    response = provider.get_sectors(Market.A)

    assert response.status.status == "unavailable"
    assert response.items == []
    assert "A-share sector ranking" in (response.status.message or "")


def test_provider_returns_yahoo_hk_sector_activity_and_us_sector_proxies():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    hk = provider.get_sectors(Market.HK)
    us = provider.get_sectors(Market.US)

    assert hk.status.status == "ok"
    assert hk.status.source == "yfinance / Yahoo Finance HK active stocks"
    assert [item.name for item in hk.items] == ["通信服务", "金融服务", "科技", "原材料"]
    assert hk.items[0].change_percent == 2.0
    assert hk.items[0].volume == 100_000_000
    assert us.status.status == "ok"
    assert us.status.source == "yfinance / Yahoo Finance sector ETFs"
    assert [item.name for item in us.items[:2]] == ["Technology", "Health Care"]
    assert us.items[-1].name == "Financials"
    assert us.items[0].change_percent == 5.0


def test_provider_falls_back_to_akshare_hk_quotes_when_yahoo_hk_sectors_are_limited():
    provider = MarketDataProvider(ak_module=HKSectorFallbackAKShare(), yf_module=FailingYFinance())

    response = provider.get_sectors(Market.HK)

    assert response.status.status == "ok"
    assert response.status.source == "AKShare / Eastmoney HK sector fallback"
    assert [item.name for item in response.items[:3]] == ["通信服务", "金融服务", "非必需消费"]
    assert response.items[0].change_percent == 2.37
    assert response.items[0].volume == 180000000


def test_provider_falls_back_to_stock_proxy_for_hk_sector_proxies(monkeypatch):
    monkeypatch.setenv("MARKET_MONITOR_STOCK_PROXY_URL", "https://apiproxy.myvobot.com/stock")

    def fake_get(url, **kwargs):
        assert url == "https://apiproxy.myvobot.com/stock"
        assert kwargs["params"]["symbols"].startswith("0700.HK,0941.HK,9988.HK")
        return FakeHttpResponse(
            {
                "stocks": [
                    {"symbol": "0700.HK", "shortName": "TENCENT", "currency": "HKD", "currentPrice": 440.0, "previousClose": 430.0},
                    {"symbol": "0941.HK", "shortName": "CHINA MOBILE", "currency": "HKD", "currentPrice": 85.0, "previousClose": 84.0},
                    {"symbol": "9988.HK", "shortName": "BABA-W", "currency": "HKD", "currentPrice": 105.0, "previousClose": 100.0},
                ]
            }
        )

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = MarketDataProvider(ak_module=FailingAKShare(), yf_module=FailingYFinance())

    response = provider.get_sectors(Market.HK)

    assert response.status.status == "ok"
    assert response.status.source == "apiproxy.myvobot.com HK sector proxies"
    assert [item.name for item in response.items] == ["通信服务", "非必需消费"]
    assert response.items[1].change_percent == 5.0


def test_provider_falls_back_to_stock_proxy_for_us_sector_etfs(monkeypatch):
    monkeypatch.setenv("MARKET_MONITOR_STOCK_PROXY_URL", "https://apiproxy.myvobot.com/stock")

    def fake_get(url, **kwargs):
        assert url == "https://apiproxy.myvobot.com/stock"
        assert kwargs["params"] == {
            "symbols": "XLK,XLF,XLV,XLE,XLY,XLP,XLI,XLB,XLU,XLRE,XLC"
        }
        return FakeHttpResponse(
            {
                "stocks": [
                    {"symbol": "XLK", "shortName": "Technology", "currency": "USD", "currentPrice": 212, "previousClose": 200},
                    {"symbol": "XLF", "shortName": "Financials", "currency": "USD", "currentPrice": 49, "previousClose": 50},
                    {"symbol": "XLV", "shortName": "Health Care", "currency": "USD", "currentPrice": 101, "previousClose": 100},
                ]
            }
        )

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FailingYFinance())

    response = provider.get_sectors(Market.US)

    assert response.status.status == "ok"
    assert response.status.source == "apiproxy.myvobot.com stock sector ETFs"
    assert [item.name for item in response.items] == ["Technology", "Health Care", "Financials"]
    assert response.items[0].change_percent == 6.0
    assert response.items[2].change_percent == -2.0


def test_provider_loads_us_sector_etfs_concurrently():
    yf = SlowConcurrentYFinance()
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=yf)

    response = provider.get_sectors(Market.US)

    assert response.status.status == "ok"
    assert yf.max_active > 1


def test_provider_loads_yfinance_watch_quotes_concurrently():
    yf = SlowConcurrentYFinance()
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=yf)
    items = [
        WatchItem(id="us:AAPL", market=Market.US, symbol="AAPL", name="Apple"),
        WatchItem(id="us:MSFT", market=Market.US, symbol="MSFT", name="Microsoft"),
        WatchItem(id="crypto:BTC-USD", market=Market.CRYPTO, symbol="BTC-USD", name="Bitcoin"),
    ]

    quotes = provider.get_quotes(items)

    assert [quote.symbol for quote in quotes] == ["AAPL", "MSFT", "BTC-USD"]
    assert yf.max_active > 1


def test_provider_passes_configured_proxy_session_to_yfinance(monkeypatch):
    monkeypatch.setenv("MARKET_MONITOR_YAHOO_PROXY_URL", "http://172.19.0.1:10829")
    yf = ProxyAwareYFinance()
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=yf)

    quotes = provider.get_quotes([WatchItem(id="us:AAPL", market=Market.US, symbol="AAPL", name="Apple")])

    assert quotes[0].status.status == "ok"
    assert yf.sessions
    assert yf.sessions[0] is not None


def test_provider_times_out_slow_yfinance_quotes():
    provider = MarketDataProvider(
        ak_module=FakeAKShare(),
        yf_module=SlowYFinance(),
        call_timeout_seconds=0.01,
        yfinance_timeout_seconds=0.01,
    )

    start = time.perf_counter()
    quotes = provider.get_quotes([WatchItem(id="us:AAPL", market=Market.US, symbol="AAPL", name="Apple")])
    elapsed = time.perf_counter() - start

    assert elapsed < 0.15
    assert quotes[0].status.status == "error"
    assert "timed out" in (quotes[0].status.message or "").lower()


def test_provider_allows_slower_yfinance_watch_quotes():
    provider = MarketDataProvider(
        ak_module=FakeAKShare(),
        yf_module=SlowYFinance(),
        call_timeout_seconds=0.01,
    )

    quotes = provider.get_quotes(
        [
            WatchItem(id="us:AAPL", market=Market.US, symbol="AAPL", name="Apple"),
            WatchItem(id="crypto:BTC-USD", market=Market.CRYPTO, symbol="BTC-USD", name="Bitcoin"),
        ]
    )

    assert [quote.status.status for quote in quotes] == ["ok", "ok"]
    assert quotes[0].price == 192.4
    assert quotes[1].price == 65000.0


def test_provider_uses_stock_proxy_for_us_and_crypto_quotes(monkeypatch):
    monkeypatch.setenv("MARKET_MONITOR_STOCK_PROXY_URL", "https://apiproxy.myvobot.com/stock")
    requests = []

    def fake_get(url, **kwargs):
        requests.append((url, kwargs))
        assert url == "https://apiproxy.myvobot.com/stock"
        assert kwargs["params"] == {"symbols": "AAPL,BTC-USD"}
        return FakeHttpResponse(
            {
                "stocks": [
                    {
                        "symbol": "AAPL",
                        "shortName": "Apple Inc.",
                        "currency": "USD",
                        "currentPrice": 298.01,
                        "previousClose": 295.95,
                    },
                    {
                        "symbol": "BTC-USD",
                        "shortName": "Bitcoin USD",
                        "currency": "USD",
                        "currentPrice": 86000.0,
                        "previousClose": 85000.0,
                    },
                ]
            }
        )

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FailingYFinance())
    items = [
        WatchItem(id="us:AAPL", market=Market.US, symbol="AAPL", name="Apple"),
        WatchItem(id="crypto:BTC-USD", market=Market.CRYPTO, symbol="BTC-USD", name="Bitcoin"),
    ]

    quotes = provider.get_quotes(items)

    assert len(requests) == 1
    assert quotes[0].name == "Apple Inc."
    assert quotes[0].price == 298.01
    assert quotes[0].change == 2.06
    assert quotes[0].change_percent == 0.7
    assert quotes[0].status.status == "ok"
    assert quotes[0].status.source == "apiproxy.myvobot.com stock"
    assert quotes[1].price == 86000.0
    assert quotes[1].change_percent == 1.18
    assert quotes[1].status.source == "apiproxy.myvobot.com stock"


def test_provider_falls_back_to_stock_proxy_for_a_and_hk_quotes(monkeypatch):
    monkeypatch.setenv("MARKET_MONITOR_STOCK_PROXY_URL", "https://apiproxy.myvobot.com/stock")

    def fake_get(url, **kwargs):
        if "push2.eastmoney.com/api/qt/stock/get" in url:
            raise ConnectionError("eastmoney failed")
        assert url == "https://apiproxy.myvobot.com/stock"
        assert kwargs["params"] == {"SYMBOL": "0700.HK"}
        return FakeHttpResponse(
            {
                "symbol": "0700.HK",
                "shortName": "TENCENT",
                "currency": "HKD",
                "currentPrice": 440.2,
                "previousClose": 445.4,
            }
        )

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = MarketDataProvider(ak_module=FailingAKShare(), yf_module=FailingYFinance())

    quote = provider.get_quotes([WatchItem(id="hk:00700", market=Market.HK, symbol="00700", name="腾讯控股")])[0]

    assert quote.name == "TENCENT"
    assert quote.price == 440.2
    assert quote.change == -5.2
    assert quote.change_percent == -1.17
    assert quote.currency == "HKD"
    assert quote.status.status == "ok"
    assert quote.status.source == "apiproxy.myvobot.com stock"


def test_provider_falls_back_to_stock_proxy_for_index_quotes(monkeypatch):
    monkeypatch.setenv("MARKET_MONITOR_STOCK_PROXY_URL", "https://apiproxy.myvobot.com/stock")

    def fake_get(url, **kwargs):
        assert url == "https://apiproxy.myvobot.com/stock"
        assert kwargs["params"] == {"symbols": "000001.SS,^HSI,^GSPC"}
        return FakeHttpResponse(
            {
                "stocks": [
                    {
                        "symbol": "000001.SS",
                        "shortName": "SSE Composite Index",
                        "currency": "CNY",
                        "currentPrice": 4100.0,
                        "previousClose": 4090.0,
                    },
                    {
                        "symbol": "^HSI",
                        "shortName": "HANG SENG INDEX",
                        "currency": "HKD",
                        "currentPrice": 24000.0,
                        "previousClose": 24200.0,
                    },
                    {
                        "symbol": "^GSPC",
                        "shortName": "S&P 500",
                        "currency": "USD",
                        "currentPrice": 6800.0,
                        "previousClose": 6700.0,
                    },
                ]
            }
        )

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = FailingGoogleFallbackProvider(ak_module=FailingIndexAKShare(), yf_module=FailingYFinance())

    indexes = provider.get_index_quotes()

    assert [item.status.source for item in indexes] == [
        "apiproxy.myvobot.com stock",
        "apiproxy.myvobot.com stock",
        "apiproxy.myvobot.com stock",
    ]
    assert indexes[2].market == Market.US
    assert indexes[2].price == 6800.0
    assert indexes[2].change == 100.0
    assert indexes[2].change_percent == 1.49
    assert indexes[2].status.status == "ok"
    assert indexes[2].status.source == "apiproxy.myvobot.com stock"


def test_provider_falls_back_to_eastmoney_single_quote_when_market_frames_fail(monkeypatch):
    def fake_get(url, **kwargs):
        assert "push2.eastmoney.com/api/qt/stock/get" in url
        assert kwargs["params"]["secid"] == "0.000858"
        return FakeHttpResponse(
            {
                "data": {
                    "f43": 7585,
                    "f44": 7736,
                    "f45": 7585,
                    "f46": 7728,
                    "f47": 326843,
                    "f48": 2499475187.41,
                    "f57": "000858",
                    "f58": "五 粮 液",
                    "f60": 7749,
                    "f116": 294419967179.25,
                    "f162": 913,
                    "f168": 84,
                    "f170": -212,
                }
            }
        )

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = MarketDataProvider(ak_module=FailingAKShare(), yf_module=FailingYFinance())
    item = WatchItem(id="a:000858", market=Market.A, symbol="000858", name="五粮液")

    quote = provider.get_quotes([item])[0]

    assert quote.status.status == "ok"
    assert quote.status.source == "Eastmoney single quote fallback"
    assert quote.name == "五 粮 液"
    assert quote.price == 75.85
    assert quote.change_percent == -2.12
    assert quote.amount == 2499475187.41
    assert quote.volume_ratio == 0.84
    assert quote.pe_ratio == 9.13
    assert quote.market_cap == 294419967179.25


def test_provider_uses_shanghai_eastmoney_secid_for_exchange_funds(monkeypatch):
    seen_secids: list[str] = []

    def fake_get(url, **kwargs):
        assert "push2.eastmoney.com/api/qt/stock/get" in url
        seen_secids.append(kwargs["params"]["secid"])
        return FakeHttpResponse(
            {
                "data": {
                    "f43": 1234,
                    "f44": 1240,
                    "f45": 1200,
                    "f46": 1210,
                    "f47": 100000,
                    "f48": 123400000,
                    "f57": "513300",
                    "f58": "纳指ETF",
                    "f60": 1200,
                    "f116": 5000000000,
                    "f162": 0,
                    "f168": 96,
                    "f170": 283,
                }
            }
        )

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = MarketDataProvider(ak_module=FailingAKShare(), yf_module=FailingYFinance())
    item = WatchItem(id="a:513300", market=Market.A, symbol="513300.SH", name="纳指ETF")

    quote = provider.get_quotes([item])[0]

    assert seen_secids == ["1.513300"]
    assert quote.status.status == "ok"
    assert quote.symbol == "513300.SH"
    assert quote.name == "纳指ETF"


def test_provider_does_not_return_a_share_data_for_crypto_sector_endpoints():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    sectors = provider.get_sectors(Market.CRYPTO)
    details = provider.get_sector_details(Market.CRYPTO, "Layer 1")

    assert sectors.market == Market.CRYPTO
    assert sectors.status.status == "unavailable"
    assert sectors.items == []
    assert "not configured" in (sectors.status.message or "")
    assert details.market == Market.CRYPTO
    assert details.status.status == "unavailable"
    assert details.items == []
    assert "not configured" in (details.status.message or "")


def test_provider_returns_sector_details_for_a_hk_and_us():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    a_detail = provider.get_sector_details(Market.A, "半导体")
    hk_detail = provider.get_sector_details(Market.HK, "通信服务")
    us_detail = provider.get_sector_details(Market.US, "Technology")

    assert a_detail.status.status == "ok"
    assert [(item.symbol, item.name) for item in a_detail.items[:2]] == [
        ("688981", "中芯国际"),
        ("603986", "兆易创新"),
    ]
    assert hk_detail.status.status == "ok"
    assert hk_detail.items[0].symbol == "0700.HK"
    assert us_detail.status.status == "ok"
    assert us_detail.items[0].symbol == "XLK"
    assert us_detail.items[0].name == "Technology ETF"


def test_provider_allows_slower_yfinance_us_sector_details():
    provider = MarketDataProvider(
        ak_module=FakeAKShare(),
        yf_module=SlowYFinance(),
        call_timeout_seconds=0.01,
    )

    us_detail = provider.get_sector_details(Market.US, "Technology")

    assert us_detail.status.status == "ok"
    assert us_detail.items[0].symbol == "XLK"
    assert us_detail.items[0].price == 210.0


def test_provider_falls_back_to_sina_sector_constituents_for_a_share_details():
    provider = MarketDataProvider(ak_module=SinaDetailFallbackAKShare(), yf_module=FakeYFinance())

    detail = provider.get_sector_details(Market.A, "有色金属")

    assert detail.status.status == "ok"
    assert detail.status.source == "AKShare / Sina sector constituents"
    assert [(item.symbol, item.name) for item in detail.items[:2]] == [
        ("600111", "北方稀土"),
        ("000807", "云铝股份"),
    ]
    assert detail.items[0].price == 54.15
    assert detail.items[0].change_percent == 5.35
    assert detail.items[0].amount == 13073459531


def test_provider_caches_expensive_akshare_quote_frames():
    ak = CountingAKShare()
    provider = MarketDataProvider(ak_module=ak, yf_module=FakeYFinance(), cache_ttl_seconds=60)
    items = [WatchItem(id="a:600519", market=Market.A, symbol="600519", name=None)]

    provider.get_quotes(items)
    provider.get_quotes(items)

    assert ak.a_calls == 1


def test_provider_uses_akshare_fallback_quote_interfaces():
    provider = MarketDataProvider(ak_module=FallbackAKShare(), yf_module=FakeYFinance())
    items = [
        WatchItem(id="a:600519", market=Market.A, symbol="600519", name=None),
        WatchItem(id="hk:00700", market=Market.HK, symbol="00700", name=None),
    ]

    quotes = provider.get_quotes(items)

    assert quotes[0].price == 1510.0
    assert quotes[0].status.status == "ok"
    assert "Sina" in quotes[0].status.source
    assert quotes[1].price == 411.0
    assert quotes[1].status.status == "ok"
    assert "fallback" in quotes[1].status.source


def test_provider_times_out_slow_akshare_calls():
    provider = MarketDataProvider(
        ak_module=SlowAKShare(),
        yf_module=FailingYFinance(),
        call_timeout_seconds=0.01,
    )

    quotes = provider.get_quotes([WatchItem(id="a:600519", market=Market.A, symbol="600519", name=None)])

    assert quotes[0].status.status == "error"
    assert "timed out" in (quotes[0].status.message or "").lower()


def test_provider_times_out_slow_akshare_index_calls():
    provider = FailingGoogleFallbackProvider(
        ak_module=SlowIndexAKShare(),
        yf_module=FailingYFinance(),
        call_timeout_seconds=0.01,
    )

    start = time.perf_counter()
    indexes = provider.get_index_quotes()
    elapsed = time.perf_counter() - start

    assert elapsed < 0.15
    assert indexes[0].status.status == "error"
    assert indexes[1].status.status == "error"


def test_provider_loads_a_and_hk_quote_frames_concurrently():
    provider = MarketDataProvider(
        ak_module=SlowDualMarketAKShare(),
        yf_module=FakeYFinance(),
        call_timeout_seconds=1,
    )
    items = [
        WatchItem(id="a:600519", market=Market.A, symbol="600519", name=None),
        WatchItem(id="hk:00700", market=Market.HK, symbol="00700", name=None),
    ]

    start = time.perf_counter()
    provider.get_quotes(items)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.35


def test_provider_falls_back_to_yahoo_for_a_and_hk_single_quotes():
    provider = MarketDataProvider(ak_module=FailingAKShare(), yf_module=FakeYFinance())
    items = [
        WatchItem(id="a:600519", market=Market.A, symbol="600519", name="贵州茅台"),
        WatchItem(id="hk:00700", market=Market.HK, symbol="00700", name="腾讯控股"),
    ]

    quotes = provider.get_quotes(items)

    assert quotes[0].price == 192.4
    assert quotes[0].currency == "CNY"
    assert quotes[0].status.status == "ok"
    assert "Yahoo Finance fallback" in quotes[0].status.source
    assert quotes[1].price == 192.4
    assert quotes[1].currency == "HKD"
    assert quotes[1].status.status == "ok"
    assert "Yahoo Finance fallback" in quotes[1].status.source


def test_provider_allows_slower_yahoo_fallback_for_a_share_funds(monkeypatch):
    def fake_get(url, **kwargs):
        if "push2.eastmoney.com/api/qt/stock/get" in url:
            raise ConnectionError("eastmoney failed")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("app.providers.httpx.get", fake_get)
    provider = MarketDataProvider(
        ak_module=FailingAKShare(),
        yf_module=SlowYFinance(),
        call_timeout_seconds=0.01,
    )
    item = WatchItem(id="a:513300", market=Market.A, symbol="513300", name="纳斯达克ETF华夏")

    quote = provider.get_quotes([item])[0]

    assert quote.status.status == "ok"
    assert quote.price == 192.4
    assert quote.currency == "CNY"
    assert "Yahoo Finance fallback" in quote.status.source
