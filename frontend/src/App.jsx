import { useEffect, useState } from "react";
import { getTheme, setTheme } from "./theme/theme";
import { apiGet, apiPost, getApiBase } from "./api";
import { buildDashboardUiState } from "./uiStateModel";
import "./app.css";

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
  const [savingProvider, setSavingProvider] = useState(false);
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
    const [nodeResult, governanceResult, providerResult] = await Promise.allSettled([
      apiGet("/api/node/status"),
      apiGet("/api/governance/status"),
      apiGet("/api/providers/config"),
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
    const partialFailures = [];
    if (governanceResult.status !== "fulfilled") {
      partialFailures.push("governance_status_unavailable");
    }
    if (providerResult.status !== "fulfilled") {
      partialFailures.push("provider_config_unavailable");
    }

    setBackendStatus(payload.status || "unknown");
    setPendingApprovalUrl(payload.pending_approval_url || "");
    setNodeId(payload.node_id || "");
    setError("");
    if ((payload.status || "unknown") === "capability_setup_pending" && providerPayload) {
      const enabledProviders = providerPayload?.config?.providers?.enabled || [];
      setOpenaiEnabled(enabledProviders.includes("openai"));
    }
    setUiState(
      buildDashboardUiState({
        nodeStatus: payload,
        governanceStatus: governancePayload,
        providerConfig: providerPayload,
        apiReachable: true,
        lastUpdatedAt,
        partialFailures,
      })
    );
  }

  async function loadProviderConfig() {
    try {
      const payload = await apiGet("/api/providers/config");
      const enabledProviders = payload?.config?.providers?.enabled || [];
      setOpenaiEnabled(enabledProviders.includes("openai"));
    } catch (_err) {
      // keep provider section usable even if initial load fails
    }
  }

  useEffect(() => {
    loadStatus();
    const id = setInterval(loadStatus, 5000);
    return () => clearInterval(id);
  }, []);

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

  async function onSaveProviderSelection(event) {
    event.preventDefault();
    setSavingProvider(true);
    setError("");
    try {
      await apiPost("/api/providers/config", { openai_enabled: openaiEnabled });
    } catch (err) {
      const message = String(err?.message || err).replace(/^request failed \(\d+\):\s*/, "");
      setError(message);
    } finally {
      setSavingProvider(false);
    }
  }

  return (
    <main className="page">
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
            <h2>Lifecycle</h2>
            <p className="muted">Primary node diagnostic state</p>
            <div className="state-grid">
              <span>Current State</span>
              <code>{uiState.lifecycle.current}</code>
              <span>Trust Status</span>
              <code>{uiState.lifecycle.trustStatus}</code>
              <span>Paired Core ID</span>
              <code>{uiState.coreConnection.pairedCoreId || "not_paired"}</code>
              <span>Pairing Timestamp</span>
              <code>{uiState.coreConnection.pairingTimestamp || "unavailable"}</code>
              <span>Governance</span>
              <code>{uiState.runtimeHealth.governanceFreshness}</code>
            </div>
          </article>
          <article className="card">
            <h2>Onboarding</h2>
            <p className="muted">Live onboarding progress by lifecycle stage.</p>
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
                <button className="btn btn-primary" type="submit" disabled={savingProvider}>
                  {savingProvider ? "Saving..." : "Save Provider Selection"}
                </button>
              </form>
            ) : null}
          </article>
          <article className="card">
            <h2>Runtime</h2>
            <p className="muted">Operational handoff, degraded recovery, telemetry.</p>
          </article>
          <article className="card">
            <h2>Service</h2>
            <p className="muted">
              Controlled with user systemd units:
              <br />
              <code>synthia-ai-node-backend.service</code>
              <br />
              <code>synthia-ai-node-frontend.service</code>
            </p>
          </article>
        </section>
      )}
    </main>
  );
}
