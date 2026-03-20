import { StatusBadge } from "../../components/uiPrimitives";

export function SetupCoreConnectionPanel({ mqttHost, lifecycleState, nodeId }) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        The node is using the saved bootstrap host to establish its first Core connection and wait for bootstrap discovery.
      </p>
      <div className="state-grid">
        <span>Bootstrap Host</span>
        <code>{mqttHost || "unavailable"}</code>
        <span>Lifecycle</span>
        <StatusBadge value={lifecycleState || "unknown"} />
        <span>Node ID</span>
        <code>{nodeId || "unavailable"}</code>
      </div>
    </div>
  );
}

export function SetupRegistrationPanel({ nodeId }) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        Core discovery completed. The node is now registering itself with Core and waiting for the approval session to be created.
      </p>
      <div className="state-grid">
        <span>Node ID</span>
        <code>{nodeId || "unavailable"}</code>
        <span>Status</span>
        <code>registration pending</code>
      </div>
    </div>
  );
}

export function SetupApprovalPanel({ nodeId, pendingApprovalUrl }) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        Registration is complete. Core must approve the node before trust activation and capability setup can continue.
      </p>
      <div className="state-grid">
        <span>Node ID</span>
        <code>{nodeId || "unavailable"}</code>
        <span>Approval Link</span>
        <code>{pendingApprovalUrl || "waiting_for_core"}</code>
      </div>
    </div>
  );
}

export function SetupTrustActivationPanel({ trustStatus, pairedCoreId, startupMode }) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        Trust activation is complete. The node is validating its trusted runtime context before provider and capability setup continues.
      </p>
      <div className="state-grid">
        <span>Trust Status</span>
        <StatusBadge value={trustStatus || "unknown"} />
        <span>Startup Mode</span>
        <code>{startupMode || "unknown"}</code>
        <span>Paired Core</span>
        <code>{pairedCoreId || "unavailable"}</code>
      </div>
    </div>
  );
}

export function SetupProviderPanel({
  openaiEnabled,
  selectedTaskFamilies,
  setupReadinessFlags,
  children,
}) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        Configure the AI provider and choose which task families this node should expose before declaration.
      </p>
      <div className="state-grid">
        <span>OpenAI Enabled</span>
        <StatusBadge value={openaiEnabled ? "enabled" : "disabled"} />
        <span>Task Families</span>
        <code>{selectedTaskFamilies.join(", ") || "none_selected"}</code>
        <span>Provider Ready</span>
        <StatusBadge value={setupReadinessFlags.provider_selection_valid ? "ready" : "blocked"} />
        <span>Task Selection</span>
        <StatusBadge value={setupReadinessFlags.task_capability_selection_valid ? "ready" : "blocked"} />
      </div>
      {children}
    </div>
  );
}

export function SetupCapabilityDeclarationPanel({
  declarationAllowed,
  setupReadinessFlags,
  setupBlockingReasons,
}) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        Review the declaration blockers, verify provider and task readiness, and submit the capability declaration to Core.
      </p>
      <div className="state-grid">
        <span>Declare Ready</span>
        <StatusBadge value={declarationAllowed ? "ready" : "blocked"} />
        <span>Trust Ready</span>
        <StatusBadge value={setupReadinessFlags.trust_state_valid ? "ready" : "blocked"} />
        <span>Identity Ready</span>
        <StatusBadge value={setupReadinessFlags.node_identity_valid ? "ready" : "blocked"} />
        <span>Runtime Context</span>
        <StatusBadge value={setupReadinessFlags.core_runtime_context_valid ? "ready" : "blocked"} />
        <span>Model Readiness</span>
        <StatusBadge value={setupReadinessFlags.openai_usable_models_ready ? "ready" : "blocked"} />
      </div>
      {setupBlockingReasons.length ? (
        <p className="warning tiny">
          Blocking: <code>{setupBlockingReasons.join(", ")}</code>
        </p>
      ) : null}
    </div>
  );
}

export function SetupGovernancePanel({ governanceFreshness, policyVersion, declaredAt }) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        Capability acceptance is in place. The node now needs a fresh governance bundle before it can fully hand off to operational mode.
      </p>
      <div className="state-grid">
        <span>Governance</span>
        <StatusBadge value={governanceFreshness || "unknown"} />
        <span>Policy Version</span>
        <code>{policyVersion || "unknown"}</code>
        <span>Declaration Timestamp</span>
        <code>{declaredAt || "pending"}</code>
      </div>
    </div>
  );
}

export function SetupReadyPanel({ pairedCoreId, lifecycleState, governanceFreshness }) {
  return (
    <div className="setup-stage-panel">
      <p className="muted">
        Setup is complete. The node is ready for the operational dashboard and can still reopen setup later for reconfiguration.
      </p>
      <div className="state-grid">
        <span>Lifecycle</span>
        <StatusBadge value={lifecycleState || "unknown"} />
        <span>Core</span>
        <code>{pairedCoreId || "unavailable"}</code>
        <span>Governance</span>
        <StatusBadge value={governanceFreshness || "unknown"} />
      </div>
    </div>
  );
}
