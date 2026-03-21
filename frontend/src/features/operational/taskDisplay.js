const TASK_DISPLAY = {
  "task.classification": {
    label: "Classification",
    description: "Classify text or content into operator-defined categories.",
  },
  "task.summarization": {
    label: "Summarization",
    description: "Condense source content into concise operator-facing summaries.",
  },
};

function titleizeSegment(value) {
  return String(value || "")
    .split(/[_\-.]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

export function getTaskDisplay(taskId) {
  const normalized = String(taskId || "").trim();
  if (!normalized) {
    return { label: "Unknown Task", description: "" };
  }
  if (TASK_DISPLAY[normalized]) {
    return TASK_DISPLAY[normalized];
  }
  const suffix = normalized.startsWith("task.") ? normalized.slice(5) : normalized;
  return {
    label: titleizeSegment(suffix),
    description: normalized,
  };
}
