import { formatUsdExact } from "../../shared/formatters";

function formatProviderLabel(providerId) {
  const normalized = String(providerId || "").trim().toLowerCase();
  if (!normalized) {
    return "Provider";
  }
  if (normalized === "openai") {
    return "OpenAI";
  }
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function summarizeProviderBudgets({ providerConfig, budgetState }) {
  const configuredLimits = providerConfig?.config?.providers?.budget_limits;
  const configuredEntries =
    configuredLimits && typeof configuredLimits === "object" ? Object.entries(configuredLimits) : [];
  const budgetEntries = Array.isArray(budgetState?.provider_budgets) ? budgetState.provider_budgets : [];
  const budgetByProvider = new Map();

  budgetEntries.forEach((entry) => {
    const providerId = String(entry?.provider_id || "").trim().toLowerCase();
    if (!providerId) {
      return;
    }
    budgetByProvider.set(providerId, entry);
  });

  return configuredEntries
    .map(([providerId, settings]) => {
      const normalizedProviderId = String(providerId || "").trim().toLowerCase();
      const configuredBudget = Number(settings?.max_cost_cents);
      if (!normalizedProviderId || !Number.isFinite(configuredBudget) || configuredBudget < 0) {
        return null;
      }
      const usage = budgetByProvider.get(normalizedProviderId);
      const budgetLimitCents = Number(usage?.budget_limit_cents);
      const remainingCostCents = Number(usage?.remaining_cost_cents);
      const budgetLimitUsdExact = Number(usage?.budget_limit_usd_exact);
      const remainingCostUsdExact = Number(usage?.remaining_cost_usd_exact);
      const period = String(usage?.period || settings?.period || "monthly").trim().toLowerCase() || "monthly";
      return {
        providerId: normalizedProviderId,
        period,
        budgetLimitCents: Number.isFinite(budgetLimitCents) ? budgetLimitCents : configuredBudget,
        remainingCostCents: Number.isFinite(remainingCostCents) ? remainingCostCents : configuredBudget,
        budgetLimitUsdExact: Number.isFinite(budgetLimitUsdExact) ? budgetLimitUsdExact : configuredBudget / 100,
        remainingCostUsdExact: Number.isFinite(remainingCostUsdExact) ? remainingCostUsdExact : configuredBudget / 100,
        usedCostUsdExact: Number(usage?.used_cost_usd_exact),
      };
    })
    .filter(Boolean)
    .sort((left, right) => left.providerId.localeCompare(right.providerId));
}

export function providerBudgetTone(summary) {
  const budgetLimitCents = Number(summary?.budgetLimitCents);
  const remainingCostCents = Number(summary?.remainingCostCents);
  if (!Number.isFinite(budgetLimitCents) || budgetLimitCents <= 0) {
    return "meta";
  }
  if (!Number.isFinite(remainingCostCents) || remainingCostCents <= 0) {
    return "danger";
  }
  if (remainingCostCents / budgetLimitCents <= 0.2) {
    return "warning";
  }
  return "success";
}

export function formatProviderBudgetPill(summary) {
  return `${formatProviderLabel(summary?.providerId)} ${formatUsdExact(summary?.remainingCostUsdExact)}/${formatUsdExact(summary?.budgetLimitUsdExact)} ${String(summary?.period || "monthly").toLowerCase()} · spent ${formatUsdExact(summary?.usedCostUsdExact)}`;
}
