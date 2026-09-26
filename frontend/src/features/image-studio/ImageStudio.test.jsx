import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ImageStudio, applyCharacterFoundation, characterDraftBrief, nextIncompleteInterviewStep, templateCharacterPath, templateCreationType } from "./ImageStudio";

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

  it("renders the new-character creative brief with resident text model status", () => {
    const template = {
      template_id: "template.avatar_body_depth_reference_transparent.realvisxl.v1",
      template_name: "Simple Avatar Generation",
      metadata: { domain: "avatar", edit_intent: "avatar_body_depth_reference" },
    };
    const markup = renderToStaticMarkup(
      <ImageStudio
        templates={[template]}
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialSelectedTemplateId={template.template_id}
        initialCreativeSetupOpen
        runtimeStatus={{
          services: {
            local_llm: {
              model_residency: { model_state: "loaded", loaded_model: "qwen3-8b-q4_k_m" },
            },
          },
        }}
      />
    );

    expect(markup).toContain("Define the new character");
    expect(markup).toContain("Local text LLM loaded");
    expect(markup).toContain("Character name");
    expect(markup).toContain("Master prompt");
    expect(markup).toContain("Identity bootstrap required before generation");
  });

  it("offers a six-step character interview with optional local LLM guidance", () => {
    const template = {
      template_id: "template.avatar_body_depth_reference_transparent.realvisxl.v1",
      template_name: "Simple Avatar Generation",
      metadata: { domain: "avatar", edit_intent: "avatar_body_depth_reference" },
    };
    const markup = renderToStaticMarkup(
      <ImageStudio
        templates={[template]}
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialSelectedTemplateId={template.template_id}
        initialCreativeSetupOpen
        initialInterviewOpen
        runtimeStatus={{ services: { local_llm: { model_residency: { model_state: "loaded" } } } }}
      />
    );

    expect(markup).toContain("Character interview");
    expect(markup).toContain("Name &amp; concept");
    expect(markup).toContain("Face &amp; features");
    expect(markup).toContain("Body &amp; proportions");
    expect(markup).toContain("Initial clothing");
    expect(markup).toContain("Initial pose");
    expect(markup).toContain("Expression");
    expect(markup).toContain("Let the local LLM ask guiding questions");
    expect(markup).toContain("Check answer with LLM");
    expect(markup).toContain("Continue anyway");
    expect(markup).toContain("1 of 6");
    expect(markup).toContain("Gender");
    expect(markup).toContain("Non-binary");
    expect(markup).toContain("Semi-realistic");
    expect(markup).toContain("Adult (18+)");
    expect(markup).toContain("NSFW — adults only");
  });

  it("provides rich selectable face and feature options", () => {
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialCreativeSetupOpen
        initialInterviewOpen
        initialInterviewStep={1}
      />
    );

    expect(markup).toContain("Face &amp; features");
    expect(markup).toContain("Face shape");
    expect(markup).toContain("Eye color");
    expect(markup).toContain("Hair texture");
    expect(markup).toContain("Distinctive features");
    expect(markup).toContain("facial cybernetics");
    expect(markup).toContain("Combined face description");
    expect(markup).toContain("image-studio-option-visual");
    expect(markup).toContain("background:#4f83bd");
    expect(markup).toContain("/image-studio/guides/face-shape-options-v2.webp");
    expect(markup).toContain("/image-studio/guides/eye-shape-options-v2.webp");
    expect(markup).toContain("/image-studio/guides/nose-shape-options-v2.webp");
    expect(markup).toContain("/image-studio/guides/lip-shape-options-v2.webp");
    expect(markup).toContain("image-studio-feature-option-image");
    expect(markup).toContain("Rendered preview");
    expect(markup).toContain("Generate face preview");
  });

  it("forces SFW when an adult character is changed to an under-18 age group", () => {
    expect(applyCharacterFoundation(
      { age_group: "adult (18+)", content_rating: "NSFW adult content" },
      "age_group",
      "teen (13-17)",
    )).toEqual({ age_group: "teen (13-17)", content_rating: "SFW" });
  });

  it("lists saved incomplete characters on step 3 with a continue action", () => {
    const brief = { name: "Nova", concept: "space pilot", appearance: "" };
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        characterProfiles={[{
          profile_id: "Nova",
          name: "Nova",
          description: "space pilot",
          completion_status: "incomplete",
          initial_data: JSON.stringify({ source: "image_studio", character_brief: brief }),
        }]}
      />
    );

    expect(markup).toContain("Incomplete characters");
    expect(markup).toContain("Continue character");
    expect(characterDraftBrief({ initial_data: JSON.stringify({ source: "image_studio", character_brief: brief }) })).toEqual(brief);
    expect(nextIncompleteInterviewStep(brief)).toBe(1);
  });
});
