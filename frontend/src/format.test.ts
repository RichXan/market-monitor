import { describe, expect, it } from "vitest";
import { formatCurrency, formatPercent, movementClass } from "./format";

describe("format helpers", () => {
  it("formats currency with the expected market symbol", () => {
    expect(formatCurrency(1500.5, "CNY")).toBe("¥1,500.50");
    expect(formatCurrency(410.2, "HKD")).toBe("HK$410.20");
    expect(formatCurrency(192.4, "USD")).toBe("$192.40");
  });

  it("formats signed percentages", () => {
    expect(formatPercent(0.81)).toBe("+0.81%");
    expect(formatPercent(-0.58)).toBe("-0.58%");
    expect(formatPercent(null)).toBe("--");
  });

  it("maps movement values to display classes", () => {
    expect(movementClass(1)).toBe("positive");
    expect(movementClass(-1)).toBe("negative");
    expect(movementClass(0)).toBe("flat");
    expect(movementClass(null)).toBe("flat");
  });
});
