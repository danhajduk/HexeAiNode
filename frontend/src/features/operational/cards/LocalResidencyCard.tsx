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

function laneForComponentId(componentId) {
  const normalized = compactText(componentId, "").toLowerCase();
  if (normalized === "visual_runtime") {
    return "visual_gpu";
  }
  return normalized;
}

function lanePayload(executionQueue, laneName) {
  const lanes = serviceObject(executionQueue?.lanes);
  const queues = serviceObject(executionQueue?.queues);
  const lane = serviceObject(lanes[laneName]);
  if (Object.keys(lane).length) {
    return lane;
  }
  if (laneName === "visual_cpu") {
    return Object.keys(serviceObject(queues.visual_cpu)).length ? serviceObject(queues.visual_cpu) : serviceObject(queues.cpu_comfyui);
  }
  return serviceObject(queues[laneName]);
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
  const lane = lanePayload(executionQueue, laneForComponentId(component.component_id));
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

function cloudWork(executionQueue) {
  const cloud = lanePayload(executionQueue, "cloud");
  return {
    running: numericCount(cloud.active_count, 0),
    staged: numericCount(cloud.staged_count, 0),
    backlog: numericCount(cloud.backlog_count, numericCount(cloud.queued_count, 0)),
  };
}

function residencyDisplayState(component, work) {
  const observed = compactText(component.observed_state, "unknown").toLowerCase();
  const containerState = compactText(component.container_state, "").toLowerCase();
  const modelState = compactText(component.model_state, "").toLowerCase();
  const hasWork = (work.running || 0) > 0 || (work.staged || 0) > 0 || (work.backlog || 0) > 0;
  if (modelState === "loading" || modelState === "unloading" || modelState === "failed") {
    return modelState;
  }
  if (modelState === "unloaded" && (containerState === "running" || observed === "running")) {
    return "model_unloaded";
  }
  if (modelState === "loaded") {
    return hasWork ? "busy" : "idle";
  }
  return observed;
}

function queueDisplayState(work) {
  return (work.running || 0) > 0 || (work.staged || 0) > 0 || (work.backlog || 0) > 0 ? "busy" : "idle";
}

function compactJobName(job) {
  return compactText(job?.job_name || job?.task_id || job?.job_id, "none");
}

function compactJobMeta(job) {
  const parts = [];
  if (job?.task_family) {
    parts.push(job.task_family);
  }
  if (job?.importance) {
    parts.push(job.importance);
  } else if (job?.queue_state?.importance) {
    parts.push(job.queue_state.importance);
  }
  if (job?.client_id) {
    parts.push(job.client_id);
  }
  if (job?.queue_position !== null && job?.queue_position !== undefined) {
    parts.push(`pos ${job.queue_position}`);
  }
  return parts.join(" / ") || compactText(job?.status, "queued");
}

function laneBacklogJob({ executionQueue, laneName, stagedJobId }) {
  const globalQueue = serviceObject(executionQueue?.global_queue);
  const queuedJobs = Array.isArray(globalQueue.queued_jobs) ? globalQueue.queued_jobs : [];
  return queuedJobs.find((job) => {
    const runtimeLane = laneForComponentId(job?.runtime_lane);
    const jobId = compactText(job?.job_id, "");
    return runtimeLane === laneName && (!stagedJobId || jobId !== stagedJobId);
  }) || null;
}

function laneWorkMetadata({ executionQueue, laneName }) {
  const lane = lanePayload(executionQueue, laneName);
  const activeJob = serviceObject(lane.active_job);
  const stagedJob = serviceObject(lane.staged_job || lane.next_job);
  const stagedJobId = compactText(stagedJob.job_id, "");
  const backlogJob = laneBacklogJob({ executionQueue, laneName, stagedJobId });
  return [
    { label: "Active", job: Object.keys(activeJob).length ? activeJob : null },
    { label: "Staged", job: Object.keys(stagedJob).length ? stagedJob : null },
    { label: "Backlog", job: backlogJob },
  ];
}

function previewNextAction(preview) {
  const actions = Array.isArray(preview?.actions) ? preview.actions : [];
  const action = actions[0] && typeof actions[0] === "object" ? actions[0] : null;
  if (!action) {
    return "none";
  }
  const actionName = compactText(action.action, "action");
  const componentId = compactText(action.component_id, "");
  return componentId ? `${actionName}:${componentId}` : actionName;
}

function loadedModelText(component) {
  const loadedModels = Array.isArray(component.loaded_models) ? component.loaded_models.filter(Boolean) : [];
  return compactText(component.loaded_model || loadedModels.join(", "), "none");
}

function RuntimeWorkMetadata({ items }) {
  const rows = Array.isArray(items) ? items : [];
  return (
    <div className="runtime-residency-job-meta">
      {rows.map((item) => {
        const hasJob = Boolean(item?.job);
        return (
          <div className={hasJob ? "" : "is-empty"} key={item.label}>
            <span>{item.label}</span>
            <strong>
              {hasJob ? compactJobName(item.job) : `No ${String(item.label || "queued").toLowerCase()} job`}
            </strong>
            <code>{hasJob ? compactJobMeta(item.job) : "empty"}</code>
          </div>
        );
      })}
    </div>
  );
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
  const cloudQueueWork = cloudWork(executionQueue);
  const cloudMetadata = laneWorkMetadata({ executionQueue, laneName: "cloud" });

  return (
    <article className={`card ${className}`.trim()}>
      <CardHeader title="Local Residency" subtitle="Scheduler view of local model and runtime residency." />
      <div className="runtime-residency-legend">
        <span><b>Work</b></span>
        <span><code>run / staged / backlog</code></span>
      </div>
      <div className="runtime-residency-grid">
        <article className="runtime-residency-card runtime-residency-card-cloud">
          <div className="runtime-residency-card-header">
            <div className="runtime-residency-card-title">
              <strong>Cloud Execution</strong>
              <span className="muted tiny">external_provider_queue</span>
            </div>
            <StatusBadge value={queueDisplayState(cloudQueueWork)} />
          </div>
          <div className="runtime-residency-summary">
            <div>
              <span>Type</span>
              <code>queue</code>
            </div>
            <div>
              <span>Phase</span>
              <code>external</code>
            </div>
            <div>
              <span>Work</span>
              <code>
                {cloudQueueWork.running} / {cloudQueueWork.staged} / {cloudQueueWork.backlog}
              </code>
            </div>
            <div>
              <span>Decision</span>
              <code>cloud_lane</code>
            </div>
          </div>
          <RuntimeWorkMetadata items={cloudMetadata} />
          <p className="runtime-residency-reason">
            <span>Note</span>
            <code>not local residency</code>
          </p>
        </article>
        {localSchedulerComponents.map((component) => {
          const blockers = Array.isArray(component.blockers) ? component.blockers : [];
          const preview = serviceObject(requestPreviews[component.component_id]);
          const stats = componentStats(component);
          const work = componentWork({ component, executionQueue });
          const busy = localSchedulerBusyTarget === component.component_id;
          const reason = compactText(preview.reason || blockers.join(", "), "");
          const nextAction = previewNextAction(preview);
          const displayState = residencyDisplayState(component, work);
          const metadata = laneWorkMetadata({ executionQueue, laneName: laneForComponentId(component.component_id) });
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
                  <code>{compactText(component.desired_state)}</code>
                </div>
                <div>
                  <span>Target</span>
                  <code>{compactText(component.desired_model_state, "unloaded")}</code>
                </div>
                <div>
                  <span>Container</span>
                  <code>{compactText(component.container_state, compactText(component.observed_state))}</code>
                </div>
                <div>
                  <span>Model</span>
                  <code>{compactText(component.model_state, "unknown")}</code>
                </div>
                <div>
                  <span>Loaded</span>
                  <code>{loadedModelText(component)}</code>
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
                <div>
                  <span>Next</span>
                  <code>{nextAction}</code>
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
              <RuntimeWorkMetadata items={metadata} />
              <p className="runtime-residency-reason">
                <span>Reason</span>
                <code>{reason || "none"}</code>
              </p>
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
