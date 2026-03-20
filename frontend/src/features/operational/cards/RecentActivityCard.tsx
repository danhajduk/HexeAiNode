import { CardHeader, SeverityIndicator } from "../../../components/uiPrimitives";

function inferTone(item) {
  if (item.tone) return item.tone;
  if (String(item.value || "").includes("failed") || String(item.value || "").includes("error")) return "danger";
  if (String(item.value || "").includes("stale") || String(item.value || "").includes("retry")) return "warning";
  return "meta";
}

export function RecentActivityCard({ items = [], degraded = false }) {
  return (
    <article className="card">
      <CardHeader
        title="Recent Activity"
        subtitle={degraded ? "Recent events are shown while the node remains available in degraded mode." : "Recent node events and timestamps."}
      />
      {items.length ? (
        <div className="activity-list">
          {items.map((item) => (
            <div key={item.label} className="activity-row">
              <div>
                <strong>{item.label}</strong>
                {item.hint ? <p className="muted tiny">{item.hint}</p> : null}
              </div>
              <SeverityIndicator tone={inferTone(item)}>
                <span>{item.value || "unavailable"}</span>
              </SeverityIndicator>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted tiny">No recent activity available yet.</p>
      )}
    </article>
  );
}
