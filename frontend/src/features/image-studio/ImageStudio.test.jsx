import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ImageStudio, applyCharacterFoundation, buildBodyPreviewPayload, buildBodyPreviewPrompt, buildFacePreviewNegativePrompt, buildFacePreviewPrompt, characterDraftBodyFeatureCatalog, characterDraftBrief, characterDraftFeatureCatalog, composeBodyDescription, composeFaceDescription, faceFeaturePromptDescription, inferFaceFeatureSelections, isEscapeKey, latestSavedFacePreview, magnitudeLabel, nextBodyFeatureSelections, nextIncompleteInterviewStep, previewArtifactReady, templateCharacterPath, templateCreationType } from "./ImageStudio";

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
    expect(markup).toContain("Feminine / masculine traits");
    expect(markup).toContain("pronounced feminine");
    expect(markup).toContain("androgynous");
    expect(markup).toContain("pronounced masculine");
    expect(markup).toContain("Limb proportions");
    expect(markup).toContain("Visible muscle volume and definition");
    expect(markup).toContain("Body hair");
    expect(markup).toContain("Butt fullness");
    expect(markup).toContain("Butt shape");
    expect(markup).not.toContain("Body magnitudes");
    expect(markup).toContain("Shoulder width");
    expect(markup).toContain("Torso length");
    expect(markup).toContain("Miscellaneous");
    expect(markup).toContain("no tattoos");
    expect(markup).toContain("image-studio-body-dropdown");
    expect(markup).toContain("Automatic / none selected");
    expect(markup).not.toContain("Breast size");
    expect(markup).not.toContain("Pubic hair");
    expect(markup).toContain("Neck-down full-body foundation");
    expect(markup).toContain("424242");
    expect(markup).toContain("Generate again with saved seed");
    const prompt = buildBodyPreviewPrompt({ age_group: "adult (18+)", gender_identity: "female", visual_style: "realistic", body: "tall; athletic" });
    expect(prompt).toContain("exactly one living human person");
    expect(prompt).toContain("real living human person");
    expect(prompt).toContain("natural camera crop at the base of the neck");
    expect(prompt).toContain("head naturally outside the canvas");
    expect(prompt).toContain("skin with pores");
    expect(prompt).toContain("relaxed anatomical A-pose");
    expect(prompt).toContain("feet hip-width apart");
    expect(prompt).toContain("palms inward");
    expect(prompt).not.toContain("bodysuit");
    expect(markup).toContain("Lock body seed");
    expect(markup).toContain("Leave unlocked to try a fresh composition");
  });

  it("shows adult intimate body controls only for an adult NSFW character", () => {
    const femaleMarkup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialCreativeSetupOpen
        initialInterviewOpen
        initialInterviewStep={2}
        initialCharacterBrief={{ age_group: "adult (18+)", content_rating: "NSFW adult content", gender_identity: "female" }}
      />
    );
    const maleMarkup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialCreativeSetupOpen
        initialInterviewOpen
        initialInterviewStep={2}
        initialCharacterBrief={{ age_group: "adult (18+)", content_rating: "NSFW adult content", gender_identity: "male" }}
      />
    );
    const sfwMarkup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialCreativeSetupOpen
        initialInterviewOpen
        initialInterviewStep={2}
        initialCharacterBrief={{ age_group: "adult (18+)", content_rating: "SFW", gender_identity: "female" }}
      />
    );

    expect(femaleMarkup).toContain("Breast shape &amp; size");
    expect(femaleMarkup).toContain("Size magnitude");
    expect(femaleMarkup).toContain("teardrop");
    expect(femaleMarkup.match(/Breast shape &amp; size/g)).toHaveLength(1);
    expect(femaleMarkup).toContain("Automatic");
    expect(femaleMarkup).toContain("Pubic hair");
    expect(femaleMarkup).toContain("Pubic hair color");
    expect(femaleMarkup).toContain("inherit from head hair");
    expect(femaleMarkup).toContain("External genital anatomy — vulva");
    expect(femaleMarkup).toContain("External genital anatomy — penis");
    expect(femaleMarkup).toContain("mutually exclusive");
    expect(maleMarkup).toContain("Breast shape &amp; size");
    expect(maleMarkup).toContain("External genital anatomy — penis");
    expect(maleMarkup).toContain("External genital anatomy — vulva");
    expect(sfwMarkup).not.toContain("Breast size");
    expect(sfwMarkup).not.toContain("Pubic hair");
    expect(sfwMarkup).not.toContain("External genital anatomy");
  });

  it("keeps body descriptions as concise frontend selections", () => {
    expect(composeBodyDescription({ body_traits: ["pronounced feminine"], build: ["curvy"] }))
      .toContain("feminine / masculine traits: pronounced feminine");
    expect(composeBodyDescription({ body_traits: ["masculine"], build: ["athletic"] }))
      .toContain("overall build: athletic");
    expect(composeBodyDescription({ height: ["tall"], build: ["curvy"], musculature: ["lightly toned"] }))
      .toContain("height: tall");
    expect(composeBodyDescription({ height: ["tall"], build: ["curvy"], musculature: ["lightly toned"] }))
      .toContain("musculature: lightly toned");
    expect(composeBodyDescription({ body_hair: ["natural"], breast_size: ["medium"], breast_shape: ["teardrop"], butt_shape: ["round"] }))
      .toContain("breast shape: teardrop");
    expect(composeBodyDescription({ body_hair: ["natural"], breast_size: ["medium"], breast_shape: ["teardrop"], butt_shape: ["round"] }))
      .toContain("butt shape: round");
  });

  it("inherits pubic hair color from face hair unless explicitly overridden", () => {
    const inherited = composeBodyDescription(
      { pubic_hair: ["natural"] },
      "",
      { "hair color": ["auburn"] },
    );
    const overridden = composeBodyDescription(
      { pubic_hair: ["natural"], pubic_hair_color: ["black"] },
      "",
      { "hair color": ["auburn"] },
    );

    expect(inherited).toContain("pubic hair color: auburn (inherited from head hair)");
    expect(overridden).toContain("pubic hair color: black");
    expect(overridden).not.toContain("(inherited from head hair)");
    expect(composeBodyDescription({ pubic_hair: ["none"] }, "", { "hair color": ["auburn"] }))
      .not.toContain("pubic hair color:");
  });

  it("unselects a body option when it is clicked again", () => {
    expect(nextBodyFeatureSelections({ build: ["curvy"] }, "build", "curvy")).toEqual({ build: [] });
    expect(nextBodyFeatureSelections({ build: ["curvy"] }, "build", "athletic")).toEqual({ build: ["athletic"] });
  });

  it("allows breast traits with penile anatomy but prevents dual genital anatomy", () => {
    const withPenis = nextBodyFeatureSelections(
      { breast_size: ["medium"], vulva_description: ["natural"] },
      "penis_description",
      "average",
    );
    expect(withPenis).toEqual({
      breast_size: ["medium"],
      vulva_description: [],
      penis_description: ["average"],
    });

    const withVulva = nextBodyFeatureSelections(withPenis, "vulva_description", "natural");
    expect(withVulva.breast_size).toEqual(["medium"]);
    expect(withVulva.vulva_description).toEqual(["natural"]);
    expect(withVulva.penis_description).toEqual([]);
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
        bodyPreviewResult={{ preview: { status: "submitted", prompt_id: "prompt-123" } }}
        onRefreshGeneration={() => Promise.resolve()}
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
    expect(markup).toContain("Refresh Preview");
    expect(markup).toContain("Redo");
    expect(markup).toContain("Keep seed for Redo");
    expect(markup).toContain("Close");
    expect(markup).toContain("Generated preview");
    expect(markup).toContain("Job details");
    expect(markup).toContain("Submitted");
    expect(markup).toContain("Seed");
    expect(markup).toContain("Breast size");
    expect(markup).toContain("Breast shape");
    expect(markup).toContain("Magnitudes for Redo");
    expect(markup).toContain("Torso length");
    expect(markup).toContain("Profile");
    expect(markup).toContain("Output");
  });

  it("recognizes Escape and waits for an imported preview artifact", () => {
    expect(isEscapeKey({ key: "Escape" })).toBe(true);
    expect(isEscapeKey({ key: "Enter" })).toBe(false);
    expect(previewArtifactReady({ status: "completed", url: "/preview.png", placeholder: false })).toBe(false);
    expect(previewArtifactReady({ status: "completed", url: "/preview.svg", imported_at: "now", placeholder: true })).toBe(false);
    expect(previewArtifactReady({ status: "completed", url: "/preview.png", imported_at: "now", placeholder: false })).toBe(true);
  });

  it("shows importing instead of done until the preview file is available", () => {
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialCreationType="character"
        initialCharacterPath="create_new"
        initialGenerationProgressOpen
        initialGenerationKind="body"
        bodyPreviewTracking
        bodyPreviewResult={{ preview: { status: "submitted", prompt_id: "prompt-123" } }}
        generationActivity={{ latest_job: { status: "completed", prompt_id: "prompt-123", progress_detail: { status: "completed", percent: 100 } } }}
      />
    );

    expect(markup).toContain("importing preview");
    expect(markup).toContain("still being saved and imported");
  });

  it("ignores status and progress from a different latest job", () => {
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialGenerationProgressOpen
        initialGenerationKind="body"
        bodyPreviewTracking
        bodyPreviewResult={{ preview: { status: "submitted", prompt_id: "current-prompt" } }}
        generationActivity={{
          generation_status: {
            progress: { prompt_id: "old-prompt", percent: 100, value: 28, max: 28 },
            session: { running_count: 0, pending_count: 0 },
          },
          latest_job: {
            status: "failed",
            prompt_id: "old-prompt",
            progress_detail: { prompt_id: "old-prompt", status: "failed", percent: 100, message: "Old job failed." },
          },
        }}
      />
    );

    expect(markup).toContain("current-prompt");
    expect(markup).toContain("submitted");
    expect(markup).not.toContain("old-prompt");
    expect(markup).not.toContain("Old job failed.");
    expect(markup).not.toContain("100.0%");
  });

  it("treats an imported preview as complete when the matching global job is stale", () => {
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialGenerationProgressOpen
        initialGenerationKind="body"
        bodyPreviewResult={{ preview: { status: "completed", prompt_id: "current-prompt", url: "/current.png", imported_at: "now", placeholder: false } }}
        generationActivity={{
          latest_job: {
            status: "submitted",
            prompt_id: "current-prompt",
            progress_detail: { prompt_id: "current-prompt", status: "submitted", percent: 100 },
          },
        }}
      />
    );

    expect(markup).toContain("<strong>completed</strong>");
    expect(markup).toContain("file available");
    expect(markup).not.toContain("waiting for render");
  });

  it("adds a rendering prompt that matches the initial character visual style", () => {
    const semiRealistic = buildBodyPreviewPrompt({ age_group: "adult (18+)", gender_identity: "female", visual_style: "semi-realistic", body: "curvy" });
    const anime = buildBodyPreviewPrompt({ age_group: "adult (18+)", gender_identity: "female", visual_style: "anime", body: "curvy" });

    expect(semiRealistic).toContain("Polished semi-realistic human character body");
    expect(anime).toContain("Clean anime character body design");
    expect(anime).toContain("BODY PROPORTIONS: curvy");
  });

  it("inherits the selected face skin tone in the body prompt", () => {
    const prompt = buildBodyPreviewPrompt(
      { age_group: "adult (18+)", gender_identity: "female", visual_style: "realistic", body: "athletic" },
      { "skin tone": ["olive"] },
    );

    expect(prompt).toContain("INHERITED FACE SKIN TONE: olive natural skin tone with realistic tonal variation");
    expect(prompt).toContain("across the neck and entire body");
  });

  it("submits structured body selections for backend prompt compilation", () => {
    expect(buildBodyPreviewPayload(
      { age_group: "adult (18+)", gender_identity: "female", visual_style: "realistic", body: "ignored summary" },
      { build: ["athletic"], pubic_hair: ["natural"] },
      { "skin tone": ["olive"], "hair color": ["auburn"] },
      "long fingers",
      { breast_size: 0.72 },
    )).toEqual({
      body_feature_selections: { build: ["athletic"], pubic_hair: ["natural"] },
      body_feature_magnitudes: { breast_size: 0.72 },
      face_feature_selections: { "skin tone": ["olive"], "hair color": ["auburn"] },
      body_custom_details: "long fingers",
      character_context: { age_group: "adult (18+)", gender_identity: "female", visual_style: "realistic", content_rating: undefined },
    });
    expect(magnitudeLabel(0)).toBe("Very small");
    expect(magnitudeLabel(0.72)).toBe("Large");
    expect(magnitudeLabel(1)).toBe("Very large");
  });

  it("does not describe pubic hair color when pubic hair is none", () => {
    expect(composeBodyDescription(
      { pubic_hair: ["none"], pubic_hair_color: ["black"] }, "", { "hair color": ["auburn"] }
    )).not.toContain("pubic hair color");
  });

  it("does not show a previous completed job while a new submission is being saved", () => {
    const markup = renderToStaticMarkup(
      <ImageStudio
        initialGenerationProgressOpen
        initialGenerationKind="body"
        initialGenerationSubmissionStage="saving profile"
        bodyPreviewResult={{ preview: { status: "completed", prompt_id: "old-prompt", seed: 123, url: "/old.png", imported_at: "now" } }}
        generationActivity={{ generation_status: { progress: { percent: 100 } }, latest_job: { status: "completed", prompt_id: "old-prompt", progress_detail: { status: "completed", percent: 100 } } }}
      />
    );
    expect(markup).toContain("saving profile");
    expect(markup).toContain("Saving the current character selections before submission.");
    expect(markup).not.toContain("100.0%");
    expect(markup).not.toContain("old-prompt");
    expect(markup).not.toContain("/old.png");
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
