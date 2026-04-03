import { describe, expect, it } from "vitest";

import { resolveUiMode, resolveUiRouteIntent } from "./uiModeResolver";
import {
  buildOperationalRoute,
  buildSetupRoute,
  isProviderSetupRoute,
  isSetupRoute,
  resolveDefaultRouteHashForMode,
  resolveOperationalSection,
  shouldArmSetupCompletionRedirect,
  shouldAutoRedirectCompletedSetup,
} from "./uiRoutes";

describe("resolveUiRouteIntent", () => {
  it("detects setup provider route", () => {
    expect(resolveUiRouteIntent("#/providers/openai")).toBe("provider_openai");
    expect(resolveUiRouteIntent("#/setup/provider/openai")).toBe("provider_openai");
  });

  it("detects diagnostics route", () => {
    expect(resolveUiRouteIntent("#/dashboard/diagnostics")).toBe("diagnostics");
  });
});

describe("resolveUiMode", () => {
  it("maps unconfigured to identity mode", () => {
    expect(resolveUiMode({ lifecycleState: "unconfigured", routeHash: "#/" })).toMatchObject({
      mode: "identity",
      reason: "lifecycle_unconfigured",
    });
  });

  it("maps capability setup pending to setup mode", () => {
    expect(resolveUiMode({ lifecycleState: "capability_setup_pending", routeHash: "#/" })).toMatchObject({
      mode: "setup",
      reason: "lifecycle_setup",
    });
  });

  it("keeps degraded state in operational mode", () => {
    expect(resolveUiMode({ lifecycleState: "degraded", routeHash: "#/" })).toMatchObject({
      mode: "operational",
      diagnosticsOpen: false,
      providerSetupOpen: false,
    });
  });

  it("opens diagnostics inside operational mode", () => {
    expect(resolveUiMode({ lifecycleState: "operational", routeHash: "#/dashboard/diagnostics" })).toMatchObject({
      mode: "operational",
      diagnosticsOpen: true,
      routeIntent: "diagnostics",
    });
  });

  it("allows manual setup override from operational state", () => {
    expect(resolveUiMode({ lifecycleState: "operational", routeHash: "#/setup" })).toMatchObject({
      mode: "setup",
      routeIntent: "setup",
      reason: "manual_setup_override_from_operational",
    });
  });

  it("supports direct provider setup route while still in setup states", () => {
    expect(resolveUiMode({ lifecycleState: "trusted", routeHash: "#/providers/openai" })).toMatchObject({
      mode: "setup",
      providerSetupOpen: true,
      reason: "manual_provider_setup_route",
    });
  });

  it("supports direct provider setup override from operational state", () => {
    expect(resolveUiMode({ lifecycleState: "degraded", routeHash: "#/providers/openai" })).toMatchObject({
      mode: "setup",
      providerSetupOpen: true,
      reason: "manual_provider_setup_override_from_operational",
    });
  });
});

describe("uiRoutes", () => {
  it("builds canonical setup and dashboard routes", () => {
    expect(buildSetupRoute()).toBe("#/setup");
    expect(buildSetupRoute("openai")).toBe("#/setup/provider/openai");
    expect(buildOperationalRoute()).toBe("#/dashboard");
    expect(buildOperationalRoute("diagnostics")).toBe("#/dashboard/diagnostics");
  });

  it("resolves operational sections and setup helpers", () => {
    expect(resolveOperationalSection("#/dashboard/runtime")).toBe("runtime");
    expect(resolveOperationalSection("#/dashboard/clients")).toBe("clients");
    expect(resolveOperationalSection("#/dashboard")).toBe("overview");
    expect(isSetupRoute("#/setup/provider/openai")).toBe(true);
    expect(isProviderSetupRoute("#/setup/provider/openai")).toBe(true);
  });

  it("defaults operational lifecycle roots to dashboard", () => {
    expect(resolveDefaultRouteHashForMode("operational", "#/")).toBe("#/dashboard");
    expect(resolveDefaultRouteHashForMode("operational", "")).toBe("#/dashboard");
    expect(resolveDefaultRouteHashForMode("operational", "#/dashboard/runtime")).toBeNull();
  });

  it("auto-redirects to dashboard only when setup completion was armed", () => {
    expect(shouldArmSetupCompletionRedirect("capability_setup_pending", "setup")).toBe(true);
    expect(
      shouldAutoRedirectCompletedSetup({
        lifecycleState: "operational",
        routeIntent: "setup",
        redirectArmed: true,
      })
    ).toBe(true);
    expect(
      shouldAutoRedirectCompletedSetup({
        lifecycleState: "operational",
        routeIntent: "setup",
        redirectArmed: false,
      })
    ).toBe(false);
  });
});
