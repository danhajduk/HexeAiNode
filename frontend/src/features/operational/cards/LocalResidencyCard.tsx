import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function serviceObject(value) {
  return value && typeof value === "object" ? value : {};
}

function formatPercent(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(1)}%` : "-";
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
  taskAvailability = [],
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
          return (
            <article className="runtime-residency-card" key={component.component_id}>
              <div className="runtime-residency-card-header">
                <div>
                  <strong>{component.display_name || component.component_id}</strong>
                  <code>{component.adapter_id || "adapter_unknown"}</code>
                </div>
                <StatusBadge value={component.observed_state || "unknown"} />
              </div>
              <div className="state-grid compact-grid">
                <span>Desired</span>
                <StatusBadge value={component.desired_state || "unknown"} />
                <span>Phase</span>
                <code>{component.phase || "unknown"}</code>
                <span>CPU</span>
                <code>{formatPercent(stats.current.cpu_percent)}</code>
                <span>RAM</span>
                <code>{formatPercent(stats.current.ram_percent)}</code>
                <span>Avg CPU</span>
                <code>{formatPercent(stats.average.cpu_percent)}</code>
                <span>Max CPU</span>
                <code>{formatPercent(stats.max.cpu_percent)}</code>
                <span>In Flight</span>
                <code>{idle.in_flight ?? 0}</code>
                <span>Queued</span>
                <code>{idle.queued ?? 0}</code>
                <span>Decision</span>
                <code>{preview.decision || "unknown"}</code>
                <span>Reason</span>
                <code>{preview.reason || blockers.join(", ") || "none"}</code>
              </div>
              <div className="row">
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
      <div className="runtime-task-availability">
        <h3>Task Availability</h3>
        <div className="runtime-task-availability-grid">
          {(Array.isArray(taskAvailability) ? taskAvailability : []).map((item) => (
            <div className="runtime-task-availability-row" key={item.taskFamily}>
              <code>{item.taskFamily}</code>
              <StatusBadge value={item.providerMode || "unavailable"} />
              <span>{item.reason || "no_reason"}</span>
            </div>
          ))}
          {Array.isArray(taskAvailability) && taskAvailability.length ? null : (
            <div className="runtime-task-availability-row">
              <code>none</code>
              <StatusBadge value="unavailable" />
              <span>no resolved tasks</span>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
