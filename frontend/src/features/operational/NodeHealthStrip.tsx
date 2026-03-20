import { HealthIndicator, StatusBadge } from "../../components/uiPrimitives";

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
    <article className="card node-health-strip">
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
          <span className="muted tiny">Last Telemetry</span>
          <code>{lastTelemetryTimestamp || "none"}</code>
        </div>
      </div>
    </article>
  );
}
