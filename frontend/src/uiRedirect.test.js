import { describe, expect, it, vi } from "vitest";

import { buildCoreProxyRedirect, isCoreProxiedUi, redirectDirectUiToCore } from "./uiRedirect";

describe("direct UI redirect", () => {
  it("recognizes the Core proxy mount", () => {
    expect(isCoreProxiedUi("/nodes/proxy/ui/node-123/")).toBe(true);
    expect(isCoreProxiedUi("/")).toBe(false);
  });

  it("builds the registered Core proxy dashboard URL", () => {
    expect(
      buildCoreProxyRedirect(
        { proxy_ui_url: "http://10.0.0.100:9001/nodes/proxy/ui/node-123/" },
        { hash: "" },
      ),
    ).toBe("http://10.0.0.100:9001/nodes/proxy/ui/node-123/#/dashboard");
  });

  it("redirects direct access and preserves an explicit route", async () => {
    const locationObject = { pathname: "/", hash: "#/dashboard/runtime", replace: vi.fn() };
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ proxy_ui_url: "http://core:9001/nodes/proxy/ui/node-123/" }),
    });

    expect(await redirectDirectUiToCore(locationObject, fetchImpl)).toBe(true);
    expect(locationObject.replace).toHaveBeenCalledWith(
      "http://core:9001/nodes/proxy/ui/node-123/#/dashboard/runtime",
    );
  });

  it("does not fetch or redirect when already proxied", async () => {
    const locationObject = {
      pathname: "/nodes/proxy/ui/node-123/",
      hash: "#/dashboard",
      replace: vi.fn(),
    };
    const fetchImpl = vi.fn();

    expect(await redirectDirectUiToCore(locationObject, fetchImpl)).toBe(false);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(locationObject.replace).not.toHaveBeenCalled();
  });
});
