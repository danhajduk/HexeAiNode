import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ImageStudio, templateCharacterPath, templateCreationType } from "./ImageStudio";

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

  it("asks for the character goal before showing templates", () => {
    const markup = renderToStaticMarkup(<ImageStudio initialCreationType="character" />);

    expect(markup).toContain("What would you like to do with the character?");
    expect(markup).toContain("Create New Character");
    expect(markup).toContain("Use Existing Character");
    expect(markup).toContain("Edit Character Image");
    expect(markup).toContain("Character goal");
  });

  it("classifies character workflows by goal", () => {
    expect(templateCharacterPath({ template_name: "Simple Avatar Generation", metadata: { edit_intent: "avatar_body_depth_reference" } })).toBe("create_new");
    expect(templateCharacterPath({ template_name: "Avatar Head LoRA Pose Control", metadata: { edit_intent: "avatar_head_lora_pose_dataset" } })).toBe("use_existing");
    expect(templateCharacterPath({ template_name: "Avatar Clothing Inpaint", metadata: { input_mode: "image" } })).toBe("edit_image");
  });
});
