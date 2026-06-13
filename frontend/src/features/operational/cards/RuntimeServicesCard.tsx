import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function serviceState(value) {
  if (value && typeof value === "object") {
    return value.state || "unknown";
  }
  return value || "unknown";
}

function formatSeconds(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return "none";
  }
  if (parsed < 60) {
    return `${Math.floor(parsed)}s`;
  }
  return `${Math.floor(parsed / 60)}m ${Math.floor(parsed % 60)}s`;
}

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

export function RuntimeServicesCard({
  serviceStatus = {},
  comfyuiWebuiBusy = false,
  localSchedulerBusyTarget = "",
  taskAvailability = [],
  onStartComfyuiWebui,
  onStopComfyuiWebui,
  onOpenComfyuiWebui,
  onRequestLocalScheduler,
  onReleaseLocalScheduler,
}) {
  const comfyuiGpu = serviceObject(serviceStatus.comfyui_gpu);
  const comfyuiCpu = serviceObject(serviceStatus.comfyui_cpu);
  const comfyuiWebui = serviceObject(serviceStatus.comfyui_webui);
  const visionRuntime = serviceObject(serviceStatus.vision_llm);
  const localScheduler = serviceObject(serviceStatus.local_scheduler);
  const localSchedulerComponents = Array.isArray(localScheduler.components) ? localScheduler.components : [];
  const requestPreviews = serviceObject(localScheduler.request_previews);
  const visionResidency = serviceObject(visionRuntime.residency);
  const session = serviceObject(comfyuiWebui.session);
  const webuiActive = serviceState(comfyuiWebui) === "running" || Boolean(comfyuiWebui.manual_session_active);
  const manualPaths = serviceObject(comfyuiWebui.manual_paths);
  const visionRuntimeDetail =
    visionResidency.residency_state ||
    visionResidency.reason ||
    (visionResidency.model_loaded ? "model_loaded" : visionRuntime.default_model_id || "unknown");

  function onToggleComfyuiWebui(event) {
    if (event.target.checked) {
      onStartComfyuiWebui?.();
      return;
    }
    onStopComfyuiWebui?.();
  }

  return (
    <article className="card">
      <CardHeader title="Runtime Services" subtitle="Primary home for backend, frontend, node, local LLM, vision, and ComfyUI service state." />
      <div className="state-grid">
        <span>Backend</span>
        <StatusBadge value={serviceState(serviceStatus.backend)} />
        <span>Frontend</span>
        <StatusBadge value={serviceState(serviceStatus.frontend)} />
        <span>Local LLM</span>
        <StatusBadge value={serviceState(serviceStatus.local_llm)} />
        <span>Vision Runtime</span>
        <StatusBadge value={serviceState(visionRuntime)} />
        <span>Vision Residency</span>
        <code>{visionRuntimeDetail}</code>
        <span>ComfyUI GPU</span>
        <StatusBadge value={serviceState(comfyuiGpu)} />
        <span>ComfyUI CPU</span>
        <StatusBadge value={serviceState(comfyuiCpu)} />
        <span>ComfyUI Web UI</span>
        <StatusBadge value={serviceState(comfyuiWebui)} />
        <span>Manual Session</span>
        <StatusBadge value={session.state || (webuiActive ? "active" : "inactive")} />
        <span>Idle</span>
        <code>{formatSeconds(session.idle_seconds)}</code>
        <span>Idle Timeout</span>
        <code>{formatSeconds(session.idle_timeout_seconds)}</code>
        <span>Manual Output</span>
        <code>{manualPaths.output_dir || "not_configured"}</code>
        <span>Node</span>
        <StatusBadge value={serviceState(serviceStatus.node)} />
      </div>
      <div className="row">
        <label className="inline-toggle">
          <input type="checkbox" checked={webuiActive} onChange={onToggleComfyuiWebui} disabled={comfyuiWebuiBusy} />
          <span>{comfyuiWebuiBusy ? "Working..." : "ComfyUI Web UI"}</span>
        </label>
        {comfyuiWebui.url && serviceState(comfyuiWebui) === "running" ? (
          <button className="btn btn-primary" type="button" onClick={onOpenComfyuiWebui}>
            Open ComfyUI
          </button>
        ) : null}
      </div>
      <section className="runtime-subsection">
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
      </section>
    </article>
  );
}
