import { CardHeader } from "../../components/uiPrimitives";
import { SetupShell } from "./SetupShell";

export function SetupModeView({
  title,
  subtitle,
  summaryItems = [],
  stages = [],
  activeStageLabel,
  activePanel,
  primaryActions = [],
  secondaryActions = [],
  dangerActions = [],
  completionState = null,
}) {
  return (
    <section className="setup-mode-view">
      <SetupShell
        stages={stages}
        activePanel={
          <div className="setup-main-stack">
            {completionState ? (
              <article className="card setup-complete-banner">
                <h2>{completionState.title}</h2>
                <p className="muted">{completionState.subtitle}</p>
                {completionState.actions?.length ? (
                  <div className="row setup-complete-actions">
                    {completionState.actions.map((action) => (
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
            ) : null}
            <article className="card setup-shell-header">
              <CardHeader title={title} subtitle={subtitle} />
              {summaryItems.length ? (
                <div className="setup-shell-summary-pills">
                  {summaryItems.map((item) => (
                    <div key={item.label} className="setup-shell-summary-pill">
                      <span className="muted tiny">{item.label}</span>
                      <div>{item.value}</div>
                    </div>
                  ))}
                </div>
              ) : null}
            </article>
            <article className="card setup-shell-main-card">
              <CardHeader
                title={activeStageLabel || "Setup"}
                subtitle="Only the information and actions for the current stage are shown here."
              />
              <div className="setup-shell-panel">{activePanel}</div>
            </article>
          </div>
        }
        primaryActions={primaryActions}
        secondaryActions={secondaryActions}
        dangerActions={dangerActions}
      />
    </section>
  );
}
