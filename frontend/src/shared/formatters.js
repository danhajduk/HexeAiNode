export function formatPrice(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "unavailable";
  }
  return `$${value.toFixed(value >= 1 ? 2 : 3)}/1M`;
}

export function parseIsoTimestamp(value) {
  const parsed = Date.parse(String(value || ""));
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function formatLocalTimestamp(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "";
  }
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(parsed));
}

export function formatTierLabel(value) {
  const normalized = String(value || "unknown").replaceAll("_", " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function formatBudgetPeriod(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "weekly") {
    return "Weekly (Mon-Sun)";
  }
  if (normalized === "monthly") {
    return "Monthly";
  }
  return "not_set";
}

export function formatUsdExact(value) {
  const normalized = Number(value);
  if (!Number.isFinite(normalized) || normalized < 0) {
    return "$0.000000";
  }
  return `$${normalized.toFixed(normalized >= 1 ? 2 : 6)}`;
}

export function formatTokenHint(value) {
  const normalized = String(value || "").trim();
  if (!normalized || normalized === "not_saved") {
    return "not_saved";
  }
  const suffix = normalized.replace(/\*/g, "").slice(-5) || normalized.slice(-5);
  return `********${suffix}`;
}
