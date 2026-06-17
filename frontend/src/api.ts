import type { GoldQuote, Market, OverviewResponse, Quote, SectorResponse, SymbolSearchResult, WatchItem, WatchItemPayload } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function fetchOverview(): Promise<OverviewResponse> {
  return request<OverviewResponse>("/api/overview");
}

export function fetchWatchlist(): Promise<WatchItem[]> {
  return request<WatchItem[]>("/api/watchlist");
}

export function fetchQuotes(): Promise<Quote[]> {
  return request<Quote[]>("/api/quotes");
}

export function fetchGold(): Promise<GoldQuote> {
  return request<GoldQuote>("/api/gold");
}

export function fetchSectors(market: Market): Promise<SectorResponse> {
  return request<SectorResponse>(`/api/sectors?market=${market}`);
}

export function fetchSymbolSearch(market: Market, query: string): Promise<SymbolSearchResult[]> {
  const params = new URLSearchParams({ market, q: query });
  return request<SymbolSearchResult[]>(`/api/search-symbols?${params.toString()}`);
}

export function addWatchItem(payload: WatchItemPayload): Promise<WatchItem> {
  return request<WatchItem>("/api/watchlist", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function deleteWatchItem(id: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/api/watchlist/${encodeURIComponent(id)}`, {
    method: "DELETE"
  });
}
