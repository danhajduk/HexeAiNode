export type OperationalSection =
  | "overview"
  | "capabilities"
  | "runtime"
  | "manual_image"
  | "activity"
  | "clients"
  | "scheduled"
  | "local_llm"
  | "diagnostics";
export type UiModeRoute = "identity" | "setup" | "operational";
export type UiRouteIntent = "auto" | "setup" | "provider_openai" | "provider_local" | "dashboard" | "diagnostics";

const OPERATIONAL_SECTIONS: OperationalSection[] = [
  "overview",
  "capabilities",
  "runtime",
  "manual_image",
  "activity",
  "clients",
  "scheduled",
  "local_llm",
  "diagnostics",
];

export function buildSetupRoute(provider?: "openai" | "local" | null): string {
  if (provider === "openai") {
    return "#/setup/provider/openai";
  }
  if (provider === "local") {
    return "#/setup/provider/local";
  }
  return "#/setup";
}

export function buildOperationalRoute(section?: OperationalSection | null): string {
  if (!section || section === "overview") {
    return "#/dashboard";
  }
  return `#/dashboard/${section}`;
}

export function resolveOperationalSection(routeHash?: string | null): OperationalSection {
  const normalized = String(routeHash || "#/dashboard").trim().toLowerCase();
  const matched = OPERATIONAL_SECTIONS.filter((section) => section !== "overview")
    .find((section) => normalized.startsWith(buildOperationalRoute(section).toLowerCase()));
  return matched || "overview";
}

export function isSetupRoute(routeHash?: string | null): boolean {
  const normalized = String(routeHash || "").trim().toLowerCase();
  return normalized === "#/setup" || normalized.startsWith("#/setup/");
}

export function isProviderSetupRoute(routeHash?: string | null): boolean {
  const normalized = String(routeHash || "").trim().toLowerCase();
  return (
    normalized === "#/providers/openai" ||
    normalized === "#/providers/local" ||
    normalized.includes("provider/openai") ||
    normalized.includes("provider/local")
  );
}

export function resolveDefaultRouteHashForMode(mode: UiModeRoute, routeHash?: string | null): string | null {
  const normalized = String(routeHash || "").trim();
  if (normalized && normalized !== "#/") {
    return null;
  }
  if (mode === "operational") {
    return buildOperationalRoute();
  }
  if (mode === "setup") {
    return buildSetupRoute();
  }
  return null;
}

function isReadyLifecycleState(lifecycleState?: string | null): boolean {
  const normalized = String(lifecycleState || "").trim().toLowerCase();
  return normalized === "operational" || normalized === "degraded";
}

function isSetupIntent(routeIntent?: UiRouteIntent | null): boolean {
  return routeIntent === "setup" || routeIntent === "provider_openai" || routeIntent === "provider_local";
}

export function shouldArmSetupCompletionRedirect(
  lifecycleState?: string | null,
  routeIntent?: UiRouteIntent | null,
): boolean {
  return !isReadyLifecycleState(lifecycleState) && isSetupIntent(routeIntent);
}

export function shouldAutoRedirectCompletedSetup({
  lifecycleState,
  routeIntent,
  redirectArmed,
}: {
  lifecycleState?: string | null;
  routeIntent?: UiRouteIntent | null;
  redirectArmed?: boolean;
}): boolean {
  return Boolean(redirectArmed) && isReadyLifecycleState(lifecycleState) && isSetupIntent(routeIntent);
}
