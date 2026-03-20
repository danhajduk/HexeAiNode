const STAGE_ORDER = [
  "node_identity",
  "core_connection",
  "bootstrap_discovery",
  "registration",
  "approval",
  "trust_activation",
  "provider_setup",
  "capability_declaration",
  "governance_sync",
  "ready",
];

const STAGE_LABELS = {
  node_identity: "Node Identity",
  core_connection: "Core Connection",
  bootstrap_discovery: "Bootstrap Discovery",
  registration: "Registration",
  approval: "Approval",
  trust_activation: "Trust Activation",
  provider_setup: "AI Provider Setup",
  capability_declaration: "Capability Declaration",
  governance_sync: "Governance Sync",
  ready: "Ready",
};

function getActiveStage({
  lifecycleState,
  routeIntent,
  setupReadinessFlags,
}) {
  if (routeIntent === "provider_openai") {
    return "provider_setup";
  }
  switch (lifecycleState) {
    case "bootstrap_connecting":
    case "bootstrap_connected":
      return "core_connection";
    case "core_discovered":
      return "bootstrap_discovery";
    case "registration_pending":
      return "registration";
    case "pending_approval":
      return "approval";
    case "trusted":
      return "trust_activation";
    case "capability_declaration_in_progress":
    case "capability_declaration_accepted":
      return "governance_sync";
    case "capability_declaration_failed_retry_pending":
      return "capability_declaration";
    case "capability_setup_pending":
    default:
      if (!setupReadinessFlags.provider_selection_valid || !setupReadinessFlags.task_capability_selection_valid) {
        return "provider_setup";
      }
      return "capability_declaration";
  }
}

function getStageState(stageId, activeStage, lifecycleState) {
  const activeIndex = STAGE_ORDER.indexOf(activeStage);
  const currentIndex = STAGE_ORDER.indexOf(stageId);
  if (stageId === activeStage) {
    if (lifecycleState === "capability_declaration_failed_retry_pending" && stageId === "capability_declaration") {
      return "error";
    }
    return "current";
  }
  if (currentIndex >= 0 && currentIndex < activeIndex) {
    return "completed";
  }
  return "pending";
}

function getStageStatusText(stageId, { lifecycleState, pendingApprovalUrl, governanceFreshness, setupBlockingReasons }) {
  switch (stageId) {
    case "core_connection":
      return lifecycleState === "bootstrap_connected" ? "broker connected" : "connecting to bootstrap";
    case "bootstrap_discovery":
      return lifecycleState === "core_discovered" ? "Core discovered" : "waiting for discovery";
    case "registration":
      return lifecycleState === "registration_pending" ? "registration in progress" : "awaiting registration";
    case "approval":
      return pendingApprovalUrl ? "approval link available" : "awaiting Core approval";
    case "trust_activation":
      return lifecycleState === "trusted" ? "trusted locally" : "waiting for trust";
    case "provider_setup":
      return setupBlockingReasons.length ? `${setupBlockingReasons.length} blockers` : "provider and task selection";
    case "capability_declaration":
      return lifecycleState === "capability_declaration_failed_retry_pending" ? "retry required" : "ready to declare";
    case "governance_sync":
      return governanceFreshness === "fresh" ? "governance ready" : "syncing governance";
    case "ready":
      return "handoff to dashboard";
    default:
      return "";
  }
}

export function buildSetupFlowModel({
  lifecycleState,
  routeIntent,
  pendingApprovalUrl,
  governanceFreshness,
  setupReadinessFlags = {},
  setupBlockingReasons = [],
}) {
  const activeStage = getActiveStage({
    lifecycleState,
    routeIntent,
    setupReadinessFlags,
  });

  return {
    activeStage,
    stages: STAGE_ORDER.map((stageId) => ({
      id: stageId,
      label: STAGE_LABELS[stageId],
      state: getStageState(stageId, activeStage, lifecycleState),
      statusText: getStageStatusText(stageId, {
        lifecycleState,
        pendingApprovalUrl,
        governanceFreshness,
        setupBlockingReasons,
      }),
    })),
  };
}
