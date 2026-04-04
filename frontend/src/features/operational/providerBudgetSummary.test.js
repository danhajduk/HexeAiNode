import { describe, expect, it } from "vitest";
import {
  formatProviderBudgetPill,
  providerBudgetTone,
  summarizeProviderBudgets,
} from "./providerBudgetSummary";

describe("provider budget summary", () => {
  it("builds provider summaries from configured limits and runtime usage", () => {
    const summaries = summarizeProviderBudgets({
      providerConfig: {
        config: {
          providers: {
            budget_limits: {
              openai: { max_cost_cents: 10000, period: "monthly" },
              anthropic: { max_cost_cents: 5000, period: "weekly" },
            },
          },
        },
      },
      budgetState: {
        provider_budgets: [
          {
            provider_id: "openai",
            budget_limit_cents: 10000,
            remaining_cost_cents: 1500,
            budget_limit_usd_exact: 100,
            remaining_cost_usd_exact: 15,
            used_cost_usd_exact: 85,
            period: "monthly",
          },
        ],
      },
    });

    expect(summaries).toHaveLength(2);
    expect(summaries[0].providerId).toBe("anthropic");
    expect(summaries[1]).toMatchObject({
      providerId: "openai",
      remainingCostCents: 1500,
      budgetLimitUsdExact: 100,
      remainingCostUsdExact: 15,
      usedCostUsdExact: 85,
    });
  });

  it("derives warning and danger tones from remaining budget", () => {
    expect(providerBudgetTone({ budgetLimitCents: 1000, remainingCostCents: 900 })).toBe("success");
    expect(providerBudgetTone({ budgetLimitCents: 1000, remainingCostCents: 100 })).toBe("warning");
    expect(providerBudgetTone({ budgetLimitCents: 1000, remainingCostCents: 0 })).toBe("danger");
  });

  it("renders compact provider budget pills", () => {
    expect(
      formatProviderBudgetPill({
        providerId: "openai",
        remainingCostUsdExact: 10,
        budgetLimitUsdExact: 20,
        usedCostUsdExact: 10,
        period: "weekly",
      })
    ).toBe("OpenAI $10.00/$20.00 weekly · spent $10.00");
  });
});
