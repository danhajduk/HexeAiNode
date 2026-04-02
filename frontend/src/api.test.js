import { afterEach, describe, expect, it, vi } from "vitest";

import { getApiBase } from "./api";

describe("getApiBase", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the proxied node API path when mounted under a node UI prefix", () => {
    vi.stubGlobal("window", {
      location: {
        origin: "https://core.example",
        pathname: "/nodes/node-123/ui/",
        protocol: "https:",
        hostname: "core.example",
      },
    });

    expect(getApiBase()).toBe("https://core.example/api/nodes/node-123");
  });

  it("falls back to the local node API origin outside the proxy mount", () => {
    vi.stubGlobal("window", {
      location: {
        origin: "http://192.168.1.55:8081",
        pathname: "/",
        protocol: "http:",
        hostname: "192.168.1.55",
      },
    });

    expect(getApiBase()).toBe("http://192.168.1.55:9002");
  });
});
