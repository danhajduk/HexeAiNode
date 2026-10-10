export type OperationalSection =
  | "overview"
  | "capabilities"
  | "runtime"
  | "jobs_queue"
  | "manual_image"
  | "avatar_generation"
  | "synthetic_adult_studio"
  | "activity"
  | "clients"
  | "scheduled"
  | "local_llm"
  | "diagnostics";
export type UiModeRoute = "identity" | "setup" | "operational";
export type UiRouteIntent = "auto" | "setup" | "provider_openai" | "provider_local" | "dashboard" | "diagnostics";
export type AvatarGenerationDetailTab = "profile" | "head_face" | "upper_torso" | "lower_torso" | "full_body";

const OPERATIONAL_SECTIONS: OperationalSection[] = [
  "overview",
  "capabilities",
  "runtime",
  "jobs_queue",
  "manual_image",
  "avatar_generation",
  "synthetic_adult_studio",
  "activity",
  "clients",
  "scheduled",
  "local_llm",
  "diagnostics",
];

const AVATAR_GENERATION_DETAIL_TAB_TOKENS: Record<AvatarGenerationDetailTab, string> = {
  profile: "Profile",
  head_face: "Face",
  upper_torso: "UpperTorso",
  lower_torso: "LowerTorso",
  full_body: "FullBody",
};

const AVATAR_GENERATION_DETAIL_TAB_ALIASES: Record<string, AvatarGenerationDetailTab> = {
  profile: "profile",
  face: "head_face",
  head: "head_face",
  headface: "head_face",
  head_face: "head_face",
  "head-face": "head_face",
  head_face_tab: "head_face",
  uppertorso: "upper_torso",
  upper_torso: "upper_torso",
  "upper-torso": "upper_torso",
  lowertorso: "lower_torso",
  lower_torso: "lower_torso",
  "lower-torso": "lower_torso",
  fullbody: "full_body",
  full_body: "full_body",
  "full-body": "full_body",
};

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

export function buildImageStudioRoute(): string {
  return "#/image-studio";
}

export type ImageStudioRouteState = {
  creationType?: string;
  characterPath?: string;
  templateId?: string;
  profileId?: string;
  interviewStep?: number;
  creativeSetupOpen?: boolean;
  interviewOpen?: boolean;
  progressKind?: "face" | "body" | "";
};

export function buildImageStudioStateRoute(state: ImageStudioRouteState = {}): string {
  const params = new URLSearchParams();
  if (state.creationType) params.set("type", state.creationType);
  if (state.characterPath) params.set("path", state.characterPath);
  if (state.templateId) params.set("template", state.templateId);
  if (state.profileId) params.set("profile", state.profileId);
  if (Number.isInteger(state.interviewStep) && Number(state.interviewStep) >= 0) params.set("step", String(state.interviewStep));
  if (state.creativeSetupOpen) params.set("setup", "1");
  if (state.interviewOpen) params.set("interview", "1");
  if (state.progressKind === "face" || state.progressKind === "body") params.set("progress", state.progressKind);
  const query = params.toString();
  return `${buildImageStudioRoute()}${query ? `?${query}` : ""}`;
}

export function resolveImageStudioRouteState(routeHash?: string | null): ImageStudioRouteState {
  const raw = String(routeHash || "").trim();
  const query = raw.includes("?") ? raw.slice(raw.indexOf("?") + 1) : "";
  const params = new URLSearchParams(query);
  const step = Number.parseInt(params.get("step") || "", 10);
  const progress = params.get("progress") || "";
  return {
    creationType: params.get("type") || "",
    characterPath: params.get("path") || "",
    templateId: params.get("template") || "",
    profileId: params.get("profile") || "",
    interviewStep: Number.isInteger(step) && step >= 0 ? step : 0,
    creativeSetupOpen: params.get("setup") === "1",
    interviewOpen: params.get("interview") === "1",
    progressKind: progress === "face" || progress === "body" ? progress : "",
  };
}

export function isImageStudioRoute(routeHash?: string | null): boolean {
  const normalized = String(routeHash || "").trim().toLowerCase();
  return normalized === buildImageStudioRoute() || normalized.startsWith(`${buildImageStudioRoute()}/`) || normalized.startsWith(`${buildImageStudioRoute()}?`);
}

export function buildAvatarGenerationProfileRoute(
  profileId: string,
  detailTab?: AvatarGenerationDetailTab | null,
): string {
  const normalized = String(profileId || "").trim();
  if (!normalized) {
    return buildOperationalRoute("avatar_generation");
  }
  const normalizedTab = detailTab && AVATAR_GENERATION_DETAIL_TAB_TOKENS[detailTab] ? detailTab : null;
  const tabSegment = normalizedTab ? `/${AVATAR_GENERATION_DETAIL_TAB_TOKENS[normalizedTab]}` : "";
  return `${buildOperationalRoute("avatar_generation")}/${encodeURIComponent(normalized)}${tabSegment}`;
}

function avatarGenerationRouteSegments(routeHash?: string | null): string[] {
  const normalized = String(routeHash || "").trim();
  const prefix = `${buildOperationalRoute("avatar_generation")}/`;
  if (!normalized.toLowerCase().startsWith(prefix.toLowerCase())) {
    return [];
  }
  return normalized
    .slice(prefix.length)
    .split(/[?#]/)[0]
    .split("/")
    .filter(Boolean);
}

export function resolveAvatarGenerationProfileId(routeHash?: string | null): string {
  const segments = avatarGenerationRouteSegments(routeHash);
  if (!segments.length) {
    return "";
  }
  const rawProfileId = segments[0] || "";
  try {
    return decodeURIComponent(rawProfileId);
  } catch {
    return rawProfileId;
  }
}

export function resolveAvatarGenerationDetailTab(routeHash?: string | null): AvatarGenerationDetailTab {
  const segments = avatarGenerationRouteSegments(routeHash);
  const rawTab = segments[1] || "";
  const normalized = rawTab.trim().toLowerCase();
  return AVATAR_GENERATION_DETAIL_TAB_ALIASES[normalized] || "profile";
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
