import time

import pandas as pd

from app.models import Market, WatchItem
from app.providers import MarketDataProvider


class FakeFastInfo(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        currency = "USD"
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
                "lastVolume": 55000000,
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
        self.info = {"sector": sector, "industry": industry, "shortName": symbol}


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
    def Ticker(self, symbol: str) -> FakeTicker:
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


class FailingYFinance:
    def Ticker(self, symbol: str):
        raise ConnectionError("Yahoo failed")


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


class FailingAKShare(FakeAKShare):
    def stock_zh_a_spot_em(self):
        raise ConnectionError("primary A failed")

    def stock_zh_a_spot(self):
        raise ConnectionError("fallback A failed")

    def stock_hk_spot_em(self):
        raise ConnectionError("primary HK failed")

    def stock_hk_spot(self):
        raise ConnectionError("fallback HK failed")


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
    ]

    quotes = provider.get_quotes(items)

    assert [quote.symbol for quote in quotes] == ["600519", "00700", "AAPL"]
    assert quotes[0].name == "贵州茅台"
    assert quotes[0].price == 1500.5
    assert quotes[0].currency == "CNY"
    assert quotes[1].change_percent == -0.58
    assert quotes[1].currency == "HKD"
    assert quotes[2].price == 192.4
    assert quotes[2].change == 2.4
    assert quotes[2].change_percent == 1.26
    assert quotes[2].currency == "USD"


def test_provider_normalizes_gold_quote():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    quote = provider.get_gold_quote()

    assert quote.symbol == "Au99.99"
    assert quote.name == "上海金 Au99.99"
    assert quote.price == 756.2
    assert quote.status.status == "ok"
    assert quote.status.source == "AKShare / Shanghai Gold Exchange"


def test_provider_searches_a_hk_and_us_symbols_by_name():
    provider = MarketDataProvider(ak_module=FakeAKShare(), yf_module=FakeYFinance())

    a_results = provider.search_symbols(Market.A, "贵州")
    a_name_results = provider.search_symbols(Market.A, "五粮液")
    hk_results = provider.search_symbols(Market.HK, "腾讯")
    us_results = provider.search_symbols(Market.US, "Apple")

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
