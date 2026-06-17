const currencySymbols: Record<string, string> = {
  CNY: "¥",
  HKD: "HK$",
  USD: "$"
};

export function formatCurrency(value: number | null | undefined, currency: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  const symbol = currencySymbols[currency] ?? `${currency} `;
  return `${symbol}${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function movementClass(value: number | null | undefined): "positive" | "negative" | "flat" {
  if (value === null || value === undefined || value === 0 || Number.isNaN(value)) {
    return "flat";
  }
  return value > 0 ? "positive" : "negative";
}
