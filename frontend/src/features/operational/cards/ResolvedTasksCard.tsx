import { useState } from "react";
import { CardHeader } from "../../../components/uiPrimitives";
import { groupResolvedTasks } from "./resolvedTaskGroups";
import { getTaskDisplay } from "../taskDisplay";

const DEFAULT_VISIBLE_COUNT = 6;

export function ResolvedTasksCard({ tasks = [] }) {
  const [expandedCategories, setExpandedCategories] = useState({});
  const grouped = groupResolvedTasks(tasks);

  function toggleCategory(category) {
    setExpandedCategories((current) => ({
      ...current,
      [category]: !current[category],
    }));
  }

  return (
    <article className="card capability-summary-card">
      <CardHeader title="Resolved Tasks" subtitle="Grouped capability families for operational readability." />
      {grouped.length ? (
        <div className="resolved-task-groups">
          {grouped.map((group) => {
            const expanded = Boolean(expandedCategories[group.category]);
            const visibleItems = expanded ? group.items : group.items.slice(0, DEFAULT_VISIBLE_COUNT);
            const hiddenCount = Math.max(group.items.length - visibleItems.length, 0);
            return (
              <section key={group.category} className="resolved-task-group">
                <div className="model-section-header">
                  <h3>{group.category}</h3>
                  <span className="muted tiny">{group.items.length} tasks</span>
                </div>
                <div className="recommended-task-list">
                  {visibleItems.map((task) => {
                    const display = getTaskDisplay(task);
                    return (
                      <span
                        key={`${group.category}-${task}`}
                        className="capability-badge"
                        title={display.description || task}
                      >
                        {display.label}
                      </span>
                    );
                  })}
                </div>
                {hiddenCount > 0 ? (
                  <button className="btn" type="button" onClick={() => toggleCategory(group.category)}>
                    {expanded ? "Show Less" : `Show ${hiddenCount} More`}
                  </button>
                ) : null}
              </section>
            );
          })}
        </div>
      ) : (
        <p className="muted tiny">No resolved tasks available.</p>
      )}
    </article>
  );
}
