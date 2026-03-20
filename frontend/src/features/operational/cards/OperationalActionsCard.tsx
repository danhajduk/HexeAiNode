import { CardHeader } from "../../../components/uiPrimitives";

function ActionGroup({ title, subtitle, actions = [] }) {
  if (!actions.length) {
    return null;
  }
  return (
    <section className="action-group">
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
  setupActions = [],
  runtimeActions = [],
  adminHint,
  onOpenDiagnostics,
}) {
  return (
    <article className="card">
      <CardHeader title="Actions" subtitle="Operational controls are grouped by purpose so routine actions stay separate from diagnostics and admin tools." />
      <div className="action-groups">
        <ActionGroup
          title="Configuration"
          subtitle="Everyday sync and reconfiguration actions."
          actions={setupActions}
        />
        <ActionGroup
          title="Runtime Controls"
          subtitle="Service restarts and runtime recovery actions."
          actions={runtimeActions}
        />
        <section className="action-group action-group-admin">
          <div className="action-group-header">
            <h3>Admin & Diagnostics</h3>
            <p className="muted tiny">{adminHint || "Advanced maintenance stays behind diagnostics instead of the default dashboard."}</p>
          </div>
          <div className="row action-group-buttons">
            <button className="btn" type="button" onClick={onOpenDiagnostics}>
              Open Diagnostics
            </button>
          </div>
        </section>
      </div>
    </article>
  );
}
