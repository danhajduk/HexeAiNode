import { useState } from "react";

const DEFAULT_VISIBLE = 8;

export function CompactChipList({
  items = [],
  emptyLabel = "none",
  maxVisible = DEFAULT_VISIBLE,
  className = "",
}) {
  const [expanded, setExpanded] = useState(false);
  const visibleItems = expanded ? items : items.slice(0, maxVisible);
  const hiddenCount = Math.max(items.length - visibleItems.length, 0);

  if (!items.length) {
    return <p className="muted tiny">{emptyLabel}</p>;
  }

  return (
    <div className={`compact-chip-list ${className}`.trim()}>
      <div className="recommended-task-list">
        {visibleItems.map((item) => (
          <span key={item.id || item.label} className={`capability-badge ${item.tone ? `capability-badge-${item.tone}` : ""}`.trim()}>
            {item.label}
          </span>
        ))}
      </div>
      {hiddenCount > 0 ? (
        <button className="btn compact-chip-list-toggle" type="button" onClick={() => setExpanded((current) => !current)}>
          {expanded ? "Show Less" : `Show ${hiddenCount} More`}
        </button>
      ) : null}
    </div>
  );
}
