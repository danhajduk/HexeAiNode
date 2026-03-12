const LIFECYCLE_TONE = {
  unconfigured: "pending",
  bootstrap_connecting: "pending",
  bootstrap_connected: "pending",
  core_discovered: "pending",
  registration_pending: "pending",
  pending_approval: "pending",
  trusted: "pending",
  capability_setup_pending: "pending",
  capability_declaration_in_progress: "pending",
  capability_declaration_accepted: "healthy",
  capability_declaration_failed_retry_pending: "degraded",
  operational: "healthy",
  degraded: "degraded",
  offline: "error",
  unknown: "error",
};

function onboardingStepState(current, fromStates) {
  if (current === "offline" || current === "unknown") {
    return "failed";
  }
  if (fromStates.includes(current)) {
    return "in_progress";
  }
  return "pending";
}

function buildOnboardingProgress(lifecycleState) {
  const doneStates = new Set([
    "trusted",
    "capability_setup_pending",
    "capability_declaration_in_progress",
    "capability_declaration_accepted",
    "capability_declaration_failed_retry_pending",
    "operational",
    "degraded",
  ]);
  const registrationDoneStates = new Set(["pending_approval", ...doneStates]);

  return {
    bootstrap_discovery: doneStates.has(lifecycleState)
      ? "completed"
      : onboardingStepState(lifecycleState, ["bootstrap_connecting", "bootstrap_connected", "core_discovered"]),
    registration: registrationDoneStates.has(lifecycleState)
      ? "completed"
      : onboardingStepState(lifecycleState, ["registration_pending"]),
    approval: doneStates.has(lifecycleState) ? "completed" : onboardingStepState(lifecycleState, ["pending_approval"]),
    trust_activation: doneStates.has(lifecycleState)
      ? "completed"
      : onboardingStepState(lifecycleState, ["trusted", "capability_setup_pending"]),
  };
}

export function buildDashboardUiState({
  nodeStatus = null,
  governanceStatus = null,
  providerConfig = null,
  capabilityConfig = null,
  apiReachable = true,
  lastUpdatedAt = null,
  partialFailures = [],
  serviceStatus = null,
} = {}) {
  const lifecycleState = nodeStatus?.status || (apiReachable ? "unknown" : "offline");
  const capability = nodeStatus?.capability_declaration || {};
  const capabilitySetup = nodeStatus?.capability_setup || {};
  const trustedContext = nodeStatus?.trusted_runtime_context || {};
  const governance = governanceStatus?.status || capability?.governance_status || {};
  const providerEnabled = providerConfig?.config?.providers?.enabled || [];
  const selectedTaskFamiliesFromConfig = capabilityConfig?.config?.selected_task_families || [];
  const readiness = capability?.operational_mqtt_readiness || {};
  const telemetry = capability?.telemetry || {};

  const resolvedServiceStatus =
    serviceStatus ||
    (nodeStatus?.services && typeof nodeStatus.services === "object" ? nodeStatus.services : null);

  return {
    lifecycle: {
      current: lifecycleState,
      tone: LIFECYCLE_TONE[lifecycleState] || "error",
      startupMode: nodeStatus?.startup_mode || "unknown",
      trustStatus: nodeStatus?.startup_mode === "trusted_resume" ? "trusted" : "onboarding",
    },
    onboarding: {
      progress: buildOnboardingProgress(lifecycleState),
      pendingApprovalUrl: nodeStatus?.pending_approval_url || "",
      pendingSessionId: nodeStatus?.pending_session_id || "",
    },
    runtimeHealth: {
      state: lifecycleState === "operational" ? "healthy" : lifecycleState === "degraded" ? "degraded" : "pending",
      coreApiConnectivity: trustedContext?.core_api_endpoint
        ? lifecycleState === "degraded"
          ? "degraded"
          : "connected"
        : "unknown",
      operationalMqttConnectivity: readiness?.ready ? "connected" : readiness?.last_error ? "disconnected" : "unknown",
      governanceFreshness: governance?.state || "unknown",
      lastTelemetryTimestamp: telemetry?.last_published_at || null,
      nodeHealthState: lifecycleState === "degraded" ? "degraded" : lifecycleState === "operational" ? "healthy" : "pending",
    },
    coreConnection: {
      pairedCoreId: trustedContext?.paired_core_id || "",
      coreApiEndpoint: trustedContext?.core_api_endpoint || "",
      operationalMqttHost: trustedContext?.operational_mqtt_host || "",
      operationalMqttPort: trustedContext?.operational_mqtt_port || null,
      pairingTimestamp: trustedContext?.pairing_timestamp || "",
      connected: Boolean(trustedContext?.paired_core_id),
    },
    capabilitySummary: {
      capabilityStatus: capability?.status || "idle",
      enabledProviders: providerEnabled,
      declaredTaskFamilies: capability?.manifest_summary?.task_families || [],
      selectedTaskFamilies:
        capability?.manifest_summary?.task_families?.length > 0
          ? capability?.manifest_summary?.task_families
          : selectedTaskFamiliesFromConfig,
      capabilityDeclarationTimestamp: capability?.accepted_profile?.acceptance_timestamp || null,
      governancePolicyVersion: governance?.active_governance_version || "",
      setupReadinessFlags: capabilitySetup?.readiness_flags || {},
      setupBlockingReasons: capabilitySetup?.blocking_reasons || [],
      declarationAllowed: Boolean(capabilitySetup?.declaration_allowed),
    },
    serviceStatus: resolvedServiceStatus || {
      backend: "unknown",
      frontend: "unknown",
      node: "unknown",
    },
    meta: {
      apiReachable,
      partialFailures,
      lastUpdatedAt,
    },
  };
}
