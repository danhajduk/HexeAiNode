import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { SetupModeView } from "../setup/SetupModeView";
import { buildSetupFlowModel } from "../setup/setupFlowModel";
import { OperationalDashboard } from "../operational/OperationalDashboard";
import { BackendUnavailableScreen } from "./BackendUnavailableScreen";

function buildOperationalProps(overrides = {}) {
  return {
    currentSection: "overview",
    sections: [
      { id: "overview", label: "Overview", onClick: () => {} },
      { id: "scheduled", label: "Scheduled Tasks", onClick: () => {} },
      { id: "clients", label: "Clients", onClick: () => {} },
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
    providerRefreshProps: {
      lastRefreshedAt: "2026-04-03T16:10:00Z",
      lastSubmittedAt: "2026-04-03T16:12:00Z",
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
    clientCostItems: [],
    clientUsageMonth: "2026-04",
    governanceStatus: {
      configured: true,
      status: {
        state: "fresh",
        active_governance_version: "1",
        next_refresh_due_at: "2026-04-05T19:53:49.164289+00:00",
      },
    },
    scheduledTasksProps: {
      scheduler: {
        scheduler_status: "running",
        tasks: {
          heartbeat: {
            task_id: "heartbeat",
            display_name: "HB",
            task_kind: "local_recurring",
            schedule_name: "heartbeat_5_seconds",
            schedule_detail: "Heartbeat every 5 seconds",
            status: "healthy",
            last_success_at: "2026-04-05T19:54:00Z",
            last_failure_at: null,
            next_run_at: "2026-04-05T19:54:05Z",
            last_error: null,
          },
          telemetry: {
            task_id: "telemetry",
            display_name: "Telemetry",
            task_kind: "local_recurring",
            schedule_name: "telemetry_60_seconds",
            schedule_detail: "Telemetry every 60 seconds",
            status: "scheduled",
            last_success_at: "2026-04-05T19:53:50Z",
            last_failure_at: null,
            next_run_at: "2026-04-05T19:54:40Z",
            last_error: null,
          },
        },
        schedule_catalog: [
          { name: "interval_seconds", detail: "Every N seconds (requires integer seconds)" },
          { name: "heartbeat_5_seconds", detail: "Heartbeat every 5 seconds" },
          { name: "telemetry_60_seconds", detail: "Telemetry every 60 seconds" },
          { name: "every_10_seconds", detail: "Every 10 seconds" },
        ],
      },
    },
    onboardingSteps: [{ key: "registration", label: "Registration" }],
    onboardingProgress: { registration: "completed" },
    pendingApprovalNodeId: "",
    diagnosticsProps: {
      capabilityDiagnostics: {
        resolved_tasks: ["task.classification"],
        internal_scheduler: {
          scheduler_status: "running",
          tasks: {
            provider_capability_refresh: {
              display_name: "Provider Capability Refresh",
              schedule_name: "4_times_a_day",
              schedule_detail: "00:00, 06:00, 12:00, 18:00",
              status: "healthy",
            },
          },
        },
      },
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
    expect(flow.stages.find((stage) => stage.id === "ready")?.state).toBe("completed");
    expect(flow.stages.find((stage) => stage.id === "capability_declaration")?.state).toBe("completed");
  });
});

describe("OperationalDashboard", () => {
  it("keeps diagnostics content out of the default overview", () => {
    const markup = renderToStaticMarkup(<OperationalDashboard {...buildOperationalProps()} />);

    expect(markup).toContain("Node Overview");
    expect(markup).toContain("Actions");
    expect(markup).toContain("Runtime Controls");
    expect(markup).toContain("Last Heartbeat");
    expect(markup).not.toContain("Advanced inspection and admin controls");
    expect(markup).not.toContain("Admin &amp; Diagnostics");
  });

  it("shows diagnostics only on the diagnostics section", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard {...buildOperationalProps({ currentSection: "diagnostics" })} />
    );

    expect(markup).toContain("Diagnostics");
    expect(markup).toContain("Internal Scheduler");
    expect(markup).toContain("provider_capability_refresh");
    expect(markup).not.toContain("Node Overview");
  });

  it("shows scheduled tasks on the scheduled section", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard {...buildOperationalProps({ currentSection: "scheduled" })} />
    );

    expect(markup).toContain("Scheduled Tasks");
    expect(markup).toContain("HB");
    expect(markup).toContain("Heartbeat 5 Seconds");
    expect(markup).toContain("Runtime");
    expect(markup).toContain("Type");
    expect(markup).toContain("Every 10 seconds");
    expect(markup).not.toContain("Node Overview");
  });

  it("shows friendly task kind and schedule names and sorts the legend by duration", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "scheduled",
          scheduledTasksProps: {
            scheduler: {
              scheduler_status: "running",
              tasks: {},
              schedule_catalog: [
                { name: "interval_seconds", detail: "Every N seconds (requires integer seconds)" },
                { name: "telemetry_60_seconds", detail: "Telemetry every 60 seconds" },
                { name: "every_10_seconds", detail: "Every 10 seconds" },
                { name: "heartbeat_5_seconds", detail: "Heartbeat every 5 seconds" },
              ],
            },
          },
        })}
      />
    );

    expect(markup).toContain("Heartbeat 5 Seconds");
    expect(markup).toContain("Telemetry 60 Seconds");
    expect(markup.indexOf("Heartbeat 5 Seconds")).toBeLessThan(markup.indexOf("Every 10 Seconds"));
    expect(markup.indexOf("Every 10 Seconds")).toBeLessThan(markup.indexOf("Telemetry 60 Seconds"));
    expect(markup.indexOf("General Interval")).toBeGreaterThan(markup.indexOf("Telemetry 60 Seconds"));
  });

  it("uses scheduler-specific status tones for scheduled task badges", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "scheduled",
          scheduledTasksProps: {
            scheduler: {
              scheduler_status: "running",
              tasks: {
                heartbeat: {
                  task_id: "heartbeat",
                  display_name: "HB",
                  task_kind: "local_recurring",
                  schedule_name: "heartbeat_5_seconds",
                  schedule_detail: "Heartbeat every 5 seconds",
                  status: "running",
                },
                telemetry: {
                  task_id: "telemetry",
                  display_name: "Telemetry",
                  task_kind: "local_recurring",
                  schedule_name: "telemetry_60_seconds",
                  schedule_detail: "Telemetry every 60 seconds",
                  status: "scheduled",
                },
                provider_capability_refresh: {
                  task_id: "provider_capability_refresh",
                  display_name: "Provider Capability Refresh",
                  task_kind: "provider_specific_recurring",
                  schedule_name: "4_times_a_day",
                  schedule_detail: "00:00, 06:00, 12:00, 18:00",
                  status: "idle",
                },
                operational_mqtt_health: {
                  task_id: "operational_mqtt_health",
                  display_name: "Operational MQTT Health",
                  task_kind: "local_recurring",
                  schedule_name: "every_10_seconds",
                  schedule_detail: "Every 10 seconds",
                  status: "failing",
                },
              },
              schedule_catalog: [],
            },
          },
        })}
      />
    );

    expect(markup).toContain("severity-success-strong");
    expect(markup).toContain("status-running");
    expect(markup).toContain("severity-success");
    expect(markup).toContain("status-scheduled");
    expect(markup).toContain("severity-warning");
    expect(markup).toContain("status-idle");
    expect(markup).toContain("severity-danger");
    expect(markup).toContain("status-failing");
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
    expect(capabilitiesMarkup).toContain("Provider Refresh");
    expect(capabilitiesMarkup).toContain("Last Catalog Refresh");
    expect(capabilitiesMarkup).toContain("Last Submitted To Core");
    expect(overviewMarkup).toContain("Paired Hexe Core");
    expect(overviewMarkup).toContain("Telemetry Freshness");
    expect(overviewMarkup).toContain("Telemetry Age");
  });

  it("shows client cost breakdowns on the clients section", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "clients",
          clientCostItems: [
            {
              clientId: "node-email",
              clientLabel: "node-email",
              customerId: "local-user",
              grant: {
                grantDisplayName: "node 4000",
                grantName: "grant:***************user",
                grantId: "grant:node-123e4567-e89b-42d3-a456-426614174000:node",
                validFrom: "2026-04-01T00:00:00+00:00",
                validTo: "2026-05-01T00:00:00+00:00",
                status: "active",
                budgetCents: 500,
              },
              lifetime: { calls: 502, total_tokens: 229217, cost_usd: 0.0672463 },
              current_month: { calls: 502, total_tokens: 229217, cost_usd: 0.0672463 },
              prompts: [
                {
                  promptId: "prompt.email.classify",
                  promptLabel: "prompt.email.classify",
                  currentVersion: "v3",
                  registeredAt: "2026-03-22T00:00:00Z",
                  status: "active",
                  accessScope: "service",
                  ownerService: "node-email",
                  defaultModel: "gpt-5.4-nano",
                  lifetime: { calls: 502, total_tokens: 229217, cost_usd: 0.0672463 },
                  current_month: { calls: 502, total_tokens: 229217, cost_usd: 0.0672463 },
                  models: [
                    {
                      modelId: "gpt-5.4-nano",
                      modelLabel: "gpt-5.4-nano",
                      lifetime: { calls: 501, total_tokens: 229107, cost_usd: 0.0672463 },
                      current_month: { calls: 501, total_tokens: 229107, cost_usd: 0.0672463 },
                    },
                    {
                      modelId: "gpt-5.4",
                      modelLabel: "gpt-5.4",
                      lifetime: { calls: 1, total_tokens: 110, cost_usd: 0 },
                      current_month: { calls: 1, total_tokens: 110, cost_usd: 0 },
                    },
                  ],
                },
              ],
              unusedPrompts: [
                {
                  promptId: "prompt.email.summarize",
                  promptLabel: "prompt.email.summarize",
                  currentVersion: "v1",
                  registeredAt: "2026-04-04T00:00:00Z",
                  status: "active",
                  accessScope: "service",
                  ownerService: "node-email",
                  defaultModel: "gpt-5.4-mini",
                  lifetime: { calls: 0, total_tokens: 0, cost_usd: 0 },
                  current_month: { calls: 0, total_tokens: 0, cost_usd: 0 },
                  models: [],
                },
              ],
              totalPromptCount: 2,
            },
          ],
        })}
      />
    );

    expect(markup).toContain("Client Usage");
    expect(markup).toContain("node-email");
    expect(markup).toContain("local-user");
    expect(markup).toContain("node 4000");
    expect(markup).toContain("Apr 1, 2026 - May 1, 2026");
    expect(markup).toContain("Model");
    expect(markup).toContain("April 2026");
    expect(markup).toContain("prompt.email.classify");
    expect(markup).toContain("v3");
    expect(markup).toContain("registered Mar 22, 2026");
    expect(markup).toContain("Client Registration");
    expect(markup).toContain("Total Prompts");
    expect(markup).toContain(">2<");
    expect(markup).toContain("Grant State");
    expect(markup).toContain("active");
    expect(markup).toContain("Default gpt-5.4-nano | State active | Access service | Owner node-email");
    expect(markup).toContain("Un-Used Prompts");
    expect(markup).toContain("prompt.email.summarize");
    expect(markup).toContain("Created");
    expect(markup).toContain("Default Model");
    expect(markup).toContain("Apr 4, 2026");
    expect(markup).toContain("gpt-5.4-mini");
    expect(markup).toContain("Lifetime $0.067246");
    expect(markup).toContain("April 2026 $0.067246");
    expect(markup).toContain("gpt-5.4-nano");
    expect(markup).toContain("502");
  });

  it("keeps the activity section focused on onboarding and recent activity", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "activity",
          clientCostItems: [
            {
              clientId: "node-email",
              clientLabel: "node-email",
              customerId: "local-user",
              lifetime: { calls: 1, total_tokens: 10, cost_usd: 0.01 },
              current_month: { calls: 1, total_tokens: 10, cost_usd: 0.01 },
              prompts: [],
            },
          ],
        })}
      />
    );

    expect(markup).toContain("Onboarding");
    expect(markup).toContain("Recent Activity");
    expect(markup).not.toContain("Client Usage");
  });
});

describe("BackendUnavailableScreen", () => {
  it("renders a dedicated backend unavailable page", () => {
    const markup = renderToStaticMarkup(
      <BackendUnavailableScreen
        apiBase="http://localhost:9002"
        error="fetch failed"
        lastUpdatedAt="Apr 03, 2026, 9:01:00 AM"
        onRetry={() => {}}
      />
    );

    expect(markup).toContain("Backend Unavailable");
    expect(markup).toContain("Retry Connection");
    expect(markup).toContain("http://localhost:9002");
    expect(markup).toContain("fetch failed");
  });
});
