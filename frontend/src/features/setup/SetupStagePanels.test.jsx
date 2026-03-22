import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { SetupCapabilityDeclarationPanel } from "./SetupStagePanels";

describe("SetupCapabilityDeclarationPanel", () => {
  it("renders readable blocker guidance for capability declaration", () => {
    const markup = renderToStaticMarkup(
      <SetupCapabilityDeclarationPanel
        declarationAllowed={false}
        setupReadinessFlags={{
          trust_state_valid: true,
          node_identity_valid: true,
          core_runtime_context_valid: true,
          openai_usable_models_ready: false,
        }}
        setupBlockingReasons={[
          "openai_enabled_models_required_before_declare",
          "openai_usable_models_required_before_declare",
        ]}
      />
    );

    expect(markup).toContain("Enable at least one OpenAI model before declaring capabilities.");
    expect(markup).toContain("At least one enabled OpenAI model must be usable before declaration can continue.");
  });
});
