import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import {
  addWatchItem,
  deleteWatchItem,
  fetchGold,
  fetchHealth,
  fetchIndexes,
  fetchMarketStatuses,
  fetchQuotes,
  fetchSectorDetails,
  fetchSectors,
  fetchSymbolSearch,
  fetchWatchlist
} from "./api";
import type {
  GoldQuote,
  HealthResponse,
  IndexQuote,
  MarketStatus,
  Quote,
  SectorDetailResponse,
  SectorResponse,
  SymbolSearchResult,
  WatchItem
} from "./types";

vi.mock("./api", () => ({
  fetchWatchlist: vi.fn(),
  fetchQuotes: vi.fn(),
  fetchGold: vi.fn(),
  fetchIndexes: vi.fn(),
  fetchSectors: vi.fn(),
  fetchSectorDetails: vi.fn(),
  fetchHealth: vi.fn(),
  fetchMarketStatuses: vi.fn(),
  fetchSymbolSearch: vi.fn(),
  addWatchItem: vi.fn(),
  deleteWatchItem: vi.fn()
}));

const watchlist: WatchItem[] = [
  { id: "us:AAPL", market: "us", symbol: "AAPL", name: "Apple" },
  { id: "a:600519", market: "a", symbol: "600519", name: "贵州茅台" },
  { id: "crypto:BTC-USD", market: "crypto", symbol: "BTC-USD", name: "Bitcoin" },
  { id: "crypto:ETH-USD", market: "crypto", symbol: "ETH-USD", name: "Ethereum" }
];

const quotes: Quote[] = [
  {
    id: "us:AAPL",
    market: "us",
    symbol: "AAPL",
    name: "Apple",
    price: 192.4,
    change: 2.4,
    change_percent: 1.26,
    open: 190,
    high: 195,
    low: 188,
    previous_close: 190,
    volume: 7654321,
    amount: 123456789,
    volume_ratio: 1.37,
    pe_ratio: 29.48,
    market_cap: 3200000000000,
    currency: "USD",
    status: { status: "ok", source: "yfinance", updated_at: "2026-06-17T00:00:00+00:00" }
  },
  {
    id: "a:600519",
    market: "a",
    symbol: "600519",
    name: "贵州茅台",
    price: 1500.5,
    change: 12,
    change_percent: 0.81,
    open: 1488,
    high: 1508,
    low: 1480,
    previous_close: 1488.5,
    volume: 1200000,
    amount: 1800000000,
    volume_ratio: 1.12,
    pe_ratio: 24.2,
    market_cap: 1800000000000,
    currency: "CNY",
    status: { status: "ok", source: "AKShare", updated_at: "2026-06-17T00:00:00+00:00" }
  },
  {
    id: "crypto:BTC-USD",
    market: "crypto",
    symbol: "BTC-USD",
    name: "Bitcoin",
    price: 65000,
    change: 1000,
    change_percent: 1.56,
    open: 64200,
    high: 66000,
    low: 63000,
    previous_close: 64000,
    volume: 32000,
    amount: 2080000000,
    market_cap: 1280000000000,
    currency: "USD",
    status: { status: "ok", source: "yfinance / Yahoo Finance crypto", updated_at: "2026-06-17T00:00:00+00:00" }
  },
  {
    id: "crypto:ETH-USD",
    market: "crypto",
    symbol: "ETH-USD",
    name: "Ethereum",
    price: 3500,
    change: -50,
    change_percent: -1.41,
    open: 3560,
    high: 3600,
    low: 3450,
    previous_close: 3550,
    volume: 580000,
    amount: 2030000000,
    market_cap: 420000000000,
    currency: "USD",
    status: { status: "ok", source: "yfinance / Yahoo Finance crypto", updated_at: "2026-06-17T00:00:00+00:00" }
  }
];

const gold: GoldQuote = {
  symbol: "Au99.99",
  name: "上海金 Au99.99",
  price: 756.2,
  currency: "CNY/g",
  status: { status: "ok", source: "AKShare", updated_at: "2026-06-17T00:00:00+00:00" }
};

const indexes: IndexQuote[] = [
  {
    market: "a",
    symbol: "000001.SS",
    name: "上证指数",
    price: 3100,
    change: 12,
    change_percent: 0.39,
    currency: "CNY",
    status: { status: "ok", source: "yfinance / Yahoo Finance index", updated_at: "2026-06-17T00:00:00+00:00" }
  },
  {
    market: "hk",
    symbol: "^HSI",
    name: "恒生指数",
    price: 18000,
    change: -80,
    change_percent: -0.44,
    currency: "HKD",
    status: { status: "ok", source: "yfinance / Yahoo Finance index", updated_at: "2026-06-17T00:00:00+00:00" }
  },
  {
    market: "us",
    symbol: "^GSPC",
    name: "标普500",
    price: 4900,
    change: 20,
    change_percent: 0.41,
    currency: "USD",
    status: { status: "ok", source: "yfinance / Yahoo Finance index", updated_at: "2026-06-17T00:00:00+00:00" }
  }
];

const sectors: Record<string, SectorResponse> = {
  a: {
    market: "a",
    status: { status: "ok", source: "AKShare", updated_at: "2026-06-17T00:00:00+00:00" },
    items: [{ name: "机器人概念", price: 1200, change: 36, change_percent: 3.1, amount: 7300000000 }]
  },
  hk: {
    market: "hk",
    status: {
      status: "unavailable",
      source: "AKShare / Yahoo Finance",
      updated_at: "2026-06-17T00:00:00+00:00",
      message: "No reliable free Hong Kong sector ranking source is configured yet."
    },
    items: []
  },
  us: {
    market: "us",
    status: {
      status: "ok",
      source: "yfinance / Yahoo Finance sector ETFs",
      updated_at: "2026-06-17T00:00:00+00:00",
      message: "US sector activity is represented by liquid sector ETF proxies."
    },
    items: [{ name: "Technology", price: 210, change: 10, change_percent: 5, volume: 55000000 }]
  }
};

const symbolResults: SymbolSearchResult[] = [
  { market: "a", symbol: "600519", name: "贵州茅台", source: "AKShare / Eastmoney A-share" }
];

const marketStatuses: MarketStatus[] = [
  { market: "a", state: "trading", label: "交易中", timezone: "Asia/Shanghai", session: "09:30-11:30 / 13:00-15:00", updated_at: "2026-06-17T00:00:00+00:00" },
  { market: "hk", state: "closed", label: "休市", timezone: "Asia/Hong_Kong", session: "09:30-12:00 / 13:00-16:00", updated_at: "2026-06-17T00:00:00+00:00" },
  { market: "us", state: "pre_market", label: "盘前", timezone: "America/New_York", session: "09:30-16:00", updated_at: "2026-06-17T00:00:00+00:00" },
  { market: "crypto", state: "trading", label: "24/7", timezone: "UTC", session: "24/7", updated_at: "2026-06-17T00:00:00+00:00" }
];

const health: HealthResponse = {
  status: "partial",
  services: [
    { name: "FastAPI", status: "ok", source: "local api", updated_at: "2026-06-17T00:00:00+00:00" },
    { name: "Cache", status: "ok", source: "InMemoryJsonCache", updated_at: "2026-06-17T00:00:00+00:00" },
    {
      name: "Background refresh",
      status: "partial",
      source: "60s interval",
      updated_at: "2026-06-17T00:00:00+00:00",
      message: "部分板块成分刷新超时"
    },
    { name: "Quotes", status: "ok", source: "AKShare", updated_at: "2026-06-17T00:00:00+00:00" },
    { name: "Gold", status: "ok", source: "AKShare", updated_at: "2026-06-17T00:00:00+00:00" },
    { name: "Sectors", status: "unavailable", source: "fake-sector", updated_at: "2026-06-17T00:00:00+00:00" }
  ]
};

const sectorDetail: SectorDetailResponse = {
  market: "a",
  sector_name: "机器人概念",
  status: { status: "ok", source: "AKShare detail", updated_at: "2026-06-17T00:00:00+00:00" },
  items: [
    { symbol: "300024", name: "机器人", price: 18.2, change_percent: 3.8, volume: 45000000, source: "AKShare detail" }
  ]
};

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchWatchlist).mockResolvedValue(watchlist);
    vi.mocked(fetchQuotes).mockResolvedValue(quotes);
    vi.mocked(fetchGold).mockResolvedValue(gold);
    vi.mocked(fetchIndexes).mockResolvedValue(indexes);
    vi.mocked(fetchSectors).mockImplementation(async (market) => sectors[market]);
    vi.mocked(fetchSectorDetails).mockResolvedValue(sectorDetail);
    vi.mocked(fetchHealth).mockResolvedValue(health);
    vi.mocked(fetchMarketStatuses).mockResolvedValue(marketStatuses);
    vi.mocked(fetchSymbolSearch).mockResolvedValue([]);
    vi.mocked(addWatchItem).mockResolvedValue({ id: "us:TSLA", market: "us", symbol: "TSLA", name: "Tesla" });
    vi.mocked(deleteWatchItem).mockResolvedValue({ deleted: true });
  });

  it("renders the dashboard shell immediately while data requests are pending", () => {
    vi.mocked(fetchWatchlist).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchQuotes).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchGold).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchIndexes).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchSectors).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchHealth).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchMarketStatuses).mockReturnValue(new Promise(() => {}));

    render(<App />);

    expect(screen.getByText("全球行情监控")).toBeInTheDocument();
    expect(screen.getByText("自选股行情")).toBeInTheDocument();
    expect(screen.getAllByText("加载中")).not.toHaveLength(0);
    expect(screen.queryByText("正在连接本地行情服务...")).not.toBeInTheDocument();
  });

  it("renders quotes, gold, market summaries, and sector states", async () => {
    render(<App />);

    expect(await screen.findByText("Apple")).toBeInTheDocument();
    expect(screen.getByText("$192.40")).toBeInTheDocument();
    expect(screen.getByText("Bitcoin")).toBeInTheDocument();
    expect(screen.getAllByText("$65,000.00").length).toBeGreaterThan(0);
    expect(screen.getByText("Ethereum")).toBeInTheDocument();
    expect(screen.getAllByText("加密货币").length).toBeGreaterThan(0);
    expect(screen.getByText("上海金 Au99.99")).toBeInTheDocument();
    expect(screen.getByText("上证指数")).toBeInTheDocument();
    expect(screen.getByText("恒生指数")).toBeInTheDocument();
    expect(screen.getByText("标普500")).toBeInTheDocument();
    expect(screen.getByText("¥3,100.00")).toBeInTheDocument();
    expect(screen.getByText("HK$18,000.00")).toBeInTheDocument();
    expect(screen.getByText("$4,900.00")).toBeInTheDocument();
    expect(screen.getByText("暂无板块排行")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText(/交易中/)).toBeInTheDocument();
    expect(screen.getAllByText(/更新/).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("AAPL 行情卡")).toBeInTheDocument();
  });

  it("shows BTC and ETH live prices in the crypto summary card", async () => {
    render(<App />);

    const cryptoCard = await screen.findByLabelText("加密货币实时价格");

    expect(within(cryptoCard).getByText("BTC")).toBeInTheDocument();
    expect(within(cryptoCard).getByText("$65,000.00")).toBeInTheDocument();
    expect(within(cryptoCard).getByText("+1.56%")).toBeInTheDocument();
    expect(within(cryptoCard).getByText("ETH")).toBeInTheDocument();
    expect(within(cryptoCard).getByText("$3,500.00")).toBeInTheDocument();
    expect(within(cryptoCard).getByText("-1.41%")).toBeInTheDocument();
    expect(within(cryptoCard).queryByText(/自选/)).not.toBeInTheDocument();
  });

  it("keeps interface health in a topbar menu until requested", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("Apple")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "接口健康" })).not.toBeInTheDocument();

    const healthButton = screen.getByRole("button", { name: "接口健康" });
    await user.click(healthButton);

    expect(screen.getByRole("region", { name: "接口健康" })).toBeInTheDocument();
    expect(screen.getByText("Cache")).toBeInTheDocument();
    expect(screen.getByText("部分板块成分刷新超时")).toBeInTheDocument();

    await user.click(healthButton);
    expect(screen.queryByRole("region", { name: "接口健康" })).not.toBeInTheDocument();
  });

  it("renders compact quote cards with status text and sparklines", async () => {
    render(<App />);

    expect(await screen.findByText("Apple")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByLabelText("AAPL 行情卡")).toBeInTheDocument();
    expect(screen.getByLabelText("AAPL 日内走势示意")).toBeInTheDocument();
    expect(screen.getAllByText("震荡上涨").length).toBeGreaterThan(0);
    expect(screen.getByText("震荡下跌")).toBeInTheDocument();
    expect(screen.getByText("+1.26%")).toBeInTheDocument();
    expect(screen.getAllByText("-1.41%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$65,000.00").length).toBeGreaterThan(0);
  });

  it("renders quote card activity and valuation metrics", async () => {
    render(<App />);

    const appleCard = await screen.findByLabelText("AAPL 行情卡");

    expect(within(appleCard).getByText("成交额")).toBeInTheDocument();
    expect(within(appleCard).getByText("1.23亿")).toBeInTheDocument();
    expect(within(appleCard).getByText("量比")).toBeInTheDocument();
    expect(within(appleCard).getByText("1.37")).toBeInTheDocument();
    expect(within(appleCard).getByText("市盈率")).toBeInTheDocument();
    expect(within(appleCard).getByText("29.48")).toBeInTheDocument();
    expect(within(appleCard).getByText("总市值")).toBeInTheDocument();
    expect(within(appleCard).getByText("3.2万亿")).toBeInTheDocument();
  });

  it("loads sector constituents when a sector row is selected", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("机器人概念");

    await user.click(screen.getByRole("button", { name: /查看机器人概念成分/ }));

    expect(fetchSectorDetails).toHaveBeenCalledWith("a", "机器人概念");
    expect(await screen.findByText("板块成分")).toBeInTheDocument();
    expect(screen.getByText("机器人")).toBeInTheDocument();
    expect(screen.getByText("300024")).toBeInTheDocument();
  });

  it("renders the watchlist before slower quotes finish", async () => {
    let resolveQuotes: (value: Quote[]) => void = () => {};
    vi.mocked(fetchQuotes).mockReturnValue(
      new Promise((resolve) => {
        resolveQuotes = resolve;
      })
    );

    render(<App />);

    expect(await screen.findByText("Apple")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    resolveQuotes(quotes);

    expect(await screen.findByText("$192.40")).toBeInTheDocument();
  });

  it("adds a watch item from the inline form", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Apple");

    await user.selectOptions(screen.getByLabelText("市场"), "us");
    await user.type(screen.getByLabelText("代码"), "TSLA");
    await user.type(screen.getByLabelText("名称"), "Tesla");
    await user.click(screen.getByRole("button", { name: "添加自选" }));

    expect(addWatchItem).toHaveBeenCalledWith({ market: "us", symbol: "TSLA", name: "Tesla" });
    await waitFor(() => expect(fetchWatchlist).toHaveBeenCalledTimes(2));
  });

  it("searches symbols from the name field and fills the selected candidate", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchSymbolSearch).mockResolvedValue(symbolResults);
    render(<App />);
    await screen.findByText("Apple");

    await user.selectOptions(screen.getByLabelText("市场"), "a");
    await user.type(screen.getByLabelText("名称"), "贵州");
    await user.click(await screen.findByRole("button", { name: "贵州茅台 600519 A股" }));
    await user.click(screen.getByRole("button", { name: "添加自选" }));

    expect(fetchSymbolSearch).toHaveBeenCalledWith("a", "贵州");
    expect(addWatchItem).toHaveBeenCalledWith({ market: "a", symbol: "600519", name: "贵州茅台" });
  });

  it("shows the created watch item immediately when the watchlist refresh is stale", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchWatchlist).mockResolvedValue(watchlist);
    vi.mocked(addWatchItem).mockResolvedValue({ id: "us:TSLA", market: "us", symbol: "TSLA", name: "Tesla" });
    render(<App />);
    await screen.findByText("Apple");

    await user.selectOptions(screen.getByLabelText("市场"), "us");
    await user.type(screen.getByLabelText("代码"), "TSLA");
    await user.type(screen.getByLabelText("名称"), "Tesla");
    await user.click(screen.getByRole("button", { name: "添加自选" }));

    expect(await screen.findByText("Tesla")).toBeInTheDocument();
    await waitFor(() => expect(fetchQuotes).toHaveBeenCalledTimes(2));
  });

  it("removes a watch item", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("Apple");

    await user.click(screen.getByRole("button", { name: "删除 AAPL" }));

    expect(deleteWatchItem).toHaveBeenCalledWith("us:AAPL");
    await waitFor(() => expect(fetchWatchlist).toHaveBeenCalledTimes(2));
  });
});
