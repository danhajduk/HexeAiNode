export type UiMode = "identity" | "setup" | "operational";
export type UiRouteIntent = "auto" | "setup" | "provider_openai" | "dashboard" | "diagnostics";

export type UiModeInput = {
  lifecycleState?: string | null;
  routeHash?: string | null;
};

export type UiModeResolution = {
  mode: UiMode;
  routeIntent: UiRouteIntent;
  diagnosticsOpen: boolean;
  providerSetupOpen: boolean;
  reason: string;
};

const SETUP_STATES = new Set([
  "bootstrap_connecting",
  "bootstrap_connected",
  "core_discovered",
  "registration_pending",
  "pending_approval",
  "trusted",
  "capability_setup_pending",
  "capability_declaration_in_progress",
  "capability_declaration_failed_retry_pending",
  "capability_declaration_accepted",
  "unknown",
  "offline",
]);

const OPERATIONAL_STATES = new Set(["operational", "degraded"]);

export function resolveUiRouteIntent(routeHash?: string | null): UiRouteIntent {
  const normalized = String(routeHash || "#/").trim().toLowerCase();
  if (
    normalized === "#/setup" ||
    normalized.startsWith("#/setup/") ||
    normalized === "#/providers/openai"
  ) {
    return normalized.includes("provider/openai") || normalized === "#/providers/openai"
      ? "provider_openai"
      : "setup";
  }
  if (normalized === "#/dashboard/diagnostics" || normalized === "#/diagnostics") {
    return "diagnostics";
  }
  if (normalized === "#/dashboard" || normalized.startsWith("#/dashboard/")) {
    return "dashboard";
  }
  return "auto";
}

export function resolveUiMode({ lifecycleState, routeHash }: UiModeInput): UiModeResolution {
  const currentState = String(lifecycleState || "unknown").trim().toLowerCase() || "unknown";
  const routeIntent = resolveUiRouteIntent(routeHash);

  if (currentState === "unconfigured") {
    return {
      mode: "identity",
      routeIntent,
      diagnosticsOpen: false,
      providerSetupOpen: false,
      reason: "lifecycle_unconfigured",
    };
  }

  if (OPERATIONAL_STATES.has(currentState)) {
    if (routeIntent === "provider_openai") {
      return {
        mode: "setup",
        routeIntent,
        diagnosticsOpen: false,
        providerSetupOpen: true,
        reason: "manual_provider_setup_override_from_operational",
      };
    }
    if (routeIntent === "setup") {
      return {
        mode: "setup",
        routeIntent,
        diagnosticsOpen: false,
        providerSetupOpen: false,
        reason: "manual_setup_override_from_operational",
      };
    }
    return {
      mode: "operational",
      routeIntent,
      diagnosticsOpen: routeIntent === "diagnostics",
      providerSetupOpen: false,
      reason: "lifecycle_operational",
    };
  }

  if (routeIntent === "provider_openai") {
    return {
      mode: "setup",
      routeIntent,
      diagnosticsOpen: false,
      providerSetupOpen: true,
      reason: "manual_provider_setup_route",
    };
  }

  if (routeIntent === "setup") {
    return {
      mode: "setup",
      routeIntent,
      diagnosticsOpen: false,
      providerSetupOpen: false,
      reason: "manual_setup_route",
    };
  }

  if (SETUP_STATES.has(currentState)) {
    return {
      mode: "setup",
      routeIntent,
      diagnosticsOpen: false,
      providerSetupOpen: false,
      reason: "lifecycle_setup",
    };
  }

  return {
    mode: "setup",
    routeIntent,
    diagnosticsOpen: false,
    providerSetupOpen: false,
    reason: "fallback_setup",
  };
}
