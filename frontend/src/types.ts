export type Market = "a" | "hk" | "us";
export type StatusKind = "ok" | "partial" | "unavailable" | "error";

export interface ProviderStatus {
  status: StatusKind;
  source: string;
  updated_at: string;
  message?: string | null;
}

export interface WatchItem {
  id: string;
  market: Market;
  symbol: string;
  name?: string | null;
}

export interface WatchItemPayload {
  market: Market;
  symbol: string;
  name?: string | null;
}

export interface Quote {
  id: string;
  market: Market;
  symbol: string;
  name?: string | null;
  price?: number | null;
  change?: number | null;
  change_percent?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  previous_close?: number | null;
  volume?: number | null;
  amount?: number | null;
  currency: string;
  status: ProviderStatus;
}

export interface GoldQuote {
  symbol: string;
  name: string;
  price?: number | null;
  currency: string;
  status: ProviderStatus;
}

export interface SectorItem {
  name: string;
  price?: number | null;
  change?: number | null;
  change_percent?: number | null;
  volume?: number | null;
  amount?: number | null;
}

export interface SectorResponse {
  market: Market;
  status: ProviderStatus;
  items: SectorItem[];
}

export interface SymbolSearchResult {
  market: Market;
  symbol: string;
  name: string;
  source: string;
}

export interface OverviewResponse {
  watchlist: WatchItem[];
  quotes: Quote[];
  gold: GoldQuote;
  sectors: SectorResponse[];
}
