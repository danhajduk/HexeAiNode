function ActionGroup({ title, subtitle, actions = [], className = "" }) {
  if (!actions.length) {
    return null;
  }
  return (
    <section className={`action-group ${className}`.trim()}>
      <div className="action-group-header">
        <h3>{title}</h3>
        {subtitle ? <p className="muted tiny">{subtitle}</p> : null}
      </div>
      <div className="row action-group-buttons">
        {actions.map((action) => (
          <button
            key={action.label}
            className={`btn ${action.primary ? "btn-primary" : ""}`.trim()}
            type="button"
            onClick={action.onClick}
            disabled={Boolean(action.disabled)}
          >
            {action.label}
          </button>
        ))}
      </div>
    </section>
  );
}

export function OperationalActionsCard({
  runtimeActions = [],
}) {
  return (
    <article className="card">
      <div className="card-header">
        <h2>Actions</h2>
      </div>
      <div className="action-groups">
        <ActionGroup
          className="action-group-runtime"
          title="Runtime Controls"
          subtitle={null}
          actions={runtimeActions}
        />
      </div>
    </article>
  );
}
