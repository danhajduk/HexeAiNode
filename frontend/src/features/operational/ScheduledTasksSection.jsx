import { CardHeader, StatusBadge } from "../../components/uiPrimitives";

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
  if (normalized === "healthy") {
    return "success";
  }
  if (normalized === "running" || normalized === "scheduled") {
    return "warning";
  }
  if (normalized === "failing" || normalized === "stopped") {
    return "danger";
  }
  return "meta";
}

export function ScheduledTasksSection({ scheduler = null, className = "" }) {
  const tasks = scheduler?.tasks && typeof scheduler.tasks === "object"
    ? Object.values(scheduler.tasks).sort((left, right) => String(left?.display_name || left?.task_id || "").localeCompare(String(right?.display_name || right?.task_id || "")))
    : [];
  const scheduleCatalog = Array.isArray(scheduler?.schedule_catalog) ? scheduler.schedule_catalog : [];

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
                <th>Kind</th>
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
                  <td>{task.task_kind || "-"}</td>
                  <td>
                    <div><code>{task.schedule_name || "-"}</code></div>
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
              <code>{entry.name}</code>
              <span className="muted tiny">{entry.detail}</span>
            </div>
          ))}
        </div>
      ) : null}
    </article>
  );
}
