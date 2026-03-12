export function CardHeader({ title, subtitle }) {
  return (
    <div className="card-header">
      <h2>{title}</h2>
      {subtitle ? <p className="muted">{subtitle}</p> : null}
    </div>
  );
}

export function StatusBadge({ value }) {
  const normalized = String(value || "unknown").toLowerCase();
  return <span className={`status-badge status-${normalized}`}>{normalized}</span>;
}

export function HealthIndicator({ label, value }) {
  const normalized = String(value || "unknown").toLowerCase();
  return (
    <span className={`health-indicator health-${normalized}`}>
      <span className="health-dot" />
      {label || normalized}
    </span>
  );
}
