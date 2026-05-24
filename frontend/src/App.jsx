import { useEffect, useRef, useState } from "react";
import { getTheme, setTheme } from "./theme/theme";
import { apiAdminGet, apiAdminPost, apiGet, apiPost, getApiBase } from "./api";
import { buildDashboardUiState } from "./uiStateModel";
import { CardHeader, SeverityIndicator, StatusBadge } from "./components/uiPrimitives";
import { IdentityScreen } from "./features/node-ui/IdentityScreen";
import { BackendUnavailableScreen } from "./features/node-ui/BackendUnavailableScreen";
import { resolveUiMode } from "./features/node-ui/uiModeResolver";
import {
  buildOperationalRoute,
  buildSetupRoute,
  resolveDefaultRouteHashForMode,
  resolveOperationalSection,
  shouldArmSetupCompletionRedirect,
  shouldAutoRedirectCompletedSetup,
} from "./features/node-ui/uiRoutes";
import { SetupModeView } from "./features/setup/SetupModeView";
import { buildSetupFlowModel } from "./features/setup/setupFlowModel";
import { OperationalDashboard } from "./features/operational/OperationalDashboard";
import { normalizeClientUsagePayload } from "./features/operational/clientUsageSummary";
import {
  formatModelFamily,
  getCapabilityBadges,
  getModelPricingRows,
  groupOpenAiCatalogModels,
} from "./features/operational/openaiModelPresentation";
import {
  formatProviderBudgetPill,
  providerBudgetTone,
  summarizeProviderBudgets,
} from "./features/operational/providerBudgetSummary";
import {
  SetupApprovalPanel,
  SetupCapabilityDeclarationPanel,
  SetupCoreConnectionPanel,
  SetupGovernancePanel,
  SetupProviderPanel,
  SetupReadyPanel,
  SetupRegistrationPanel,
  SetupTrustActivationPanel,
} from "./features/setup/SetupStagePanels";
import {
  formatBudgetPeriod,
  formatLocalTimestamp,
  formatTierLabel,
  formatTokenHint,
} from "./shared/formatters";
import "./app.css";

const REFRESH_INTERVAL_MS = 5000;
const UI_VERSION = "0.1.0";
const OPENAI_LATEST_MODELS_LIMIT = 200;
const DIAGNOSTIC_ENDPOINTS = [
  "/api/node/status",
  "/api/governance/status",
  "/api/providers/config",
  "/api/providers/openai/credentials",
  "/api/providers/openai/models/catalog",
  "/api/providers/openai/models/capabilities",
  "/api/providers/openai/models/features",
  "/api/providers/openai/models/enabled",
  `/api/providers/openai/models/latest?limit=${OPENAI_LATEST_MODELS_LIMIT}`,
  "/api/providers/openai/capability-resolution",
  "/api/capabilities/node/resolved",
  "/api/capabilities/config",
  "/api/services/status",
];
const TASK_CAPABILITY_OPTIONS = [
  "task.classification",
  "task.summarization",
  "task.chat",
  "task.image_generation",
];
const OPENAI_TOKEN_FORMAT = /^[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9._-]+)+$/;
const PROVIDER_BUDGET_PERIOD_OPTIONS = [
  ["monthly", "Monthly"],
  ["weekly", "Weekly (Mon-Sun)"],
];
function ThemeToggle() {
  const [theme, setLocalTheme] = useState(getTheme());

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setLocalTheme(next);
  }

  return (
    <button className="btn btn-ghost app-header-theme-btn" onClick={toggleTheme}>
      Theme: {theme}
    </button>
  );
}

export default function App() {
  const setupCompletionRedirectArmedRef = useRef(false);
  const [routeHash, setRouteHash] = useState(() => window.location.hash || "#/");
  const [backendStatus, setBackendStatus] = useState("loading");
  const [pendingApprovalUrl, setPendingApprovalUrl] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [mqttHost, setMqttHost] = useState("");
  const [nodeName, setNodeName] = useState("Main AI Node");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [openaiEnabled, setOpenaiEnabled] = useState(false);
  const [openaiBudgetCents, setOpenaiBudgetCents] = useState("");
  const [openaiBudgetPeriod, setOpenaiBudgetPeriod] = useState("monthly");
  const [selectedTaskFamilies, setSelectedTaskFamilies] = useState(TASK_CAPABILITY_OPTIONS);
  const [savingProvider, setSavingProvider] = useState(false);
  const [declaringCapabilities, setDeclaringCapabilities] = useState(false);
  const [redeclaringCapabilities, setRedeclaringCapabilities] = useState(false);
  const [rerequestingTrust, setRerequestingTrust] = useState(false);
  const [restartingServiceTarget, setRestartingServiceTarget] = useState("");
  const [copiedDiagnostics, setCopiedDiagnostics] = useState(false);
  const [retryingBackend, setRetryingBackend] = useState(false);
  const [providerCredentials, setProviderCredentials] = useState(null);
  const [providerBudgetSummaries, setProviderBudgetSummaries] = useState([]);
  const [governanceStatusPayload, setGovernanceStatusPayload] = useState(null);
  const [budgetStatePayload, setBudgetStatePayload] = useState(null);
  const [openaiCatalogModels, setOpenaiCatalogModels] = useState([]);
  const [openaiModelCapabilities, setOpenaiModelCapabilities] = useState([]);
  const [enabledOpenaiModelIds, setEnabledOpenaiModelIds] = useState([]);
  const [resolvedOpenaiCapabilities, setResolvedOpenaiCapabilities] = useState(null);
  const [openaiModelFeatures, setOpenaiModelFeatures] = useState([]);
  const [resolvedNodeCapabilities, setResolvedNodeCapabilities] = useState(null);
  const [latestOpenaiModels, setLatestOpenaiModels] = useState([]);
  const [openaiApiToken, setOpenaiApiToken] = useState("");
  const [openaiServiceToken, setOpenaiServiceToken] = useState("");
  const [openaiProjectName, setOpenaiProjectName] = useState("");
  const [providerSetupDirty, setProviderSetupDirty] = useState(false);
  const [selectedOpenaiModelIds, setSelectedOpenaiModelIds] = useState([]);
  const [manualPricingInput, setManualPricingInput] = useState("");
  const [manualPricingOutput, setManualPricingOutput] = useState("");
  const [savingCredentials, setSavingCredentials] = useState(false);
  const [savingModelPreference, setSavingModelPreference] = useState(false);
  const [savingManualPricing, setSavingManualPricing] = useState(false);
  const [savingBulkManualPricing, setSavingBulkManualPricing] = useState(false);
  const [declaringBudget, setDeclaringBudget] = useState(false);
  const [refreshingLatestModels, setRefreshingLatestModels] = useState(false);
  const [pricingRefreshState, setPricingRefreshState] = useState("");
  const [showModelPricingPopup, setShowModelPricingPopup] = useState(false);
  const [pricingReviewModelIds, setPricingReviewModelIds] = useState([]);
  const [pricingReviewIndex, setPricingReviewIndex] = useState(0);
  const [popupPricingInput, setPopupPricingInput] = useState("");
  const [popupPricingOutput, setPopupPricingOutput] = useState("");
  const [savingPopupPricing, setSavingPopupPricing] = useState(false);
  const [capabilityDiagnostics, setCapabilityDiagnostics] = useState(null);
  const [clientUsageSummary, setClientUsageSummary] = useState({ currentMonth: "", clients: [] });
  const [runningAdminAction, setRunningAdminAction] = useState("");
  const [adminActionState, setAdminActionState] = useState("");
  const [uiState, setUiState] = useState(() =>
    buildDashboardUiState({
      nodeStatus: null,
      governanceStatus: null,
      providerConfig: null,
      apiReachable: false,
      partialFailures: ["node_status_unavailable"],
    })
  );

  async function loadStatus() {
    const lastUpdatedAt = new Date().toISOString();
    const [
      nodeResult,
      governanceResult,
      providerResult,
      providerCredentialsResult,
      modelCatalogResult,
      modelCapabilitiesResult,
      enabledModelsResult,
      latestModelsResult,
      capabilityResolutionResult,
      modelFeaturesResult,
      nodeCapabilitiesResult,
      capabilityConfigResult,
      servicesResult,
      budgetResult,
      clientUsageResult,
      promptServicesResult,
      capabilityDiagnosticsResult,
    ] = await Promise.allSettled([
      apiGet("/api/node/status"),
      apiGet("/api/governance/status"),
      apiGet("/api/providers/config"),
      apiGet("/api/providers/openai/credentials"),
      apiGet("/api/providers/openai/models/catalog"),
      apiGet("/api/providers/openai/models/capabilities"),
      apiGet("/api/providers/openai/models/enabled"),
      apiGet(`/api/providers/openai/models/latest?limit=${OPENAI_LATEST_MODELS_LIMIT}`),
      apiGet("/api/providers/openai/capability-resolution"),
      apiGet("/api/providers/openai/models/features"),
      apiGet("/api/capabilities/node/resolved"),
      apiGet("/api/capabilities/config"),
      apiGet("/api/services/status"),
      apiGet("/api/budgets/state"),
      apiGet("/api/usage/clients"),
      apiGet("/api/prompts/services"),
      apiAdminGet("/api/capabilities/diagnostics"),
    ]);

    if (nodeResult.status !== "fulfilled") {
      setBackendStatus("offline");
      setPendingApprovalUrl("");
      setNodeId("");
      setProviderBudgetSummaries([]);
      const message = String(nodeResult.reason?.message || nodeResult.reason || "backend offline");
      setError(message);
      setUiState(
        buildDashboardUiState({
          nodeStatus: null,
          governanceStatus: null,
          providerConfig: null,
          apiReachable: false,
          lastUpdatedAt,
          partialFailures: ["node_status_unavailable"],
        })
      );
      return;
    }

    const payload = nodeResult.value || {};
    const governancePayload = governanceResult.status === "fulfilled" ? governanceResult.value : null;
    const providerPayload = providerResult.status === "fulfilled" ? providerResult.value : null;
    const providerCredentialsPayload = providerCredentialsResult.status === "fulfilled" ? providerCredentialsResult.value : null;
    const modelCatalogPayload = modelCatalogResult.status === "fulfilled" ? modelCatalogResult.value : null;
    const modelCapabilitiesPayload = modelCapabilitiesResult.status === "fulfilled" ? modelCapabilitiesResult.value : null;
    const enabledModelsPayload = enabledModelsResult.status === "fulfilled" ? enabledModelsResult.value : null;
    const latestModelsPayload = latestModelsResult.status === "fulfilled" ? latestModelsResult.value : null;
    const capabilityResolutionPayload = capabilityResolutionResult.status === "fulfilled" ? capabilityResolutionResult.value : null;
    const modelFeaturesPayload = modelFeaturesResult.status === "fulfilled" ? modelFeaturesResult.value : null;
    const nodeCapabilitiesPayload = nodeCapabilitiesResult.status === "fulfilled" ? nodeCapabilitiesResult.value : null;
    const capabilityConfigPayload = capabilityConfigResult.status === "fulfilled" ? capabilityConfigResult.value : null;
    const servicePayload = servicesResult.status === "fulfilled" ? servicesResult.value : null;
    const budgetPayload = budgetResult.status === "fulfilled" ? budgetResult.value : null;
    const clientUsagePayload = clientUsageResult.status === "fulfilled" ? clientUsageResult.value : null;
    const promptServicesPayload = promptServicesResult.status === "fulfilled" ? promptServicesResult.value : null;
    const capabilityDiagnosticsPayload = capabilityDiagnosticsResult.status === "fulfilled" ? capabilityDiagnosticsResult.value : null;
    const partialFailures = [];
    if (governanceResult.status !== "fulfilled") {
      partialFailures.push("governance_status_unavailable");
    }
    if (providerResult.status !== "fulfilled") {
      partialFailures.push("provider_config_unavailable");
    }
    if (providerCredentialsResult.status !== "fulfilled") {
      partialFailures.push("provider_credentials_unavailable");
    }
    if (modelCatalogResult.status !== "fulfilled") {
      partialFailures.push("provider_model_catalog_unavailable");
    }
    if (modelCapabilitiesResult.status !== "fulfilled") {
      partialFailures.push("provider_model_capabilities_unavailable");
    }
    if (enabledModelsResult.status !== "fulfilled") {
      partialFailures.push("provider_enabled_models_unavailable");
    }
    if (latestModelsResult.status !== "fulfilled") {
      partialFailures.push("provider_models_unavailable");
    }
    if (capabilityResolutionResult.status !== "fulfilled") {
      partialFailures.push("provider_capability_resolution_unavailable");
    }
    if (modelFeaturesResult.status !== "fulfilled") {
      partialFailures.push("provider_model_features_unavailable");
    }
    if (nodeCapabilitiesResult.status !== "fulfilled") {
      partialFailures.push("node_capabilities_unavailable");
    }
    if (capabilityConfigResult.status !== "fulfilled") {
      partialFailures.push("capability_config_unavailable");
    }
    if (servicesResult.status !== "fulfilled") {
      partialFailures.push("service_status_unavailable");
    }
    if (budgetResult.status !== "fulfilled") {
      partialFailures.push("budget_state_unavailable");
    }
    if (clientUsageResult.status !== "fulfilled") {
      partialFailures.push("client_usage_unavailable");
    }
    if (promptServicesResult.status !== "fulfilled") {
      partialFailures.push("prompt_services_unavailable");
    }
    setBackendStatus(payload.status || "unknown");
    setPendingApprovalUrl(payload.pending_approval_url || "");
    setNodeId(payload.node_id || "");
    setProviderCredentials(providerCredentialsPayload);
    setOpenaiCatalogModels(
      Array.isArray(modelCatalogPayload?.ui_models)
        ? modelCatalogPayload.ui_models
        : Array.isArray(modelCatalogPayload?.models)
          ? modelCatalogPayload.models
          : []
    );
    setOpenaiModelCapabilities(Array.isArray(modelCapabilitiesPayload?.entries) ? modelCapabilitiesPayload.entries : []);
    setEnabledOpenaiModelIds(
      Array.isArray(enabledModelsPayload?.models)
        ? enabledModelsPayload.models.filter((model) => model?.enabled).map((model) => model.model_id)
        : []
    );
    setLatestOpenaiModels(Array.isArray(latestModelsPayload?.models) ? latestModelsPayload.models : []);
    setResolvedOpenaiCapabilities(capabilityResolutionPayload);
    setOpenaiModelFeatures(Array.isArray(modelFeaturesPayload?.entries) ? modelFeaturesPayload.entries : []);
    setResolvedNodeCapabilities(nodeCapabilitiesPayload);
    setCapabilityDiagnostics(capabilityDiagnosticsPayload);
    setClientUsageSummary(normalizeClientUsagePayload(clientUsagePayload, promptServicesPayload));
    setGovernanceStatusPayload(governancePayload);
    setBudgetStatePayload(budgetPayload);
    setProviderBudgetSummaries(summarizeProviderBudgets({ providerConfig: providerPayload, budgetState: budgetPayload }));
    setError("");
    if (!providerSetupDirty && providerCredentialsPayload?.credentials?.project_name) {
      setOpenaiProjectName(providerCredentialsPayload.credentials.project_name);
    }
    if (!providerSetupDirty) {
      setSelectedOpenaiModelIds(
        Array.isArray(providerCredentialsPayload?.credentials?.selected_model_ids)
          ? providerCredentialsPayload.credentials.selected_model_ids
          : []
      );
    }
    if (!providerSetupDirty && providerPayload) {
      const enabledProviders = providerPayload?.config?.providers?.enabled || [];
      const openaiBudgetLimit = providerPayload?.config?.providers?.budget_limits?.openai?.max_cost_cents;
      const openaiBudgetWindow = providerPayload?.config?.providers?.budget_limits?.openai?.period;
      setOpenaiEnabled(enabledProviders.includes("openai"));
      setOpenaiBudgetCents(Number.isFinite(openaiBudgetLimit) ? String(openaiBudgetLimit) : "");
      setOpenaiBudgetPeriod(
        openaiBudgetWindow === "weekly" || openaiBudgetWindow === "monthly" ? openaiBudgetWindow : "monthly"
      );
    }
    if ((payload.status || "unknown") === "capability_setup_pending" && capabilityConfigPayload) {
      const selected = capabilityConfigPayload?.config?.selected_task_families || [];
      if (Array.isArray(selected) && selected.length) {
        setSelectedTaskFamilies(selected);
      }
    }
    setUiState(
      buildDashboardUiState({
        nodeStatus: payload,
        governanceStatus: governancePayload,
        providerConfig: providerPayload,
        capabilityConfig: capabilityConfigPayload,
        serviceStatus: servicePayload?.services || null,
        apiReachable: true,
        lastUpdatedAt,
        partialFailures,
      })
    );
  }

  useEffect(() => {
    let cancelled = false;
    let timeoutId;

    function scheduleNextRefresh() {
      const now = Date.now();
      const remainder = now % REFRESH_INTERVAL_MS;
      const delay = remainder === 0 ? REFRESH_INTERVAL_MS : REFRESH_INTERVAL_MS - remainder;

      timeoutId = window.setTimeout(async () => {
        if (cancelled) {
          return;
        }
        await loadStatus();
        if (!cancelled) {
          scheduleNextRefresh();
        }
      }, delay);
    }

    loadStatus();
    scheduleNextRefresh();

    return () => {
      cancelled = true;
      if (timeoutId) {
        window.clearTimeout(timeoutId);
      }
    };
  }, []);

  async function onRetryBackendConnection() {
    if (retryingBackend) {
      return;
    }
    setRetryingBackend(true);
    try {
      await loadStatus();
    } finally {
      setRetryingBackend(false);
    }
  }

  useEffect(() => {
    function onHashChange() {
      setRouteHash(window.location.hash || "#/");
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    if (!selectedOpenaiModelIds.length && latestOpenaiModels.length) {
      const savedModels = Array.isArray(providerCredentials?.credentials?.selected_model_ids)
        ? providerCredentials.credentials.selected_model_ids
        : [];
      setSelectedOpenaiModelIds(savedModels.length ? savedModels : [providerCredentials?.credentials?.default_model_id || latestOpenaiModels[0].model_id]);
    }
  }, [latestOpenaiModels, providerCredentials, selectedOpenaiModelIds]);

  useEffect(() => {
    const selectedModelId = selectedOpenaiModelIds[0] || "";
    const selectedModel = latestOpenaiModels.find((model) => model.model_id === selectedModelId);
    if (!selectedModel) {
      setManualPricingInput("");
      setManualPricingOutput("");
      return;
    }
    setManualPricingInput(
      typeof selectedModel.pricing?.input_per_1m_tokens === "number" ? String(selectedModel.pricing.input_per_1m_tokens) : ""
    );
    setManualPricingOutput(
      typeof selectedModel.pricing?.output_per_1m_tokens === "number" ? String(selectedModel.pricing.output_per_1m_tokens) : ""
    );
  }, [selectedOpenaiModelIds, latestOpenaiModels]);

  useEffect(() => {
    const reviewModelId = pricingReviewModelIds[pricingReviewIndex] || "";
    const reviewModel = latestOpenaiModels.find((model) => model.model_id === reviewModelId);
    if (!reviewModel) {
      setPopupPricingInput("");
      setPopupPricingOutput("");
      return;
    }
    setPopupPricingInput(
      typeof reviewModel.pricing?.input_per_1m_tokens === "number"
        ? String(reviewModel.pricing.input_per_1m_tokens)
        : ""
    );
    setPopupPricingOutput(
      typeof reviewModel.pricing?.output_per_1m_tokens === "number"
        ? String(reviewModel.pricing.output_per_1m_tokens)
        : ""
    );
  }, [pricingReviewModelIds, pricingReviewIndex, latestOpenaiModels]);

  async function onSubmit(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = await apiPost("/api/onboarding/initiate", {
        mqtt_host: mqttHost,
        node_name: nodeName,
      });
      setBackendStatus(payload.status || "bootstrap_connecting");
      setNodeId(payload.node_id || nodeId);
      window.location.hash = "#/setup";
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSaving(false);
    }
  }

  async function onRestartSetup() {
    setRestarting(true);
    setError("");
    try {
      const payload = await apiPost("/api/onboarding/restart", {});
      setBackendStatus(payload.status || "unconfigured");
      setPendingApprovalUrl(payload.pending_approval_url || "");
      setNodeId(payload.node_id || nodeId);
      window.location.hash = "#/";
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setRestarting(false);
    }
  }

  const modeResolution = resolveUiMode({ lifecycleState: backendStatus, routeHash });
  const isIdentityMode = modeResolution.mode === "identity";
  const isSetupMode = modeResolution.mode === "setup";
  const isOperationalMode = modeResolution.mode === "operational";
  const isPendingApproval = backendStatus === "pending_approval";
  const isCapabilitySetupPending = backendStatus === "capability_setup_pending";
  const isProviderSetupRoute = modeResolution.providerSetupOpen;
  const openaiCredentialSummary = providerCredentials?.credentials || {};
  const hasCapabilityRegistration = Boolean(uiState.capabilitySummary.capabilityDeclarationTimestamp);
  const canManageOpenAiCredentials =
    uiState.capabilitySummary.enabledProviders.includes("openai") && (hasCapabilityRegistration || isSetupMode);
  const selectedOpenaiModel = latestOpenaiModels.find((model) => model.model_id === (selectedOpenaiModelIds[0] || "")) || null;
  const openaiModelPriceById = Object.fromEntries(latestOpenaiModels.map((model) => [model.model_id, model.pricing || {}]));
  const openaiModelCreatedById = Object.fromEntries(latestOpenaiModels.map((model) => [model.model_id, model.created || 0]));
  const openaiCapabilityById = Object.fromEntries(
    openaiModelCapabilities.map((entry) => [entry.model_id, entry])
  );
  const groupedOpenAiCatalogModels = groupOpenAiCatalogModels(openaiCatalogModels, openaiModelCreatedById);
  const resolvedCapabilityFlags = resolvedOpenaiCapabilities?.capabilities || {};
  const openaiFeatureUnion = openaiModelFeatures.reduce((acc, entry) => {
    if (!entry || typeof entry !== "object" || !entry.features || typeof entry.features !== "object") {
      return acc;
    }
    Object.entries(entry.features).forEach(([feature, enabled]) => {
      if (enabled) {
        acc[feature] = true;
      } else if (!(feature in acc)) {
        acc[feature] = false;
      }
    });
    return acc;
  }, {});
  const resolvedNodeTasks = Array.isArray(resolvedNodeCapabilities?.enabled_task_capabilities)
    ? resolvedNodeCapabilities.enabled_task_capabilities
    : Array.isArray(resolvedNodeCapabilities?.resolved_tasks)
      ? resolvedNodeCapabilities.resolved_tasks
      : [];
  const usableResolvedModelIds = Array.isArray(resolvedNodeCapabilities?.enabled_models)
    ? resolvedNodeCapabilities.enabled_models
    : Array.isArray(resolvedOpenaiCapabilities?.enabled_models)
      ? resolvedOpenaiCapabilities.enabled_models.map((entry) => entry?.model_id).filter(Boolean)
      : [];
  const blockedResolvedModels = Array.isArray(resolvedNodeCapabilities?.blocked_models)
    ? resolvedNodeCapabilities.blocked_models
    : Array.isArray(resolvedOpenaiCapabilities?.blocked_models)
      ? resolvedOpenaiCapabilities.blocked_models
      : [];
  const blockedResolvedModelMap = Object.fromEntries(
    blockedResolvedModels
      .filter((entry) => entry && typeof entry === "object" && entry.model_id)
      .map((entry) => [entry.model_id, entry])
  );
  const classifierModelUsed =
    openaiModelFeatures.find((entry) => entry?.classification_model)?.classification_model ||
    resolvedOpenaiCapabilities?.classification_model ||
    "unavailable";
  const pricingReviewModelId = pricingReviewModelIds[pricingReviewIndex] || "";
  const pricingReviewModel = latestOpenaiModels.find((model) => model.model_id === pricingReviewModelId) || null;
  const pricingDiagnostics = capabilityDiagnostics?.pricing_diagnostics || {};
  const setupReadinessFlags = uiState.capabilitySummary.setupReadinessFlags || {};
  const setupBlockingReasons = uiState.capabilitySummary.setupBlockingReasons || [];
  const capabilityDeclareAllowed = uiState.capabilitySummary.declarationAllowed;
  const hasAdminToken = Boolean(import.meta.env.VITE_ADMIN_TOKEN);
  const showCorePanel = Boolean(uiState.coreConnection.connected);
  const lifecycleToneClass = `tone-${uiState.lifecycle.tone || "error"}`;
  const onboardingSteps = [
    { key: "bootstrap_discovery", label: "Bootstrap Discovery" },
    { key: "registration", label: "Registration" },
    { key: "approval", label: "Approval" },
    { key: "trust_activation", label: "Trust Activation" },
  ];
  const setupFlow = buildSetupFlowModel({
    lifecycleState: backendStatus,
    routeIntent: modeResolution.routeIntent,
    pendingApprovalUrl,
    governanceFreshness: uiState.runtimeHealth.governanceFreshness,
    setupReadinessFlags,
    setupBlockingReasons,
  });

  function navigateToDashboard() {
    window.location.hash = buildOperationalRoute();
  }

  function navigateToOpenAiProviderSetup() {
    window.location.hash = buildSetupRoute("openai");
  }

  function navigateToSetup() {
    window.location.hash = buildSetupRoute();
  }

  function navigateToDiagnostics() {
    window.location.hash = buildOperationalRoute("diagnostics");
  }

  useEffect(() => {
    const nextRoute = resolveDefaultRouteHashForMode(modeResolution.mode, routeHash);
    if (nextRoute) {
      window.location.hash = nextRoute;
    }
  }, [modeResolution.mode, routeHash]);

  useEffect(() => {
    if (shouldArmSetupCompletionRedirect(backendStatus, modeResolution.routeIntent)) {
      setupCompletionRedirectArmedRef.current = true;
      return;
    }
    if (
      shouldAutoRedirectCompletedSetup({
        lifecycleState: backendStatus,
        routeIntent: modeResolution.routeIntent,
        redirectArmed: setupCompletionRedirectArmedRef.current,
      })
    ) {
      setupCompletionRedirectArmedRef.current = false;
      window.location.hash = buildOperationalRoute();
    }
  }, [backendStatus, modeResolution.routeIntent]);

  function isValidToken(value) {
    return typeof value === "string" && value.trim().length >= 12 && OPENAI_TOKEN_FORMAT.test(value.trim());
  }

  async function onCopyNodeId() {
    if (!nodeId) {
      return;
    }
    try {
      await navigator.clipboard.writeText(nodeId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch (_err) {
      setError("Failed to copy node ID");
    }
  }

  function onToggleTaskFamily(taskFamily, enabled) {
    setSelectedTaskFamilies((current) => {
      const existing = new Set(current);
      if (enabled) {
        existing.add(taskFamily);
      } else {
        existing.delete(taskFamily);
      }
      return TASK_CAPABILITY_OPTIONS.filter((item) => existing.has(item));
  });
}

  async function persistOpenAiPreferences(nextSelectedModelIds, { refreshModels = false } = {}) {
    setSavingModelPreference(true);
    setError("");
    try {
      const payload = await apiPost("/api/providers/openai/preferences", {
        default_model_id: nextSelectedModelIds[0] || null,
        selected_model_ids: nextSelectedModelIds,
      });
      setProviderCredentials(payload);
      if (refreshModels) {
        await refreshOpenAiModels();
      }
      return payload;
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
      throw err;
    } finally {
      setSavingModelPreference(false);
    }
  }

  async function onToggleOpenAiModel(modelId) {
    const model = latestOpenaiModels.find((item) => item.model_id === modelId);
    const wasSelected = selectedOpenaiModelIds.includes(modelId);
    const nextSelectedModelIds = selectedOpenaiModelIds.includes(modelId)
      ? selectedOpenaiModelIds.filter((item) => item !== modelId)
      : [...selectedOpenaiModelIds, modelId];
    setSelectedOpenaiModelIds(nextSelectedModelIds);
    try {
      await persistOpenAiPreferences(nextSelectedModelIds);
      const hasUnavailablePricing =
        typeof model?.pricing?.input_per_1m_tokens !== "number" || typeof model?.pricing?.output_per_1m_tokens !== "number";
      if (!wasSelected && hasUnavailablePricing) {
        setPricingReviewModelIds([modelId]);
        setPricingReviewIndex(0);
        setShowModelPricingPopup(true);
      }
    } catch (_err) {
      setSelectedOpenaiModelIds(selectedOpenaiModelIds);
    }
  }

  async function persistEnabledOpenAiModels(nextEnabledModelIds) {
    setError("");
    const payload = await apiPost("/api/providers/openai/models/enabled", {
      model_ids: nextEnabledModelIds,
    });
    setEnabledOpenaiModelIds(Array.isArray(payload?.models) ? payload.models.filter((model) => model?.enabled).map((model) => model.model_id) : []);
    const resolutionPayload = await apiGet("/api/providers/openai/capability-resolution");
    setResolvedOpenaiCapabilities(resolutionPayload);
  }

  async function onToggleEnabledOpenAiModel(modelId) {
    const nextEnabledModelIds = enabledOpenaiModelIds.includes(modelId)
      ? enabledOpenaiModelIds.filter((item) => item !== modelId)
      : [...enabledOpenaiModelIds, modelId];
    setEnabledOpenaiModelIds(nextEnabledModelIds);
    try {
      await persistEnabledOpenAiModels(nextEnabledModelIds);
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
      setEnabledOpenaiModelIds(enabledOpenaiModelIds);
    }
  }

  function renderTaskCapabilityToggles(prefix) {
    return (
      <div className="capability-toggle-grid">
        {TASK_CAPABILITY_OPTIONS.map((taskFamily) => {
          const enabled = selectedTaskFamilies.includes(taskFamily);
          return (
            <button
              key={`${prefix}-${taskFamily}`}
              type="button"
              className={`btn capability-toggle-btn ${enabled ? "is-on" : "is-off"}`}
              onClick={() => onToggleTaskFamily(taskFamily, !enabled)}
              aria-pressed={enabled}
            >
              {taskFamily}: {enabled ? "ON" : "OFF"}
            </button>
          );
        })}
      </div>
    );
  }

  async function onSaveProviderSelection(event) {
    event?.preventDefault?.();
    setSavingProvider(true);
    setError("");
    try {
      await persistProviderSelectionConfig();
      await apiPost("/api/capabilities/config", { selected_task_families: selectedTaskFamilies });
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingProvider(false);
    }
  }

  async function persistProviderSelectionConfig() {
    const trimmedBudget = String(openaiBudgetCents || "").trim();
    const parsedBudget = trimmedBudget === "" ? null : Number.parseInt(trimmedBudget, 10);
    if (parsedBudget !== null && (!Number.isFinite(parsedBudget) || parsedBudget < 0)) {
      throw new Error("openai budget must be a non-negative whole number of cents");
    }
    const normalizedBudgetPeriod = openaiBudgetPeriod === "weekly" ? "weekly" : "monthly";
    await apiPost("/api/providers/config", {
      openai_enabled: openaiEnabled,
      provider_budget_limits: {
        openai: {
          max_cost_cents: parsedBudget,
          period: normalizedBudgetPeriod,
        },
      },
    });
  }

  async function onSaveOpenAiProviderConfig(event) {
    event?.preventDefault?.();
    setSavingProvider(true);
    setError("");
    try {
      await persistProviderSelectionConfig();
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingProvider(false);
    }
  }

  async function onDeclareOpenAiBudget() {
    if (declaringBudget) {
      return;
    }
    setDeclaringBudget(true);
    setSavingProvider(true);
    setError("");
    try {
      await persistProviderSelectionConfig();
      await apiPost("/api/budgets/declare", { provider_id: "openai" });
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingProvider(false);
      setDeclaringBudget(false);
    }
  }

  async function onRefreshGovernance() {
    setError("");
    try {
      await apiPost("/api/governance/refresh", {});
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    }
  }

  async function onRerequestTrust() {
    if (rerequestingTrust) {
      return;
    }
    setRerequestingTrust(true);
    setError("");
    try {
      await apiPost("/api/node/retrust", {});
      navigateToSetup();
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setRerequestingTrust(false);
    }
  }

  async function onRestartService(target) {
    if (restartingServiceTarget) {
      return;
    }
    setRestartingServiceTarget(target);
    setError("");
    try {
      await apiPost("/api/services/restart", { target });
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setRestartingServiceTarget("");
    }
  }

  async function onDeclareCapabilities() {
    if (declaringCapabilities) {
      return;
    }
    setDeclaringCapabilities(true);
    setError("");
    try {
      await apiPost("/api/capabilities/declare", {});
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
      await loadStatus();
    } finally {
      setDeclaringCapabilities(false);
    }
  }

  async function onRedeclareCapabilities() {
    if (redeclaringCapabilities) {
      return;
    }
    setRedeclaringCapabilities(true);
    setError("");
    try {
      await apiAdminPost("/api/capabilities/redeclare", { force_refresh: true });
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setRedeclaringCapabilities(false);
    }
  }

  async function refreshOpenAiModels() {
    setRefreshingLatestModels(true);
    setError("");
    setPricingRefreshState("");
    try {
      const providerRefreshPayload = await apiPost("/api/capabilities/providers/refresh", { force_refresh: true });
      setPricingRefreshState(
        String(providerRefreshPayload?.openai_model_reload?.status || providerRefreshPayload?.status || "unknown")
      );
      const modelCatalogPayload = await apiGet("/api/providers/openai/models/catalog");
      const modelCapabilitiesPayload = await apiGet("/api/providers/openai/models/capabilities");
      const latestModelsPayload = await apiGet(`/api/providers/openai/models/latest?limit=${OPENAI_LATEST_MODELS_LIMIT}`);
      const enabledModelsPayload = await apiGet("/api/providers/openai/models/enabled");
      const capabilityResolutionPayload = await apiGet("/api/providers/openai/capability-resolution");
      setOpenaiCatalogModels(
        Array.isArray(modelCatalogPayload?.ui_models)
          ? modelCatalogPayload.ui_models
          : Array.isArray(modelCatalogPayload?.models)
            ? modelCatalogPayload.models
            : []
      );
      setOpenaiModelCapabilities(Array.isArray(modelCapabilitiesPayload?.entries) ? modelCapabilitiesPayload.entries : []);
      setLatestOpenaiModels(Array.isArray(latestModelsPayload?.models) ? latestModelsPayload.models : []);
      setEnabledOpenaiModelIds(
        Array.isArray(enabledModelsPayload?.models)
          ? enabledModelsPayload.models.filter((model) => model?.enabled).map((model) => model.model_id)
          : []
      );
      setResolvedOpenaiCapabilities(capabilityResolutionPayload);
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setRefreshingLatestModels(false);
    }
  }

  async function onSaveOpenAiCredentials(event) {
    event.preventDefault();
    if (!isValidToken(openaiApiToken)) {
      setError("OpenAI API token format looks invalid");
      return;
    }
    if (!isValidToken(openaiServiceToken)) {
      setError("OpenAI service token format looks invalid");
      return;
    }
    if (!openaiProjectName.trim()) {
      setError("OpenAI project name is required");
      return;
    }
    setSavingCredentials(true);
    setError("");
    try {
      const credentialsPayload = await apiPost("/api/providers/openai/credentials", {
        api_token: openaiApiToken.trim(),
        service_token: openaiServiceToken.trim(),
        project_name: openaiProjectName.trim(),
      });
      setProviderCredentials(credentialsPayload);
      setOpenaiApiToken("");
      setOpenaiServiceToken("");
      setOpenaiProjectName(credentialsPayload?.credentials?.project_name || openaiProjectName.trim());
      setProviderSetupDirty(false);
      await refreshOpenAiModels();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingCredentials(false);
    }
  }

  async function onSaveOpenAiPreference() {
    if (!selectedOpenaiModelIds.length || savingModelPreference) {
      return;
    }
    try {
      await persistOpenAiPreferences(selectedOpenaiModelIds, { refreshModels: true });
    } catch (_err) {}
  }

  async function onSaveManualPricing(event) {
    event.preventDefault();
    if (!selectedOpenaiModelIds.length || savingManualPricing) {
      return;
    }
    setSavingManualPricing(true);
    setError("");
    try {
      await apiPost("/api/providers/openai/pricing/manual", {
        model_id: selectedOpenaiModelIds[0],
        display_name: selectedOpenaiModel?.display_name || selectedOpenaiModelIds[0],
        input_price_per_1m: manualPricingInput === "" ? null : Number(manualPricingInput),
        output_price_per_1m: manualPricingOutput === "" ? null : Number(manualPricingOutput),
      });
      await persistOpenAiPreferences(selectedOpenaiModelIds);
      await refreshOpenAiModels();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingManualPricing(false);
    }
  }

  async function onSaveManualPricingForSelected(event) {
    event.preventDefault();
    if (!selectedOpenaiModelIds.length || savingBulkManualPricing) {
      return;
    }
    setSavingBulkManualPricing(true);
    setError("");
    try {
      for (const modelId of selectedOpenaiModelIds) {
        const model = latestOpenaiModels.find((item) => item.model_id === modelId);
        await apiPost("/api/providers/openai/pricing/manual", {
          model_id: modelId,
          display_name: model?.display_name || modelId,
          input_price_per_1m: manualPricingInput === "" ? null : Number(manualPricingInput),
          output_price_per_1m: manualPricingOutput === "" ? null : Number(manualPricingOutput),
        });
      }
      await persistOpenAiPreferences(selectedOpenaiModelIds);
      await refreshOpenAiModels();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingBulkManualPricing(false);
    }
  }

  async function runAdminAction(action, endpoint, body = {}) {
    if (runningAdminAction) {
      return;
    }
    setRunningAdminAction(action);
    setAdminActionState("");
    setError("");
    try {
      const payload = await apiAdminPost(endpoint, body);
      setAdminActionState(`${action}: ${String(payload?.status || "ok")}`);
      const diagnosticsPayload = await apiAdminGet("/api/capabilities/diagnostics");
      setCapabilityDiagnostics(diagnosticsPayload);
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setAdminActionState(`${action}: failed`);
      setError(message);
    } finally {
      setRunningAdminAction("");
    }
  }

  function startPricingReview(modelIds) {
    const normalizedModelIds = modelIds.filter(Boolean);
    if (!normalizedModelIds.length) {
      return;
    }
    setPricingReviewModelIds(normalizedModelIds);
    setPricingReviewIndex(0);
    setShowModelPricingPopup(true);
  }

  function openSingleModelPricing(modelId) {
    startPricingReview([modelId]);
  }

  function advancePricingReview() {
    if (pricingReviewIndex + 1 < pricingReviewModelIds.length) {
      setPricingReviewIndex((current) => current + 1);
      return;
    }
    setShowModelPricingPopup(false);
    setPricingReviewModelIds([]);
    setPricingReviewIndex(0);
  }

  async function onSavePopupPricing(event) {
    event.preventDefault();
    if (!pricingReviewModelId || savingPopupPricing) {
      return;
    }
    setSavingPopupPricing(true);
    setError("");
    try {
      await apiPost("/api/providers/openai/pricing/manual", {
        model_id: pricingReviewModelId,
        display_name: pricingReviewModel?.display_name || pricingReviewModelId,
        input_price_per_1m: popupPricingInput === "" ? null : Number(popupPricingInput),
        output_price_per_1m: popupPricingOutput === "" ? null : Number(popupPricingOutput),
      });
      await refreshOpenAiModels();
      advancePricingReview();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingPopupPricing(false);
    }
  }

  async function onCopyDiagnostics() {
    const payload = {
      lifecycle_state: uiState.lifecycle.current,
      api_base: getApiBase(),
      api_endpoints: DIAGNOSTIC_ENDPOINTS,
      last_backend_update: uiState.meta.lastUpdatedAt,
      ui_version: UI_VERSION,
    };
    try {
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      setCopiedDiagnostics(true);
      window.setTimeout(() => setCopiedDiagnostics(false), 1200);
    } catch (_err) {
      setError("Failed to copy diagnostics");
    }
  }

  const setupSummaryItems = [
    { label: "Lifecycle", value: <StatusBadge value={uiState.lifecycle.current} /> },
    { label: "Trust", value: <StatusBadge value={uiState.lifecycle.trustStatus} /> },
    { label: "Governance", value: <StatusBadge value={uiState.runtimeHealth.governanceFreshness} /> },
    { label: "Core", value: <StatusBadge value={uiState.coreConnection.pairedCoreId ? "paired" : "not_paired"} /> },
  ];

  function renderProviderSetupContent() {
    return (
      <div className="provider-page-shell">
        <article className="card provider-page-card">
          <form className="setup-form" onSubmit={onSaveOpenAiProviderConfig}>
            <label>
              <input
                type="checkbox"
                checked={openaiEnabled}
                onChange={(event) => setOpenaiEnabled(event.target.checked)}
              />{" "}
              Enable OpenAI on this node
            </label>
            <label>
              Provider Budget Limit (cents)
              <input
                type="number"
                min="0"
                step="1"
                value={openaiBudgetCents}
                onChange={(event) => setOpenaiBudgetCents(event.target.value)}
                placeholder="Optional provider ceiling"
              />
            </label>
            <label>
              Budget Period
              <select value={openaiBudgetPeriod} onChange={(event) => setOpenaiBudgetPeriod(event.target.value)}>
                {PROVIDER_BUDGET_PERIOD_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <div className="state-grid">
              <span>Budget Window</span>
              <code>{formatBudgetPeriod(openaiBudgetPeriod)}</code>
              <span>Scope</span>
              <code>provider.openai</code>
            </div>
            <p className="muted tiny">
              Save stores the node-local OpenAI ceiling. Declare Budget To Core submits the Core budget declaration for this
              provider.
            </p>
            <div className="row">
              <button className="btn" type="submit" disabled={savingProvider || declaringBudget}>
                {savingProvider ? "Saving..." : "Save Provider Budget"}
              </button>
              <button className="btn btn-primary" type="button" onClick={onDeclareOpenAiBudget} disabled={savingProvider || declaringBudget}>
                {declaringBudget ? "Declaring..." : "Declare Budget To Core"}
              </button>
            </div>
          </form>
          <form className="setup-form" onSubmit={onSaveOpenAiCredentials}>
            <label>
              OpenAI API Token
              <input
                type="password"
                value={openaiApiToken}
                onChange={(event) => {
                  setOpenaiApiToken(event.target.value);
                  setProviderSetupDirty(true);
                }}
                placeholder="sk-proj-..."
                required
              />
            </label>
            <label>
              OpenAI Service Token
              <input
                type="password"
                value={openaiServiceToken}
                onChange={(event) => {
                  setOpenaiServiceToken(event.target.value);
                  setProviderSetupDirty(true);
                }}
                placeholder="sk-service-..."
                required
              />
            </label>
            <label>
              OpenAI Project Name
              <input
                value={openaiProjectName}
                onChange={(event) => {
                  setOpenaiProjectName(event.target.value);
                  setProviderSetupDirty(true);
                }}
                placeholder="project-name"
                required
              />
            </label>
            <div className="state-grid">
              <span>Provider</span>
              <code>openai</code>
              <span>Provider State</span>
              <StatusBadge value={openaiCredentialSummary.configured ? "configured" : "pending"} />
              <span>Saved API Token</span>
              <code>{openaiCredentialSummary.api_token_hint || "not_saved"}</code>
              <span>Saved Service Token</span>
              <code>{openaiCredentialSummary.service_token_hint || "not_saved"}</code>
              <span>Project Name</span>
              <code>{openaiCredentialSummary.project_name || "not_saved"}</code>
              <span>Saved Model</span>
              <code>{openaiCredentialSummary.default_model_id || "not_selected"}</code>
            </div>
            <div className="row">
              <button className="btn btn-primary" type="submit" disabled={savingCredentials || refreshingLatestModels}>
                {savingCredentials ? "Saving..." : "Save Provider Setup"}
              </button>
              <button
                className="btn"
                type="button"
                onClick={refreshOpenAiModels}
                disabled={refreshingLatestModels || !openaiCredentialSummary.has_api_token}
              >
                {refreshingLatestModels ? "Reloading Models..." : "Reload Models"}
              </button>
            </div>
          </form>
          <div className="row capability-actions">
            <button className="btn" type="button" onClick={onSaveOpenAiPreference} disabled={savingModelPreference || !selectedOpenaiModelIds.length}>
              {savingModelPreference ? "Saving Selection..." : "Save Model Selection"}
            </button>
            <button className="btn" type="button" onClick={refreshOpenAiModels} disabled={refreshingLatestModels}>
              Refresh Provider Catalog
            </button>
            <button className="btn" type="button" onClick={() => startPricingReview(selectedOpenaiModelIds)} disabled={!selectedOpenaiModelIds.length}>
              Review Pricing
            </button>
          </div>
          <div className="modal-capability-data">
            <div className="model-section-header">
              <h3>Filtered OpenAI Models</h3>
              <span className="muted tiny">
                {savingModelPreference ? "Saving selections..." : `${openaiCatalogModels.length} filtered models`}
              </span>
            </div>
            {groupedOpenAiCatalogModels.length ? (
              <div className="grouped-model-sections">
                {groupedOpenAiCatalogModels.map((group) => (
                  <section key={group.family} className="model-group-section">
                    <div className="model-section-header">
                      <h3>{group.label}</h3>
                      <span className="muted tiny">{group.models.length} models</span>
                    </div>
                    <div className="model-list mini-card-grid">
                      {group.models.map((model) => {
                        const capabilityEntry = openaiCapabilityById[model.model_id] || null;
                        const pricingEntry = openaiModelPriceById[model.model_id] || null;
                        const blockedEntry = blockedResolvedModelMap[model.model_id] || null;
                        const capabilityBadges = getCapabilityBadges(capabilityEntry);
                        const pricingRows = getModelPricingRows(pricingEntry);
                        const statusBadges = [
                          selectedOpenaiModelIds.includes(model.model_id) ? "Selected" : null,
                          enabledOpenaiModelIds.includes(model.model_id) ? "Enabled selection" : null,
                          usableResolvedModelIds.includes(model.model_id) ? "Usable" : null,
                          blockedEntry && Array.isArray(blockedEntry.blockers) && blockedEntry.blockers.length
                            ? `Blocked: ${blockedEntry.blockers.join(",")}`
                            : null,
                          pricingEntry?.pricing_status ? formatTierLabel(pricingEntry.pricing_status) : null,
                        ].filter(Boolean);
                        return (
                          <article
                            key={model.model_id}
                            className={`model-card mini-model-card ${
                              selectedOpenaiModelIds.includes(model.model_id) || enabledOpenaiModelIds.includes(model.model_id)
                                ? "is-selected"
                                : ""
                            }`}
                          >
                            <div className="model-card-header">
                              <strong>{model.model_id}</strong>
                              <StatusBadge
                                value={
                                  usableResolvedModelIds.includes(model.model_id)
                                    ? "ready"
                                    : blockedEntry
                                      ? "blocked"
                                      : enabledOpenaiModelIds.includes(model.model_id)
                                        ? "enabled"
                                        : "available"
                                }
                              />
                            </div>
                            <div className="capability-badge-list">
                              <span className="capability-badge">{formatModelFamily(capabilityEntry?.family || model.family)}</span>
                              {statusBadges.map((badge) => (
                                <span key={`${model.model_id}-status-${badge}`} className="capability-badge capability-badge-muted">
                                  {badge}
                                </span>
                              ))}
                            </div>
                            <div className="state-grid compact-grid">
                              <span>Model ID</span>
                              <code>{model.model_id}</code>
                              <span>Discovered</span>
                              <code>{model.discovered_at ? model.discovered_at.slice(0, 10) : "unknown"}</code>
                              {pricingRows.flatMap(([label, value]) => ([
                                <span key={`${model.model_id}-${label}-label`}>{label}</span>,
                                <code key={`${model.model_id}-${label}-value`}>{value}</code>,
                              ]))}
                            </div>
                            <div className="capability-badge-list">
                              {capabilityBadges.length ? (
                                capabilityBadges.map((badge) => (
                                  <span key={`${model.model_id}-${badge}`} className="capability-badge">
                                    {badge}
                                  </span>
                                ))
                              ) : (
                                <span className="muted tiny">Deterministic capability defaults applied</span>
                              )}
                            </div>
                            <div className="row model-card-actions">
                              <button
                                className={`btn ${enabledOpenaiModelIds.includes(model.model_id) ? "btn-primary" : ""}`}
                                type="button"
                                onClick={() => onToggleEnabledOpenAiModel(model.model_id)}
                              >
                                {enabledOpenaiModelIds.includes(model.model_id) ? "Disable" : "Enable"}
                              </button>
                              <button
                                className={`btn ${selectedOpenaiModelIds.includes(model.model_id) ? "btn-primary" : ""}`}
                                type="button"
                                onClick={() => onToggleOpenAiModel(model.model_id)}
                              >
                                {selectedOpenaiModelIds.includes(model.model_id) ? "Selected" : "Select"}
                              </button>
                              <button className="btn" type="button" onClick={() => openSingleModelPricing(model.model_id)}>
                                Set Price
                              </button>
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
            ) : (
              <p className="muted tiny">
                No OpenAI models discovered yet. Save provider setup and reload discovery to populate this list.
              </p>
            )}
          </div>
        </article>
      </div>
    );
  }

  function renderSetupActivePanel() {
    switch (setupFlow.activeStage) {
      case "core_connection":
      case "bootstrap_discovery":
        return <SetupCoreConnectionPanel mqttHost={mqttHost} lifecycleState={backendStatus} nodeId={nodeId} />;
      case "registration":
        return <SetupRegistrationPanel nodeId={nodeId} />;
      case "approval":
        return <SetupApprovalPanel nodeId={nodeId} pendingApprovalUrl={pendingApprovalUrl} />;
      case "trust_activation":
        return (
          <SetupTrustActivationPanel
            trustStatus={uiState.lifecycle.trustStatus}
            pairedCoreId={uiState.coreConnection.pairedCoreId}
            startupMode={uiState.lifecycle.startupMode}
          />
        );
      case "provider_setup":
        return (
          <SetupProviderPanel
            openaiEnabled={openaiEnabled}
            openaiBudgetCents={Number.parseInt(openaiBudgetCents || "", 10)}
            openaiBudgetPeriod={openaiBudgetPeriod}
            selectedTaskFamilies={selectedTaskFamilies}
            setupReadinessFlags={setupReadinessFlags}
          >
            {isProviderSetupRoute ? (
              renderProviderSetupContent()
            ) : (
              <form className="setup-form" onSubmit={onSaveProviderSelection}>
                <label>
                  <input
                    type="checkbox"
                    checked={openaiEnabled}
                    onChange={(event) => setOpenaiEnabled(event.target.checked)}
                  />{" "}
                  Enable OpenAI on this node
                </label>
                <p className="muted tiny">
                  Provider budgets are configured per provider route. Open <code>#/setup/provider/openai</code> to set the OpenAI
                  monthly or weekly cap.
                </p>
                <div className="state-grid">
                  <span>OpenAI Budget</span>
                  <code>
                    {Number.isFinite(Number.parseInt(openaiBudgetCents || "", 10))
                      ? `${Number.parseInt(openaiBudgetCents || "", 10)} cents / ${formatBudgetPeriod(openaiBudgetPeriod)}`
                      : "not_set"}
                  </code>
                  <span>Task Capabilities</span>
                  <code>{selectedTaskFamilies.join(", ") || "none_selected"}</code>
                </div>
                {renderTaskCapabilityToggles("setup-shell")}
              </form>
            )}
          </SetupProviderPanel>
        );
      case "governance_sync":
        return (
          <SetupGovernancePanel
            governanceFreshness={uiState.runtimeHealth.governanceFreshness}
            policyVersion={uiState.capabilitySummary.governancePolicyVersion}
            declaredAt={uiState.capabilitySummary.capabilityDeclarationTimestamp}
          />
        );
      case "ready":
        return (
          <SetupReadyPanel
            pairedCoreId={uiState.coreConnection.pairedCoreId}
            lifecycleState={uiState.lifecycle.current}
            governanceFreshness={uiState.runtimeHealth.governanceFreshness}
          />
        );
      case "capability_declaration":
      default:
        return (
          <SetupCapabilityDeclarationPanel
            declarationAllowed={capabilityDeclareAllowed}
            setupReadinessFlags={setupReadinessFlags}
            setupBlockingReasons={setupBlockingReasons}
          />
        );
    }
  }

  function buildSetupActions() {
    const primaryActions = [];
    const secondaryActions = [];
    const dangerActions = [{ label: restarting ? "Restarting..." : "Restart Setup", onClick: onRestartSetup, disabled: restarting }];

    if (setupFlow.activeStage === "approval" && pendingApprovalUrl) {
      primaryActions.push({
        label: "Open Approval In Hexe Core",
        onClick: () => window.open(pendingApprovalUrl, "_blank", "noopener,noreferrer"),
      });
    }
    if (setupFlow.activeStage === "provider_setup" && !isProviderSetupRoute) {
      primaryActions.push({
        label: savingProvider ? "Saving..." : "Save Setup Selection",
        onClick: () => onSaveProviderSelection(),
        disabled: savingProvider,
        primary: true,
      });
      secondaryActions.push({ label: "Configure OpenAI Provider", onClick: navigateToOpenAiProviderSetup });
      secondaryActions.push({
        label: redeclaringCapabilities ? "Redeclaring..." : "Redeclare Capabilities",
        onClick: onRedeclareCapabilities,
        disabled: redeclaringCapabilities || !hasAdminToken,
      });
    }
    if (setupFlow.activeStage === "provider_setup" && isProviderSetupRoute) {
      secondaryActions.push({ label: "Back To Setup Flow", onClick: navigateToSetup });
      secondaryActions.push({
        label: redeclaringCapabilities ? "Redeclaring..." : "Redeclare Capabilities",
        onClick: onRedeclareCapabilities,
        disabled: redeclaringCapabilities || !hasAdminToken,
      });
    }
    if (setupFlow.activeStage === "capability_declaration") {
      primaryActions.push({
        label: declaringCapabilities ? "Declaring..." : "Declare Capabilities",
        onClick: onDeclareCapabilities,
        disabled: declaringCapabilities || !capabilityDeclareAllowed,
        primary: true,
      });
      secondaryActions.push({ label: "Configure Provider", onClick: navigateToOpenAiProviderSetup });
      secondaryActions.push({
        label: redeclaringCapabilities ? "Redeclaring..." : "Redeclare Capabilities",
        onClick: onRedeclareCapabilities,
        disabled: redeclaringCapabilities || !hasAdminToken,
      });
    }
    if (setupFlow.activeStage === "governance_sync") {
      primaryActions.push({ label: "Refresh Governance", onClick: onRefreshGovernance, primary: true });
    }
    if (setupFlow.activeStage === "ready") {
      primaryActions.push({ label: "Open Dashboard", onClick: navigateToDashboard, primary: true });
      secondaryActions.push({ label: "Reopen Provider Setup", onClick: navigateToOpenAiProviderSetup });
    }

    return { primaryActions, secondaryActions, dangerActions };
  }

  const setupActions = buildSetupActions();
  const enabledProviderSummary = uiState.capabilitySummary.enabledProviders.join(", ");
  const currentOperationalSection = resolveOperationalSection(routeHash);
  const operationalSections = [
    ["overview", "Overview"],
    ["capabilities", "Capabilities"],
    ["runtime", "Runtime"],
    ["activity", "Activity"],
    ["clients", "Clients"],
    ["scheduled", "Scheduled Tasks"],
    ["diagnostics", "Diagnostics"],
  ].map(([id, label]) => ({
    id,
    label,
    onClick: () => {
      window.location.hash = buildOperationalRoute(id);
    },
  }));
  const recentActivityItems = [
    {
      label: "Last declaration",
      value: formatLocalTimestamp(uiState.capabilitySummary.capabilityDeclarationTimestamp) || "pending",
      hint: "Most recent accepted capability declaration timestamp.",
    },
    {
      label: "Governance status",
      value: `${uiState.runtimeHealth.governanceFreshness}${capabilityDiagnostics?.governance_status?.last_refresh_error ? ` (${capabilityDiagnostics.governance_status.last_refresh_error})` : ""}`,
      hint: "Current governance freshness and refresh error state when present.",
    },
    {
      label: "Provider intelligence refresh",
      value: formatLocalTimestamp(capabilityDiagnostics?.provider_intelligence_last_submitted_at) || "none",
      hint: "Last provider intelligence submission timestamp.",
    },
    {
      label: "Last declaration result",
      value: capabilityDiagnostics?.last_declaration_result?.status || "none",
      hint: "Most recent declaration result code.",
    },
    {
      label: "Current warning/error",
      value: error || capabilityDiagnostics?.last_error || "none",
      hint: "Most recent UI or runtime visible warning.",
    },
  ];
  const clientCostItems = Array.isArray(clientUsageSummary?.clients) ? clientUsageSummary.clients : [];
  const clientUsageMonth = clientUsageSummary?.currentMonth || "";
  const completionState =
    isSetupMode && (uiState.lifecycle.current === "operational" || uiState.lifecycle.current === "degraded")
      ? {
          title: uiState.lifecycle.current === "degraded" ? "Setup Complete With Warnings" : "Setup Complete",
          subtitle:
            uiState.lifecycle.current === "degraded"
              ? "Hexe Core onboarding is complete. Open the dashboard to review the degraded warning details and continue operating."
              : "Onboarding and governance are ready. Open the dashboard when you are ready to move into operational mode.",
          actions: [
            { label: "Open Dashboard", onClick: navigateToDashboard, primary: true },
            { label: "Review Provider Setup", onClick: navigateToOpenAiProviderSetup },
          ],
        }
      : null;
  const setupSubtitle = completionState
    ? "Setup remains available until you deliberately switch into the operational dashboard."
    : "Setup mode focuses on onboarding, provider readiness, declaration, and governance without dashboard clutter.";
  const degradedReason =
    error ||
    capabilityDiagnostics?.last_error ||
    uiState.meta.partialFailures?.[0] ||
    (uiState.runtimeHealth.governanceFreshness !== "fresh" ? `governance_${uiState.runtimeHealth.governanceFreshness}` : "") ||
    (uiState.runtimeHealth.operationalMqttConnectivity !== "connected"
      ? `mqtt_${uiState.runtimeHealth.operationalMqttConnectivity}`
      : "");
  const operationalActions = {
    setupActions: [
      { label: "Configure OpenAI Provider", onClick: navigateToOpenAiProviderSetup, disabled: !canManageOpenAiCredentials },
      { label: "Refresh Governance", onClick: onRefreshGovernance },
      { label: rerequestingTrust ? "Re-requesting Trust..." : "Re-request Trust", onClick: onRerequestTrust, disabled: rerequestingTrust },
      { label: refreshingLatestModels ? "Refreshing Models..." : "Refresh Provider Models", onClick: refreshOpenAiModels, disabled: refreshingLatestModels },
      { label: redeclaringCapabilities ? "Redeclaring..." : "Redeclare Capabilities", onClick: onRedeclareCapabilities, disabled: redeclaringCapabilities || !hasAdminToken },
    ],
    runtimeActions: [
      { label: restartingServiceTarget === "backend" ? "Restarting Backend..." : "Restart Backend", onClick: () => onRestartService("backend"), disabled: Boolean(restartingServiceTarget) },
      { label: restartingServiceTarget === "frontend" ? "Restarting Frontend..." : "Restart Frontend", onClick: () => onRestartService("frontend"), disabled: Boolean(restartingServiceTarget) },
      { label: restartingServiceTarget === "node" ? "Restarting Node..." : "Restart Node", onClick: () => onRestartService("node"), disabled: Boolean(restartingServiceTarget), primary: true },
    ],
    adminHint: "Advanced rebuild and inspection actions stay on the diagnostics page.",
    onOpenDiagnostics: navigateToDiagnostics,
  };
  const operationalDashboardProps = {
    currentSection: currentOperationalSection,
    sections: operationalSections,
      healthStripProps: {
        lifecycleState: uiState.lifecycle.current,
        trustStatus: uiState.lifecycle.trustStatus,
        coreApiStatus: uiState.runtimeHealth.coreApiConnectivity,
        mqttStatus: uiState.runtimeHealth.operationalMqttConnectivity,
        governanceStatus: uiState.runtimeHealth.governanceFreshness,
        providerStatus: enabledProviderSummary ? "configured" : "none",
        lastTelemetryTimestamp: uiState.runtimeHealth.lastTelemetryTimestamp,
      },
    degradedBanner:
      uiState.lifecycle.current === "degraded"
        ? {
            reason: degradedReason,
            actions: [
              { label: "Open Setup", onClick: navigateToSetup },
              { label: rerequestingTrust ? "Re-requesting Trust..." : "Re-request Trust", onClick: onRerequestTrust, disabled: rerequestingTrust },
              { label: "Open Diagnostics", onClick: navigateToDiagnostics, primary: true },
            ],
          }
        : null,
    overviewCardProps: {
      nodeId,
      nodeName,
      pairedCoreId: uiState.coreConnection.pairedCoreId,
      softwareVersion: UI_VERSION,
      lifecycleState: uiState.lifecycle.current,
      trustState: uiState.lifecycle.trustStatus,
      pairingTimestamp: uiState.coreConnection.pairingTimestamp,
    },
    coreConnection: {
      show: showCorePanel,
      pairedCoreId: uiState.coreConnection.pairedCoreId,
      coreApiEndpoint: uiState.coreConnection.coreApiEndpoint,
      operationalMqttAddress:
        uiState.coreConnection.operationalMqttHost
          ? `${uiState.coreConnection.operationalMqttHost}${uiState.coreConnection.operationalMqttPort ? `:${uiState.coreConnection.operationalMqttPort}` : ""}`
          : "",
      connected: uiState.coreConnection.connected,
      onboardingReference: uiState.onboarding.pendingSessionId || uiState.lifecycle.current,
    },
    runtimeHealth: uiState.runtimeHealth,
    capabilitySummaryProps: {
      enabledProviders: uiState.capabilitySummary.enabledProviders,
      usableModels: usableResolvedModelIds,
      blockedModels: blockedResolvedModels,
      featureUnion: Object.entries(openaiFeatureUnion)
        .filter(([, enabled]) => Boolean(enabled))
        .map(([feature]) => feature),
      resolvedTaskCount: resolvedNodeTasks.length,
      classifierSource: classifierModelUsed,
      capabilityGraphVersion: resolvedNodeCapabilities?.capability_graph_version,
      onOpenProviderSetup: navigateToOpenAiProviderSetup,
      providerSetupEnabled: canManageOpenAiCredentials,
      providerHint:
        !canManageOpenAiCredentials
          ? "Available after capability registration completes with OpenAI enabled."
          : `Saved token: ${formatTokenHint(openaiCredentialSummary.api_token_hint)} | Default model: ${
              openaiCredentialSummary.default_model_id || "not_selected"
            }`,
    },
    providerRefreshProps: {
      lastRefreshedAt: capabilityDiagnostics?.provider_capability_report?.generated_at,
      lastSubmittedAt: capabilityDiagnostics?.provider_intelligence_last_submitted_at,
    },
    resolvedTasks: resolvedNodeTasks,
    runtimeServicesProps: {
      serviceStatus: uiState.serviceStatus,
    },
    operationalActions,
    activityItems: recentActivityItems,
    clientCostItems,
    clientUsageMonth,
    governanceStatus: governanceStatusPayload,
    scheduledTasksProps: {
      scheduler: capabilityDiagnostics?.internal_scheduler || null,
    },
    onboardingSteps,
    onboardingProgress: uiState.onboarding.progress,
    pendingApprovalNodeId: isPendingApproval && nodeId ? nodeId : "",
    diagnosticsProps: {
      capabilityDiagnostics,
      adminActionState,
      runningAdminAction,
      runAdminAction,
      onCopyDiagnostics,
      copiedDiagnostics,
      uiState,
    },
  };
  const isBackendUnavailable = !uiState.meta.apiReachable;

  return (
    <div className="shell">
      <main className="app-frame">
      {isBackendUnavailable ? (
        <BackendUnavailableScreen
          apiBase={getApiBase()}
          error={error}
          lastUpdatedAt={formatLocalTimestamp(uiState.meta.lastUpdatedAt) || "never"}
          retrying={retryingBackend}
          onRetry={onRetryBackendConnection}
        />
      ) : (
        <>
      {showModelPricingPopup && pricingReviewModel ? (
        <section className="modal-overlay pricing-modal-overlay" role="dialog" aria-modal="true" aria-label="Model pricing">
          <article className="card modal-card">
            <CardHeader
              title="Model Pricing"
              subtitle="Enter pricing for this selected model if it is unavailable. You can skip and continue."
            />
            <div className="state-grid">
              <span>Model</span>
              <code>{pricingReviewModel.display_name || pricingReviewModel.model_id}</code>
              <span>Model ID</span>
              <code>{pricingReviewModel.model_id}</code>
              <span>Step</span>
              <code>
                {pricingReviewIndex + 1} / {pricingReviewModelIds.length}
              </code>
            </div>
            <form className="manual-pricing-form" onSubmit={onSavePopupPricing}>
              <label>
                Input Price / 1M
                <input
                  type="number"
                  step="0.001"
                  min="0"
                  value={popupPricingInput}
                  onChange={(event) => setPopupPricingInput(event.target.value)}
                  placeholder="e.g. 3.000"
                />
              </label>
              <label>
                Output Price / 1M
                <input
                  type="number"
                  step="0.001"
                  min="0"
                  value={popupPricingOutput}
                  onChange={(event) => setPopupPricingOutput(event.target.value)}
                  placeholder="e.g. 15.000"
                />
              </label>
              <div className="row">
                <button className="btn btn-primary" type="submit" disabled={savingPopupPricing}>
                  {savingPopupPricing ? "Saving..." : "Save Price"}
                </button>
                <button className="btn" type="button" onClick={advancePricingReview}>
                  Skip
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={() => {
                    setShowModelPricingPopup(false);
                    setPricingReviewModelIds([]);
                    setPricingReviewIndex(0);
                  }}
                >
                  Close
                </button>
              </div>
            </form>
          </article>
        </section>
      ) : null}
      {!isProviderSetupRoute ? (
        <section className="card app-header">
          <div className="app-header-top">
            <div>
              <h1>Hexe AI Node</h1>
            </div>
            <div className="app-header-status-pills">
              <StatusBadge value={backendStatus} />
              {providerBudgetSummaries.map((summary) => (
                <SeverityIndicator key={summary.providerId} tone={providerBudgetTone(summary)}>
                  <span className="status-badge">{formatProviderBudgetPill(summary)}</span>
                </SeverityIndicator>
              ))}
            </div>
          </div>
          <div className="app-header-bottom">
            <ThemeToggle />
            <div className="app-header-actions">
              {isOperationalMode ? (
                <button className="btn" onClick={navigateToSetup}>
                  Open Setup
                </button>
              ) : null}
              {isPendingApproval && pendingApprovalUrl ? (
                <a className="btn btn-primary" href={pendingApprovalUrl} target="_blank" rel="noreferrer">
                  Approve In Hexe Core
                </a>
              ) : null}
              <button className="btn" onClick={onCopyNodeId} disabled={!nodeId}>
                {copied ? "Copied ID" : "Copy Node ID"}
              </button>
            </div>
          </div>
          <div className="app-header-meta">
            <span className="muted tiny">Updated: <code>{formatLocalTimestamp(uiState.meta.lastUpdatedAt) || "never"}</code></span>
            <span className="muted tiny">Node: <code>{nodeId || "unavailable"}</code></span>
          </div>
          {uiState.meta.partialFailures?.length ? (
            <p className="warning tiny">
              Partial data unavailable: <code>{uiState.meta.partialFailures.join(", ")}</code>
            </p>
          ) : null}
          {error ? <p className="error">{error}</p> : null}
        </section>
      ) : null}

      {isIdentityMode ? (
        <IdentityScreen
          nodeId={nodeId}
          mqttHost={mqttHost}
          nodeName={nodeName}
          saving={saving}
          onMqttHostChange={setMqttHost}
          onNodeNameChange={setNodeName}
          onSubmit={onSubmit}
        />
      ) : isSetupMode ? (
        <SetupModeView
          title={isProviderSetupRoute ? "AI Provider Setup" : "Node Setup"}
          subtitle={setupSubtitle}
          summaryItems={setupSummaryItems}
          stages={setupFlow.stages}
          activeStageLabel={setupFlow.stages.find((stage) => stage.id === setupFlow.activeStage)?.label}
          activePanel={renderSetupActivePanel()}
          primaryActions={setupActions.primaryActions}
          secondaryActions={setupActions.secondaryActions}
          dangerActions={setupActions.dangerActions}
          completionState={completionState}
        />
      ) : isOperationalMode ? (
        <OperationalDashboard {...operationalDashboardProps} />
      ) : null}
        </>
      )}
      </main>
    </div>
  );
}
