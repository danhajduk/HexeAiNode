import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ImageStudio, templateCreationType } from "./ImageStudio";

describe("ImageStudio", () => {
  it("starts with the three creation types", () => {
    const markup = renderToStaticMarkup(<ImageStudio />);

    expect(markup).toContain("What are you creating?");
    expect(markup).toContain("Character");
    expect(markup).toContain("Location");
    expect(markup).toContain("Scene");
    expect(markup).toContain("Legacy Generator");
  });

  it("classifies existing avatar templates as character workflows", () => {
    expect(templateCreationType({ metadata: { domain: "avatar", edit_intent: "avatar_head_face_preview" } })).toBe("character");
    expect(templateCreationType({ metadata: { domain: "environment", edit_intent: "exterior_location" } })).toBe("location");
    expect(templateCreationType({ metadata: { domain: "scene", edit_intent: "cinematic_composition" } })).toBe("scene");
  });
});
