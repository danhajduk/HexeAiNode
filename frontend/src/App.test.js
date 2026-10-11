import { describe, expect, it } from "vitest";

import {
  IMAGE_STUDIO_DATA_ENDPOINTS,
  buildComfyuiWebuiBrowserUrl,
  findImageStudioBodyPreview,
  resolveManualGenerationTracking,
  shouldTrackImageStudioPreview,
} from "./App";
import { buildDashboardUiState } from "./uiStateModel";

describe("Image Studio data boundary", () => {
  it("loads only templates, runtime status, character profiles, and the face catalog", () => {
    expect(IMAGE_STUDIO_DATA_ENDPOINTS).toEqual([
      "/api/comfyui/templates",
      "/api/services/status",
      "/api/avatar-generation",
      "/api/image-studio/face-feature-catalog",
    ]);
  });
});

describe("buildComfyuiWebuiBrowserUrl", () => {
  it("opens localhost bridge URLs on the current node UI hostname", () => {
    const locationObject = {
      origin: "http://100.112.161.57:8081",
      hostname: "100.112.161.57",
    };

    expect(buildComfyuiWebuiBrowserUrl("http://localhost:18188", locationObject)).toBe(
      "http://100.112.161.57:18188/"
    );
    expect(buildComfyuiWebuiBrowserUrl("http://127.0.0.1:18188", locationObject)).toBe(
      "http://100.112.161.57:18188/"
    );
    expect(buildComfyuiWebuiBrowserUrl("http://0.0.0.0:18188", locationObject)).toBe(
      "http://100.112.161.57:18188/"
    );
  });

  it("keeps explicitly configured non-local bridge hosts", () => {
    const locationObject = {
      origin: "http://100.112.161.57:8081",
      hostname: "100.112.161.57",
    };

    expect(buildComfyuiWebuiBrowserUrl("http://node.local:18188", locationObject)).toBe(
      "http://node.local:18188/"
    );
  });
});

describe("buildDashboardUiState", () => {
  it("uses capability setup provider selection when provider config is unavailable", () => {
    const uiState = buildDashboardUiState({
      nodeStatus: {
        status: "operational",
        capability_setup: {
          provider_selection: {
            enabled: ["local", "openai"],
          },
        },
      },
      providerConfig: null,
    });

    expect(uiState.capabilitySummary.enabledProviders).toEqual(["local", "openai"]);
  });
});

describe("resolveManualGenerationTracking", () => {
  it("keeps tracking a newly submitted prompt when the observed payload is stale", () => {
    expect(
      resolveManualGenerationTracking({
        result: { prompt_id: "new-prompt", status: "submitted" },
        payload: { latest_job: { prompt_id: "old-prompt", status: "completed" } },
      })
    ).toEqual({ status: "submitted", active: true });
  });

  it("stops tracking when the submitted prompt is observed as completed", () => {
    expect(
      resolveManualGenerationTracking({
        result: { prompt_id: "new-prompt", status: "submitted" },
        payload: { latest_job: { prompt_id: "new-prompt", status: "completed" } },
      })
    ).toEqual({ status: "completed", active: false });
  });
});

describe("shouldTrackImageStudioPreview", () => {
  it("tracks a newly submitted preview", () => {
    expect(shouldTrackImageStudioPreview({ status: "submitted" })).toBe(true);
  });

  it.each(["completed", "completed_with_fallback", "failed", "error", "cancelled"])(
    "stops tracking a %s preview",
    (status) => {
      expect(shouldTrackImageStudioPreview({ status })).toBe(false);
    }
  );
});

describe("findImageStudioBodyPreview", () => {
  it("finds an active body job stored outside preview history", () => {
    const currentJob = { prompt_id: "body-current", status: "running" };
    const profiles = [{
      prompt_workspaces: {
        upper_torso: {
          current_job: currentJob,
          preview_history: [{ prompt_id: "body-old", status: "completed" }],
        },
      },
    }];

    expect(findImageStudioBodyPreview(profiles, "body-current")).toBe(currentJob);
  });
});
