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
      <SetupShell
        title={title}
        subtitle={subtitle}
        summaryItems={summaryItems}
        stages={stages}
        activeStageLabel={activeStageLabel}
        activePanel={activePanel}
        primaryActions={primaryActions}
        secondaryActions={secondaryActions}
        dangerActions={dangerActions}
      />
    </section>
  );
}
