import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function serviceObject(value) {
  return value && typeof value === "object" ? value : {};
}

function formatPercent(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(1)}%` : "-";
}

function compactText(value, fallback = "unknown") {
  const text = String(value || "").trim();
  return text || fallback;
}

function componentStats(component) {
  const stats = serviceObject(component.usage_statistics);
  const current = serviceObject(stats.current);
  const average = serviceObject(stats.rolling_average);
  const max = serviceObject(stats.rolling_max);
  return { stats, current, average, max };
}

export function LocalResidencyCard({
  serviceStatus = {},
  localSchedulerBusyTarget = "",
  onRequestLocalScheduler,
  onReleaseLocalScheduler,
}) {
  const localScheduler = serviceObject(serviceStatus.local_scheduler);
  const localSchedulerComponents = Array.isArray(localScheduler.components) ? localScheduler.components : [];
  const requestPreviews = serviceObject(localScheduler.request_previews);

  return (
    <article className="card">
      <CardHeader title="Local Residency" subtitle="Scheduler view of local model and runtime residency." />
      <div className="runtime-residency-grid">
        {localSchedulerComponents.map((component) => {
          const idle = serviceObject(component.idle);
          const blockers = Array.isArray(component.blockers) ? component.blockers : [];
          const preview = serviceObject(requestPreviews[component.component_id]);
          const stats = componentStats(component);
          const busy = localSchedulerBusyTarget === component.component_id;
          const reason = compactText(preview.reason || blockers.join(", "), "");
          return (
            <article className="runtime-residency-card" key={component.component_id}>
              <div className="runtime-residency-card-header">
                <div className="runtime-residency-card-title">
                  <strong>{component.display_name || component.component_id}</strong>
                  <span className="muted tiny">{component.adapter_id || "adapter_unknown"}</span>
                </div>
                <StatusBadge value={component.observed_state || "unknown"} />
              </div>
              <div className="runtime-residency-summary">
                <div>
                  <span>Desired</span>
                  <StatusBadge value={component.desired_state || "unknown"} />
                </div>
                <div>
                  <span>Phase</span>
                  <code>{compactText(component.phase)}</code>
                </div>
                <div>
                  <span>Work</span>
                  <code>
                    {idle.in_flight ?? 0} running / {idle.queued ?? 0} queued
                  </code>
                </div>
                <div>
                  <span>Decision</span>
                  <code>{compactText(preview.decision)}</code>
                </div>
              </div>
              <div className="runtime-residency-metrics">
                <span>
                  <b>CPU</b>
                  <code>{formatPercent(stats.current.cpu_percent)}</code>
                </span>
                <span>
                  <b>RAM</b>
                  <code>{formatPercent(stats.current.ram_percent)}</code>
                </span>
                <span>
                  <b>Avg</b>
                  <code>{formatPercent(stats.average.cpu_percent)}</code>
                </span>
                <span>
                  <b>Max</b>
                  <code>{formatPercent(stats.max.cpu_percent)}</code>
                </span>
              </div>
              {reason ? (
                <p className="runtime-residency-reason">
                  <span>Reason</span>
                  <code>{reason}</code>
                </p>
              ) : null}
              <div className="runtime-residency-actions">
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={() => onRequestLocalScheduler?.(component.component_id)}
                >
                  {busy ? "Working..." : "Request"}
                </button>
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={() => onReleaseLocalScheduler?.(component.component_id)}
                >
                  {busy ? "Working..." : "Release"}
                </button>
              </div>
            </article>
          );
        })}
        {localSchedulerComponents.length ? null : (
          <p className="muted tiny">No local residency data is available yet.</p>
        )}
      </div>
    </article>
  );
}
