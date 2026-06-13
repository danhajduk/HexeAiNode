import { CardHeader, StatusBadge } from "../../components/uiPrimitives";

const TASK_KIND_LABELS = {
  local_recurring: "Runtime",
  provider_specific_recurring: "Provider",
  runtime_recurring: "Runtime",
  provider_recurring: "Provider",
  system_recurring: "System",
  governance_recurring: "Governance",
  trust_recurring: "Trust",
  messaging_recurring: "Messaging",
  execution_recurring: "Execution",
  budget_recurring: "Budget",
  storage_recurring: "Storage",
  diagnostics_recurring: "Diagnostics",
  security_recurring: "Security",
};

const SCHEDULE_LABELS = {
  interval_seconds: "General Interval",
  daily: "Daily",
  weekly: "Weekly",
  "4_times_a_day": "4 Times A Day",
  every_5_minutes: "Every 5 Minutes",
  hourly: "Hourly",
  bi_weekly: "Bi-Weekly",
  monthly: "Monthly",
  every_other_day: "Every Other Day",
  twice_a_week: "Twice A Week",
  on_start: "On Start",
  every_10_seconds: "Every 10 Seconds",
  heartbeat_5_seconds: "Heartbeat 5 Seconds",
  telemetry_60_seconds: "Telemetry 60 Seconds",
};

const SCHEDULE_SORT_ORDER = {
  heartbeat_5_seconds: 5,
  every_10_seconds: 10,
  telemetry_60_seconds: 60,
  every_5_minutes: 300,
  hourly: 3600,
  "4_times_a_day": 21600,
  daily: 86400,
  every_other_day: 172800,
  twice_a_week: 302400,
  weekly: 604800,
  bi_weekly: 1209600,
  monthly: 2678400,
  on_start: 900000000,
  interval_seconds: 1000000000,
};

function formatTimestamp(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "none";
  }
  const parsed = Date.parse(normalized);
  if (Number.isNaN(parsed)) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(parsed));
}

function schedulerStatusTone(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "running") {
    return "success-strong";
  }
  if (normalized === "idle" || normalized === "stopped") {
    return "warning";
  }
  if (normalized === "failing") {
    return "danger";
  }
  if (normalized) {
    return "success";
  }
  return "meta";
}

function friendlyTaskKind(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return TASK_KIND_LABELS[normalized] || normalized.replaceAll("_", " ") || "-";
}

function friendlyScheduleName(value) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "-";
  }
  return SCHEDULE_LABELS[normalized] || normalized.replaceAll("_", " ");
}

function formatSeconds(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "-";
  }
  if (numeric < 60) {
    return `${Math.max(Math.round(numeric), 0)}s`;
  }
  if (numeric < 3600) {
    return `${Math.round(numeric / 60)}m`;
  }
  return `${(numeric / 3600).toFixed(numeric < 7200 ? 1 : 0)}h`;
}

function friendlyQueueName(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "cpu_comfyui") {
    return "Visual CPU";
  }
  return normalized.replaceAll("_", " ") || "queue";
}

function queueDecisionLine(queue) {
  const nextState = queue?.next_job?.queue_state || queue?.active_job?.queue_state || {};
  const parts = [];
  if (nextState.queue_class) {
    parts.push(nextState.queue_class);
  }
  if (nextState.importance) {
    parts.push(nextState.importance);
  }
  if (nextState.max_wait_seconds !== null && nextState.max_wait_seconds !== undefined) {
    parts.push(`wait ${formatSeconds(nextState.remaining_wait_seconds)} / ${formatSeconds(nextState.max_wait_seconds)}`);
  }
  if (nextState.spillover_selected) {
    parts.push("spilled to cloud");
  } else if (nextState.spillover_allowed) {
    parts.push("cloud spillover allowed");
  }
  if (nextState.local_unavailable_reason) {
    parts.push(nextState.local_unavailable_reason);
  } else if (nextState.routing_reason) {
    parts.push(nextState.routing_reason);
  }
  return parts.length ? parts.join(" • ") : "No pending decision";
}

function sortScheduleCatalog(entries) {
  return [...entries].sort((left, right) => {
    const leftName = String(left?.name || "").trim();
    const rightName = String(right?.name || "").trim();
    const leftOrder = SCHEDULE_SORT_ORDER[leftName] ?? 950000000;
    const rightOrder = SCHEDULE_SORT_ORDER[rightName] ?? 950000000;
    if (leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }
    if (leftName === "interval_seconds" && rightName !== "interval_seconds") {
      return 1;
    }
    if (rightName === "interval_seconds" && leftName !== "interval_seconds") {
      return -1;
    }
    return leftName.localeCompare(rightName);
  });
}

export function ScheduledTasksSection({ scheduler = null, executionQueue = null, className = "" }) {
  const tasks = scheduler?.tasks && typeof scheduler.tasks === "object"
    ? Object.values(scheduler.tasks).sort((left, right) => String(left?.display_name || left?.task_id || "").localeCompare(String(right?.display_name || right?.task_id || "")))
    : [];
  const scheduleCatalog = Array.isArray(scheduler?.schedule_catalog) ? sortScheduleCatalog(scheduler.schedule_catalog) : [];
  const queues = executionQueue?.queues && typeof executionQueue.queues === "object"
    ? Object.entries(executionQueue.queues).sort(([left], [right]) => left.localeCompare(right))
    : [];

  return (
    <article className={`card operational-card-full-span ${className}`.trim()}>
      <CardHeader
        title="Scheduled Tasks"
        subtitle="Scheduler-driven background jobs with current cadence and latest execution state."
      />
      {tasks.length ? (
        <div className="scheduled-tasks-table-wrap">
          <table className="scheduled-tasks-table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Type</th>
                <th>Schedule</th>
                <th>Status</th>
                <th>Last Success</th>
                <th>Last Failure</th>
                <th>Next Run</th>
                <th>Last Error</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr key={task.task_id}>
                  <td><strong>{task.display_name || task.task_id}</strong></td>
                  <td>{friendlyTaskKind(task.task_kind)}</td>
                  <td>
                    <div>
                      <strong>{friendlyScheduleName(task.schedule_name)}</strong>
                    </div>
                    <div className="muted tiny">{task.schedule_detail || "-"}</div>
                  </td>
                  <td><StatusBadge value={task.status || "unknown"} tone={schedulerStatusTone(task.status)} /></td>
                  <td>{formatTimestamp(task.last_success_at)}</td>
                  <td>{formatTimestamp(task.last_failure_at)}</td>
                  <td>{formatTimestamp(task.next_run_at)}</td>
                  <td>{task.last_error || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted tiny">No scheduled task data is available yet.</p>
      )}
      {scheduleCatalog.length ? (
        <div className="scheduled-tasks-legend">
          {scheduleCatalog.map((entry) => (
            <div key={entry.name} className="scheduled-tasks-legend-item">
              <strong>{friendlyScheduleName(entry.name)}</strong>
              <span className="muted tiny">{entry.detail}</span>
            </div>
          ))}
        </div>
      ) : null}
      {queues.length ? (
        <section className="execution-queue-summary" aria-label="Execution queue summary">
          <div className="execution-queue-summary-header">
            <strong>Execution Queues</strong>
            <span className="muted tiny">
              priority, wait budget, and cloud spillover decisions
            </span>
          </div>
          <div className="execution-queue-grid">
            {queues.map(([queueName, queue]) => {
              const nextJob = queue.next_job || queue.active_job || null;
              const queueState = nextJob?.queue_state || {};
              return (
                <div key={queueName} className="execution-queue-card">
                  <div className="execution-queue-card-title">
                    <strong>{friendlyQueueName(queueName)}</strong>
                    <StatusBadge value={`${queue.active_count || 0} active / ${queue.queued_count || 0} queued`} tone={queue.active_count || queue.queued_count ? "success" : "meta"} />
                  </div>
                  <div className="muted tiny">{queueDecisionLine(queue)}</div>
                  {nextJob ? (
                    <dl className="execution-queue-meta">
                      <div>
                        <dt>Next</dt>
                        <dd>{nextJob.job_name || nextJob.task_id || nextJob.job_id}</dd>
                      </div>
                      <div>
                        <dt>ETA</dt>
                        <dd>{formatSeconds(queueState.estimated_start_seconds)}</dd>
                      </div>
                      <div>
                        <dt>Deadline</dt>
                        <dd>{formatTimestamp(queueState.deadline_at || queueState.wait_budget_deadline_at)}</dd>
                      </div>
                    </dl>
                  ) : (
                    <p className="muted tiny">No queued or active execution work.</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}
    </article>
  );
}
