import { CardHeader } from "../../components/uiPrimitives";
import { SetupStepper } from "./SetupStepper";

export function SetupShell({
  stages = [],
  activePanel,
  primaryActions = [],
  secondaryActions = [],
  dangerActions = [],
}) {
  return (
    <section className="setup-shell">
      <div className="setup-shell-layout">
        <aside className="card setup-shell-sidebar">
          <CardHeader title="Setup Progress" subtitle="Follow the current onboarding and readiness stages." />
          <SetupStepper stages={stages} />
        </aside>
        <section className="setup-shell-main">
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
