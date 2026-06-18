export type Market = "a" | "hk" | "us" | "crypto";
export type StatusKind = "ok" | "partial" | "unavailable" | "error";
export type MarketState = "trading" | "break" | "pre_market" | "after_hours" | "closed";

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

export interface MarketStatus {
  market: Market;
  state: MarketState;
  label: string;
  timezone: string;
  session: string;
  updated_at: string;
}

export interface HealthService {
  name: string;
  status: StatusKind;
  source: string;
  updated_at: string;
  message?: string | null;
}

export interface HealthResponse {
  status: StatusKind;
  services: HealthService[];
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

export interface IndexQuote {
  market: Market;
  symbol: string;
  name: string;
  price?: number | null;
  change?: number | null;
  change_percent?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  previous_close?: number | null;
  volume?: number | null;
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

export interface SectorConstituent {
  symbol: string;
  name: string;
  price?: number | null;
  change_percent?: number | null;
  volume?: number | null;
  amount?: number | null;
  currency?: string | null;
  source: string;
}

export interface SectorDetailResponse {
  market: Market;
  sector_name: string;
  status: ProviderStatus;
  items: SectorConstituent[];
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
