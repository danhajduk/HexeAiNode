import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function serviceObject(value) {
  return value && typeof value === "object" ? value : {};
}

function formatPercent(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(1)}%` : "-";
}

function formatMib(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "-";
  }
  if (parsed >= 1024) {
    return `${(parsed / 1024).toFixed(1)}G`;
  }
  return `${Math.round(parsed)}M`;
}

function compactText(value, fallback = "unknown") {
  const text = String(value || "").trim();
  return text || fallback;
}

function numericCount(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function componentStats(component) {
  const stats = serviceObject(component.usage_statistics);
  const current = serviceObject(stats.current);
  const average = serviceObject(stats.rolling_average);
  const max = serviceObject(stats.rolling_max);
  return { stats, current, average, max };
}

function componentWork({ component, executionQueue }) {
  const idle = serviceObject(component.idle);
  const lanes = serviceObject(executionQueue?.lanes);
  const lane = serviceObject(lanes[component.component_id]);
  if (Object.keys(lane).length) {
    return {
      running: numericCount(lane.active_count, idle.in_flight ?? 0),
      staged: numericCount(lane.staged_count, 0),
      backlog: numericCount(lane.backlog_count, 0),
    };
  }
  return {
    running: idle.in_flight ?? 0,
    staged: 0,
    backlog: idle.queued ?? 0,
  };
}

function residencyDisplayState(component, work) {
  const observed = compactText(component.observed_state, "unknown").toLowerCase();
  const hasWork = (work.running || 0) > 0 || (work.staged || 0) > 0 || (work.backlog || 0) > 0;
  if (observed === "running") {
    return hasWork ? "busy" : "idle";
  }
  return observed;
}

export function LocalResidencyCard({
  serviceStatus = {},
  executionQueue = null,
  localSchedulerBusyTarget = "",
  className = "",
  onRequestLocalScheduler,
  onReleaseLocalScheduler,
}) {
  const localScheduler = serviceObject(serviceStatus.local_scheduler);
  const localSchedulerComponents = Array.isArray(localScheduler.components) ? localScheduler.components : [];
  const requestPreviews = serviceObject(localScheduler.request_previews);

  return (
    <article className={`card ${className}`.trim()}>
      <CardHeader title="Local Residency" subtitle="Scheduler view of local model and runtime residency." />
      <div className="runtime-residency-legend">
        <span><b>Work</b></span>
        <span><code>run / staged / backlog</code></span>
      </div>
      <div className="runtime-residency-grid">
        {localSchedulerComponents.map((component) => {
          const blockers = Array.isArray(component.blockers) ? component.blockers : [];
          const preview = serviceObject(requestPreviews[component.component_id]);
          const stats = componentStats(component);
          const work = componentWork({ component, executionQueue });
          const busy = localSchedulerBusyTarget === component.component_id;
          const reason = compactText(preview.reason || blockers.join(", "), "");
          const displayState = residencyDisplayState(component, work);
          return (
            <article className="runtime-residency-card" key={component.component_id}>
              <div className="runtime-residency-card-header">
                <div className="runtime-residency-card-title">
                  <strong>{component.display_name || component.component_id}</strong>
                  <span className="muted tiny">{component.adapter_id || "adapter_unknown"}</span>
                </div>
                <StatusBadge value={displayState} />
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
                    {work.running} / {work.staged} / {work.backlog}
                  </code>
                </div>
                <div>
                  <span>Decision</span>
                  <code>{compactText(preview.decision)}</code>
                </div>
              </div>
              <div className="runtime-residency-metrics">
                <span>
                  <b>VRAM</b>
                  <code>{formatMib(stats.current.vram_mib)}</code>
                </span>
                <span>
                  <b>Avg VRAM</b>
                  <code>{formatMib(stats.average.vram_mib)}</code>
                </span>
                <span>
                  <b>Max VRAM</b>
                  <code>{formatMib(stats.max.vram_mib)}</code>
                </span>
                <span>
                  <b>GPU</b>
                  <code>{formatPercent(stats.current.gpu_util_percent)}</code>
                </span>
                <span>
                  <b>Avg GPU</b>
                  <code>{formatPercent(stats.average.gpu_util_percent)}</code>
                </span>
                <span>
                  <b>Max GPU</b>
                  <code>{formatPercent(stats.max.gpu_util_percent)}</code>
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
