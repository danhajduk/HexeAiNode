import { useEffect, useState } from "react";
import { getTheme, setTheme } from "./theme/theme";
import { apiGet, apiPost, getApiBase } from "./api";
import { buildDashboardUiState } from "./uiStateModel";
import { CardHeader, HealthIndicator, StatusBadge } from "./components/uiPrimitives";
import "./app.css";

const REFRESH_INTERVAL_MS = 7000;
const UI_VERSION = "0.1.0";
const DIAGNOSTIC_ENDPOINTS = [
  "/api/node/status",
  "/api/governance/status",
  "/api/providers/config",
  "/api/providers/openai/credentials",
  "/api/providers/openai/models/latest?limit=9",
  "/api/capabilities/config",
  "/api/services/status",
];
const TASK_CAPABILITY_OPTIONS = [
  "task.classification.text",
  "task.classification.email",
  "task.classification.image",
  "task.summarization.text",
  "task.summarization.email",
  "task.summarization.event",
  "task.generation.text",
  "task.generation.image",
];

function ThemeToggle() {
  const [theme, setLocalTheme] = useState(getTheme());

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setLocalTheme(next);
  }

  return (
    <button className="btn btn-primary" onClick={toggleTheme}>
      Theme: {theme}
    </button>
  );
}

function formatPrice(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "unavailable";
  }
  return `$${value.toFixed(value >= 1 ? 2 : 3)}/1M`;
}

function formatCreatedAt(value) {
  if (typeof value !== "number" || value <= 0) {
    return "unknown";
  }
  return new Date(value * 1000).toISOString().slice(0, 10);
}

export default function App() {
  const [backendStatus, setBackendStatus] = useState("loading");
  const [pendingApprovalUrl, setPendingApprovalUrl] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [mqttHost, setMqttHost] = useState("");
  const [nodeName, setNodeName] = useState("main-ai-node");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [copied, setCopied] = useState(false);
  const [openaiEnabled, setOpenaiEnabled] = useState(false);
  const [selectedTaskFamilies, setSelectedTaskFamilies] = useState(TASK_CAPABILITY_OPTIONS);
  const [savingProvider, setSavingProvider] = useState(false);
  const [declaringCapabilities, setDeclaringCapabilities] = useState(false);
  const [showCapabilitySetupPopup, setShowCapabilitySetupPopup] = useState(false);
  const [capabilityPopupDismissed, setCapabilityPopupDismissed] = useState(false);
  const [restartingServiceTarget, setRestartingServiceTarget] = useState("");
  const [copiedDiagnostics, setCopiedDiagnostics] = useState(false);
  const [providerCredentials, setProviderCredentials] = useState(null);
  const [latestOpenaiModels, setLatestOpenaiModels] = useState([]);
  const [showProviderCredentialsPopup, setShowProviderCredentialsPopup] = useState(false);
  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [openaiAdminKey, setOpenaiAdminKey] = useState("");
  const [openaiUserIdentifier, setOpenaiUserIdentifier] = useState("");
  const [selectedOpenaiModelIds, setSelectedOpenaiModelIds] = useState([]);
  const [manualPricingInput, setManualPricingInput] = useState("");
  const [manualPricingOutput, setManualPricingOutput] = useState("");
  const [savingCredentials, setSavingCredentials] = useState(false);
  const [savingModelPreference, setSavingModelPreference] = useState(false);
  const [savingManualPricing, setSavingManualPricing] = useState(false);
  const [savingBulkManualPricing, setSavingBulkManualPricing] = useState(false);
  const [refreshingLatestModels, setRefreshingLatestModels] = useState(false);
  const [pricingRefreshState, setPricingRefreshState] = useState("");
  const [showModelPricingPopup, setShowModelPricingPopup] = useState(false);
  const [pricingReviewModelIds, setPricingReviewModelIds] = useState([]);
  const [pricingReviewIndex, setPricingReviewIndex] = useState(0);
  const [popupPricingInput, setPopupPricingInput] = useState("");
  const [popupPricingOutput, setPopupPricingOutput] = useState("");
  const [savingPopupPricing, setSavingPopupPricing] = useState(false);
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
      latestModelsResult,
      capabilityConfigResult,
      servicesResult,
    ] = await Promise.allSettled([
      apiGet("/api/node/status"),
      apiGet("/api/governance/status"),
      apiGet("/api/providers/config"),
      apiGet("/api/providers/openai/credentials"),
      apiGet("/api/providers/openai/models/latest?limit=9"),
      apiGet("/api/capabilities/config"),
      apiGet("/api/services/status"),
    ]);

    if (nodeResult.status !== "fulfilled") {
      setBackendStatus("offline");
      setPendingApprovalUrl("");
      setNodeId("");
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
    const latestModelsPayload = latestModelsResult.status === "fulfilled" ? latestModelsResult.value : null;
    const capabilityConfigPayload = capabilityConfigResult.status === "fulfilled" ? capabilityConfigResult.value : null;
    const servicePayload = servicesResult.status === "fulfilled" ? servicesResult.value : null;
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
    if (latestModelsResult.status !== "fulfilled") {
      partialFailures.push("provider_models_unavailable");
    }
    if (capabilityConfigResult.status !== "fulfilled") {
      partialFailures.push("capability_config_unavailable");
    }
    if (servicesResult.status !== "fulfilled") {
      partialFailures.push("service_status_unavailable");
    }

    setBackendStatus(payload.status || "unknown");
    setPendingApprovalUrl(payload.pending_approval_url || "");
    setNodeId(payload.node_id || "");
    setProviderCredentials(providerCredentialsPayload);
    setLatestOpenaiModels(Array.isArray(latestModelsPayload?.models) ? latestModelsPayload.models : []);
    setError("");
    if (!showProviderCredentialsPopup && providerCredentialsPayload?.credentials?.user_identifier) {
      setOpenaiUserIdentifier(providerCredentialsPayload.credentials.user_identifier);
    }
    if (!showProviderCredentialsPopup) {
      setSelectedOpenaiModelIds(
        Array.isArray(providerCredentialsPayload?.credentials?.selected_model_ids)
          ? providerCredentialsPayload.credentials.selected_model_ids
          : []
      );
    }
    if ((payload.status || "unknown") === "capability_setup_pending" && providerPayload) {
      const enabledProviders = providerPayload?.config?.providers?.enabled || [];
      setOpenaiEnabled(enabledProviders.includes("openai"));
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
    loadStatus();
    const id = setInterval(loadStatus, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (backendStatus === "capability_setup_pending" && !capabilityPopupDismissed) {
      setShowCapabilitySetupPopup(true);
      return;
    }
    if (backendStatus !== "capability_setup_pending") {
      setShowCapabilitySetupPopup(false);
      setCapabilityPopupDismissed(false);
    }
  }, [backendStatus, capabilityPopupDismissed]);

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
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setRestarting(false);
    }
  }

  const isUnconfigured = backendStatus === "unconfigured";
  const isPendingApproval = backendStatus === "pending_approval";
  const isCapabilitySetupPending = backendStatus === "capability_setup_pending";
  const openaiCredentialSummary = providerCredentials?.credentials || {};
  const hasCapabilityRegistration = Boolean(uiState.capabilitySummary.capabilityDeclarationTimestamp);
  const canManageOpenAiCredentials =
    hasCapabilityRegistration && uiState.capabilitySummary.enabledProviders.includes("openai");
  const selectedOpenaiModel = latestOpenaiModels.find((model) => model.model_id === (selectedOpenaiModelIds[0] || "")) || null;
  const pricingReviewModelId = pricingReviewModelIds[pricingReviewIndex] || "";
  const pricingReviewModel = latestOpenaiModels.find((model) => model.model_id === pricingReviewModelId) || null;
  const setupReadinessFlags = uiState.capabilitySummary.setupReadinessFlags || {};
  const setupBlockingReasons = uiState.capabilitySummary.setupBlockingReasons || [];
  const capabilityDeclareAllowed = uiState.capabilitySummary.declarationAllowed;
  const showCorePanel = Boolean(uiState.coreConnection.connected);
  const lifecycleToneClass = `tone-${uiState.lifecycle.tone || "error"}`;
  const onboardingSteps = [
    { key: "bootstrap_discovery", label: "Bootstrap Discovery" },
    { key: "registration", label: "Registration" },
    { key: "approval", label: "Approval" },
    { key: "trust_activation", label: "Trust Activation" },
  ];

  function stepStateLabel(value) {
    if (value === "completed") return "Completed";
    if (value === "in_progress") return "In Progress";
    if (value === "failed") return "Failed";
    return "Pending";
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
    event.preventDefault();
    setSavingProvider(true);
    setError("");
    try {
      await apiPost("/api/providers/config", { openai_enabled: openaiEnabled });
      await apiPost("/api/capabilities/config", { selected_task_families: selectedTaskFamilies });
      await loadStatus();
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingProvider(false);
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

  async function refreshOpenAiModels() {
    setRefreshingLatestModels(true);
    setError("");
    setPricingRefreshState("");
    try {
      const pricingRefreshPayload = await apiPost("/api/providers/openai/pricing/refresh", { force_refresh: true });
      setPricingRefreshState(String(pricingRefreshPayload?.status || "unknown"));
      await apiPost("/api/capabilities/providers/refresh", { force_refresh: true });
      const latestModelsPayload = await apiGet("/api/providers/openai/models/latest?limit=9");
      setLatestOpenaiModels(Array.isArray(latestModelsPayload?.models) ? latestModelsPayload.models : []);
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
    setSavingCredentials(true);
    setError("");
    try {
      const credentialsPayload = await apiPost("/api/providers/openai/credentials", {
        api_key: openaiApiKey,
        admin_key: openaiAdminKey || null,
        user_identifier: openaiUserIdentifier || null,
      });
      setProviderCredentials(credentialsPayload);
      setOpenaiApiKey("");
      setOpenaiAdminKey("");
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

  return (
    <main className="page">
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
      {showCapabilitySetupPopup ? (
        <section className="modal-overlay" role="dialog" aria-modal="true" aria-label="Capability setup required">
          <article className="card modal-card">
            <CardHeader title="Capability Setup Required" subtitle="Complete required inputs to continue onboarding." />
            <div className="state-grid">
              <span>Node ID</span>
              <code>{nodeId || "unavailable"}</code>
              <span>Core ID</span>
              <code>{uiState.coreConnection.pairedCoreId || "unavailable"}</code>
              <span>Core API</span>
              <code>{uiState.coreConnection.coreApiEndpoint || "unavailable"}</code>
            </div>
            <form className="setup-form" onSubmit={onSaveProviderSelection}>
              <label>
                <input
                  type="checkbox"
                  checked={openaiEnabled}
                  onChange={(event) => setOpenaiEnabled(event.target.checked)}
                />{" "}
                Enable OpenAI on this node
              </label>
              <div className="state-grid">
                <span>Task Capabilities</span>
                <code>{selectedTaskFamilies.join(", ") || "none_selected"}</code>
              </div>
              {renderTaskCapabilityToggles("modal")}
              <div className="row">
                <button className="btn btn-primary" type="submit" disabled={savingProvider}>
                  {savingProvider ? "Saving..." : "Save Setup Selection"}
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={onDeclareCapabilities}
                  disabled={declaringCapabilities || !capabilityDeclareAllowed}
                >
                  {declaringCapabilities ? "Declaring..." : "Declare Capabilities"}
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={() => {
                    setShowCapabilitySetupPopup(false);
                    setCapabilityPopupDismissed(true);
                  }}
                >
                  Dismiss
                </button>
              </div>
            </form>
            {setupBlockingReasons.length ? (
              <p className="warning tiny">
                Blocking: <code>{setupBlockingReasons.join(", ")}</code>
              </p>
            ) : (
              <p className="muted tiny">Setup is ready. Declare capabilities to continue.</p>
            )}
            <div className="modal-capability-data">
              <h3>Capability Data</h3>
              <div className="state-grid">
                <span>Capability Status</span>
                <code>{uiState.capabilitySummary.capabilityStatus || "unknown"}</code>
                <span>Task Families</span>
                <code>{uiState.capabilitySummary.selectedTaskFamilies.join(", ") || "none"}</code>
                <span>Enabled Providers</span>
                <code>{uiState.capabilitySummary.enabledProviders.join(", ") || "none"}</code>
                <span>Governance Policy</span>
                <code>{uiState.capabilitySummary.governancePolicyVersion || "unknown"}</code>
                <span>Declare Allowed</span>
                <StatusBadge value={capabilityDeclareAllowed ? "ready" : "blocked"} />
                <span>Trust Ready</span>
                <StatusBadge value={setupReadinessFlags.trust_state_valid ? "ready" : "blocked"} />
                <span>Identity Ready</span>
                <StatusBadge value={setupReadinessFlags.node_identity_valid ? "ready" : "blocked"} />
                <span>Provider Ready</span>
                <StatusBadge value={setupReadinessFlags.provider_selection_valid ? "ready" : "blocked"} />
                <span>Task Capability Ready</span>
                <StatusBadge value={setupReadinessFlags.task_capability_selection_valid ? "ready" : "blocked"} />
                <span>Runtime Context</span>
                <StatusBadge value={setupReadinessFlags.core_runtime_context_valid ? "ready" : "blocked"} />
              </div>
            </div>
          </article>
        </section>
      ) : null}
      {showProviderCredentialsPopup ? (
        <section className="modal-overlay" role="dialog" aria-modal="true" aria-label="OpenAI credentials">
          <article className="card modal-card">
            <CardHeader
              title="OpenAI Credentials"
              subtitle="Save local provider credentials, pick a canonical model, and enter manual pricing when live pricing is blocked."
            />
            <form className="setup-form" onSubmit={onSaveOpenAiCredentials}>
              <label>
                OpenAI API Key
                <input
                  type="password"
                  value={openaiApiKey}
                  onChange={(event) => setOpenaiApiKey(event.target.value)}
                  placeholder="sk-..."
                  required
                />
              </label>
              <label>
                Admin Token
                <input
                  type="password"
                  value={openaiAdminKey}
                  onChange={(event) => setOpenaiAdminKey(event.target.value)}
                  placeholder="Optional reserved token"
                />
              </label>
              <label>
                User / Org Label
                <input
                  value={openaiUserIdentifier}
                  onChange={(event) => setOpenaiUserIdentifier(event.target.value)}
                  placeholder="Optional operator label"
                />
              </label>
              <div className="state-grid">
                <span>Saved API Key</span>
                <code>{openaiCredentialSummary.api_key_hint || "not_saved"}</code>
                <span>Saved Admin Token</span>
                <code>{openaiCredentialSummary.admin_key_hint || "not_saved"}</code>
                <span>Saved Label</span>
                <code>{openaiCredentialSummary.user_identifier || "none"}</code>
                <span>Primary Model</span>
                <code>{openaiCredentialSummary.default_model_id || "not_selected"}</code>
                <span>Selected Models</span>
                <code>{(openaiCredentialSummary.selected_model_ids || []).join(", ") || "none"}</code>
                <span>Updated</span>
                <code>{openaiCredentialSummary.updated_at || "never"}</code>
              </div>
              <div className="row">
                <button className="btn btn-primary" type="submit" disabled={savingCredentials || refreshingLatestModels}>
                  {savingCredentials ? "Saving..." : "Save Credentials"}
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={refreshOpenAiModels}
                  disabled={refreshingLatestModels || !openaiCredentialSummary.has_api_key}
                >
                  {refreshingLatestModels ? "Reloading Models..." : "Reload Models"}
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={() => {
                    setShowProviderCredentialsPopup(false);
                    setOpenaiApiKey("");
                    setOpenaiAdminKey("");
                  }}
                >
                  Close
                </button>
              </div>
              <p className="muted tiny">
                Reload Models keeps pricing manual-only, refreshes provider discovery, and reloads the latest saved model list.
              </p>
              {pricingRefreshState ? (
                <p className="muted tiny">
                  Last pricing sync result: <code>{pricingRefreshState}</code>
                </p>
              ) : null}
            </form>
            <div className="modal-capability-data">
              <div className="model-section-header">
                <h3>Canonical OpenAI Models</h3>
                <span className="muted tiny">
                  {savingModelPreference ? "Saving selections..." : "Selections save automatically"}
                </span>
              </div>
              {latestOpenaiModels.length ? (
                <div className="model-list mini-card-grid">
                  {latestOpenaiModels.map((model) => (
                    <article
                      key={model.model_id}
                      className={`model-card mini-model-card ${selectedOpenaiModelIds.includes(model.model_id) ? "is-selected" : ""}`}
                    >
                      <div className="model-card-header">
                        <strong>{model.display_name || model.model_id}</strong>
                        <StatusBadge value={model.status || "available"} />
                      </div>
                      <div className="state-grid compact-grid">
                        <span>Model ID</span>
                        <code>{model.model_id}</code>
                        <span>Created</span>
                        <code>{formatCreatedAt(model.created)}</code>
                        <span>Input Price</span>
                        <code>{formatPrice(model.pricing?.input_per_1m_tokens)}</code>
                        <span>Output Price</span>
                        <code>{formatPrice(model.pricing?.output_per_1m_tokens)}</code>
                      </div>
                      <div className="row">
                        <button
                          className={`btn ${selectedOpenaiModelIds.includes(model.model_id) ? "btn-primary" : ""}`}
                          type="button"
                          onClick={() => onToggleOpenAiModel(model.model_id)}
                        >
                          {selectedOpenaiModelIds.includes(model.model_id) ? "Selected" : "Add Model"}
                        </button>
                        <button className="btn" type="button" onClick={() => openSingleModelPricing(model.model_id)}>
                          Set Price
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="muted tiny">
                  No OpenAI models discovered yet. Save credentials and run a refresh to populate this list.
                </p>
              )}
              {selectedOpenaiModel ? (
                <form className="manual-pricing-form" onSubmit={onSaveManualPricing}>
                  <div className="model-section-header">
                    <h3>Manual Pricing</h3>
                    <span className="muted tiny">
                      Primary: <code>{selectedOpenaiModel.model_id}</code>
                    </span>
                  </div>
                  <p className="muted tiny">
                    Manual pricing uses the first selected model as primary. You can also apply the same values to all selected models.
                  </p>
                  <div className="state-grid">
                    <span>Current Input</span>
                    <code>{formatPrice(selectedOpenaiModel.pricing?.input_per_1m_tokens)}</code>
                    <span>Current Output</span>
                    <code>{formatPrice(selectedOpenaiModel.pricing?.output_per_1m_tokens)}</code>
                  </div>
                  <label>
                    Manual Input Price / 1M
                    <input
                      type="number"
                      step="0.001"
                      min="0"
                      value={manualPricingInput}
                      onChange={(event) => setManualPricingInput(event.target.value)}
                      placeholder="e.g. 3.000"
                    />
                  </label>
                  <label>
                    Manual Output Price / 1M
                    <input
                      type="number"
                      step="0.001"
                      min="0"
                      value={manualPricingOutput}
                      onChange={(event) => setManualPricingOutput(event.target.value)}
                      placeholder="e.g. 15.000"
                    />
                  </label>
                  <div className="row">
                    <button className="btn btn-primary" type="submit" disabled={savingManualPricing}>
                      {savingManualPricing ? "Saving..." : "Save Manual Price"}
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => startPricingReview(selectedOpenaiModelIds)}
                      disabled={!selectedOpenaiModelIds.length}
                    >
                      Review Selected Model Prices
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={onSaveManualPricingForSelected}
                      disabled={savingBulkManualPricing || !selectedOpenaiModelIds.length}
                    >
                      {savingBulkManualPricing ? "Updating All..." : "Apply To All Selected Models"}
                    </button>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => {
                        setManualPricingInput("");
                        setManualPricingOutput("");
                      }}
                    >
                      Skip
                    </button>
                  </div>
                </form>
              ) : null}
            </div>
          </article>
        </section>
      ) : null}
      <section className="card hero">
        <h1>Synthia AI Node</h1>
        <p className="muted">Node setup and onboarding controls</p>
        <div className="row">
          <ThemeToggle />
          <span className="pill">{backendStatus}</span>
          <button className="btn" onClick={onRestartSetup} disabled={restarting}>
            {restarting ? "Restarting..." : "Restart Setup"}
          </button>
          {isPendingApproval && pendingApprovalUrl ? (
            <a className="btn btn-primary" href={pendingApprovalUrl} target="_blank" rel="noreferrer">
              Approve In Core
            </a>
          ) : null}
        </div>
        <p className="muted tiny">API: {getApiBase()}</p>
        <p className="muted tiny">
          Last update: <code>{uiState.meta.lastUpdatedAt || "never"}</code> | Refresh:{" "}
          <code>{REFRESH_INTERVAL_MS / 1000}s</code>
        </p>
        {uiState.meta.partialFailures?.length ? (
          <p className="warning tiny">
            Partial data unavailable: <code>{uiState.meta.partialFailures.join(", ")}</code>
          </p>
        ) : null}
        <div className="row">
          <span className="muted tiny">
            Unique ID: <code>{nodeId || "unavailable"}</code>
          </span>
          <button className="btn" onClick={onCopyNodeId} disabled={!nodeId}>
            {copied ? "Copied" : "Copy Unique ID"}
          </button>
        </div>
        {error ? <p className="error">{error}</p> : null}
      </section>

      {isUnconfigured ? (
        <section className="card setup-card">
          <h2>Setup Node</h2>
          <p className="muted">
            Node is <code>UNCONFIGURED</code>. Enter bootstrap MQTT host to begin onboarding.
          </p>
          {nodeId ? (
            <p className="muted tiny">
              This node identity is fixed for onboarding: <code>{nodeId}</code>
            </p>
          ) : null}
          <form onSubmit={onSubmit} className="setup-form">
            <label>
              MQTT Host
              <input
                value={mqttHost}
                onChange={(event) => setMqttHost(event.target.value)}
                placeholder="10.0.0.100"
                required
              />
            </label>
            <label>
              Node Name
              <input
                value={nodeName}
                onChange={(event) => setNodeName(event.target.value)}
                placeholder="main-ai-node"
                required
              />
            </label>
            <button className="btn btn-primary" type="submit" disabled={saving}>
              {saving ? "Starting..." : "Start Onboarding"}
            </button>
          </form>
        </section>
      ) : (
        <section className="grid">
          <article className={`card lifecycle-card ${lifecycleToneClass}`}>
            <CardHeader title="Lifecycle" subtitle="Primary node diagnostic state" />
            <div className="state-grid">
              <span>Current State</span>
              <StatusBadge value={uiState.lifecycle.current} />
              <span>Trust Status</span>
              <StatusBadge value={uiState.lifecycle.trustStatus} />
              <span>Paired Core ID</span>
              <code>{uiState.coreConnection.pairedCoreId || "not_paired"}</code>
              <span>Pairing Timestamp</span>
              <code>{uiState.coreConnection.pairingTimestamp || "unavailable"}</code>
              <span>Governance</span>
              <code>{uiState.runtimeHealth.governanceFreshness}</code>
            </div>
          </article>
          <article className="card">
            <CardHeader title="Onboarding" subtitle="Live onboarding progress by lifecycle stage." />
            <div className="progress-list">
              {onboardingSteps.map((step) => {
                const state = uiState.onboarding.progress?.[step.key] || "pending";
                return (
                  <div className="progress-row" key={step.key}>
                    <span>{step.label}</span>
                    <span className={`step-badge step-${state}`}>{stepStateLabel(state)}</span>
                  </div>
                );
              })}
            </div>
            {isPendingApproval && nodeId ? (
              <p className="muted tiny">
                Pending approval for node: <code>{nodeId}</code>
              </p>
            ) : null}
            {isCapabilitySetupPending ? (
              <form className="setup-form" onSubmit={onSaveProviderSelection}>
                <label>
                  <input
                    type="checkbox"
                    checked={openaiEnabled}
                    onChange={(event) => setOpenaiEnabled(event.target.checked)}
                  />{" "}
                  Enable OpenAI on this node
                </label>
                <div className="state-grid">
                  <span>Task Capabilities</span>
                  <code>{selectedTaskFamilies.join(", ") || "none_selected"}</code>
                </div>
                {renderTaskCapabilityToggles("page")}
                <button className="btn btn-primary" type="submit" disabled={savingProvider}>
                  {savingProvider ? "Saving..." : "Save Setup Selection"}
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={onDeclareCapabilities}
                  disabled={declaringCapabilities || !capabilityDeclareAllowed}
                >
                  {declaringCapabilities ? "Declaring..." : "Declare Capabilities"}
                </button>
                <div className="state-grid">
                  <span>Trust Ready</span>
                  <StatusBadge value={setupReadinessFlags.trust_state_valid ? "ready" : "blocked"} />
                  <span>Identity Ready</span>
                  <StatusBadge value={setupReadinessFlags.node_identity_valid ? "ready" : "blocked"} />
                  <span>Provider Ready</span>
                  <StatusBadge value={setupReadinessFlags.provider_selection_valid ? "ready" : "blocked"} />
                  <span>Task Capability Ready</span>
                  <StatusBadge value={setupReadinessFlags.task_capability_selection_valid ? "ready" : "blocked"} />
                  <span>Runtime Context</span>
                  <StatusBadge value={setupReadinessFlags.core_runtime_context_valid ? "ready" : "blocked"} />
                </div>
                {setupBlockingReasons.length ? (
                  <p className="warning tiny">
                    Blocking: <code>{setupBlockingReasons.join(", ")}</code>
                  </p>
                ) : null}
              </form>
            ) : null}
          </article>
          <article className="card">
            <CardHeader title="Runtime" subtitle="Operational signals and health indicators" />
            <div className="state-grid">
              <span>Core API</span>
              <HealthIndicator value={uiState.runtimeHealth.coreApiConnectivity} />
              <span>Operational MQTT</span>
              <HealthIndicator value={uiState.runtimeHealth.operationalMqttConnectivity} />
              <span>Governance</span>
              <HealthIndicator value={uiState.runtimeHealth.governanceFreshness} />
              <span>Last Telemetry</span>
              <code>{uiState.runtimeHealth.lastTelemetryTimestamp || "none"}</code>
              <span>Node Health</span>
              <HealthIndicator value={uiState.runtimeHealth.nodeHealthState} />
            </div>
          </article>
          {showCorePanel ? (
            <article className="card">
              <CardHeader title="Core Connection" subtitle="Trusted Core endpoint metadata" />
              <div className="state-grid">
                <span>Core ID</span>
                <code>{uiState.coreConnection.pairedCoreId}</code>
                <span>Core API</span>
                <code>{uiState.coreConnection.coreApiEndpoint || "unavailable"}</code>
                <span>Operational MQTT</span>
                <code>
                  {uiState.coreConnection.operationalMqttHost || "unavailable"}
                  {uiState.coreConnection.operationalMqttPort ? `:${uiState.coreConnection.operationalMqttPort}` : ""}
                </code>
                <span>Connection</span>
                <HealthIndicator value={uiState.coreConnection.connected ? "connected" : "disconnected"} />
                <span>Onboarding Ref</span>
                <code>{uiState.onboarding.pendingSessionId || uiState.lifecycle.current}</code>
              </div>
            </article>
          ) : null}
          <article className="card">
            <CardHeader title="Capability Summary" subtitle="Phase 2 declaration readiness snapshot" />
            <div className="row capability-actions">
              <button
                className="btn btn-primary"
                type="button"
                disabled={!canManageOpenAiCredentials}
                onClick={() => {
                  setShowProviderCredentialsPopup(true);
                  setOpenaiApiKey("");
                  setOpenaiAdminKey("");
                  setOpenaiUserIdentifier(providerCredentials?.credentials?.user_identifier || "");
                }}
              >
                OpenAI Credentials
              </button>
              {!canManageOpenAiCredentials ? (
                <span className="muted tiny">Available after capability registration completes with OpenAI enabled.</span>
              ) : (
                <span className="muted tiny">
                  Saved key: <code>{openaiCredentialSummary.api_key_hint || "not_saved"}</code> | Model:{" "}
                  <code>{openaiCredentialSummary.default_model_id || "not_selected"}</code>
                </span>
              )}
            </div>
            <div className="state-grid">
              <span>Task Families</span>
              <code>{uiState.capabilitySummary.declaredTaskFamilies.join(", ") || "not_declared"}</code>
              <span>Enabled Providers</span>
              <code>{uiState.capabilitySummary.enabledProviders.join(", ") || "none"}</code>
              <span>Declared At</span>
              <code>{uiState.capabilitySummary.capabilityDeclarationTimestamp || "pending"}</code>
              <span>Governance Policy</span>
              <code>{uiState.capabilitySummary.governancePolicyVersion || "unknown"}</code>
              <span>Provider Expansion</span>
              <code>openai (active), local/future (placeholder)</code>
            </div>
            {canManageOpenAiCredentials ? (
              <div className="model-preview">
                <h3>Latest 9 Canonical OpenAI Models</h3>
                {latestOpenaiModels.length ? (
                  <div className="model-preview-list">
                    {latestOpenaiModels.map((model) => (
                      <div key={model.model_id} className="model-preview-row">
                        <span>
                          {selectedOpenaiModelIds.includes(model.model_id) ? <span className="selected-model-check">✓ </span> : null}
                          {model.display_name || model.model_id}
                        </span>
                        <code>
                          {formatPrice(model.pricing?.input_per_1m_tokens)} in / {formatPrice(model.pricing?.output_per_1m_tokens)} out
                        </code>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted tiny">No model pricing cached yet. Open the credential popup and refresh discovery.</p>
                )}
              </div>
            ) : null}
          </article>
          <article className="card">
            <CardHeader title="Service" subtitle="User systemd service state and controls" />
            <div className="state-grid">
              <span>Backend</span>
              <StatusBadge value={uiState.serviceStatus.backend} />
              <span>Frontend</span>
              <StatusBadge value={uiState.serviceStatus.frontend} />
              <span>Node</span>
              <StatusBadge value={uiState.serviceStatus.node} />
            </div>
            <div className="row">
              <button
                className="btn"
                onClick={() => onRestartService("backend")}
                disabled={Boolean(restartingServiceTarget)}
              >
                {restartingServiceTarget === "backend" ? "Restarting..." : "Restart Backend"}
              </button>
              <button
                className="btn"
                onClick={() => onRestartService("frontend")}
                disabled={Boolean(restartingServiceTarget)}
              >
                {restartingServiceTarget === "frontend" ? "Restarting..." : "Restart Frontend"}
              </button>
              <button
                className="btn btn-primary"
                onClick={() => onRestartService("node")}
                disabled={Boolean(restartingServiceTarget)}
              >
                {restartingServiceTarget === "node" ? "Restarting..." : "Restart Node"}
              </button>
            </div>
          </article>
          <article className="card diagnostics-card">
            <details>
              <summary>Diagnostics</summary>
              <p className="muted tiny">Safe debug data for support and troubleshooting</p>
              <div className="state-grid">
                <span>Lifecycle</span>
                <code>{uiState.lifecycle.current}</code>
                <span>API Base</span>
                <code>{getApiBase()}</code>
                <span>Endpoints</span>
                <code>{DIAGNOSTIC_ENDPOINTS.join(", ")}</code>
                <span>Last Update</span>
                <code>{uiState.meta.lastUpdatedAt || "never"}</code>
                <span>UI Version</span>
                <code>{UI_VERSION}</code>
              </div>
              <button className="btn" onClick={onCopyDiagnostics}>
                {copiedDiagnostics ? "Diagnostics Copied" : "Copy Diagnostics"}
              </button>
            </details>
          </article>
        </section>
      )}
    </main>
  );
}
