import { CardHeader } from "../../../components/uiPrimitives";

function formatTimestamp(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "none";
  }
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(parsed));
}

export function ProviderRefreshCard({
  lastRefreshedAt,
  lastSubmittedAt,
}) {
  return (
    <article className="card capability-summary-card">
      <CardHeader
        title="Provider Refresh"
        subtitle="Latest provider catalog reload and provider-intelligence submission timestamps."
      />
      <div className="state-grid">
        <span>Last Catalog Refresh</span>
        <code>{formatTimestamp(lastRefreshedAt)}</code>
        <span>Last Submitted To Core</span>
        <code>{formatTimestamp(lastSubmittedAt)}</code>
      </div>
    </article>
  );
}
