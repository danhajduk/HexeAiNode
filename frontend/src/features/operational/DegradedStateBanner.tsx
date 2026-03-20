export function DegradedStateBanner({ reason, actions = [] }) {
  return (
    <article className="card degraded-banner">
      <div className="degraded-banner-copy">
        <h2>Operational With Warnings</h2>
        <p className="muted">
          The node is still available for dashboard access, but at least one runtime or governance signal needs attention.
        </p>
        <p className="warning tiny">
          Reason: <code>{reason || "runtime warning reported"}</code>
        </p>
      </div>
      {actions.length ? (
        <div className="row degraded-banner-actions">
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
      ) : null}
    </article>
  );
}
