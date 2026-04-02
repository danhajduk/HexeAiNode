import { HealthIndicator, StatusBadge } from "../../components/uiPrimitives";

function formatRelativeHeartbeatAge(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "none";
  }

  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }

  const diffSeconds = Math.max(0, Math.floor((Date.now() - parsed) / 1000));
  if (diffSeconds < 60) {
    return `${diffSeconds} sec ago`;
  }
  if (diffSeconds < 3600) {
    return `${Math.floor(diffSeconds / 60)} min ago`;
  }
  if (diffSeconds < 86400) {
    return `${Math.floor(diffSeconds / 3600)} hour ago`;
  }
  return `${Math.floor(diffSeconds / 86400)} day ago`;
}

export function NodeHealthStrip({
  lifecycleState,
  trustStatus,
  coreApiStatus,
  mqttStatus,
  governanceStatus,
  providerStatus,
  lastTelemetryTimestamp,
}) {
  return (
    <article className="card node-health-strip operational-content-header">
      <div className="node-health-strip-grid">
        <div className="node-health-strip-item">
          <span className="muted tiny">Lifecycle</span>
          <StatusBadge value={lifecycleState || "unknown"} />
        </div>
        <div className="node-health-strip-item">
          <span className="muted tiny">Trust</span>
          <StatusBadge value={trustStatus || "unknown"} />
        </div>
        <div className="node-health-strip-item">
          <span className="muted tiny">Core API</span>
          <HealthIndicator value={coreApiStatus || "unknown"} />
        </div>
        <div className="node-health-strip-item">
          <span className="muted tiny">MQTT</span>
          <HealthIndicator value={mqttStatus || "unknown"} />
        </div>
        <div className="node-health-strip-item">
          <span className="muted tiny">Governance</span>
          <HealthIndicator value={governanceStatus || "unknown"} />
        </div>
        <div className="node-health-strip-item">
          <span className="muted tiny">Providers</span>
          <StatusBadge value={providerStatus || "unknown"} />
        </div>
        <div className="node-health-strip-item">
          <span className="muted tiny">Last Heartbeat</span>
          <code>{formatRelativeHeartbeatAge(lastTelemetryTimestamp)}</code>
        </div>
      </div>
    </article>
  );
}
