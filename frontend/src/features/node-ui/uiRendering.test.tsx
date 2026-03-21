import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { SetupModeView } from "../setup/SetupModeView";
import { buildSetupFlowModel } from "../setup/setupFlowModel";
import { OperationalDashboard } from "../operational/OperationalDashboard";

function buildOperationalProps(overrides = {}) {
  return {
    currentSection: "overview",
    sections: [
      { id: "overview", label: "Overview", onClick: () => {} },
      { id: "diagnostics", label: "Diagnostics", onClick: () => {} },
    ],
    healthStripProps: {
      lifecycleState: "operational",
      trustStatus: "trusted",
      coreApiStatus: "connected",
      mqttStatus: "connected",
      governanceStatus: "fresh",
      providerStatus: "configured",
      lastTelemetryTimestamp: "2026-03-19T20:00:00Z",
    },
    degradedBanner: null,
    overviewCardProps: {
      nodeId: "node-1",
      nodeName: "Main AI Node",
      pairedCoreId: "core-1",
      softwareVersion: "0.1.0",
      lifecycleState: "operational",
      trustState: "trusted",
      pairingTimestamp: "2026-03-19T19:00:00Z",
    },
    coreConnection: {
      show: true,
      pairedCoreId: "core-1",
      coreApiEndpoint: "http://core.local",
      operationalMqttAddress: "core.local:1883",
      connected: true,
      onboardingReference: "session-1",
    },
    runtimeHealth: {
      coreApiConnectivity: "connected",
      operationalMqttConnectivity: "connected",
      governanceFreshness: "fresh",
      lastTelemetryTimestamp: "2026-03-19T20:00:00Z",
      nodeHealthState: "healthy",
    },
    capabilitySummaryProps: {
      enabledProviders: ["openai"],
      usableModels: ["gpt-5.4", "gpt-5-mini"],
      blockedModels: [{ model_id: "tts-1", blockers: ["missing_pricing"] }],
      featureUnion: ["chat", "reasoning", "image_generation"],
      resolvedTaskCount: 6,
      classifierSource: "gpt-5-mini",
      capabilityGraphVersion: "v1",
      onOpenProviderSetup: () => {},
      providerSetupEnabled: true,
      providerHint: "Saved token: sk-**** | Default model: gpt-5.4",
    },
    resolvedTasks: ["task.classification"],
    runtimeServicesProps: {
      serviceStatus: {
        backend: "running",
        frontend: "running",
        node: "running",
      },
    },
    operationalActions: {
      setupActions: [{ label: "Open Setup", onClick: () => {} }],
      runtimeActions: [{ label: "Restart Node", onClick: () => {}, primary: true }],
      adminHint: "Advanced actions stay in diagnostics.",
      onOpenDiagnostics: () => {},
    },
    activityItems: [{ label: "Last declaration", value: "accepted" }],
    onboardingSteps: [{ key: "registration", label: "Registration" }],
    onboardingProgress: { registration: "completed" },
    pendingApprovalNodeId: "",
    diagnosticsProps: {
      capabilityDiagnostics: { resolved_tasks: ["task.classification"] },
      adminActionState: "idle",
      runningAdminAction: "",
      runAdminAction: () => {},
      onCopyDiagnostics: () => {},
      copiedDiagnostics: false,
      uiState: {
        lifecycle: { current: "operational" },
        meta: { lastUpdatedAt: "2026-03-19T20:00:00Z", partialFailures: [] },
      },
    },
    ...overrides,
  };
}

describe("SetupModeView", () => {
  it("renders the setup completion handoff instead of jumping straight to dashboard", () => {
    const markup = renderToStaticMarkup(
      <SetupModeView
        title="Node Setup"
        subtitle="Setup flow"
        summaryItems={[{ label: "Lifecycle", value: "operational" }]}
        stages={[{ id: "ready", label: "Ready", state: "completed" }]}
        activeStageLabel="Ready"
        activePanel={<div>Ready panel</div>}
        primaryActions={[{ label: "Declare", onClick: () => {} }]}
        completionState={{
          title: "Setup Complete",
          subtitle: "Open the dashboard when ready.",
          actions: [{ label: "Open Dashboard", onClick: () => {}, primary: true }],
        }}
      />
    );

    expect(markup).toContain("Setup Complete");
    expect(markup).toContain("Open Dashboard");
    expect(markup).toContain("Ready panel");
  });

  it("maps operational lifecycle to the ready setup stage", () => {
    const flow = buildSetupFlowModel({
      lifecycleState: "operational",
      routeIntent: "setup",
      pendingApprovalUrl: null,
      governanceFreshness: "fresh",
      setupReadinessFlags: {},
      setupBlockingReasons: [],
    });

    expect(flow.activeStage).toBe("ready");
    expect(flow.stages.find((stage) => stage.id === "ready")?.state).toBe("current");
    expect(flow.stages.find((stage) => stage.id === "capability_declaration")?.state).toBe("completed");
  });
});

describe("OperationalDashboard", () => {
  it("keeps diagnostics content out of the default overview", () => {
    const markup = renderToStaticMarkup(<OperationalDashboard {...buildOperationalProps()} />);

    expect(markup).toContain("Node Overview");
    expect(markup).toContain("Actions");
    expect(markup).not.toContain("Advanced inspection and admin controls");
  });

  it("shows diagnostics only on the diagnostics section", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard {...buildOperationalProps({ currentSection: "diagnostics" })} />
    );

    expect(markup).toContain("Diagnostics");
    expect(markup).not.toContain("Node Overview");
  });

  it("keeps degraded nodes in dashboard mode with a warning banner", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          degradedBanner: {
            reason: "governance_stale",
            actions: [{ label: "Open Diagnostics", onClick: () => {}, primary: true }],
          },
        })}
      />
    );

    expect(markup).toContain("Operational With Warnings");
    expect(markup).toContain("Open Diagnostics");
    expect(markup).toContain("Node Overview");
  });

  it("renders Hexe-facing task and pairing labels for operator views", () => {
    const capabilitiesMarkup = renderToStaticMarkup(
      <OperationalDashboard {...buildOperationalProps({ currentSection: "capabilities" })} />
    );
    const overviewMarkup = renderToStaticMarkup(<OperationalDashboard {...buildOperationalProps()} />);

    expect(capabilitiesMarkup).toContain("Classification");
    expect(overviewMarkup).toContain("Paired Hexe Core");
  });
});
