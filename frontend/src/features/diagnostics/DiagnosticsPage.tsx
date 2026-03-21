import { CardHeader } from "../../components/uiPrimitives";
import { getTaskDisplay } from "../operational/taskDisplay";

function Section({ title, subtitle, children, defaultOpen = false }) {
  return (
    <details className="diagnostics-section" open={defaultOpen}>
      <summary>{title}</summary>
      {subtitle ? <p className="muted tiny">{subtitle}</p> : null}
      <div className="diagnostics-section-body">{children}</div>
    </details>
  );
}

export function DiagnosticsPage({
  capabilityDiagnostics,
  adminActionState,
  runningAdminAction,
  runAdminAction,
  onCopyDiagnostics,
  copiedDiagnostics,
  uiState,
}) {
  const resolvedTasks = capabilityDiagnostics?.resolved_tasks || [];
  const resolvedTaskSummary = resolvedTasks.length
    ? resolvedTasks.map((taskId) => {
        const display = getTaskDisplay(taskId);
        return display.description && display.description !== taskId
          ? `${display.label} (${taskId})`
          : display.label;
      }).join(", ")
    : "none";

  return (
    <article className="card diagnostics-card">
      <CardHeader title="Diagnostics" subtitle="Advanced inspection and admin controls live here instead of the main dashboard." />

      <Section title="Capability Diagnostics" subtitle="Current model visibility and capability graph summary." defaultOpen>
        <div className="state-grid">
          <span>Discovered Models</span>
          <code>{(capabilityDiagnostics?.discovered_models?.models || []).map((model) => model.model_id).join(", ") || "none"}</code>
          <span>Enabled Models</span>
          <code>{(capabilityDiagnostics?.enabled_models?.models || []).filter((model) => model?.enabled).map((model) => model.model_id).join(", ") || "none"}</code>
          <span>Resolved Tasks</span>
          <code>{resolvedTaskSummary}</code>
          <span>Capability Graph Version</span>
          <code>{capabilityDiagnostics?.capability_graph?.capability_graph_version || "unavailable"}</code>
        </div>
      </Section>

      <Section title="Declaration Payload / Result" subtitle="Last submission details from the node runtime.">
        <details>
          <summary>Last Declaration Payload</summary>
          <pre className="json-block">{JSON.stringify(capabilityDiagnostics?.last_declaration_payload || {}, null, 2)}</pre>
        </details>
        <details>
          <summary>Last Declaration Result</summary>
          <pre className="json-block">{JSON.stringify(capabilityDiagnostics?.last_declaration_result || {}, null, 2)}</pre>
        </details>
      </Section>

      <Section title="Feature Catalog" subtitle="Feature catalog payload from local deterministic classification.">
        <pre className="json-block">{JSON.stringify(capabilityDiagnostics?.feature_catalog || {}, null, 2)}</pre>
      </Section>

      <Section title="Pricing Catalog" subtitle="Current cached pricing catalog used for OpenAI resolution.">
        <pre className="json-block">{JSON.stringify(capabilityDiagnostics?.pricing_catalog || {}, null, 2)}</pre>
      </Section>

      <Section title="Pricing Diagnostics" subtitle="Refresh state and extraction diagnostics.">
        <pre className="json-block">{JSON.stringify(capabilityDiagnostics?.pricing_diagnostics || {}, null, 2)}</pre>
      </Section>

      <Section title="Capability Graph" subtitle="Full graph payload used for resolved node capabilities.">
        <pre className="json-block">{JSON.stringify(capabilityDiagnostics?.capability_graph || {}, null, 2)}</pre>
      </Section>

      <Section title="Admin Actions" subtitle="Manual admin operations are separated from passive inspection.">
        <div className="action-groups">
          <section className="action-group">
            <div className="action-group-header">
              <h3>Sync & Refresh</h3>
              <p className="muted tiny">Routine maintenance actions that stay separate from advanced rebuild operations.</p>
            </div>
            <div className="row action-group-buttons">
              <button
                className="btn"
                type="button"
                onClick={() => runAdminAction("refresh_provider_models", "/api/capabilities/providers/refresh", { force_refresh: true })}
                disabled={Boolean(runningAdminAction)}
              >
                {runningAdminAction === "refresh_provider_models" ? "Refreshing..." : "Refresh Provider Models"}
              </button>
              <button
                className="btn btn-primary"
                type="button"
                onClick={() => runAdminAction("redeclare_capabilities", "/api/capabilities/redeclare", { force_refresh: true })}
                disabled={Boolean(runningAdminAction)}
              >
                {runningAdminAction === "redeclare_capabilities" ? "Redeclaring..." : "Redeclare Capabilities To Core"}
              </button>
            </div>
          </section>
          <section className="action-group action-group-admin">
            <div className="action-group-header">
              <h3>Advanced Maintenance</h3>
              <p className="muted tiny">Admin-only rebuild operations that are intentionally kept out of the default dashboard.</p>
            </div>
            <div className="row action-group-buttons">
              <button
                className="btn"
                type="button"
                onClick={() => runAdminAction("rerun_classification", "/api/providers/openai/models/classification/refresh", {})}
                disabled={Boolean(runningAdminAction)}
              >
                {runningAdminAction === "rerun_classification" ? "Running..." : "Recompute Deterministic Catalog"}
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => runAdminAction("recompute_capability_graph", "/api/capabilities/rebuild", {})}
                disabled={Boolean(runningAdminAction)}
              >
                {runningAdminAction === "recompute_capability_graph" ? "Computing..." : "Recompute Capability Graph"}
              </button>
            </div>
          </section>
        </div>
        <p className="muted tiny">
          Admin action result: <code>{adminActionState || "idle"}</code>
        </p>
      </Section>

      <Section title="Session Diagnostics" subtitle="Safe UI-side support summary.">
        <div className="state-grid">
          <span>Lifecycle</span>
          <code>{uiState.lifecycle.current}</code>
          <span>Last Update</span>
          <code>{uiState.meta.lastUpdatedAt || "never"}</code>
          <span>Partial Failures</span>
          <code>{uiState.meta.partialFailures?.join(", ") || "none"}</code>
        </div>
        <button className="btn" onClick={onCopyDiagnostics}>
          {copiedDiagnostics ? "Diagnostics Copied" : "Copy Diagnostics"}
        </button>
      </Section>
    </article>
  );
}
