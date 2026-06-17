import { Activity, AlertTriangle, Clock3, Plus, Radio, RefreshCw, Trash2 } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  addWatchItem,
  deleteWatchItem,
  fetchGold,
  fetchHealth,
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

const markets: Market[] = ["a", "hk", "us"];

const marketLabels: Record<Market, string> = {
  a: "A股",
  hk: "港股",
  us: "美股"
};

const marketHint: Record<Market, string> = {
  a: "AKShare / 东方财富；必要时 Yahoo 兜底",
  hk: "AKShare / 东方财富延迟；必要时 Yahoo 兜底",
  us: "Yahoo Finance / yfinance"
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

const initialSectors: SectorResponse[] = markets.map((market) => ({
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

function rangePosition(value?: number | null, low?: number | null, high?: number | null): number {
  if (value === null || value === undefined || low === null || low === undefined || high === null || high === undefined || high <= low) {
    return 50;
  }
  return Math.max(0, Math.min(100, ((value - low) / (high - low)) * 100));
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

export default function App() {
  const [watchlist, setWatchlist] = useState<WatchItem[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
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
  const loading = pendingLoads > 0;

  const quotesById = useMemo(() => {
    return new Map(quotes.map((quote) => [quote.id, quote]));
  }, [quotes]);

  const marketStatusByMarket = useMemo(() => {
    return new Map(marketStatuses.map((status) => [status.market, status]));
  }, [marketStatuses]);

  async function loadCoreData(preserveItems: WatchItem[] = []) {
    const failures: string[] = [];
    const watchlistPromise = fetchWatchlist();
    const quotesPromise = fetchQuotes();
    const goldPromise = fetchGold();
    const healthPromise = fetchHealth();
    const marketStatusesPromise = fetchMarketStatuses();

    try {
      const items = await watchlistPromise;
      setWatchlist(mergeWatchItems(items, preserveItems));
    } catch {
      failures.push("自选列表");
    }

    const [quotesResult, goldResult, healthResult, marketStatusesResult] = await Promise.allSettled([
      quotesPromise,
      goldPromise,
      healthPromise,
      marketStatusesPromise
    ]);

    if (quotesResult.status === "fulfilled") setQuotes(quotesResult.value);
    else failures.push("行情");

    if (goldResult.status === "fulfilled") setGold(goldResult.value);
    else failures.push("黄金");

    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
    else failures.push("接口健康");

    if (marketStatusesResult.status === "fulfilled") setMarketStatuses(marketStatusesResult.value);
    else failures.push("交易时段");

    return failures;
  }

  async function loadSectors() {
    setSectors((current) =>
      markets.map((market) => current.find((sector) => sector.market === market) ?? initialSectors.find((sector) => sector.market === market)!)
    );

    const results = await Promise.all(
      markets.map(async (market) => {
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
        {markets.map((market) => {
          const marketItems = watchlist.filter((item) => item.market === market);
          const quoted = marketItems.filter((item) => {
            const quote = quotesById.get(item.id);
            return quote?.status.status === "ok" && quote.price !== null && quote.price !== undefined;
          }).length;
          return (
            <div key={market}>
              <span className="strip-label">{marketLabels[market]}</span>
              <strong>{marketStatusByMarket.get(market)?.label ?? "状态读取中"}</strong>
              <small>自选 {marketItems.length}</small>
              <small>已报价 {quoted}/{marketItems.length}</small>
              <small>{marketStatusByMarket.get(market)?.session ?? marketHint[market]}</small>
            </div>
          );
        })}
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
              placeholder="AAPL / 00700 / 600519"
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

      <HealthPanel health={health} />

      <section className="dashboard-grid">
        <WatchlistPanel watchlist={watchlist} quotesById={quotesById} onDelete={handleDelete} />
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
    </div>
  );
}

function WatchlistPanel({
  watchlist,
  quotesById,
  onDelete
}: {
  watchlist: WatchItem[];
  quotesById: Map<string, Quote>;
  onDelete: (id: string) => Promise<void>;
}) {
  return (
    <section className="panel watchlist-panel">
      <div className="panel-header">
        <div>
          <h2>自选行情</h2>
          <p>页面内增删，本地保存</p>
        </div>
      </div>
      <div className="quote-table" role="table">
        <div className="quote-row quote-head" role="row">
          <span>市场</span>
          <span>标的</span>
          <span>最新</span>
          <span>涨跌幅</span>
          <span>日内</span>
          <span>成交量</span>
          <span>更新</span>
          <span></span>
        </div>
        {watchlist.length === 0 ? (
          <div className="empty-table-row">加载中</div>
        ) : (
          watchlist.map((item) => {
            const quote = quotesById.get(item.id);
            const movement = movementClass(quote?.change_percent);
            return (
              <div className="quote-row" role="row" key={item.id}>
                <span className="market-tag">{marketLabels[item.market]}</span>
                <span className="symbol-cell">
                  <strong>{quote?.name ?? item.name ?? item.symbol}</strong>
                  <small>{item.symbol}</small>
                </span>
                <span>{quote ? formatCurrency(quote.price, quote.currency) : "--"}</span>
                <span className={movement}>{formatPercent(quote?.change_percent)}</span>
                <span>
                  <PriceRange quote={quote} symbol={item.symbol} />
                </span>
                <span>{formatCompact(quote?.volume)}</span>
                <span className="source-cell">
                  <span>更新</span> {formatTime(quote?.status.updated_at)}
                  <small>{quote?.status.source ?? marketHint[item.market]}</small>
                </span>
                <button className="icon-button ghost" onClick={() => onDelete(item.id)} title={`删除 ${item.symbol}`} aria-label={`删除 ${item.symbol}`}>
                  <Trash2 aria-hidden="true" size={16} />
                </button>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

function PriceRange({ quote, symbol }: { quote?: Quote; symbol: string }) {
  if (!quote || quote.low === null || quote.low === undefined || quote.high === null || quote.high === undefined) {
    return <span className="range-empty">--</span>;
  }
  const marker = rangePosition(quote.price, quote.low, quote.high);
  const open = rangePosition(quote.open, quote.low, quote.high);
  return (
    <span className="range-cell" aria-label={`日内区间 ${symbol}`}>
      <span className="range-track">
        <span className="range-open" style={{ left: `${open}%` }} />
        <span className="range-marker" style={{ left: `${marker}%` }} />
      </span>
      <small>
        L {formatCurrency(quote.low, quote.currency)} / H {formatCurrency(quote.high, quote.currency)}
      </small>
    </span>
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
