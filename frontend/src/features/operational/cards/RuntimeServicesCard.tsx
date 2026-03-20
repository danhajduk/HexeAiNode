import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

export function RuntimeServicesCard({ serviceStatus }) {
  return (
    <article className="card">
      <CardHeader title="Runtime Services" subtitle="Primary home for backend, frontend, and node service state." />
      <div className="state-grid">
        <span>Backend</span>
        <StatusBadge value={serviceStatus.backend} />
        <span>Frontend</span>
        <StatusBadge value={serviceStatus.frontend} />
        <span>Node</span>
        <StatusBadge value={serviceStatus.node} />
      </div>
    </article>
  );
}
