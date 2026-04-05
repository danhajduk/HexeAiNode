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

export function ScheduledTasksSection({ scheduler = null, className = "" }) {
  const tasks = scheduler?.tasks && typeof scheduler.tasks === "object"
    ? Object.values(scheduler.tasks).sort((left, right) => String(left?.display_name || left?.task_id || "").localeCompare(String(right?.display_name || right?.task_id || "")))
    : [];
  const scheduleCatalog = Array.isArray(scheduler?.schedule_catalog) ? sortScheduleCatalog(scheduler.schedule_catalog) : [];

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
    </article>
  );
}
