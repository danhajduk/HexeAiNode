import { describe, expect, it } from "vitest";
import {
  formatBudgetPeriod,
  formatLocalTimestamp,
  formatPrice,
  formatTierLabel,
  formatTokenHint,
  formatUsdExact,
  parseIsoTimestamp,
} from "./formatters";

describe("shared formatters", () => {
  it("formats token pricing with the existing precision rules", () => {
    expect(formatPrice(3)).toBe("$3.00/1M");
    expect(formatPrice(0.125)).toBe("$0.125/1M");
    expect(formatPrice(undefined)).toBe("unavailable");
  });

  it("parses ISO timestamps defensively", () => {
    expect(parseIsoTimestamp("2026-04-04T12:00:00Z")).toBeGreaterThan(0);
    expect(parseIsoTimestamp("not-a-date")).toBe(0);
  });

  it("preserves unknown local timestamps and formats valid values", () => {
    expect(formatLocalTimestamp("")).toBe("");
    expect(formatLocalTimestamp("not-a-date")).toBe("not-a-date");
    expect(formatLocalTimestamp("2026-04-04T12:00:00Z")).toContain("2026");
  });

  it("formats UI labels consistently", () => {
    expect(formatTierLabel("validation_complete")).toBe("Validation complete");
    expect(formatBudgetPeriod("weekly")).toBe("Weekly (Mon-Sun)");
    expect(formatBudgetPeriod("monthly")).toBe("Monthly");
    expect(formatBudgetPeriod("quarterly")).toBe("not_set");
  });

  it("masks token hints without losing the suffix", () => {
    expect(formatTokenHint("not_saved")).toBe("not_saved");
    expect(formatTokenHint("demo-token-abcdef12345")).toBe("********12345");
  });

  it("formats USD values using the existing exact display rules", () => {
    expect(formatUsdExact(2)).toBe("$2.00");
    expect(formatUsdExact(0.125)).toBe("$0.125000");
    expect(formatUsdExact(-1)).toBe("$0.000000");
  });
});
