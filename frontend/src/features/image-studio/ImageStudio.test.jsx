import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ImageStudio, applyCharacterFoundation, buildBodyPreviewPrompt, buildFacePreviewNegativePrompt, buildFacePreviewPrompt, characterDraftBodyFeatureCatalog, characterDraftBrief, characterDraftFeatureCatalog, composeFaceDescription, faceFeaturePromptDescription, inferFaceFeatureSelections, latestSavedFacePreview, nextIncompleteInterviewStep, templateCharacterPath, templateCreationType } from "./ImageStudio";

describe("ImageStudio", () => {
  it("builds a structured face identity reference prompt", () => {
    const prompt = buildFacePreviewPrompt({
      name: "Nova",
      age_group: "adult (18+)",
      gender_identity: "female",
      concept: "space pilot",
      appearance: "oval face; green eyes; short black hair",
      expression: "quiet confidence",
      visual_style: "semi-realistic",
    }, { "face shape": ["round"] }, "preserve the eyes; soften the eyebrows");
    expect(prompt).toContain("EXACTLY ONE PERSON. EXACTLY ONE FACE.");
    expect(prompt).toContain("PRIMARY FACE SHAPE REQUIREMENT");
    expect(prompt).toContain("unmistakably round");
    expect(prompt).toContain("LLM REFINEMENT LAYER: preserve the eyes; soften the eyebrows");
    expect(prompt).toContain("Character identity reference portrait of Nova, adult (18+) female.");
    expect(prompt).toContain("Character concept: space pilot.");
    expect(prompt).toContain("Face and hair: oval face; green eyes; short black hair.");
    expect(prompt).toContain("eyes looking directly at camera");
    expect(prompt).toContain("plain neutral-gray background");
    expect(prompt).not.toContain("Body and proportions");
  });

  it("makes selected hair color a primary requirement and rejects conflicting colors", () => {
    const prompt = buildFacePreviewPrompt(
      { name: "Hexe", appearance: "blonde wavy hair", visual_style: "realistic" },
      { "hair color": ["blonde"] },
    );
    const negative = buildFacePreviewNegativePrompt({ "hair color": ["blonde"] });

    expect(prompt).toContain("PRIMARY HAIR COLOR REQUIREMENT");
    expect(prompt).toContain("blonde hair with natural strand-level tonal variation:1.45");
    expect(prompt).toContain("including at the roots and in shadow");
    expect(negative).toContain("brunette");
    expect(negative).toContain("dark brown hair");
    expect(negative).toContain("black hair");
  });

  it("makes selected hair length a primary requirement and rejects conflicting lengths", () => {
    const prompt = buildFacePreviewPrompt(
      { name: "Hexe", appearance: "shoulder-length blonde hair", visual_style: "realistic" },
      { "hair length": ["shoulder-length"] },
    );
    const negative = buildFacePreviewNegativePrompt({ "hair length": ["shoulder-length"] });

    expect(prompt).toContain("PRIMARY HAIR LENGTH REQUIREMENT");
    expect(prompt).toContain("shoulder-length hair ending at the shoulders:1.40");
    expect(prompt).toContain("full hair silhouette and its endpoints visible in frame");
    expect(negative).toContain("short hair");
    expect(negative).toContain("chin-length hair");
    expect(negative).toContain("hair extending below the shoulders");
  });

  it("drops a truncated JSON refinement instead of adding it to the prompt", () => {
    const prompt = buildFacePreviewPrompt(
      { name: "Hexe", appearance: "blonde hair" },
      { "hair color": ["blonde"] },
      '{"prompt":"truncated refinement',
    );

    expect(prompt).not.toContain("LLM REFINEMENT LAYER");
    expect(prompt).not.toContain("truncated refinement");
  });

  it("adds strong multi-face and conflicting-shape negatives", () => {
    const negative = buildFacePreviewNegativePrompt({ "face shape": ["round"] });
    expect(negative).toContain("multiple faces");
    expect(negative).toContain("portrait collage");
    expect(negative).toContain("side-by-side portraits");
    expect(negative).toContain("angular jaw");
    expect(negative).toContain("pointed chin");
  });

  it("migrates descriptive legacy drafts back into structured selections", () => {
    const appearance = composeFaceDescription({ "face shape": ["round"], "eye shape": ["almond"] }, "");
    expect(inferFaceFeatureSelections(appearance)).toMatchObject({
      "face shape": ["round"],
      "eye shape": ["almond"],
    });
  });

  it("expands eye-shape selections into structural prompt language", () => {
    expect(composeFaceDescription({ "eye shape": ["almond"] }, "")).toContain(
      "almond-shaped eyes, gently tapered inner and outer corners, softly curved eyelids, balanced proportions, iris partially covered by the upper and lower lids"
    );
    expect(composeFaceDescription({ "eye shape": ["wide-set"] }, "")).toContain(
      "greater than one eye-width of space between the inner corners"
    );
  });

  it("expands every face-feature group into descriptive prompt language", () => {
    const examples = {
      "apparent age": "mature",
      "face shape": "heart-shaped",
      "skin tone": "olive",
      complexion: "freckled",
      "eye color": "hazel",
      eyebrows: "softly arched",
      nose: "aquiline",
      lips: "defined Cupid's bow",
      "hair texture": "coily",
      "hair length": "shoulder-length",
      "hair color": "auburn",
      hairstyle: "cornrows",
      "distinctive features": "facial scar",
      "facial hair": "short beard",
    };
    Object.entries(examples).forEach(([group, value]) => {
      const description = faceFeaturePromptDescription(group, value);
      expect(description).not.toBe(value);
      expect(description.length).toBeGreaterThan(value.length + 10);
    });
  });
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
    expect(markup).toContain("Save progress");
    expect(markup).toContain("image-studio-face-preview-status");
    expect(markup).toContain("Status");
    expect(markup).toContain("Runtime");
    expect(markup).toContain("Model");
    expect(markup).toContain("Refine this result with the local LLM");
    expect(markup).toContain("Refine &amp; regenerate same seed");
  });

  it("shows matched live generation details instead of the stale submitted state", () => {
    const template = {
      template_id: "template.avatar_head_face_preview.realvisxl.v1",
      template_name: "Avatar Head Face Preview",
      metadata: { domain: "avatar_profile", edit_intent: "avatar_head_face_preview" },
      model_requirements: { checkpoint: "RealVisXL_V5.0_fp16.safetensors" },
    };
    const markup = renderToStaticMarkup(
      <ImageStudio
        templates={[template]}
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialSelectedTemplateId={template.template_id}
        initialCreativeSetupOpen
        initialInterviewOpen
        initialInterviewStep={1}
        facePreviewTracking
        facePreviewResult={{ preview: { status: "submitted", prompt_id: "prompt-live", seed_text: "123456" } }}
        runtimeStatus={{ services: { comfyui_gpu: { state: "running", vram_mib: 5030, model_residency_status: { model_state: "loaded" } } } }}
        generationActivity={{
          generation_status: { session: { running_count: 1, pending_count: 0 }, progress: { prompt_id: "prompt-live", value: 2, max: 4, percent: 50 } },
          latest_job: {
            prompt_id: "prompt-live",
            status: "running",
            progress_detail: { status: "running", phase: "sampling", label: "Sampling", message: "Rendering sampler steps.", node_class: "KSampler", node_id: "6", value: 2, max: 4, percent: 50, elapsed_seconds: 12.4 },
          },
        }}
      />
    );

    expect(markup).toContain("Rendering image — step 2 of 4");
    expect(markup).toContain("Rendering sampler steps.");
    expect(markup).toContain("50.0% (2/4)");
    expect(markup).toContain("KSampler (#6)");
    expect(markup).toContain("12.4 s");
    expect(markup).toContain("RealVisXL_V5.0_fp16.safetensors");
    expect(markup).not.toContain("<strong>submitted</strong>");
  });

  it("loads the newest completed saved face preview", () => {
    const characterProfiles = [{
      profile_id: "Nova",
      prompt_workspaces: {
        head_face: {
          preview_history: [
            { preview_id: "older", status: "completed", url: "/older.png", imported_at: "2026-09-25T18:00:00Z" },
            { preview_id: "newer", status: "completed", url: "/newer.png", imported_at: "2026-09-25T19:00:00Z" },
          ],
        },
      },
    }];
    const preview = latestSavedFacePreview(characterProfiles);
    const markup = renderToStaticMarkup(
      <ImageStudio
        apiBase="http://node.test"
        characterProfiles={characterProfiles}
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialCreativeSetupOpen
        initialInterviewOpen
        initialInterviewStep={1}
      />
    );

    expect(preview.preview_id).toBe("newer");
    expect(markup).toContain("http://node.test/newer.png");
    expect(markup).not.toContain("http://node.test/older.png");
  });

  it("shows structured body characteristics and one saved body seed", () => {
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialCreativeSetupOpen
        initialInterviewOpen
        initialInterviewStep={2}
        bodyPreviewResult={{ preview: { seed: 424242, status: "completed", url: "/body.png" } }}
      />
    );

    expect(markup).toContain("Define the body foundation");
    expect(markup).toContain("Overall build");
    expect(markup).toContain("Limb proportions");
    expect(markup).toContain("Neck-down full-body foundation");
    expect(markup).toContain("424242");
    expect(markup).toContain("Generate again with saved seed");
    const prompt = buildBodyPreviewPrompt({ age_group: "adult (18+)", gender_identity: "female", visual_style: "realistic", body: "tall; athletic" });
    expect(prompt).toContain("Strict neck-down crop");
    expect(prompt).toContain("Photorealistic natural human body");
    expect(prompt).toContain("top image boundary at the base of the neck");
    expect(prompt).toContain("entire head remains outside the canvas");
    expect(prompt).not.toContain("bodysuit");
  });

  it("shows a closable live generation progress dialog", () => {
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialCreativeSetupOpen
        initialGenerationProgressOpen
        initialGenerationKind="body"
        bodyPreviewTracking
        generationActivity={{
          generation_status: { progress: { percent: 50, value: 2, max: 4 }, session: { running_count: 1, pending_count: 0 } },
          latest_job: { status: "running", prompt_id: "prompt-123", progress_detail: { status: "sampling", percent: 50, value: 2, max: 4, label: "Sampling" } },
        }}
      />
    );

    expect(markup).toContain("Body reference progress");
    expect(markup).toContain("Live status from the Visual Runtime");
    expect(markup).toContain("50.0%");
    expect(markup).toContain("2 of 4");
    expect(markup).toContain("Close");
  });

  it("adds a rendering prompt that matches the initial character visual style", () => {
    const semiRealistic = buildBodyPreviewPrompt({ age_group: "adult (18+)", gender_identity: "female", visual_style: "semi-realistic", body: "curvy" });
    const anime = buildBodyPreviewPrompt({ age_group: "adult (18+)", gender_identity: "female", visual_style: "anime", body: "curvy" });

    expect(semiRealistic).toContain("Polished semi-realistic human character body");
    expect(anime).toContain("Clean anime character body design");
    expect(anime).toContain("BODY PROPORTIONS: curvy");
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
    expect(characterDraftFeatureCatalog({ initial_data: JSON.stringify({ source: "image_studio", face_feature_catalog: { selections: { "face shape": ["round"] } } }) })).toEqual({ selections: { "face shape": ["round"] } });
    expect(characterDraftBodyFeatureCatalog({ initial_data: JSON.stringify({ source: "image_studio", body_feature_catalog: { selections: { build: ["athletic"] }, custom_details: "long legs" } }) })).toEqual({ selections: { build: ["athletic"] }, custom_details: "long legs" });
    expect(nextIncompleteInterviewStep(brief)).toBe(1);
  });
});
