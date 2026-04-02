export function SetupStepper({ stages = [] }) {
  return (
    <nav className="flow-steps" aria-label="Setup progress">
      {stages.map((stage, index) => (
        <div key={stage.id} className={`flow-step flow-step-${stage.state || "pending"}`}>
          <div className="flow-step-marker" aria-hidden="true">
            <span>{index + 1}</span>
          </div>
          <div className="flow-step-content">
            <strong>{stage.label}</strong>
          </div>
          {stage.state === "completed" ? <span className="flow-step-check" aria-hidden="true">✓</span> : null}
        </div>
      ))}
    </nav>
  );
}
