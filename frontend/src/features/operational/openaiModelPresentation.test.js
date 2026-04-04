import { describe, expect, it } from "vitest";
import {
  formatModelFamily,
  getCapabilityBadges,
  getModelPricingRows,
  groupOpenAiCatalogModels,
} from "./openaiModelPresentation";

describe("openai model presentation", () => {
  it("formats capability families and pricing rows for display", () => {
    expect(formatModelFamily("image_generation")).toBe("Image Generation");
    expect(
      getModelPricingRows({
        pricing_basis: "per_1m_tokens",
        input_per_1m_tokens: 3,
        output_per_1m_tokens: 12,
        cached_input_per_1m_tokens: 0.3,
      })
    ).toEqual([
      ["Input", "$3.00/1M"],
      ["Output", "$12.00/1M"],
      ["Cached Input", "$0.300/1M"],
    ]);
  });

  it("extracts unique capability badges from a capability entry", () => {
    expect(
      getCapabilityBadges({
        reasoning: true,
        structured_output: true,
        feature_flags: {
          chat: true,
          tool_calling: true,
          chat_duplicate: true,
        },
      })
    ).toEqual(["Chat", "Reasoning", "Structured", "Tools"]);
  });

  it("groups and sorts catalog models by family and freshness", () => {
    const groups = groupOpenAiCatalogModels(
      [
        { model_id: "gpt-4.1", family: "llm", discovered_at: "2026-04-01T00:00:00Z" },
        { model_id: "gpt-4.1-mini", family: "llm", discovered_at: "2026-04-02T00:00:00Z" },
        { model_id: "gpt-image-1", family: "image_generation", discovered_at: "2026-04-03T00:00:00Z" },
      ],
      { "gpt-4.1": 10, "gpt-4.1-mini": 20, "gpt-image-1": 30 }
    );

    expect(groups.map((group) => group.family)).toEqual(["llm", "image_generation"]);
    expect(groups[0].models.map((model) => model.model_id)).toEqual(["gpt-4.1-mini", "gpt-4.1"]);
  });
});
