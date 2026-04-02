import { SetupStepper } from "./SetupStepper";

export function SetupShell({
  stages = [],
  activeStageLabel,
  activePanel,
  primaryActions = [],
  secondaryActions = [],
  dangerActions = [],
}) {
  return (
    <section className="app-shell">
      <aside className="card stack flow-sidebar">
        <div className="section-heading">
          <h2>Setup Flow</h2>
          <span className="pill">{activeStageLabel || "Idle"}</span>
        </div>
        <SetupStepper stages={stages} />
      </aside>
      <div className="main-column">
        <section className="content-stack">
          {activePanel}
          {(primaryActions.length || secondaryActions.length || dangerActions.length) ? (
            <footer className="card setup-shell-footer">
              {primaryActions.length ? (
                <div className="setup-shell-actions setup-shell-actions-primary">
                  <span className="setup-shell-action-label">Current Step</span>
                  {primaryActions.map((action) => (
                    <button
                      key={action.label}
                      className={`btn ${action.primary ? "btn-primary" : ""}`}
                      type="button"
                      onClick={action.onClick}
                      disabled={Boolean(action.disabled)}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              ) : null}
              {secondaryActions.length ? (
                <div className="setup-shell-actions">
                  <span className="setup-shell-action-label">More Actions</span>
                  {secondaryActions.map((action) => (
                    <button
                      key={action.label}
                      className="btn"
                      type="button"
                      onClick={action.onClick}
                      disabled={Boolean(action.disabled)}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              ) : null}
              {dangerActions.length ? (
                <div className="setup-shell-actions setup-shell-actions-danger">
                  <span className="setup-shell-action-label">Reset & Recovery</span>
                  {dangerActions.map((action) => (
                    <button
                      key={action.label}
                      className="btn"
                      type="button"
                      onClick={action.onClick}
                      disabled={Boolean(action.disabled)}
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </footer>
          ) : null}
        </section>
      </div>
    </section>
  );
}
