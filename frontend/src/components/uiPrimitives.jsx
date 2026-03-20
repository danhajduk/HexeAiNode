export function CardHeader({ title, subtitle }) {
  return (
    <div className="card-header">
      <h2>{title}</h2>
      {subtitle ? <p className="muted">{subtitle}</p> : null}
    </div>
  );
}

const STATUS_TONE_MAP = {
  operational: "success",
  running: "success",
  trusted: "success",
  connected: "success",
  ready: "success",
  enabled: "success",
  configured: "meta",
  selected: "meta",
  available: "meta",
  pending: "warning",
  bootstrap_connecting: "warning",
  bootstrap_connected: "warning",
  registration_pending: "warning",
  pending_approval: "warning",
  capability_setup_pending: "warning",
  degraded: "warning",
  disconnected: "danger",
  failed: "danger",
  stopped: "danger",
  blocked: "danger",
  error: "danger",
  offline: "danger",
  unknown: "warning",
};

export function SeverityIndicator({ tone = "meta", children }) {
  const normalized = String(tone || "meta").toLowerCase();
  return <span className={`severity-indicator severity-${normalized}`}>{children}</span>;
}

export function StatusBadge({ value, tone = null }) {
  const normalized = String(value || "unknown").toLowerCase();
  const resolvedTone = tone || STATUS_TONE_MAP[normalized] || "meta";
  return (
    <SeverityIndicator tone={resolvedTone}>
      <span className={`status-badge status-${normalized}`}>{normalized}</span>
    </SeverityIndicator>
  );
}

export function HealthIndicator({ label, value, tone = null }) {
  const normalized = String(value || "unknown").toLowerCase();
  const resolvedTone = tone || STATUS_TONE_MAP[normalized] || "meta";
  return (
    <SeverityIndicator tone={resolvedTone}>
      <span className={`health-indicator health-${normalized}`}>
        <span className="health-dot" />
        {label || normalized}
      </span>
    </SeverityIndicator>
  );
}

export function StageBadge({ value }) {
  const normalized = String(value || "pending").toLowerCase();
  const tone = normalized === "completed" ? "success" : normalized === "current" || normalized === "in_progress" ? "warning" : normalized === "error" || normalized === "failed" ? "danger" : "meta";
  return (
    <SeverityIndicator tone={tone}>
      <span className={`stage-badge stage-${normalized}`}>
        {normalized.replaceAll("_", " ")}
      </span>
    </SeverityIndicator>
  );
}
