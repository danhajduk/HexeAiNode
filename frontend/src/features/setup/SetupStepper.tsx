import { StageBadge } from "../../components/uiPrimitives";

export function SetupStepper({ stages = [] }) {
  return (
    <nav className="setup-stepper" aria-label="Setup progress">
      {stages.map((stage, index) => (
        <div key={stage.id} className={`setup-step setup-step-${stage.state || "pending"}`}>
          <div className="setup-step-marker" aria-hidden="true">
            <span>{index + 1}</span>
          </div>
          <div className="setup-step-content">
            <div className="setup-step-header">
              <strong>{stage.label}</strong>
              <StageBadge value={stage.state || "pending"} />
            </div>
            {stage.statusText ? <p className="muted tiny">{stage.statusText}</p> : null}
          </div>
        </div>
      ))}
    </nav>
  );
}
