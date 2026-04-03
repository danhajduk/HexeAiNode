import { CardHeader, SeverityIndicator } from "../../components/uiPrimitives";

export function BackendUnavailableScreen({
  apiBase,
  error,
  lastUpdatedAt,
  retrying = false,
  onRetry,
}) {
  return (
    <section className="backend-unavailable-view">
      <article className="card backend-unavailable-card">
        <CardHeader
          title="Backend Unavailable"
          subtitle="The Hexe AI Node UI loaded, but the node backend could not be reached."
        />
        <div className="backend-unavailable-meta">
          <SeverityIndicator tone="danger">
            <span>offline</span>
          </SeverityIndicator>
          <p className="muted">
            Retry after the node backend is back online, or verify the service address and process status.
          </p>
        </div>
        <div className="state-grid">
          <span>API Base</span>
          <code>{apiBase || "unavailable"}</code>
          <span>Last Attempt</span>
          <code>{lastUpdatedAt || "never"}</code>
          <span>Error</span>
          <code>{error || "backend unavailable"}</code>
        </div>
        <div className="row backend-unavailable-actions">
          <button className="btn btn-primary" type="button" onClick={onRetry} disabled={retrying}>
            {retrying ? "Retrying..." : "Retry Connection"}
          </button>
        </div>
      </article>
    </section>
  );
}
