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

export function RuntimeServicesCard({
  serviceStatus = {},
  comfyuiWebuiBusy = false,
  onStartComfyuiWebui,
  onStopComfyuiWebui,
  onOpenComfyuiWebui,
}) {
  const comfyuiGpu = serviceObject(serviceStatus.comfyui_gpu);
  const comfyuiCpu = serviceObject(serviceStatus.comfyui_cpu);
  const comfyuiWebui = serviceObject(serviceStatus.comfyui_webui);
  const visionRuntime = serviceObject(serviceStatus.vision_llm);
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
    </article>
  );
}
