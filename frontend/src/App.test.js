import { describe, expect, it } from "vitest";

import { buildComfyuiWebuiBrowserUrl } from "./App";
import { buildDashboardUiState } from "./uiStateModel";

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
