import { Activity, AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, Clock3, MoreHorizontal, Plus, Radio, RefreshCw, Trash2, TrendingUp } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
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
import { formatCurrency, formatPercent, movementClass } from "./format";
import type {
  GoldQuote,
  HealthResponse,
  IndexQuote,
  HealthService,
  Market,
  MarketStatus,
  Quote,
  SectorDetailResponse,
  SectorResponse,
  SectorItem,
  SymbolSearchResult,
  WatchItem,
  WatchItemPayload
} from "./types";
import "./styles.css";

const indexMarkets: Market[] = ["a", "hk", "us"];
const sectorMarkets: Market[] = ["a", "hk", "us"];
const cryptoSummarySymbols = ["BTC-USD", "ETH-USD"];

type WatchlistSortKey = "manual" | "identity" | "change_percent" | "price" | "amount" | "volume_ratio" | "pe_ratio" | "market_cap";
type WatchlistSortDirection = "asc" | "desc";

type WatchlistSort = {
  key: WatchlistSortKey;
  direction: WatchlistSortDirection;
};

type WatchlistSortOption = {
  key: WatchlistSortKey;
  label: string;
  defaultDirection: WatchlistSortDirection;
};

const defaultWatchlistSort: WatchlistSort = { key: "manual", direction: "desc" };

const watchlistSortOptions: WatchlistSortOption[] = [
  { key: "manual", label: "默认", defaultDirection: "desc" },
  { key: "identity", label: "名称", defaultDirection: "asc" },
  { key: "change_percent", label: "涨跌幅", defaultDirection: "desc" },
  { key: "price", label: "价格", defaultDirection: "desc" },
  { key: "amount", label: "成交额", defaultDirection: "desc" },
  { key: "volume_ratio", label: "量比", defaultDirection: "desc" },
  { key: "pe_ratio", label: "市盈率", defaultDirection: "asc" },
  { key: "market_cap", label: "总市值", defaultDirection: "desc" }
];

const marketLabels: Record<Market, string> = {
  a: "A股",
  hk: "港股",
  us: "美股",
  crypto: "加密货币"
};

const marketHint: Record<Market, string> = {
  a: "AKShare / 东方财富；必要时 Yahoo 兜底",
  hk: "AKShare / 东方财富延迟；必要时 Yahoo 兜底",
  us: "Yahoo Finance / yfinance",
  crypto: "Yahoo Finance / yfinance crypto"
};

const marketCurrencies: Record<Market, string> = {
  a: "CNY",
  hk: "HKD",
  us: "USD",
  crypto: "USD"
};

const indexFallbackNames: Partial<Record<Market, string>> = {
  a: "上证指数",
  hk: "恒生指数",
  us: "标普500"
};

const initialGold: GoldQuote = {
  symbol: "Au99.99",
  name: "上海金 Au99.99",
  price: null,
  currency: "CNY/g",
  status: {
    status: "partial",
    source: "加载中",
    updated_at: "",
    message: "正在获取黄金行情"
  }
};

const initialSectors: SectorResponse[] = sectorMarkets.map((market) => ({
  market,
  items: [],
  status: {
    status: "partial",
    source: "加载中",
    updated_at: "",
    message: "正在获取板块数据"
  }
}));

const initialHealth: HealthResponse = {
  status: "partial",
  services: [
    {
      name: "FastAPI",
      status: "partial",
      source: "加载中",
      updated_at: "",
      message: "正在检查接口状态"
    }
  ]
};

function statusLabel(status: string): string {
  if (status === "ok") return "在线";
  if (status === "partial") return "加载中";
  if (status === "error") return "接口异常";
  return "数据源暂缺";
}

function formatCompact(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 2
  }).format(value);
}

function formatMetricNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2
  }).format(value);
}

function formatTime(value?: string | null): string {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16);
  return parsed.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function goldPrice(gold: GoldQuote): string {
  const price = gold.price;
  if (price === null || price === undefined) return "--";
  return gold.currency === "CNY/g" ? `¥${price.toFixed(2)}/g` : formatCurrency(price, gold.currency);
}

function errorSector(market: Market, message: string): SectorResponse {
  return {
    market,
    items: [],
    status: {
      status: "error",
      source: "本地 API",
      updated_at: new Date().toISOString(),
      message
    }
  };
}

function mergeWatchItems(items: WatchItem[], additions: WatchItem[]): WatchItem[] {
  const additionsById = new Map(additions.map((item) => [item.id, item]));
  const merged = items.map((item) => additionsById.get(item.id) ?? item);
  const existing = new Set(merged.map((item) => item.id));
  for (const item of additions) {
    if (!existing.has(item.id)) {
      merged.push(item);
      existing.add(item.id);
    }
  }
  return merged;
}

function baseAsset(symbol: string): string {
  return symbol.split("-")[0] || symbol;
}

function quoteStatusText(quote?: Quote): string {
  const change = quote?.change_percent;
  if (change === null || change === undefined || Number.isNaN(change)) return "等待报价";
  if (change >= 3) return "快速上涨";
  if (change > 0) return "震荡上涨";
  if (change <= -3) return "快速下跌";
  if (change < 0) return "震荡下跌";
  return "横盘整理";
}

function nextWatchlistSort(current: WatchlistSort, key: WatchlistSortKey): WatchlistSort {
  const option = watchlistSortOptions.find((item) => item.key === key) ?? watchlistSortOptions[0];
  if (key === "manual") return { key, direction: option.defaultDirection };
  if (current.key !== key) return { key, direction: option.defaultDirection };
  return { key, direction: current.direction === "desc" ? "asc" : "desc" };
}

function sortableQuoteValue(item: WatchItem, quote: Quote | undefined, key: WatchlistSortKey): string | number | null {
  if (key === "identity") return quote?.name ?? item.name ?? item.symbol;
  if (key === "change_percent") return quote?.change_percent ?? null;
  if (key === "price") return quote?.price ?? null;
  if (key === "amount") return quote?.amount ?? null;
  if (key === "volume_ratio") return quote?.volume_ratio ?? null;
  if (key === "pe_ratio") return quote?.pe_ratio ?? null;
  if (key === "market_cap") return quote?.market_cap ?? null;
  return null;
}

function isMissingSortValue(value: string | number | null): boolean {
  return value === null || value === "" || (typeof value === "number" && Number.isNaN(value));
}

function sortWatchlistItems(items: WatchItem[], quotesById: Map<string, Quote>, sort: WatchlistSort): WatchItem[] {
  if (sort.key === "manual") return items;
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftValue = sortableQuoteValue(left.item, quotesById.get(left.item.id), sort.key);
      const rightValue = sortableQuoteValue(right.item, quotesById.get(right.item.id), sort.key);
      const leftMissing = isMissingSortValue(leftValue);
      const rightMissing = isMissingSortValue(rightValue);
      if (leftMissing && rightMissing) return left.index - right.index;
      if (leftMissing) return 1;
      if (rightMissing) return -1;

      const direction = sort.direction === "asc" ? 1 : -1;
      if (typeof leftValue === "string" && typeof rightValue === "string") {
        const compared = leftValue.localeCompare(rightValue, "zh-CN", { numeric: true, sensitivity: "base" });
        return compared === 0 ? left.index - right.index : compared * direction;
      }

      const compared = Number(leftValue) - Number(rightValue);
      return compared === 0 ? left.index - right.index : compared * direction;
    })
    .map(({ item }) => item);
}

export default function App() {
  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [indexes, setIndexes] = useState<IndexQuote[]>([]);
  const [gold, setGold] = useState<GoldQuote>(initialGold);
  const [sectors, setSectors] = useState<SectorResponse[]>(initialSectors);
  const [health, setHealth] = useState<HealthResponse>(initialHealth);
  const [marketStatuses, setMarketStatuses] = useState<MarketStatus[]>([]);
  const [sectorDetail, setSectorDetail] = useState<SectorDetailResponse | null>(null);
  const [sectorDetailLoading, setSectorDetailLoading] = useState(false);
  const [sectorDetailError, setSectorDetailError] = useState<string | null>(null);
  const [pendingLoads, setPendingLoads] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<WatchItemPayload>({ market: "us", symbol: "", name: "" });
  const [symbolResults, setSymbolResults] = useState<SymbolSearchResult[]>([]);
  const [symbolSearchLoading, setSymbolSearchLoading] = useState(false);
  const [symbolSearchError, setSymbolSearchError] = useState<string | null>(null);
  const [selectedLookupKey, setSelectedLookupKey] = useState("");
  const [healthMenuOpen, setHealthMenuOpen] = useState(false);
  const [watchlistSort, setWatchlistSort] = useState<WatchlistSort>(defaultWatchlistSort);
  const loading = pendingLoads > 0;

  const quotesById = useMemo(() => {
    return new Map(quotes.map((quote) => [quote.id, quote]));
  }, [quotes]);

  const sortedWatchlist = useMemo(() => {
    return sortWatchlistItems(watchlist, quotesById, watchlistSort);
  }, [watchlist, quotesById, watchlistSort]);

  const indexByMarket = useMemo(() => {
    return new Map(indexes.map((index) => [index.market, index]));
  }, [indexes]);

  const marketStatusByMarket = useMemo(() => {
    return new Map(marketStatuses.map((status) => [status.market, status]));
  }, [marketStatuses]);

  async function loadCoreData(preserveItems: WatchItem[] = []) {
    const failures: string[] = [];
    const watchlistPromise = fetchWatchlist();
    const quotesPromise = fetchQuotes();
    const indexesPromise = fetchIndexes();
    const goldPromise = fetchGold();
    const marketStatusesPromise = fetchMarketStatuses();

    try {
      const items = await watchlistPromise;
      setWatchlist(mergeWatchItems(items, preserveItems));
    } catch {
      failures.push("自选列表");
    }

    const [quotesResult, indexesResult, goldResult, marketStatusesResult] = await Promise.allSettled([
      quotesPromise,
      indexesPromise,
      goldPromise,
      marketStatusesPromise
    ]);

    if (quotesResult.status === "fulfilled") setQuotes(quotesResult.value);
    else failures.push("行情");

    if (indexesResult.status === "fulfilled") setIndexes(indexesResult.value);
    else failures.push("指数");

    if (goldResult.status === "fulfilled") setGold(goldResult.value);
    else failures.push("黄金");

    if (marketStatusesResult.status === "fulfilled") setMarketStatuses(marketStatusesResult.value);
    else failures.push("交易时段");

    return failures;
  }

  async function loadSectors() {
    setSectors((current) =>
      sectorMarkets.map((market) => current.find((sector) => sector.market === market) ?? initialSectors.find((sector) => sector.market === market)!)
    );

    const results = await Promise.all(
      sectorMarkets.map(async (market) => {
        try {
          return await fetchSectors(market);
        } catch (exc) {
          return errorSector(market, exc instanceof Error ? exc.message : "板块数据加载失败");
        }
      })
    );
    setSectors(results);
  }

  async function withPendingLoad(task: () => Promise<void>) {
    setPendingLoads((count) => count + 1);
    try {
      await task();
    } finally {
      setPendingLoads((count) => Math.max(0, count - 1));
    }
  }

  async function refresh() {
    await withPendingLoad(async () => {
      setError(null);
      try {
        const [coreFailures] = await Promise.all([loadCoreData(), loadSectors()]);
        if (coreFailures.length > 0) {
          setError(`${coreFailures.join("、")}加载失败`);
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "行情加载失败");
      }
    });
  }

  async function loadHealth() {
    try {
      setHealth(await fetchHealth());
    } catch (exc) {
      setHealth({
        status: "error",
        services: [
          {
            name: "Health",
            status: "error",
            source: "本地 API",
            updated_at: new Date().toISOString(),
            message: exc instanceof Error ? exc.message : "接口健康加载失败"
          }
        ]
      });
    }
  }

  useEffect(() => {
    let ignore = false;
    async function load() {
      await withPendingLoad(async () => {
        setError(null);
        try {
          const [coreFailures] = await Promise.all([loadCoreData(), loadSectors()]);
          if (!ignore && coreFailures.length > 0) {
            setError(`${coreFailures.join("、")}加载失败`);
          }
        } catch (exc) {
          if (!ignore) {
            setError(exc instanceof Error ? exc.message : "行情加载失败");
          }
        }
      });
    }
    load();
    const timer = window.setInterval(load, 60000);
    return () => {
      ignore = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!healthMenuOpen) return;
    loadHealth();
  }, [healthMenuOpen]);

  useEffect(() => {
    const query = form.name?.trim() ?? "";
    const lookupKey = `${form.market}:${form.symbol}:${query}`;
    if (query.length < 2 || (form.symbol && lookupKey === selectedLookupKey)) {
      setSymbolResults([]);
      setSymbolSearchLoading(false);
      setSymbolSearchError(null);
      return;
    }

    let ignore = false;
    const timer = window.setTimeout(async () => {
      setSymbolSearchLoading(true);
      setSymbolSearchError(null);
      try {
        const results = await fetchSymbolSearch(form.market, query);
        if (!ignore) {
          setSymbolResults(results);
        }
      } catch (exc) {
        if (!ignore) {
          setSymbolResults([]);
          setSymbolSearchError(exc instanceof Error ? exc.message : "名称查询失败");
        }
      } finally {
        if (!ignore) {
          setSymbolSearchLoading(false);
        }
      }
    }, 250);

    return () => {
      ignore = true;
      window.clearTimeout(timer);
    };
  }, [form.market, form.name, form.symbol, selectedLookupKey]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fallbackCandidate = !form.symbol.trim() && symbolResults.length === 1 ? symbolResults[0] : null;
    const payload: WatchItemPayload = {
      market: form.market,
      symbol: (fallbackCandidate?.symbol ?? form.symbol).trim().toUpperCase(),
      name: fallbackCandidate?.name ?? (form.name?.trim() || null)
    };
    if (!payload.symbol) {
      setError("请选择候选标的或输入代码");
      return;
    }
    const created = await addWatchItem(payload);
    setWatchlist((current) => mergeWatchItems(current, [created]));
    setForm({ market: form.market, symbol: "", name: "" });
    setSymbolResults([]);
    setSelectedLookupKey("");
    await withPendingLoad(async () => {
      setError(null);
      const coreFailures = await loadCoreData([created]);
      if (coreFailures.length > 0) {
        setError(`${coreFailures.join("、")}加载失败`);
      }
    });
  }

  async function handleDelete(id: string) {
    await deleteWatchItem(id);
    await refresh();
  }

  async function handleSelectSector(market: Market, item: SectorItem) {
    setSectorDetailLoading(true);
    setSectorDetailError(null);
    setSectorDetail(null);
    try {
      setSectorDetail(await fetchSectorDetails(market, item.name));
    } catch (exc) {
      setSectorDetailError(exc instanceof Error ? exc.message : "板块成分加载失败");
    } finally {
      setSectorDetailLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow">LOCAL MARKET TERMINAL</div>
          <h1>全球行情监控</h1>
        </div>
        <div className="topbar-actions">
          {error ? (
            <span className="error-pill">{error}</span>
          ) : (
            <span className="source-pill">{loading ? "数据加载中" : "FastAPI / AKShare / Yahoo"}</span>
          )}
          <HealthMenu health={health} open={healthMenuOpen} onToggle={() => setHealthMenuOpen((open) => !open)} />
          <button className="icon-button" onClick={refresh} disabled={loading} title="刷新行情" aria-label="刷新行情">
            <RefreshCw aria-hidden="true" size={18} />
          </button>
        </div>
      </header>

      <section className="market-strip" aria-label="行情状态">
        <div>
          <span className="strip-label">黄金</span>
          <strong>{goldPrice(gold)}</strong>
          <small>{gold.name}</small>
          <small>{gold.status.source}</small>
        </div>
        {indexMarkets.map((market) => (
          <IndexSummaryCard
            key={market}
            market={market}
            index={indexByMarket.get(market)}
            status={marketStatusByMarket.get(market)}
          />
        ))}
        <CryptoSummaryCard quotes={quotes} status={marketStatusByMarket.get("crypto")} />
      </section>

      <section className="toolbar" aria-label="自选管理">
        <form onSubmit={handleSubmit} className="add-form">
          <label>
            市场
            <select
              value={form.market}
              onChange={(event) => {
                setSelectedLookupKey("");
                setForm((current) => ({ ...current, market: event.target.value as Market }));
              }}
            >
              <option value="a">A股</option>
              <option value="hk">港股</option>
              <option value="us">美股</option>
              <option value="crypto">加密货币</option>
            </select>
          </label>
          <label>
            代码
            <input
              value={form.symbol}
              onChange={(event) => {
                setSelectedLookupKey("");
                setForm((current) => ({ ...current, symbol: event.target.value }));
              }}
              placeholder="AAPL / BTC-USD / 00700"
            />
          </label>
          <div className="lookup-field">
            <label>
              名称
              <input
                value={form.name ?? ""}
                onChange={(event) => {
                  setSelectedLookupKey("");
                  setForm((current) => ({ ...current, name: event.target.value }));
                }}
                placeholder="输入名称反查代码"
                autoComplete="off"
              />
            </label>
            {(symbolSearchLoading || symbolSearchError || symbolResults.length > 0) && (
              <div className="symbol-suggestions" role="listbox" aria-label="名称匹配结果">
                {symbolSearchLoading ? <div className="symbol-search-state">查询中</div> : null}
                {symbolSearchError ? <div className="symbol-search-state">{symbolSearchError}</div> : null}
                {!symbolSearchLoading &&
                  symbolResults.map((item) => (
                    <button
                      key={`${item.market}:${item.symbol}`}
                      type="button"
                      aria-label={`${item.name} ${item.symbol} ${marketLabels[item.market]}`}
                      className="symbol-option"
                      onClick={() => {
                        setForm({ market: item.market, symbol: item.symbol, name: item.name });
                        setSelectedLookupKey(`${item.market}:${item.symbol}:${item.name}`);
                        setSymbolResults([]);
                        setSymbolSearchError(null);
                      }}
                    >
                      <strong>{item.name}</strong>
                      <span>{item.symbol}</span>
                      <small>{marketLabels[item.market]}</small>
                    </button>
                  ))}
              </div>
            )}
          </div>
          <button className="primary-button" type="submit" aria-label="添加自选">
            <Plus aria-hidden="true" size={17} />
            添加自选
          </button>
        </form>
      </section>

      <section className="dashboard-grid">
        <WatchlistPanel
          watchlist={sortedWatchlist}
          quotesById={quotesById}
          sort={watchlistSort}
          onSortChange={(key) => setWatchlistSort((current) => nextWatchlistSort(current, key))}
          onDelete={handleDelete}
        />
        <SectorsPanel
          sectors={sectors}
          sectorDetail={sectorDetail}
          sectorDetailLoading={sectorDetailLoading}
          sectorDetailError={sectorDetailError}
          onSelectSector={handleSelectSector}
        />
      </section>
    </main>
  );
}

function CryptoSummaryCard({ quotes, status }: { quotes: Quote[]; status?: MarketStatus }) {
  const cryptoQuotes = cryptoSummarySymbols.map((symbol) => {
    const quote = quotes.find((item) => item.market === "crypto" && item.symbol.toUpperCase() === symbol);
    return { symbol, quote };
  });
  const updatedAt = cryptoQuotes.find((item) => item.quote?.status.updated_at)?.quote?.status.updated_at;

  return (
    <div className="crypto-summary-card" aria-label="加密货币实时价格">
      <span className="strip-label">{marketLabels.crypto}</span>
      <strong className="crypto-session">{status?.label ?? "24/7"}</strong>
      <div className="crypto-price-list">
        {cryptoQuotes.map(({ symbol, quote }) => (
          <div className="crypto-price-row" key={symbol}>
            <span className="crypto-symbol">{baseAsset(symbol)}</span>
            <strong className="crypto-price">{formatCurrency(quote?.price, quote?.currency ?? "USD")}</strong>
            <span className={movementClass(quote?.change_percent)}>{formatPercent(quote?.change_percent)}</span>
          </div>
        ))}
      </div>
      <small>
        {status?.session ?? "24/7"} · 更新 {formatTime(updatedAt)}
      </small>
    </div>
  );
}

function IndexSummaryCard({
  market,
  index,
  status
}: {
  market: Market;
  index?: IndexQuote;
  status?: MarketStatus;
}) {
  const currency = index?.currency ?? marketCurrencies[market];
  return (
    <div className="index-summary-card">
      <span className="strip-label">{marketLabels[market]}</span>
      <strong className="index-name">{index?.name ?? indexFallbackNames[market] ?? marketLabels[market]}</strong>
      <span className={`index-price ${movementClass(index?.change_percent)}`}>{formatCurrency(index?.price, currency)}</span>
      <small className={`index-change ${movementClass(index?.change_percent)}`}>
        {formatPercent(index?.change_percent)}
        {index?.change !== null && index?.change !== undefined ? ` / ${formatCurrency(index.change, currency)}` : ""}
      </small>
      <small>{index?.status.source ?? marketHint[market]}</small>
      <small>
        {status?.label ?? "状态读取中"} · 更新 {formatTime(index?.status.updated_at)}
      </small>
    </div>
  );
}

function HealthMenu({
  health,
  open,
  onToggle
}: {
  health: HealthResponse;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="health-menu">
      <button
        className="icon-button"
        onClick={onToggle}
        title="接口健康"
        aria-label="接口健康"
        aria-expanded={open}
        aria-controls="health-menu-panel"
      >
        <Activity aria-hidden="true" size={18} />
        <span className={`health-status-dot ${health.status}`} />
      </button>
      {open ? (
        <div className="health-popover" id="health-menu-panel">
          <HealthPanel health={health} />
        </div>
      ) : null}
    </div>
  );
}

function HealthPanel({ health }: { health: HealthResponse }) {
  return (
    <section className="health-panel panel" aria-label="接口健康">
      <div className="panel-header">
        <div>
          <h2>接口健康</h2>
          <p>行情源、缓存与板块服务状态</p>
        </div>
        <span className={`status-badge ${health.status}`}>{statusLabel(health.status)}</span>
      </div>
      <div className="health-list">
        {health.services.map((service) => (
          <HealthServiceRow service={service} key={service.name} />
        ))}
      </div>
    </section>
  );
}

function HealthServiceRow({ service }: { service: HealthService }) {
  return (
    <div className="health-row">
      <Radio aria-hidden="true" size={15} />
      <strong>{service.name}</strong>
      <span className={`mini-status ${service.status}`}>{statusLabel(service.status)}</span>
      <small>{service.source}</small>
      <small>
        <span>更新</span> {formatTime(service.updated_at)}
      </small>
      {service.message ? <p>{service.message}</p> : null}
    </div>
  );
}

function WatchlistPanel({
  watchlist,
  quotesById,
  sort,
  onSortChange,
  onDelete
}: {
  watchlist: WatchItem[];
  quotesById: Map<string, Quote>;
  sort: WatchlistSort;
  onSortChange: (key: WatchlistSortKey) => void;
  onDelete: (id: string) => Promise<void>;
}) {
  return (
    <section className="panel watchlist-panel compact-watchlist-panel">
      <div className="panel-header compact-watchlist-header">
        <div className="compact-title">
          <TrendingUp aria-hidden="true" size={18} />
          <div>
            <h2>自选股行情</h2>
            <p>页面内增删，本地保存</p>
          </div>
        </div>
        <button className="icon-button ghost compact-more-button" type="button" aria-label="自选行情更多" title="自选行情更多">
          <MoreHorizontal aria-hidden="true" size={17} />
        </button>
      </div>
      <div className="compact-sort-bar" aria-label="自选行情排序">
        {watchlistSortOptions.map((option) => {
          const active = sort.key === option.key;
          const SortIcon = !active ? ArrowUpDown : sort.direction === "asc" ? ArrowUp : ArrowDown;
          return (
            <button
              aria-label={option.key === "manual" ? "恢复默认排序" : `按${option.label}排序`}
              aria-pressed={active}
              className={`sort-button ${active ? "active" : ""}`}
              key={option.key}
              onClick={() => onSortChange(option.key)}
              type="button"
            >
              <SortIcon aria-hidden="true" size={13} />
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
      <div className="compact-quote-list" aria-label="紧凑自选行情">
        {watchlist.length === 0 ? (
          <div className="empty-table-row">加载中</div>
        ) : (
          watchlist.map((item) => {
            const quote = quotesById.get(item.id);
            const movement = movementClass(quote?.change_percent);
            return (
              <article className={`compact-quote-card ${movement}`} aria-label={`${item.symbol} 行情卡`} key={item.id}>
                <div className="compact-quote-identity">
                  <strong>{quote?.name ?? item.name ?? item.symbol}</strong>
                  <small className={movement}>{quoteStatusText(quote)}</small>
                  <small>{item.symbol}</small>
                </div>
                <QuoteMetrics quote={quote} symbol={item.symbol} />
                <div className="compact-quote-values">
                  <strong className={movement}>{formatPercent(quote?.change_percent)}</strong>
                  <small>{quote ? formatCurrency(quote.price, quote.currency) : "--"}</small>
                </div>
                <button className="icon-button ghost compact-delete-button" onClick={() => onDelete(item.id)} title={`删除 ${item.symbol}`} aria-label={`删除 ${item.symbol}`}>
                  <Trash2 aria-hidden="true" size={16} />
                </button>
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}

function QuoteMetrics({ quote, symbol }: { quote?: Quote; symbol: string }) {
  const metrics = [
    { label: "成交额", value: formatCompact(quote?.amount) },
    { label: "量比", value: formatMetricNumber(quote?.volume_ratio) },
    { label: "市盈率", value: formatMetricNumber(quote?.pe_ratio) },
    { label: "总市值", value: formatCompact(quote?.market_cap) }
  ];
  return (
    <div className="compact-quote-metrics" aria-label={`${symbol} 行情指标`}>
      {metrics.map((metric) => (
        <span className="compact-quote-metric" key={metric.label}>
          <small>{metric.label}</small>
          <strong>{metric.value}</strong>
        </span>
      ))}
    </div>
  );
}

function emptySectorTitle(sector: SectorResponse): string {
  if (sector.status.status === "partial") return "加载中";
  if (sector.status.status === "error") return "接口异常";
  return "暂无板块排行";
}

function SectorsPanel({
  sectors,
  sectorDetail,
  sectorDetailLoading,
  sectorDetailError,
  onSelectSector
}: {
  sectors: SectorResponse[];
  sectorDetail: SectorDetailResponse | null;
  sectorDetailLoading: boolean;
  sectorDetailError: string | null;
  onSelectSector: (market: Market, item: SectorItem) => Promise<void>;
}) {
  return (
    <section className="sector-stack" aria-label="活跃板块">
      {sectors.map((sector) => (
        <div className="panel sector-panel" key={sector.market}>
          <div className="panel-header">
            <div>
              <h2>{marketLabels[sector.market]}活跃板块</h2>
              <p>{sector.status.source}</p>
            </div>
            <span className={`status-badge ${sector.status.status}`}>{statusLabel(sector.status.status)}</span>
          </div>
          {sector.items.length > 0 ? (
            <div className="sector-list">
              {sector.items.slice(0, 6).map((item) => (
                <button className="sector-row sector-button" key={item.name} onClick={() => onSelectSector(sector.market, item)} aria-label={`查看${item.name}成分`}>
                  <span>{item.name}</span>
                  <strong className={movementClass(item.change_percent)}>{formatPercent(item.change_percent)}</strong>
                  <small>{formatCompact(item.amount ?? item.volume)}</small>
                </button>
              ))}
            </div>
          ) : (
            <div className={sector.status.status === "partial" ? "unavailable loading-inline" : "unavailable"}>
              {sector.status.status === "partial" ? <Activity aria-hidden="true" size={18} /> : <AlertTriangle aria-hidden="true" size={18} />}
              <div>
                <strong>{emptySectorTitle(sector)}</strong>
                <p>{sector.status.message ?? "当前数据源没有返回板块排行。"}</p>
              </div>
            </div>
          )}
        </div>
      ))}
      <SectorDetailPanel detail={sectorDetail} loading={sectorDetailLoading} error={sectorDetailError} />
    </section>
  );
}

function SectorDetailPanel({
  detail,
  loading,
  error
}: {
  detail: SectorDetailResponse | null;
  loading: boolean;
  error: string | null;
}) {
  return (
    <div className="panel sector-detail-panel">
      <div className="panel-header">
        <div>
          <h2>板块成分</h2>
          <p>{detail ? `${marketLabels[detail.market]} / ${detail.sector_name}` : "点击上方板块查看关联标的"}</p>
        </div>
        {loading ? <Clock3 aria-hidden="true" size={18} /> : detail ? <span className={`status-badge ${detail.status.status}`}>{statusLabel(detail.status.status)}</span> : null}
      </div>
      {error ? <div className="unavailable">{error}</div> : null}
      {loading ? <div className="empty-table-row">加载板块成分</div> : null}
      {!loading && detail && detail.items.length > 0 ? (
        <div className="constituent-list">
          {detail.items.slice(0, 10).map((item) => (
            <div className="constituent-row" key={`${item.symbol}:${item.name}`}>
              <span>
                <strong>{item.name}</strong>
                <small>{item.symbol}</small>
              </span>
              <span>{formatCurrency(item.price, item.currency ?? "CNY")}</span>
              <strong className={movementClass(item.change_percent)}>{formatPercent(item.change_percent)}</strong>
              <small>{formatCompact(item.amount ?? item.volume)}</small>
            </div>
          ))}
        </div>
      ) : null}
      {!loading && detail && detail.items.length === 0 ? <div className="empty-table-row">暂无可用成分数据</div> : null}
    </div>
  );
}
