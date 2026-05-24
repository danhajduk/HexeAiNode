import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function serviceState(value) {
  if (value && typeof value === "object") {
    return value.state || "unknown";
  }
  return value || "unknown";
}

export function RuntimeServicesCard({ serviceStatus }) {
  return (
    <article className="card">
      <CardHeader title="Runtime Services" subtitle="Primary home for backend, frontend, node, and local LLM service state." />
      <div className="state-grid">
        <span>Backend</span>
        <StatusBadge value={serviceState(serviceStatus.backend)} />
        <span>Frontend</span>
        <StatusBadge value={serviceState(serviceStatus.frontend)} />
        <span>Local LLM</span>
        <StatusBadge value={serviceState(serviceStatus.local_llm)} />
        <span>Node</span>
        <StatusBadge value={serviceState(serviceStatus.node)} />
      </div>
    </article>
  );
}
