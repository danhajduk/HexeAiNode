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
      { id: "runtime", label: "Runtime", onClick: () => {} },
      { id: "manual_image", label: "Manual Images", onClick: () => {} },
      { id: "avatar_generation", label: "Avatar Generation", onClick: () => {} },
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
        vision_llm: {
          state: "running",
          residency: {
            residency_state: "model_loaded",
          },
        },
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

  it("shows vision runtime status on the runtime section", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard {...buildOperationalProps({ currentSection: "runtime" })} />
    );

    expect(markup).toContain("Vision Runtime");
    expect(markup).toContain("Vision Residency");
    expect(markup).toContain("model_loaded");
    expect(markup).not.toContain("Manual Image Generation");
  });

  it("shows manual image generation on its own section", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "manual_image",
          manualImageGenerationProps: {
            payload: {
              service: { state: "running", manual_session_active: true },
              runtime_service: { state: "running" },
              generation_status: {
                session: {
                  state: "active",
                  queue_available: true,
                  queue_active: true,
                  running_count: 1,
                  pending_count: 2,
                  running_prompt_id: "prompt-running",
                },
                progress: {
                  available: true,
                  active: true,
                  percent: 25,
                  prompt_id: "prompt-running",
                },
                progress_detail: {
                  status: "running",
                  phase: "sampling",
                  label: "Sampling",
                  message: "Sampling step 1 of 4.",
                  prompt_id: "prompt-running",
                  node_id: "14",
                  node_class: "KSampler",
                  value: 1,
                  max: 4,
                  percent: 25,
                  elapsed_seconds: 42,
                  updated_ago_seconds: 2,
                  running_count: 1,
                  pending_count: 2,
                },
              },
              latest_job: {
                status: "running",
                prompt_id: "prompt-running",
              },
              manual_paths: { output_dir: "runtime/manual/comfyui-gpu/output" },
              templates: [
                {
                  template_id: "template.avatar_body_depth_reference_transparent.realvisxl.v1",
                  template_name: "Simple Avatar Generation",
                  description: "Transparent avatar workflow that uses PuLID for face identity and body-depth guidance.",
                  metadata: { domain: "avatar", input_mode: "image" },
                  defaults: {
                    negative_prompt: "low quality, blurry",
                    width: 768,
                    height: 1152,
                    steps: 4,
                    cfg: 1.8,
                    denoise: 0.55,
                  },
                  variables: [
                    { name: "positive_prompt", required: true, type: "string" },
                    { name: "input_image", required: true, type: "image" },
                    { name: "face_reference_image", required: true, type: "image" },
                    { name: "body_reference_image", required: true, type: "image" },
                    { name: "negative_prompt", required: false, type: "string" },
                    { name: "width", required: false, type: "integer" },
                    { name: "height", required: false, type: "integer" },
                    { name: "seed", required: false, type: "integer" },
                    { name: "steps", required: false, type: "integer" },
                    { name: "cfg", required: false, type: "number" },
                    { name: "denoise", required: false, type: "number" },
                    { name: "face_strength", required: false, type: "number" },
                    { name: "pulid_model", required: false, type: "string" },
                    { name: "pulid_provider", required: false, type: "string" },
                    { name: "body_strength", required: false, type: "number" },
                    { name: "body_depth_strength", required: false, type: "number" },
                  ],
                },
              ],
              outputs: [
                {
                  relative_path: "hexe/sample.png",
                  filename: "sample.png",
                  url: "/api/manual-image-generation/outputs/hexe/sample.png",
                },
              ],
              references: [
                {
                  relative_path: "avatar/jane.png",
                  filename: "jane.png",
                  name: "Jane",
                  url: "/api/manual-image-generation/references/avatar/jane.png",
                  input_image: "references/avatar/jane.png",
                },
              ],
            },
          },
        })}
      />
    );

    expect(markup).toContain("Manual Image Generation");
    expect(markup).toContain("ComfyUI Runtime");
    expect(markup).toContain("Latest Job");
    expect(markup).toContain("prompt-running");
    expect(markup).toContain("1 running / 2 pending");
    expect(markup).toContain("25.0%");
    expect(markup).toContain("Sampling (#14, KSampler)");
    expect(markup).toContain("Sampling step 1 of 4.");
    expect(markup).toContain("Template");
    expect(markup).toContain("Transparent avatar workflow that uses PuLID");
    expect(markup).toContain("Default Size");
    expect(markup).toContain("Current Size");
    expect(markup).toContain("Source Image");
    expect(markup).toContain("Avatar References");
    expect(markup).toContain("Prompt");
    expect(markup).toContain("Outputs");
    expect(markup).toContain("Upload Reference");
    expect(markup).toContain("OpenPose");
    expect(markup).toContain("Pose Text");
    expect(markup).toContain("Build Pose Guide");
    expect(markup).toContain("Vision Mode");
    expect(markup).toContain("Scene");
    expect(markup).toContain("Describe");
    expect(markup).toContain("Jane");
    expect(markup).toContain("Draft / Improve Prompt");
    expect(markup).toContain("Reset Template Settings");
    expect(markup).toContain("Delete");
    expect(markup).toContain('step="8"');
    expect(markup).toContain('step="0.01"');
    expect(markup).toContain("Images to Queue");
    expect(markup).toContain("Randomize Seed");
    expect(markup).toContain("Randomize Face/Body");
    expect(markup).toContain("Body Depth Strength");
    expect(markup).toContain("Variation");
    expect(markup).not.toContain("Runtime Health");
  });

  it("keeps the latest manual image job visible from the submit result", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "manual_image",
          manualImageGenerationProps: {
            payload: {
              service: { state: "running", manual_session_active: true },
              runtime_service: { state: "running" },
              generation_status: {
                session: { state: "active", queue_available: true, queue_active: false, running_count: 0, pending_count: 0 },
                progress: { available: false },
              },
              latest_job: {},
              manual_paths: { output_dir: "runtime/manual/comfyui-gpu/output" },
            },
            result: {
              status: "submitted",
              prompt_id: "prompt-submitted",
            },
          },
        })}
      />
    );

    expect(markup).toContain("Latest Job");
    expect(markup).toContain("submitted");
    expect(markup).toContain("prompt-submitted");
  });

  it("shows avatar generation profile creation on its own section", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "avatar_generation",
          avatarGenerationProps: {
            payload: {
              profiles: [
                {
                  profile_id: "Jane_Avatar",
                  name: "Jane Avatar",
                  description: "Face: oval face.\n\nBody: full-body reference.",
                  face_url: "/api/avatar-generation/profiles/Jane_Avatar/assets/face.png",
                  body_url: "/api/avatar-generation/profiles/Jane_Avatar/assets/body.png",
                  updated_at: "2026-06-09T12:00:00Z",
                },
              ],
            },
            apiBase: "http://node.local:9002",
          },
        })}
      />
    );

    expect(markup).toContain("Avatar Generation");
    expect(markup).toContain("Create Profile");
    expect(markup).toContain("Saved Profiles");
    expect(markup).toContain("Character Name");
    expect(markup).toContain("Gender");
    expect(markup).toContain("Skin Color");
    expect(markup).toContain("Hair Color");
    expect(markup).toContain("Character Type");
    expect(markup).toContain("Visual Style");
    expect(markup).toContain("Stylized Realistic");
    expect(markup).toContain("NSFW");
    expect(markup).not.toContain("Initial Data");
    expect(markup).toContain("Save Profile");
    expect(markup).not.toContain("Describe With Vision");
    expect(markup).not.toContain("Body Depth");
    expect(markup).not.toContain("No avatar profiles saved.");
    expect(markup).not.toContain("Manual Image Generation");
  });

  it("shows saved avatar profiles as cards on the second avatar generation tab", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "avatar_generation",
          avatarGenerationProps: {
            initialTab: "saved_profiles",
            payload: {
              selected_profile_id: "Jane_Avatar",
              profiles: [
                {
                  profile_id: "Jane_Avatar",
                  name: "Jane Avatar",
                  selected: true,
                  description: "Face: oval face.\n\nBody: full-body reference.",
                  face_url: "/api/avatar-generation/profiles/Jane_Avatar/assets/face.png",
                  body_url: "/api/avatar-generation/profiles/Jane_Avatar/assets/body.png",
                  updated_at: "2026-06-09T12:00:00Z",
                  extraction: {
                    structured: {
                      identity_prompt: "same Jane Avatar identity",
                      body: { shape: "curvy" },
                    },
                  },
                },
                {
                  profile_id: "No_Extract",
                  name: "No Extract",
                  face_url: "/api/avatar-generation/profiles/No_Extract/assets/face.png",
                  body_url: "/api/avatar-generation/profiles/No_Extract/assets/body.png",
                  updated_at: "2026-06-09T12:05:00Z",
                },
              ],
            },
            apiBase: "http://node.local:9002",
          },
        })}
      />
    );

    expect(markup).toContain("Saved Profiles");
    expect(markup).toContain("Profiles");
    expect(markup).toContain("Latest");
    expect(markup).toContain("Jane Avatar");
    expect(markup).toContain("selected");
    expect(markup).toContain("Open");
    expect(markup).toContain("Select");
    expect(markup).not.toContain("Extract First");
    expect(markup).not.toContain("Extract Data");
    expect(markup).toContain("Delete");
    expect(markup).toContain("Extracted JSON");
    expect(markup).toContain("same Jane Avatar identity");
    expect(markup).toContain("http://node.local:9002/api/avatar-generation/profiles/Jane_Avatar/assets/face.png");
    expect(markup).toContain("http://node.local:9002/api/avatar-generation/profiles/Jane_Avatar/assets/body.png");
    expect(markup).toContain("Face: oval face.");
    expect(markup).not.toContain("Character Name");
    expect(markup).not.toContain("Manual Image Generation");
  });

  it("shows an avatar profile detail route with baseline and staged prompt tabs", () => {
    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "avatar_generation",
          avatarGenerationProps: {
            routeProfileId: "Jane_Avatar",
            payload: {
              selected_profile_id: "Jane_Avatar",
              profiles: [
                {
                  profile_id: "Jane_Avatar",
                  name: "Jane Avatar",
                  selected: true,
                  gender: "female",
                  skin_color: "light",
                  hair_color: "black",
                  character_type: "human",
                  visual_style: "stylized-realistic",
                  nsfw: true,
                  general_prompt: "Jane Avatar, stylized realistic, human, female, light skin, black hair",
                },
              ],
            },
            apiBase: "http://node.local:9002",
          },
        })}
      />
    );

    expect(markup).toContain("Jane Avatar");
    expect(markup).toContain("Back");
    expect(markup).toContain("Profile");
    expect(markup).toContain("Head / Face");
    expect(markup).toContain("Upper Torso");
    expect(markup).toContain("Lower Torso");
    expect(markup).toContain("Full Body");
    expect(markup).toContain("female");
    expect(markup).toContain("black");
    expect(markup).toContain("stylized-realistic");
    expect(markup).toContain("General Initial Prompt");
    expect(markup).toContain("Jane Avatar, stylized realistic");
    expect(markup).not.toContain("Structured JSON");
  });

  it("shows the head face prompt workspace and preview history", () => {
    const profilePayload = {
      selected_profile_id: "Jane_Avatar",
      profiles: [
        {
          profile_id: "Jane_Avatar",
          name: "Jane Avatar",
          selected: true,
          prompt_workspaces: {
            head_face: {
              prompt: "head portrait, blue headset, soft smile",
              negative_prompt: "blurry",
              conversation: [{ role: "user", content: "make the smile softer" }],
              preview_history: [
                {
                  preview_id: "head_face_1",
                  status: "submitted",
                  template_id: "template.avatar_head_face_preview.realvisxl.v1",
                  prompt_id: "prompt-face-preview",
                  created_at: "2026-06-10T10:00:00Z",
                },
              ],
            },
          },
        },
      ],
    };

    const markup = renderToStaticMarkup(
      <OperationalDashboard
        {...buildOperationalProps({
          currentSection: "avatar_generation",
          avatarGenerationProps: {
            routeProfileId: "Jane_Avatar",
            initialDetailTab: "head_face",
            payload: profilePayload,
          },
        })}
      />
    );

    expect(markup).toContain("Current Head / Face Prompt");
    expect(markup).toContain("head portrait, blue headset, soft smile");
    expect(markup).toContain("Adjustment Request");
    expect(markup).toContain("Refine Prompt");
    expect(markup).toContain("Create Preview");
    expect(markup).toContain("Preview History");
    expect(markup).toContain("prompt-face-preview");
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
                  reviewDueAt: "2026-05-04T00:00:00Z",
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
    expect(markup).toContain("Review Due");
    expect(markup).toContain("Default Model");
    expect(markup).toContain("Apr 4, 2026");
    expect(markup).toContain("May 4, 2026");
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
