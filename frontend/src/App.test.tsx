import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import {
  addWatchItem,
  deleteWatchItem,
  fetchGold,
  fetchQuotes,
  fetchSectors,
  fetchSymbolSearch,
  fetchWatchlist
} from "./api";
import type { GoldQuote, Quote, SectorResponse, SymbolSearchResult, WatchItem } from "./types";

vi.mock("./api", () => ({
  fetchWatchlist: vi.fn(),
  fetchQuotes: vi.fn(),
  fetchGold: vi.fn(),
  fetchSectors: vi.fn(),
  fetchSymbolSearch: vi.fn(),
  addWatchItem: vi.fn(),
  deleteWatchItem: vi.fn()
}));

const watchlist: WatchItem[] = [
  { id: "us:AAPL", market: "us", symbol: "AAPL", name: "Apple" },
  { id: "a:600519", market: "a", symbol: "600519", name: "贵州茅台" }
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
    currency: "CNY",
    status: { status: "ok", source: "AKShare", updated_at: "2026-06-17T00:00:00+00:00" }
  }
];

const gold: GoldQuote = {
  symbol: "Au99.99",
  name: "上海金 Au99.99",
  price: 756.2,
  currency: "CNY/g",
  status: { status: "ok", source: "AKShare", updated_at: "2026-06-17T00:00:00+00:00" }
};

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

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchWatchlist).mockResolvedValue(watchlist);
    vi.mocked(fetchQuotes).mockResolvedValue(quotes);
    vi.mocked(fetchGold).mockResolvedValue(gold);
    vi.mocked(fetchSectors).mockImplementation(async (market) => sectors[market]);
    vi.mocked(fetchSymbolSearch).mockResolvedValue([]);
    vi.mocked(addWatchItem).mockResolvedValue({ id: "us:TSLA", market: "us", symbol: "TSLA", name: "Tesla" });
    vi.mocked(deleteWatchItem).mockResolvedValue({ deleted: true });
  });

  it("renders the dashboard shell immediately while data requests are pending", () => {
    vi.mocked(fetchWatchlist).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchQuotes).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchGold).mockReturnValue(new Promise(() => {}));
    vi.mocked(fetchSectors).mockReturnValue(new Promise(() => {}));

    render(<App />);

    expect(screen.getByText("全球行情监控")).toBeInTheDocument();
    expect(screen.getByText("自选行情")).toBeInTheDocument();
    expect(screen.getAllByText("加载中")).not.toHaveLength(0);
    expect(screen.queryByText("正在连接本地行情服务...")).not.toBeInTheDocument();
  });

  it("renders quotes, gold, market summaries, and sector states", async () => {
    render(<App />);

    expect(await screen.findByText("Apple")).toBeInTheDocument();
    expect(screen.getByText("$192.40")).toBeInTheDocument();
    expect(screen.getByText("上海金 Au99.99")).toBeInTheDocument();
    expect(screen.getAllByText("自选 1")).toHaveLength(2);
    expect(screen.getAllByText("已报价 1/1")).toHaveLength(2);
    expect(screen.getByText("暂无板块排行")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
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
