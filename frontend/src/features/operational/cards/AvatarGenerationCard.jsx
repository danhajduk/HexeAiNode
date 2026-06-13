import { useEffect, useMemo, useRef, useState } from "react";

import { CardHeader, StatusBadge } from "../../../components/uiPrimitives";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file) {
      resolve("");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("file_read_failed"));
    reader.readAsDataURL(file);
  });
}

function profileImageUrl(apiBase, url) {
  const normalized = String(url || "").trim();
  if (!normalized) {
    return "";
  }
  return `${apiBase || ""}${normalized}`;
}

function profileName(profile) {
  return profile?.name || profile?.profile_id || "avatar";
}

function safeFilenameComponent(value) {
  const safe = String(value || "")
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  return safe.slice(0, 80) || "avatar";
}

function previewTimestamp(preview) {
  const parsed = Date.parse(String(preview?.created_at || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function headFacePreviewHistory(profile) {
  return asArray(promptWorkspace(profile, "head_face").preview_history)
    .slice()
    .sort((left, right) => previewTimestamp(right) - previewTimestamp(left))
    .slice(0, 9);
}

function workspacePreviewHistory(profile, section) {
  return asArray(promptWorkspace(profile, section).preview_history)
    .slice()
    .sort((left, right) => previewTimestamp(right) - previewTimestamp(left))
    .slice(0, 9);
}

function headFacePreviewOutput(preview, outputs, profile) {
  const profileUrl = String(preview?.url || "").trim();
  if (profileUrl) {
    const filename = String(preview?.filename || profileUrl.split("/").pop() || "preview.png");
    return { url: profileUrl, filename, relative_path: String(preview?.input_image || profileUrl) };
  }
  const seed = preview?.seed === null || preview?.seed === undefined ? "" : String(preview.seed).trim();
  if (!seed) {
    return null;
  }
  const safeName = safeFilenameComponent(profileName(profile));
  const section = String(preview?.section || "").trim();
  const templateId = String(preview?.template_id || "").trim();
  const outputFolder =
    section === "upper_torso" || templateId === "template.avatar_upper_torso_preview.realvisxl.v1"
      ? "avatar_upper_torso_preview"
      : "avatar_head_face_preview";
  const expected = `hexe/${outputFolder}/${safeName}_seed${seed}`;
  return asArray(outputs).find((output) => String(output?.relative_path || "").startsWith(expected)) || null;
}

function headFacePreviewPromptParts(preview, fallbackParts) {
  const previewParts = objectValue(preview?.prompt_parts);
  const fallback = objectValue(fallbackParts);
  return HEAD_FACE_PROMPT_PARTS.reduce(
    (parts, part) => ({
      ...parts,
      [part.id]: compactPromptText(previewParts[part.id]) || compactPromptText(fallback[part.id]),
    }),
    {}
  );
}

function objectValue(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function hasExtraction(profile) {
  return Boolean(profile?.extraction?.structured && typeof profile.extraction.structured === "object");
}

function splitTerms(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item || "").trim()).filter(Boolean);
  }
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formattedJson(value) {
  return JSON.stringify(objectValue(value), null, 2);
}

function selectedFileNames(files) {
  return asArray(files).map((file) => file?.name).filter(Boolean).join(", ") || "none";
}

function profileReferences(profile, role) {
  return asArray(objectValue(profile?.references)[role]);
}

function bodyDepthProfile(profile) {
  return objectValue(profile?.body_depth_profile);
}

function faceProfile(profile) {
  return objectValue(profile?.face_profile);
}

function rawBodyReferences(profile) {
  return profileReferences(profile, "body_depth").filter((reference) => !reference?.background_removed);
}

function noBgBodyReferences(profile) {
  return profileReferences(profile, "body_depth").filter((reference) => Boolean(reference?.background_removed));
}

const AVATAR_PROFILE_TEMPLATE_ID = "template.avatar_profile_depth_pulid.realvisxl.v1";
const AVATAR_BODY_REFERENCE_TEMPLATE_ID = "template.avatar_body_depth_reference_transparent.realvisxl.v1";
const DEFAULT_AVATAR_NEGATIVE_TERMS = [
  "busy background",
  "detailed background",
  "cropped head",
  "cropped face",
  "cropped body",
  "out of frame",
  "close-up crop",
  "torso crop",
  "missing legs",
  "missing feet",
  "different body shape",
  "changed identity",
  "altered face",
  "low quality",
  "blurry",
  "distorted face",
  "distorted hands",
  "extra limbs",
  "malformed body",
  "watermark",
  "text",
];

function compactPromptText(value) {
  if (Array.isArray(value)) {
    return value.map((item) => compactPromptText(item)).filter(Boolean).join(", ");
  }
  if (value && typeof value === "object") {
    if (typeof value.description === "string") {
      return compactPromptText(value.description);
    }
    if (typeof value.current === "string") {
      return compactPromptText(value.current);
    }
    return Object.values(value).map((item) => compactPromptText(item)).filter(Boolean).join(", ");
  }
  return String(value || "")
    .replace(/\*\*/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function firstPromptText(...values) {
  for (const value of values) {
    const text = compactPromptText(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function mergedNegativeTerms(...values) {
  const seen = new Set();
  const terms = [];
  values.flatMap((value) => splitTerms(compactPromptText(value))).forEach((term) => {
    const key = term.toLowerCase();
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    terms.push(term);
  });
  return terms.join(", ");
}

function profileReferenceInputImage(profile, role, reference) {
  const existing = String(reference?.input_image || "").trim();
  if (existing) {
    return existing;
  }
  const filename = String(reference?.filename || "").trim();
  const profileId = String(profile?.profile_id || "").trim();
  if (!filename || !profileId) {
    return "";
  }
  return `avatar_profiles/${profileId}/refs/${role}/${filename}`;
}

function referenceOption({ profile, role, reference, fallbackName }) {
  const inputImage = profileReferenceInputImage(profile, role, reference);
  if (!inputImage) {
    return null;
  }
  return {
    inputImage,
    filename: String(reference?.filename || "").trim(),
    label: String(reference?.name || reference?.filename || fallbackName || inputImage).trim(),
    url: String(reference?.url || "").trim(),
    primary: Boolean(reference?.primary),
    backgroundRemoved: Boolean(reference?.background_removed),
  };
}

function uniqueReferenceOptions(options) {
  const seen = new Set();
  return options.filter((option) => {
    if (!option?.inputImage || seen.has(option.inputImage)) {
      return false;
    }
    seen.add(option.inputImage);
    return true;
  });
}

function faceReferenceOptions(profile) {
  const profileId = String(profile?.profile_id || "").trim();
  const primaryInput = String(profile?.pulid_face_reference_image || profile?.primary_face_input_image || "").trim();
  const refs = profileReferences(profile, "face");
  const primary = refs.find((reference) => profileReferenceInputImage(profile, "face", reference) === primaryInput || reference?.primary);
  const baseFace = String(profile?.face_input_image || "").trim();
  return uniqueReferenceOptions([
    primary ? referenceOption({ profile, role: "face", reference: primary, fallbackName: "Primary face" }) : null,
    ...refs.map((reference) => referenceOption({ profile, role: "face", reference, fallbackName: "Face reference" })),
    baseFace
      ? {
          inputImage: baseFace,
          filename: String(profile?.face_image || "face").trim(),
          label: `${profileId || "Profile"} base face`,
          url: String(profile?.face_url || "").trim(),
          primary: !primaryInput,
        }
      : null,
  ].filter(Boolean));
}

function bodyReferenceOptions(profile) {
  const profileId = String(profile?.profile_id || "").trim();
  const baseBody = String(profile?.body_input_image || "").trim();
  return uniqueReferenceOptions([
    ...noBgBodyReferences(profile).map((reference) =>
      referenceOption({ profile, role: "body_depth", reference, fallbackName: "No-BG body reference" })
    ),
    ...rawBodyReferences(profile).map((reference) =>
      referenceOption({ profile, role: "body_depth", reference, fallbackName: "Body reference" })
    ),
    baseBody
      ? {
          inputImage: baseBody,
          filename: String(profile?.body_image || "body").trim(),
          label: `${profileId || "Profile"} base body`,
          url: String(profile?.body_url || "").trim(),
        }
      : null,
  ].filter(Boolean));
}

function bodyDepthMapOptions(profile) {
  return uniqueReferenceOptions(
    profileReferences(profile, "body_depth_map").map((reference) =>
      referenceOption({ profile, role: "body_depth_map", reference, fallbackName: "Body depth map" })
    )
  );
}

function poseReferenceOptions(profile) {
  return uniqueReferenceOptions(
    profileReferences(profile, "pose").map((reference) =>
      referenceOption({ profile, role: "pose", reference, fallbackName: "Pose reference" })
    )
  );
}

function selectedReferenceOption(options, inputImage) {
  return options.find((option) => option.inputImage === inputImage) || null;
}

function referencePairKey(filename) {
  return String(filename || "")
    .trim()
    .replace(/\.[^.]+$/, "")
    .replace(/^avatar_body_depth_/, "")
    .replace(/^avatar_body_/, "")
    .toLowerCase();
}

function pairedBodyDepthInputImage(profile, bodyInputImage) {
  const bodyOption = selectedReferenceOption(bodyReferenceOptions(profile), bodyInputImage);
  const bodyKey = referencePairKey(bodyOption?.filename);
  if (!bodyKey) {
    return "";
  }
  const depthOption = bodyDepthMapOptions(profile).find((option) => referencePairKey(option.filename) === bodyKey);
  return depthOption?.inputImage || "";
}

function pairedBodyReferenceInputImage(profile, depthInputImage) {
  const depthOption = selectedReferenceOption(bodyDepthMapOptions(profile), depthInputImage);
  const depthKey = referencePairKey(depthOption?.filename);
  if (!depthKey) {
    return "";
  }
  const bodyOption = bodyReferenceOptions(profile).find((option) => referencePairKey(option.filename) === depthKey);
  return bodyOption?.inputImage || "";
}

function generationReferenceValue(value, options, { allowEmpty = false } = {}) {
  const normalized = String(value || "").trim();
  if (normalized && options.some((option) => option.inputImage === normalized)) {
    return normalized;
  }
  if (allowEmpty) {
    return "";
  }
  return options[0]?.inputImage || "";
}

function avatarGenerationProfileSignature(profile) {
  if (!profile?.profile_id) {
    return "";
  }
  return JSON.stringify({
    profile_id: profile.profile_id,
    extraction_updated_at: objectValue(profile.extraction).created_at || profile.updated_at || "",
    face_profile_updated_at: objectValue(faceProfile(profile)).created_at || objectValue(faceProfile(profile)).updated_at || "",
    body_depth_updated_at: objectValue(bodyDepthProfile(profile)).updated_at || "",
    face: faceReferenceOptions(profile).map((option) => option.inputImage),
    body: bodyReferenceOptions(profile).map((option) => option.inputImage),
    depth: bodyDepthMapOptions(profile).map((option) => option.inputImage),
    pose: poseReferenceOptions(profile).map((option) => option.inputImage),
  });
}

function reconcileGenerationEditorState(profile, current, defaults) {
  const faceOptions = faceReferenceOptions(profile);
  const bodyOptions = bodyReferenceOptions(profile);
  const depthOptions = bodyDepthMapOptions(profile);
  const poseOptions = poseReferenceOptions(profile);
  const next = { ...defaults, ...objectValue(current) };
  if (next.template_id === AVATAR_PROFILE_TEMPLATE_ID && !depthOptions.length) {
    next.template_id = AVATAR_BODY_REFERENCE_TEMPLATE_ID;
  }
  if (![AVATAR_PROFILE_TEMPLATE_ID, AVATAR_BODY_REFERENCE_TEMPLATE_ID].includes(next.template_id)) {
    next.template_id = defaults.template_id;
  }
  next.face_reference_image = generationReferenceValue(next.face_reference_image, faceOptions);
  next.body_reference_image = generationReferenceValue(next.body_reference_image, bodyOptions);
  next.body_depth_image = generationReferenceValue(next.body_depth_image, depthOptions, { allowEmpty: true });
  next.pose_reference_image = generationReferenceValue(next.pose_reference_image, poseOptions, { allowEmpty: true });
  if (next.template_id === AVATAR_PROFILE_TEMPLATE_ID && !next.body_depth_image) {
    next.body_depth_image = pairedBodyDepthInputImage(profile, next.body_reference_image) || depthOptions[0]?.inputImage || "";
  }
  return next;
}

function buildAvatarGenerationPrompt(editor) {
  const parts = [
    "full body portrait, head to toe, complete body visible",
    editor.identity,
    editor.face,
    editor.hair,
    editor.body_shape,
    editor.pose,
    editor.clothing,
    editor.accessories,
    editor.scene,
    editor.style,
    editor.preservation,
    "transparent background, isolated subject, photorealistic, realistic skin texture, detailed face, detailed hands",
  ];
  return parts.map((part) => compactPromptText(part)).filter(Boolean).join(", ");
}

function generationEditorState(profile) {
  const extraction = objectValue(profile?.extraction);
  const structured = objectValue(extraction.structured);
  const promptSections = objectValue(structured.prompt_sections);
  const bodyProfile = objectValue(structured.body_profile);
  const removableClothing = objectValue(structured.removable_clothing);
  const poseReference = objectValue(structured.pose_reference);
  const faceStructured = objectValue(faceProfile(profile).structured);
  const faceOptions = faceReferenceOptions(profile);
  const bodyOptions = bodyReferenceOptions(profile);
  const depthOptions = bodyDepthMapOptions(profile);
  const poseOptions = poseReferenceOptions(profile);
  const identity = firstPromptText(
    faceStructured.identity_prompt,
    promptSections.identity,
    structured.identity_prompt,
    objectValue(structured.permanent_identity).identity_prompt
  );
  const face = firstPromptText(faceStructured.face_prompt, promptSections.face, objectValue(structured.permanent_identity).face);
  const hair = firstPromptText(faceStructured.hair_prompt, promptSections.hair);
  const bodyShape = firstPromptText(
    promptSections.body_shape,
    bodyProfile.body_prompt,
    bodyProfile.silhouette,
    extraction.body_description
  );
  return {
    template_id: depthOptions.length ? AVATAR_PROFILE_TEMPLATE_ID : AVATAR_BODY_REFERENCE_TEMPLATE_ID,
    face_reference_image: faceOptions[0]?.inputImage || "",
    body_reference_image: bodyOptions[0]?.inputImage || "",
    body_depth_image: depthOptions[0]?.inputImage || "",
    pose_reference_image: poseOptions[0]?.inputImage || "",
    identity,
    face,
    hair,
    body_shape: bodyShape,
    pose: firstPromptText(promptSections.pose, poseReference.current_pose, poseReference.description),
    clothing: firstPromptText(promptSections.clothing, removableClothing.current, removableClothing.description),
    accessories: firstPromptText(promptSections.accessories, structured.accessories, faceStructured.accessories),
    scene: "",
    style: "high-end editorial photography, cinematic lighting, sharp focus",
    preservation: firstPromptText(
      promptSections.preservation,
      structured.preservation_notes,
      "preserve the same face identity, same body proportions, same silhouette, same shoulder waist hip relationship"
    ),
    negative: mergedNegativeTerms(
      DEFAULT_AVATAR_NEGATIVE_TERMS,
      structured.negative_prompt_terms,
      promptSections.negative,
      faceStructured.negative_prompt_terms,
      faceStructured.negative_identity_prompt
    ),
    width: "768",
    height: "1152",
    seed: "",
    steps: "4",
    cfg: "1.2",
    denoise: "1",
    batch_count: "1",
    face_strength: "0.8",
    body_depth_strength: depthOptions.length ? "0.8" : "0.75",
    body_depth_start: "0",
    body_depth_end: depthOptions.length ? "0.9" : "0.8",
    pose_strength: "0.65",
    pose_start: "0",
    pose_end: "0.8",
    randomize_seed: false,
    randomize_reference_strengths: false,
    reference_strength_jitter: "0.05",
    create_lora_metadata: false,
  };
}

function extractionEditorState(profile) {
  const extraction = objectValue(profile?.extraction);
  const structured = objectValue(extraction.structured);
  const promptSections = objectValue(structured.prompt_sections);
  const bodyProfile = objectValue(structured.body_profile);
  const permanentIdentity = objectValue(structured.permanent_identity);
  return {
    face_description: String(extraction.face_description || ""),
    body_description: String(extraction.body_description || ""),
    identity: String(promptSections.identity || structured.identity_prompt || permanentIdentity.identity_prompt || ""),
    face: String(promptSections.face || ""),
    hair: String(promptSections.hair || ""),
    body_shape: String(promptSections.body_shape || bodyProfile.body_prompt || ""),
    pose: String(promptSections.pose || ""),
    clothing: String(promptSections.clothing || ""),
    accessories: String(promptSections.accessories || ""),
    preservation: String(promptSections.preservation || ""),
    negative: splitTerms(structured.negative_prompt_terms || promptSections.negative).join(", "),
    bust_breasts: String(bodyProfile.bust_breasts || ""),
    buttocks_glutes: String(bodyProfile.buttocks_glutes || ""),
    arms_hands_fingers: String(bodyProfile.arms_hands_fingers || ""),
    legs_feet: String(bodyProfile.legs_feet || ""),
    structured_json: formattedJson(structured),
  };
}

function buildExtractionUpdatePayload(editorState) {
  const structured = JSON.parse(editorState.structured_json || "{}");
  const promptSections = objectValue(structured.prompt_sections);
  const bodyProfile = objectValue(structured.body_profile);
  const permanentIdentity = objectValue(structured.permanent_identity);
  structured.prompt_sections = {
    ...promptSections,
    identity: editorState.identity,
    face: editorState.face,
    hair: editorState.hair,
    body_shape: editorState.body_shape,
    pose: editorState.pose,
    clothing: editorState.clothing,
    accessories: editorState.accessories,
    preservation: editorState.preservation,
    negative: editorState.negative,
  };
  structured.body_profile = {
    ...bodyProfile,
    body_prompt: editorState.body_shape || bodyProfile.body_prompt || "",
    bust_breasts: editorState.bust_breasts,
    buttocks_glutes: editorState.buttocks_glutes,
    arms_hands_fingers: editorState.arms_hands_fingers,
    legs_feet: editorState.legs_feet,
  };
  structured.permanent_identity = {
    ...permanentIdentity,
    identity_prompt: editorState.identity || permanentIdentity.identity_prompt || "",
  };
  structured.identity_prompt = editorState.identity || structured.identity_prompt || "";
  structured.negative_prompt_terms = splitTerms(editorState.negative);
  return {
    face_description: editorState.face_description,
    body_description: editorState.body_description,
    structured,
  };
}

const AVATAR_GENERATION_TABS = [
  { id: "profile", label: "Create Profile" },
  { id: "saved_profiles", label: "Saved Profiles" },
];

const AVATAR_PROFILE_DETAIL_TABS = [
  { id: "profile", label: "Profile" },
  { id: "head_face", label: "Head / Face" },
  { id: "upper_torso", label: "Upper Torso" },
  { id: "lower_torso", label: "Lower Torso" },
  { id: "full_body", label: "Full Body" },
];

const HEAD_FACE_PROMPT_PARTS = [
  { id: "general", label: "General", rows: 4 },
  { id: "hair", label: "Hair", rows: 2 },
  { id: "eyes", label: "Eyes", rows: 2 },
  { id: "eyebrows", label: "Eyebrows", rows: 2 },
  { id: "nose", label: "Nose", rows: 2 },
  { id: "cheeks", label: "Cheeks", rows: 2 },
  { id: "mouth", label: "Mouth", rows: 2 },
  { id: "jaw_chin", label: "Jaw / Chin", rows: 2 },
  { id: "ears", label: "Ears", rows: 2 },
  { id: "skin", label: "Skin", rows: 2 },
  { id: "expression", label: "Expression", rows: 2 },
  { id: "style_lighting", label: "Style / Lighting", rows: 3 },
];

const UPPER_TORSO_PROMPT_PARTS = [
  { id: "general", label: "General", rows: 3 },
  { id: "neck_shoulders", label: "Neck / Shoulders", rows: 2 },
  { id: "chest_torso_shape", label: "Chest / Torso Shape", rows: 2 },
  { id: "arms_upper_arms", label: "Arms / Upper Arms", rows: 2 },
  { id: "clothing_outfit", label: "Clothing / Outfit", rows: 2 },
  { id: "skin_body_details", label: "Skin / Body Details", rows: 2 },
  { id: "pose_framing", label: "Pose / Framing", rows: 2 },
  { id: "style_lighting", label: "Style / Lighting", rows: 3 },
];

const HEAD_FACE_PROMPT_PART_ALIASES = new Map(
  HEAD_FACE_PROMPT_PARTS.flatMap((part) => {
    const base = [
      part.id,
      part.label,
      part.label.replace(/\s*\/\s*/g, " "),
      part.label.replace(/\s*\/\s*/g, "_"),
      part.label.replace(/\s*\/\s*/g, ""),
    ];
    if (part.id === "jaw_chin") {
      base.push("jaw", "chin", "jaw chin", "jaw/chin");
    }
    if (part.id === "style_lighting") {
      base.push("style", "lighting", "style lighting", "style/lighting");
    }
    return base.map((alias) => [
      String(alias || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, ""),
      part.id,
    ]);
  })
);

const HEAD_INSTRUCTION_DRAFTS = new Map();

function promptWorkspace(profile, section) {
  return objectValue(objectValue(profile?.prompt_workspaces)[section]);
}

function headInstructionDraftKey(profile, routeProfileId = "") {
  return String(profile?.profile_id || routeProfileId || "").trim();
}

function savedHeadInstructionDraft(profile, routeProfileId = "") {
  const key = headInstructionDraftKey(profile, routeProfileId);
  return key ? String(HEAD_INSTRUCTION_DRAFTS.get(key) || "") : "";
}

function defaultHeadFacePromptParts(profile) {
  const generalPrompt = compactPromptText(profile?.general_prompt);
  return {
    general:
      generalPrompt ||
      [
        profileName(profile),
        profile?.gender,
        String(profile?.character_type || "").replace("-", " "),
        String(profile?.visual_style || "").replace("-", " "),
        profile?.skin_color ? `${profile.skin_color} skin` : "",
        profile?.hair_color ? `${profile.hair_color} hair` : "",
      ].map((part) => compactPromptText(part)).filter(Boolean).join(", "),
    hair: profile?.hair_color ? `detailed ${profile.hair_color} hair` : "detailed hair",
    eyes: "expressive detailed eyes",
    eyebrows: "natural eyebrows",
    nose: "defined nose",
    cheeks: "natural cheeks",
    mouth: "natural lips",
    jaw_chin: "clear jaw and chin shape",
    ears: "natural ears",
    skin: profile?.skin_color ? `${profile.skin_color} skin, natural skin texture` : "natural skin texture",
    expression: "natural expression",
    style_lighting: "head and shoulders portrait, clear face, centered composition, clean studio lighting",
  };
}

function composeHeadFacePrompt(parts) {
  const source = objectValue(parts);
  return HEAD_FACE_PROMPT_PARTS.map((part) => compactPromptText(source[part.id])).filter(Boolean).join(", ");
}

function defaultUpperTorsoPromptParts(profile) {
  const generalPrompt = compactPromptText(profile?.general_prompt);
  return {
    general: generalPrompt || [profileName(profile), profile?.gender, "upper torso avatar reference"].map((part) => compactPromptText(part)).filter(Boolean).join(", "),
    neck_shoulders: "natural neck length, readable collarbones, balanced shoulder width",
    chest_torso_shape: "feminine upper torso shape, clear chest form, smooth ribcage and waist transition",
    arms_upper_arms: "upper arms visible, natural arm proportions, relaxed shoulders",
    clothing_outfit: "fitted simple bodysuit baseline, body shape readable, no loose clothing or bulky layers",
    skin_body_details: profile?.skin_color ? `${profile.skin_color} skin, smooth natural body skin texture` : "smooth natural body skin texture",
    pose_framing: "upper torso reference, shoulders to waist visible, centered studio framing",
    style_lighting: "polished semi-realistic avatar render, clean studio lighting, neutral background",
  };
}

function buildUpperTorsoPromptParts(profile) {
  const workspace = promptWorkspace(profile, "upper_torso");
  const defaults = defaultUpperTorsoPromptParts(profile);
  const savedParts = objectValue(workspace.prompt_parts);
  const hasSavedParts = UPPER_TORSO_PROMPT_PARTS.some((part) => compactPromptText(savedParts[part.id]));
  if (hasSavedParts) {
    return UPPER_TORSO_PROMPT_PARTS.reduce(
      (parts, part) => ({ ...parts, [part.id]: compactPromptText(savedParts[part.id] ?? defaults[part.id]) }),
      {}
    );
  }
  const savedPrompt = compactPromptText(workspace.prompt);
  if (savedPrompt) {
    return { ...defaults, general: savedPrompt };
  }
  return defaults;
}

function composeUpperTorsoPrompt(parts) {
  const source = objectValue(parts);
  return UPPER_TORSO_PROMPT_PARTS.map((part) => compactPromptText(source[part.id])).filter(Boolean).join(", ");
}

function parseHeadFaceTaggedAdjustments(value) {
  const updates = {};
  let activePartId = "";
  String(value || "").split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      return;
    }
    const tagMatch = line.match(/^([^:]{2,40}):\s*(.*)$/);
    if (tagMatch) {
      const key = String(tagMatch[1] || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      const partId = HEAD_FACE_PROMPT_PART_ALIASES.get(key) || "";
      if (partId) {
        activePartId = partId;
        updates[partId] = compactPromptText(tagMatch[2] || "");
        return;
      }
    }
    if (activePartId) {
      updates[activePartId] = compactPromptText([updates[activePartId], line].filter(Boolean).join(", "));
    }
  });
  return updates;
}

function headFacePromptParts(profile) {
  const workspace = promptWorkspace(profile, "head_face");
  const defaults = defaultHeadFacePromptParts(profile);
  const savedParts = objectValue(workspace.prompt_parts);
  const hasSavedParts = HEAD_FACE_PROMPT_PARTS.some((part) => compactPromptText(savedParts[part.id]));
  if (hasSavedParts) {
    return HEAD_FACE_PROMPT_PARTS.reduce(
      (parts, part) => ({ ...parts, [part.id]: compactPromptText(savedParts[part.id] ?? defaults[part.id]) }),
      {}
    );
  }
  const savedPrompt = compactPromptText(workspace.prompt);
  if (savedPrompt) {
    return { ...defaults, general: savedPrompt };
  }
  return defaults;
}

function headFaceLockedPromptParts(profile) {
  const locks = objectValue(promptWorkspace(profile, "head_face").locked_prompt_parts);
  return HEAD_FACE_PROMPT_PARTS.reduce(
    (parts, part) => ({ ...parts, [part.id]: Boolean(locks[part.id]) }),
    {}
  );
}

function latestHeadAssistantReply(profile) {
  const workspace = promptWorkspace(profile, "head_face");
  const savedReply = compactPromptText(workspace.assistant_reply);
  if (savedReply) {
    return savedReply;
  }
  const assistant = asArray(workspace.conversation)
    .slice()
    .reverse()
    .find((message) => message?.role === "assistant");
  return compactPromptText(assistant?.reply || assistant?.content);
}

export function AvatarGenerationCard({
  payload = null,
  manualImageGenerationPayload = null,
  busy = false,
  result = null,
  apiBase = "",
  initialTab = "profile",
  initialDetailTab = "profile",
  routeProfileId = "",
  onSaveProfile,
  onSelectProfile,
  onDeleteProfile,
  onUpdateProfileExtraction,
  onUploadProfileReference,
  onDeleteProfileReference,
  onSetPrimaryFace,
  onGenerateBodyDepthProfile,
  onRefineHeadPrompt,
  onSaveHeadPrompt,
  onCreateHeadPreview,
  onCreateUpperTorsoPreview,
  onCreateHeadSeedBatch,
  onCreateHeadJitterBatch,
  onUpdateHeadLoraDataset,
  onUploadHeadLoraDataset,
  onUploadHeadLora,
  onUploadUpperTorsoLoraDataset,
  onUpdateUpperTorsoLoraDataset,
  onUploadUpperTorsoLora,
  onSelectDetailTab,
  onSubmitGeneration,
  generationBusy = false,
  generationResult = null,
  onBackToProfiles,
  onRefresh,
}) {
  const profiles = asArray(payload?.profiles);
  const manualOutputs = asArray(manualImageGenerationPayload?.outputs);
  const selectedProfileId = String(payload?.selected_profile_id || "").trim();
  const routeProfile = useMemo(
    () => profiles.find((profile) => String(profile?.profile_id || "") === String(routeProfileId || "")),
    [profiles, routeProfileId]
  );
  const [activeTab, setActiveTab] = useState(initialTab === "saved_profiles" ? "saved_profiles" : "profile");
  const [activeDetailTab, setActiveDetailTab] = useState(
    AVATAR_PROFILE_DETAIL_TABS.some((tab) => tab.id === initialDetailTab) ? initialDetailTab : "profile"
  );
  const [characterName, setCharacterName] = useState("");
  const [gender, setGender] = useState("");
  const [skinColor, setSkinColor] = useState("");
  const [hairColor, setHairColor] = useState("");
  const [characterType, setCharacterType] = useState("human");
  const [visualStyle, setVisualStyle] = useState("stylized-realistic");
  const [nsfw, setNsfw] = useState(false);
  const [bodyDepthFiles, setBodyDepthFiles] = useState([]);
  const [faceAnalysisFiles, setFaceAnalysisFiles] = useState([]);
  const [poseFiles, setPoseFiles] = useState([]);
  const [poseText, setPoseText] = useState("");
  const [description, setDescription] = useState("");
  const [localStatus, setLocalStatus] = useState("");
  const [activeProfileAction, setActiveProfileAction] = useState("");
  const [activeReferenceAction, setActiveReferenceAction] = useState("");
  const [editorState, setEditorState] = useState(() => extractionEditorState(routeProfile));
  const [generationState, setGenerationState] = useState(() => generationEditorState(routeProfile));
  const [headPromptParts, setHeadPromptParts] = useState(() => headFacePromptParts(routeProfile));
  const [headLockedPromptParts, setHeadLockedPromptParts] = useState(() => headFaceLockedPromptParts(routeProfile));
  const [headNegativePrompt, setHeadNegativePrompt] = useState(() => promptWorkspace(routeProfile, "head_face").negative_prompt || "");
  const [headPreviewSeed, setHeadPreviewSeed] = useState(() => String(promptWorkspace(routeProfile, "head_face").preview_seed || ""));
  const [headPreviewSeedLocked, setHeadPreviewSeedLocked] = useState(() => Boolean(promptWorkspace(routeProfile, "head_face").preview_seed_locked));
  const [headInstruction, setHeadInstruction] = useState(() => savedHeadInstructionDraft(routeProfile, routeProfileId));
  const [headAssistantReply, setHeadAssistantReply] = useState(() => latestHeadAssistantReply(routeProfile));
  const [upperTorsoPromptParts, setUpperTorsoPromptParts] = useState(() => buildUpperTorsoPromptParts(routeProfile));
  const [upperTorsoNegativePrompt, setUpperTorsoNegativePrompt] = useState(() => promptWorkspace(routeProfile, "upper_torso").negative_prompt || "");
  const [selectedHeadPreview, setSelectedHeadPreview] = useState(null);
  const [showHeadSeedBatch, setShowHeadSeedBatch] = useState(false);
  const [showHeadJitterBatch, setShowHeadJitterBatch] = useState(false);
  const [showHeadLoraPopup, setShowHeadLoraPopup] = useState(false);
  const [headSeedBatchKeepIds, setHeadSeedBatchKeepIds] = useState([]);
  const [headSeedBatchManualSeeds, setHeadSeedBatchManualSeeds] = useState({});
  const [headLoraDatasetSourceDir, setHeadLoraDatasetSourceDir] = useState("");
  const [headLoraExternalPath, setHeadLoraExternalPath] = useState("");
  const [upperTorsoLoraDatasetSourceDir, setUpperTorsoLoraDatasetSourceDir] = useState("");
  const [upperTorsoLoraExternalPath, setUpperTorsoLoraExternalPath] = useState("");
  const generationProfileIdRef = useRef("");
  const headEditorProfileIdRef = useRef(String(routeProfile?.profile_id || ""));
  const generationProfileSignature = avatarGenerationProfileSignature(routeProfile);
  const latestProfile = result?.profile || profiles[0] || null;
  const canSave = Boolean(characterName.trim()) && !busy;
  const detailMode = Boolean(routeProfileId);
  const headPreviewHistory = useMemo(() => headFacePreviewHistory(routeProfile), [routeProfile]);
  const latestHeadPreview = headPreviewHistory[0] || null;
  const olderHeadPreviewHistory = useMemo(() => headPreviewHistory.slice(1), [headPreviewHistory]);
  const latestHeadPreviewOutput = headFacePreviewOutput(latestHeadPreview, manualOutputs, routeProfile);
  const headSeedBatch = objectValue(promptWorkspace(routeProfile, "head_face").seed_batch);
  const headSeedBatchPreviews = asArray(headSeedBatch.previews);
  const headSeedBatchKeepSet = useMemo(() => new Set(headSeedBatchKeepIds), [headSeedBatchKeepIds]);
  const headSeedBatchReadyPreviews = headSeedBatchPreviews.filter(
    (preview) => String(preview?.status || "") === "completed" && !preview?.placeholder
  );
  const headSeedBatchKeptCount = headSeedBatchPreviews.filter((preview) => headSeedBatchKeepSet.has(String(preview?.preview_id || ""))).length;
  const headSeedBatchTargetCount = Number(headSeedBatch.target_count || 20);
  const headSeedBatchNeedsMore = headSeedBatchReadyPreviews.length < headSeedBatchTargetCount;
  const headSeedBatchSelectedPreviewId = String(headSeedBatch.selected_preview_id || "").trim();
  const headJitterBatch = objectValue(promptWorkspace(routeProfile, "head_face").jitter_batch);
  const headJitterBatchPreviews = asArray(headJitterBatch.previews);
  const headJitterReadyPreviews = headJitterBatchPreviews.filter(
    (preview) => String(preview?.status || "") === "completed" && !preview?.placeholder
  );
  const headJitterApprovedIds = useMemo(
    () => new Set(asArray(headJitterBatch.approved_preview_ids).map((item) => String(item || ""))),
    [headJitterBatch.approved_preview_ids]
  );
  const headJitterApprovedCount = Number(headJitterBatch.approved_seed_count || headJitterApprovedIds.size || 0);
  const headJitterRequiredCount = Number(headJitterBatch.required_seed_count || 12);
  const headLoraSeedMapGroups = useMemo(() => {
    const original = headJitterBatchPreviews[0] || {};
    const originalId = String(original?.preview_id || "");
    const approved = [];
    const pending = [];
    headJitterBatchPreviews.slice(1).forEach((preview) => {
      const previewId = String(preview?.preview_id || "");
      if (headJitterApprovedIds.has(previewId) || Boolean(preview?.approved)) {
        approved.push(preview);
      } else {
        pending.push(preview);
      }
    });
    if (!originalId && !approved.length && !pending.length) {
      return { approved: [], original: {}, pending: [], pending_total: 0 };
    }
    return { approved, original, pending: pending.slice(0, 4), pending_total: pending.length };
  }, [headJitterApprovedIds, headJitterBatchPreviews]);
  const headLoraSeedSet = objectValue(promptWorkspace(routeProfile, "head_face").lora_seed_set);
  const headLoraSeedsReady = asArray(headLoraSeedSet.seeds).length >= 12;
  const headLoraDataset = objectValue(promptWorkspace(routeProfile, "head_face").lora_dataset);
  const headLoraUploadedDataset = objectValue(headLoraDataset.uploaded_dataset);
  const headLoraUploadedValidation = objectValue(headLoraUploadedDataset.validation);
  const headLoraUploadedReady = String(headLoraUploadedValidation.status || headLoraUploadedDataset.status || "").trim() === "ready";
  const headLoraUploadedItems = asArray(headLoraUploadedDataset.items);
  const headLoraExternalManifest = objectValue(headLoraDataset.external_loras);
  const headLoraExternalItems = asArray(headLoraExternalManifest.items);
  const headLoraActiveExternal = objectValue(headLoraDataset.active_lora);
  const headLoraDatasetPoses = asArray(headLoraDataset.poses);
  const headLoraDatasetReady = headLoraDatasetPoses.some((pose) =>
    Number(pose?.approved_dataset_ready_count || 0) >= Number(pose?.required_count || 6) ||
    Number(pose?.approved_count || 0) >= Number(pose?.required_count || 6) ||
    asArray(pose?.approved_dataset).some((item) =>
      ["ready", "background_removal_pending", "background_removal_submitted"].includes(String(item?.status || ""))
    )
  );
  const headLoraAvailable = true;
  const headLoraActivePoseIndex = Math.max(0, Math.min(Number(headLoraDataset.active_pose_index || 0), Math.max(headLoraDatasetPoses.length - 1, 0)));
  const headLoraActivePose = objectValue(headLoraDatasetPoses[headLoraActivePoseIndex]);
  const headLoraActivePoseItems = asArray(headLoraActivePose.items);
  const headLoraPoseApprovedCount = Number(headLoraActivePose.approved_count || 0);
  const headLoraPoseRequiredCount = Number(headLoraActivePose.required_count || 6);
  const headLoraApprovedDataset = asArray(headLoraActivePose.approved_dataset);
  const headLoraApprovedDatasetReadyCount = headLoraApprovedDataset.filter((item) => String(item?.status || "") === "ready").length;
  const headLoraAllApprovedDataset = headLoraDatasetPoses.flatMap((pose) => asArray(pose?.approved_dataset));
  const headLoraTrainingManifest = objectValue(headLoraDataset.training_manifest);
  const headLoraTrainingJob = objectValue(headLoraDataset.training_job);
  const headLoraTrainingRunning = String(headLoraTrainingJob.status || "").trim() === "running";
  const headLoraTrainingCompleted = String(headLoraTrainingJob.status || "").trim() === "completed";
  const headLoraEpochReview = objectValue(headLoraDataset.epoch_review);
  const headLoraEpochReviewPreviews = asArray(headLoraEpochReview.previews);
  const headLoraEpochReviewGroups = useMemo(() => {
    const groups = new Map();
    headLoraEpochReviewPreviews.forEach((preview) => {
      const epoch = Number(preview?.epoch || 0);
      if (!epoch) {
        return;
      }
      if (!groups.has(epoch)) {
        groups.set(epoch, []);
      }
      groups.get(epoch).push(preview);
    });
    return Array.from(groups.entries())
      .sort(([left], [right]) => left - right)
      .map(([epoch, previews]) => ({
        epoch,
        previews: previews.slice().sort((left, right) => Number(left?.sample_index || 0) - Number(right?.sample_index || 0)),
      }));
  }, [headLoraEpochReviewPreviews]);
  const headLoraReadyForTraining = headLoraUploadedReady;
  const headLoraTrainingStatus = useMemo(() => {
    const status = String(headLoraTrainingJob.status || headLoraTrainingManifest.status || (headLoraReadyForTraining ? "ready" : "waiting")).trim();
    const phase = String(headLoraTrainingJob.phase || status || "").trim();
    const detail = String(headLoraTrainingJob.status_detail || headLoraTrainingJob.last_log_line || "").trim();
    const log = String(headLoraTrainingJob.log || "").trim();
    const outputModel = String(headLoraTrainingJob.output_model || "").trim();
    const pid = String(headLoraTrainingJob.pid || "").trim();
    return {
      status,
      phase,
      detail,
      log,
      outputModel,
      pid,
      logLabel: log ? log.split("/").slice(-3).join("/") : "none",
      outputLabel: outputModel ? outputModel.split("/").slice(-2).join("/") : "none",
    };
  }, [headLoraReadyForTraining, headLoraTrainingJob, headLoraTrainingManifest]);
  const upperTorsoWorkspace = objectValue(promptWorkspace(routeProfile, "upper_torso"));
  const upperTorsoLoraDataset = objectValue(upperTorsoWorkspace.lora_dataset);
  const upperTorsoUploadedDataset = objectValue(upperTorsoLoraDataset.uploaded_dataset);
  const upperTorsoUploadedValidation = objectValue(upperTorsoUploadedDataset.validation);
  const upperTorsoUploadedItems = asArray(upperTorsoUploadedDataset.items);
  const upperTorsoExternalManifest = objectValue(upperTorsoLoraDataset.external_loras);
  const upperTorsoExternalItems = asArray(upperTorsoExternalManifest.items);
  const upperTorsoActiveExternal = objectValue(upperTorsoLoraDataset.active_lora);
  const upperTorsoTrainingManifest = objectValue(upperTorsoLoraDataset.training_manifest);
  const upperTorsoTrainingJob = objectValue(upperTorsoLoraDataset.training_job);
  const upperTorsoEpochReview = objectValue(upperTorsoLoraDataset.epoch_review);
  const upperTorsoEpochReviewPreviews = asArray(upperTorsoEpochReview.previews);
  const upperTorsoEpochReviewGroups = useMemo(() => {
    const groups = new Map();
    upperTorsoEpochReviewPreviews.forEach((preview) => {
      const epoch = Number(preview?.epoch || 0);
      if (!epoch) {
        return;
      }
      if (!groups.has(epoch)) {
        groups.set(epoch, []);
      }
      groups.get(epoch).push(preview);
    });
    return Array.from(groups.entries())
      .sort(([left], [right]) => left - right)
      .map(([epoch, previews]) => ({
        epoch,
        previews: previews.slice().sort((left, right) => Number(left?.sample_index || 0) - Number(right?.sample_index || 0)),
      }));
  }, [upperTorsoEpochReviewPreviews]);
  const upperTorsoReadyForTraining = String(upperTorsoUploadedValidation.status || upperTorsoUploadedDataset.status || "").trim() === "ready";
  const upperTorsoTrainingRunning = String(upperTorsoTrainingJob.status || "").trim() === "running";
  const upperTorsoPreviewHistory = useMemo(() => workspacePreviewHistory(routeProfile, "upper_torso"), [routeProfile]);
  const upperTorsoPrompt = useMemo(() => composeUpperTorsoPrompt(upperTorsoPromptParts), [upperTorsoPromptParts]);
  const latestUpperTorsoPreview = upperTorsoPreviewHistory[0] || null;
  const latestUpperTorsoPreviewOutput = headFacePreviewOutput(latestUpperTorsoPreview, manualOutputs, routeProfile);
  const headLoraBgStatusSummary = useMemo(() => {
    const summarize = (items) => {
      const counts = {
        total: items.length,
        ready: 0,
        submitted: 0,
        pending: 0,
        failed: 0,
      };
      let active = null;
      items.forEach((item) => {
        const status = String(item?.status || "").trim();
        if (status === "ready") {
          counts.ready += 1;
        } else if (status === "background_removal_submitted") {
          counts.submitted += 1;
          active ||= item;
        } else if (status === "background_removal_pending") {
          counts.pending += 1;
          active ||= item;
        } else if (status.includes("failed") || item?.background_removal_error) {
          counts.failed += 1;
          active ||= item;
        } else if (status) {
          counts.pending += 1;
          active ||= item;
        }
      });
      return {
        ...counts,
        activeName: String(active?.filename || active?.approved_id || active?.source_preview_id || "").trim(),
      };
    };
    return {
      activePose: summarize(headLoraApprovedDataset),
      overall: summarize(headLoraAllApprovedDataset),
    };
  }, [headLoraAllApprovedDataset, headLoraApprovedDataset]);
  const headLoraVisionFailed = headLoraActivePoseItems.some((item) => String(item?.vision_status || "").trim() === "failed");
  const headLoraReferencePreview = useMemo(() => {
    const selectedPreviewId = String(headSeedBatch.selected_preview_id || headLoraSeedSet.anchor_preview_id || "").trim();
    const anchorSeed = String(headLoraSeedSet.anchor_seed || headJitterBatch.anchor_seed || headSeedBatch.selected_seed || "").trim();
    const seedBatchMatch = headSeedBatchPreviews.find((preview) => String(preview?.preview_id || "") === selectedPreviewId);
    if (seedBatchMatch) {
      return seedBatchMatch;
    }
    const seedBatchSeedMatch = anchorSeed
      ? headSeedBatchPreviews.find((preview) => String(preview?.seed || "") === anchorSeed)
      : null;
    if (seedBatchSeedMatch) {
      return seedBatchSeedMatch;
    }
    const jitterMatch = headJitterBatchPreviews.find((preview) => String(preview?.preview_id || "") === selectedPreviewId);
    if (jitterMatch) {
      return jitterMatch;
    }
    if (headLoraSeedMapGroups.original?.preview_id) {
      return headLoraSeedMapGroups.original;
    }
    const primaryFaceReference = objectValue(routeProfile?.primary_face_reference);
    if (primaryFaceReference.url || primaryFaceReference.input_image) {
      return primaryFaceReference;
    }
    const primaryFaceInputImage = String(routeProfile?.primary_face_input_image || routeProfile?.pulid_face_reference_image || "").trim();
    if (primaryFaceInputImage) {
      const parts = primaryFaceInputImage.split("/");
      const profileId = parts[1] || routeProfile?.profile_id || "";
      const relativeName = parts.slice(4).join("/");
      if (profileId && relativeName) {
        return {
          filename: parts[parts.length - 1] || "primary_reference.png",
          input_image: primaryFaceInputImage,
          relative_name: relativeName,
          url: `/api/avatar-generation/profiles/${profileId}/references/head_face/${relativeName}`,
          status: "primary_reference",
        };
      }
    }
    for (const pose of headLoraDatasetPoses) {
      const importedReference =
        asArray(pose?.approved_dataset).find((item) => item?.url || item?.input_image) ||
        asArray(pose?.items).find((item) => item?.url || item?.input_image);
      if (importedReference) {
        return importedReference;
      }
    }
    return {};
  }, [
    headJitterBatch.anchor_seed,
    headJitterBatchPreviews,
    headLoraDatasetPoses,
    headLoraSeedMapGroups.original,
    headLoraSeedSet.anchor_preview_id,
    headLoraSeedSet.anchor_seed,
    routeProfile?.primary_face_input_image,
    routeProfile?.primary_face_reference,
    routeProfile?.profile_id,
    routeProfile?.pulid_face_reference_image,
    headSeedBatch.selected_preview_id,
    headSeedBatch.selected_seed,
    headSeedBatchPreviews,
  ]);
  const headPrompt = useMemo(() => composeHeadFacePrompt(headPromptParts), [headPromptParts]);
  const headTaggedAdjustments = useMemo(() => parseHeadFaceTaggedAdjustments(headInstruction), [headInstruction]);
  const hasHeadTaggedAdjustments = useMemo(
    () => Object.values(headTaggedAdjustments).some(Boolean),
    [headTaggedAdjustments]
  );
  const hasApplicableHeadTaggedAdjustments = useMemo(
    () => Object.entries(headTaggedAdjustments).some(([partId, value]) => value && !headLockedPromptParts[partId]),
    [headLockedPromptParts, headTaggedAdjustments]
  );
  const selectedHeadPreviewNegativePrompt = selectedHeadPreview
    ? compactPromptText(selectedHeadPreview.preview?.negative_prompt) || headNegativePrompt
    : "";
  const selectedHeadPreviewPromptParts = selectedHeadPreview
    ? headFacePreviewPromptParts(selectedHeadPreview.preview, headPromptParts)
    : {};

  useEffect(() => {
    if (AVATAR_PROFILE_DETAIL_TABS.some((tab) => tab.id === initialDetailTab)) {
      setActiveDetailTab(initialDetailTab);
    }
  }, [initialDetailTab]);

  useEffect(() => {
    if (routeProfile) {
      setEditorState(extractionEditorState(routeProfile));
      const workspace = promptWorkspace(routeProfile, "head_face");
      const profileId = String(routeProfile.profile_id || "").trim();
      const previousProfileId = headEditorProfileIdRef.current;
      headEditorProfileIdRef.current = profileId;
      setHeadPromptParts(headFacePromptParts(routeProfile));
      setHeadLockedPromptParts(headFaceLockedPromptParts(routeProfile));
      setHeadNegativePrompt(String(workspace.negative_prompt || ""));
      const upperWorkspace = promptWorkspace(routeProfile, "upper_torso");
      setUpperTorsoPromptParts(buildUpperTorsoPromptParts(routeProfile));
      setUpperTorsoNegativePrompt(String(upperWorkspace.negative_prompt || ""));
      setHeadPreviewSeed(String(workspace.preview_seed || headFacePreviewHistory(routeProfile)[0]?.seed || ""));
      setHeadPreviewSeedLocked(Boolean(workspace.preview_seed_locked));
      setHeadAssistantReply(latestHeadAssistantReply(routeProfile));
      if (profileId !== previousProfileId) {
        setHeadInstruction(savedHeadInstructionDraft(routeProfile, routeProfileId));
        setSelectedHeadPreview(null);
      }
    }
  }, [routeProfile, routeProfileId]);

  useEffect(() => {
    if (!routeProfile) {
      return;
    }
    const profileId = String(routeProfile.profile_id || "").trim();
    const previousProfileId = generationProfileIdRef.current;
    generationProfileIdRef.current = profileId;
    const defaults = generationEditorState(routeProfile);
    setGenerationState((current) =>
      previousProfileId !== profileId
        ? defaults
        : reconcileGenerationEditorState(routeProfile, current, defaults)
    );
  }, [generationProfileSignature]);

  useEffect(() => {
    if (!selectedHeadPreview && !showHeadSeedBatch && !showHeadJitterBatch && !showHeadLoraPopup) {
      return undefined;
    }
    function closePreviewOnEscape(event) {
      if (event.key === "Escape") {
        setSelectedHeadPreview(null);
        setShowHeadSeedBatch(false);
        setShowHeadJitterBatch(false);
        setShowHeadLoraPopup(false);
      }
    }
    window.addEventListener("keydown", closePreviewOnEscape);
    return () => window.removeEventListener("keydown", closePreviewOnEscape);
  }, [selectedHeadPreview, showHeadSeedBatch, showHeadJitterBatch, showHeadLoraPopup]);

  useEffect(() => {
    setHeadSeedBatchKeepIds(
      headSeedBatchPreviews
        .filter((preview) => Boolean(preview?.kept))
        .map((preview) => String(preview?.preview_id || ""))
        .filter(Boolean)
    );
  }, [headSeedBatch.batch_id]);

  function updateEditorField(name, value) {
    setEditorState((current) => ({ ...current, [name]: value }));
  }

  function selectDetailTab(tabId) {
    setActiveDetailTab(tabId);
    const profileId = String(routeProfile?.profile_id || routeProfileId || "").trim();
    if (profileId && onSelectDetailTab) {
      onSelectDetailTab(profileId, tabId);
    }
  }

  function updateGenerationField(name, value) {
    setGenerationState((current) => {
      const next = { ...current, [name]: value };
      if (name === "body_reference_image") {
        const pairedDepth = pairedBodyDepthInputImage(routeProfile, value);
        if (pairedDepth) {
          next.body_depth_image = pairedDepth;
        }
      }
      if (name === "body_depth_image") {
        const pairedBody = pairedBodyReferenceInputImage(routeProfile, value);
        if (pairedBody) {
          next.body_reference_image = pairedBody;
        }
      }
      if (name === "template_id" && value === AVATAR_PROFILE_TEMPLATE_ID && !next.body_depth_image) {
        next.body_depth_image =
          pairedBodyDepthInputImage(routeProfile, next.body_reference_image) ||
          bodyDepthMapOptions(routeProfile)[0]?.inputImage ||
          "";
      }
      return next;
    });
  }

  function updateHeadPromptPart(name, value) {
    setHeadPromptParts((current) => ({ ...current, [name]: value }));
  }

  async function toggleHeadPromptPartLock(name) {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const nextLockedPromptParts = { ...headLockedPromptParts, [name]: !headLockedPromptParts[name] };
    setHeadLockedPromptParts(nextLockedPromptParts);
    if (!profileId || busy) {
      return;
    }
    setActiveReferenceAction(`lock:head_face:${name}`);
    setLocalStatus("");
    try {
      const result = await onSaveHeadPrompt?.(profileId, {
        prompt: composeHeadFacePrompt(headPromptParts),
        prompt_parts: headPromptParts,
        locked_prompt_parts: nextLockedPromptParts,
        negative_prompt: headNegativePrompt,
      });
      if (result?.locked_prompt_parts && typeof result.locked_prompt_parts === "object") {
        setHeadLockedPromptParts(
          HEAD_FACE_PROMPT_PARTS.reduce(
            (parts, part) => ({ ...parts, [part.id]: Boolean(result.locked_prompt_parts?.[part.id]) }),
            {}
          )
        );
      }
      if (result) {
        setLocalStatus(result.status || "head_prompt_saved");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function saveHeadPreviewSeedSettings({ locked, seed }) {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const cleanSeed = String(seed || "").replace(/[^0-9]/g, "");
    setHeadPreviewSeedLocked(Boolean(locked));
    setHeadPreviewSeed(cleanSeed);
    if (!profileId || busy) {
      return;
    }
    setActiveReferenceAction("seed:head_face");
    setLocalStatus("");
    try {
      const result = await onSaveHeadPrompt?.(profileId, {
        prompt: composeHeadFacePrompt(headPromptParts),
        prompt_parts: headPromptParts,
        locked_prompt_parts: headLockedPromptParts,
        negative_prompt: headNegativePrompt,
        preview_seed: cleanSeed || null,
        preview_seed_locked: Boolean(locked),
      });
      const workspace = result?.workspace && typeof result.workspace === "object" ? result.workspace : {};
      if (result?.preview_seed !== undefined || workspace.preview_seed !== undefined) {
        const savedSeed = result?.preview_seed ?? workspace.preview_seed;
        setHeadPreviewSeed(savedSeed === null || savedSeed === undefined ? "" : String(savedSeed));
      }
      if (result?.preview_seed_locked !== undefined || workspace.preview_seed_locked !== undefined) {
        setHeadPreviewSeedLocked(Boolean(result?.preview_seed_locked ?? workspace.preview_seed_locked));
      }
      if (result) {
        setLocalStatus(result.status || "head_prompt_saved");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  function toggleHeadPreviewSeedLock(locked) {
    const seed = String(headPreviewSeed || latestHeadPreview?.seed || "").trim();
    saveHeadPreviewSeedSettings({ locked, seed });
  }

  function insertHeadPromptPartTag(name) {
    const part = HEAD_FACE_PROMPT_PARTS.find((item) => item.id === name);
    if (!part) {
      return;
    }
    const tag = `${part.label}: `;
    const lines = String(headInstruction || "").split(/\r?\n/);
    const hasTag = lines.some((line) => {
      const key = String(line.split(":")[0] || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
      return HEAD_FACE_PROMPT_PART_ALIASES.get(key) === name;
    });
    if (hasTag) {
      return;
    }
    updateHeadInstruction([headInstruction.trim(), tag].filter(Boolean).join("\n"));
  }

  async function applyHeadTaggedAdjustments() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const updates = parseHeadFaceTaggedAdjustments(headInstruction);
    const updateEntries = Object.entries(updates).filter(([partId, value]) => value && !headLockedPromptParts[partId]);
    if (!profileId || !updateEntries.length || busy) {
      return;
    }
    const nextPromptParts = {
      ...headPromptParts,
      ...Object.fromEntries(updateEntries),
    };
    setActiveReferenceAction("adjust:head_face");
    setLocalStatus("");
    try {
      const result = await onSaveHeadPrompt?.(profileId, {
        prompt: composeHeadFacePrompt(nextPromptParts),
        prompt_parts: nextPromptParts,
        locked_prompt_parts: headLockedPromptParts,
        negative_prompt: headNegativePrompt,
      });
      if (result?.prompt_parts && typeof result.prompt_parts === "object") {
        setHeadPromptParts(
          HEAD_FACE_PROMPT_PARTS.reduce(
            (parts, part) => ({ ...parts, [part.id]: String(result.prompt_parts?.[part.id] ?? nextPromptParts[part.id] ?? "") }),
            {}
          )
        );
      } else {
        setHeadPromptParts(nextPromptParts);
      }
      if (result) {
        setHeadAssistantReply(
          `Applied tagged edits to ${updateEntries
            .map(([partId]) => HEAD_FACE_PROMPT_PARTS.find((part) => part.id === partId)?.label || partId)
            .join(", ")}.`
        );
        updateHeadInstruction("");
        setLocalStatus(result.status || "head_prompt_saved");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function applyHeadPreviewPromptPartLock(name) {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const previewValue = compactPromptText(selectedHeadPreviewPromptParts[name]);
    if (!profileId || !previewValue || busy) {
      return;
    }
    const nextPromptParts = { ...headPromptParts, [name]: previewValue };
    const nextLockedPromptParts = { ...headLockedPromptParts, [name]: true };
    setActiveReferenceAction(`lock:head_face:${name}`);
    setLocalStatus("");
    try {
      const result = await onSaveHeadPrompt?.(profileId, {
        prompt: composeHeadFacePrompt(nextPromptParts),
        prompt_parts: nextPromptParts,
        locked_prompt_parts: nextLockedPromptParts,
        negative_prompt: headNegativePrompt,
      });
      if (result?.prompt_parts && typeof result.prompt_parts === "object") {
        setHeadPromptParts(
          HEAD_FACE_PROMPT_PARTS.reduce(
            (parts, part) => ({ ...parts, [part.id]: String(result.prompt_parts?.[part.id] ?? nextPromptParts[part.id] ?? "") }),
            {}
          )
        );
      } else {
        setHeadPromptParts(nextPromptParts);
      }
      if (result?.locked_prompt_parts && typeof result.locked_prompt_parts === "object") {
        setHeadLockedPromptParts(
          HEAD_FACE_PROMPT_PARTS.reduce(
            (parts, part) => ({ ...parts, [part.id]: Boolean(result.locked_prompt_parts?.[part.id]) }),
            {}
          )
        );
      } else {
        setHeadLockedPromptParts(nextLockedPromptParts);
      }
      setLocalStatus(result?.status || "head_prompt_saved");
    } finally {
      setActiveReferenceAction("");
    }
  }

  function updateHeadInstruction(value) {
    const key = headInstructionDraftKey(routeProfile, routeProfileId);
    if (key) {
      HEAD_INSTRUCTION_DRAFTS.set(key, value);
    }
    setHeadInstruction(value);
  }

  function openHeadPreviewDetails(preview, output) {
    if (!preview) {
      return;
    }
    setSelectedHeadPreview({ preview, output });
  }

  function resetGenerationDefaults() {
    if (!routeProfile) {
      return;
    }
    setGenerationState(generationEditorState(routeProfile));
    setLocalStatus("generation_defaults_loaded");
  }

  async function saveProfile(event) {
    event.preventDefault();
    if (!canSave) {
      return;
    }
    setLocalStatus("");
    const saveResult = await onSaveProfile?.({
      name: characterName.trim(),
      description: "",
      gender: gender.trim(),
      skin_color: skinColor.trim(),
      hair_color: hairColor.trim(),
      character_type: characterType.trim(),
      visual_style: visualStyle.trim(),
      nsfw: Boolean(nsfw),
    });
    if (saveResult?.profile) {
      setLocalStatus("saved");
      setActiveTab("saved_profiles");
    }
  }

  async function runProfileAction(action, profileId, callback) {
    const normalized = String(profileId || "").trim();
    if (!normalized || busy) {
      return;
    }
    setActiveProfileAction(`${action}:${normalized}`);
    setLocalStatus("");
    const actionResult = await callback?.(normalized);
    if (actionResult) {
      setLocalStatus(action);
    }
    setActiveProfileAction("");
  }

  async function saveExtractionEdits(event) {
    event.preventDefault();
    if (!routeProfile?.profile_id || busy) {
      return;
    }
    setLocalStatus("");
    try {
      const payload = buildExtractionUpdatePayload(editorState);
      const updateResult = await onUpdateProfileExtraction?.(routeProfile.profile_id, payload);
      if (updateResult) {
        setLocalStatus("saved");
      }
    } catch (err) {
      setLocalStatus("invalid_json");
    }
  }

  async function uploadReferenceFiles(role, files) {
    const selectedFiles = Array.from(files || []);
    if (!routeProfile?.profile_id || !selectedFiles.length || busy) {
      return;
    }
    setActiveReferenceAction(`upload:${role}`);
    setLocalStatus("");
    try {
      for (const file of selectedFiles) {
        const dataBase64 = await fileToDataUrl(file);
        await onUploadProfileReference?.(routeProfile.profile_id, {
          role,
          name: file.name ? file.name.replace(/\.[^.]+$/, "") : role,
          filename: file.name || `${role}.png`,
          data_base64: dataBase64,
        });
      }
      setLocalStatus("uploaded");
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function deleteReference(role, filename) {
    if (!routeProfile?.profile_id || !filename || busy) {
      return;
    }
    setActiveReferenceAction(`delete:${role}:${filename}`);
    setLocalStatus("");
    try {
      const result = await onDeleteProfileReference?.(routeProfile.profile_id, role, filename);
      if (result) {
        setLocalStatus("deleted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function generateBodyDepthProfile() {
    if (!routeProfile?.profile_id || busy) {
      return;
    }
    const sources = rawBodyReferences(routeProfile).map((reference) => String(reference.filename || "").trim()).filter(Boolean);
    setActiveReferenceAction("generate:body_depth");
    setLocalStatus("");
    try {
      const result = await onGenerateBodyDepthProfile?.(routeProfile.profile_id, {
        source_filenames: sources.length ? sources : null,
        width: 768,
        height: 1152,
        depth_resolution: 1024,
        replace_source_images: true,
      });
      if (result) {
        setLocalStatus("submitted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function setPrimaryFace(filename) {
    if (!routeProfile?.profile_id || !filename || busy) {
      return;
    }
    setActiveReferenceAction(`primary:face:${filename}`);
    setLocalStatus("");
    try {
      const result = await onSetPrimaryFace?.(routeProfile.profile_id, filename);
      if (result) {
        setLocalStatus("primary_face_selected");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function refineHeadPrompt(event, targetPromptPart = "") {
    event.preventDefault();
    if (!targetPromptPart && hasHeadTaggedAdjustments) {
      await applyHeadTaggedAdjustments();
      return;
    }
    const profileId = String(routeProfile?.profile_id || "").trim();
    const userMessage = headInstruction.trim();
    if (!profileId || !userMessage || busy) {
      return;
    }
    const normalizedTargetPromptPart = HEAD_FACE_PROMPT_PARTS.some((part) => part.id === targetPromptPart)
      ? targetPromptPart
      : "";
    if (normalizedTargetPromptPart && headLockedPromptParts[normalizedTargetPromptPart]) {
      return;
    }
    setActiveReferenceAction(normalizedTargetPromptPart ? `refine:head_face:${normalizedTargetPromptPart}` : "refine:head_face");
    setLocalStatus("");
    try {
      const result = await onRefineHeadPrompt?.(profileId, {
        current_prompt: headPrompt,
        prompt_parts: headPromptParts,
        locked_prompt_parts: headLockedPromptParts,
        target_prompt_part: normalizedTargetPromptPart || null,
        negative_prompt: headNegativePrompt,
        user_message: userMessage,
      });
      let refinedPromptParts = headPromptParts;
      let refinedNegativePrompt = headNegativePrompt;
      if (result?.prompt_parts && typeof result.prompt_parts === "object") {
        refinedPromptParts = HEAD_FACE_PROMPT_PARTS.reduce(
          (parts, part) => ({ ...parts, [part.id]: String(result.prompt_parts?.[part.id] ?? headPromptParts[part.id] ?? "") }),
          {}
        );
        setHeadPromptParts(refinedPromptParts);
      }
      if (result?.locked_prompt_parts && typeof result.locked_prompt_parts === "object") {
        setHeadLockedPromptParts(
          HEAD_FACE_PROMPT_PARTS.reduce(
            (parts, part) => ({ ...parts, [part.id]: Boolean(result.locked_prompt_parts?.[part.id]) }),
            {}
          )
        );
      }
      if (result?.negative_prompt !== undefined) {
        refinedNegativePrompt = String(result.negative_prompt || "");
        setHeadNegativePrompt(refinedNegativePrompt);
      }
      if (result?.assistant_reply !== undefined) {
        setHeadAssistantReply(String(result.assistant_reply || ""));
      }
      if (result) {
        updateHeadInstruction("");
        setActiveReferenceAction("preview:head_face");
        const previewResult = await submitHeadPreview({
          profileId,
          promptParts: refinedPromptParts,
          negativePrompt: refinedNegativePrompt,
        });
        const previewSeed = previewResult?.preview?.seed === null || previewResult?.preview?.seed === undefined ? "" : String(previewResult.preview.seed);
        if (previewSeed) {
          setHeadPreviewSeed(previewSeed);
        }
        if (previewResult?.preview?.seed_locked !== undefined) {
          setHeadPreviewSeedLocked(Boolean(previewResult.preview.seed_locked));
        }
        setLocalStatus(previewResult?.status || "preview_submitted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  function submitHeadPromptShortcut(event) {
    if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    if (hasHeadTaggedAdjustments) {
      applyHeadTaggedAdjustments();
      return;
    }
    refineHeadPrompt(event);
  }

  async function submitHeadPreview({ profileId, promptParts, negativePrompt }) {
    const prompt = composeHeadFacePrompt(promptParts);
    const seed = String(headPreviewSeed || latestHeadPreview?.seed || "").trim();
    return onCreateHeadPreview?.(profileId, {
      prompt,
      prompt_parts: promptParts,
      locked_prompt_parts: headLockedPromptParts,
      negative_prompt: negativePrompt,
      seed: headPreviewSeedLocked && seed ? seed : null,
      lock_seed: headPreviewSeedLocked,
    });
  }

  async function createHeadPreview() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    if (!profileId || !headPrompt.trim() || busy) {
      return;
    }
    setActiveReferenceAction("preview:head_face");
    setLocalStatus("");
    try {
      const result = await submitHeadPreview({
        profileId,
        promptParts: headPromptParts,
        negativePrompt: headNegativePrompt,
      });
      if (result) {
        const resultSeed = result?.preview?.seed === null || result?.preview?.seed === undefined ? "" : String(result.preview.seed);
        if (resultSeed) {
          setHeadPreviewSeed(resultSeed);
        }
        if (result?.preview?.seed_locked !== undefined) {
          setHeadPreviewSeedLocked(Boolean(result.preview.seed_locked));
        }
        setLocalStatus(result.status || "preview_submitted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function submitHeadSeedBatch(keepPreviewIds = [], preserveExisting = false, overrides = {}) {
    const profileId = String(routeProfile?.profile_id || "").trim();
    if (!profileId || !headPrompt.trim() || busy) {
      return null;
    }
    setShowHeadSeedBatch(true);
    setActiveReferenceAction("seed_batch:head_face");
    setLocalStatus("");
    try {
      const result = await onCreateHeadSeedBatch?.(profileId, {
        prompt: headPrompt,
        prompt_parts: headPromptParts,
        locked_prompt_parts: headLockedPromptParts,
        negative_prompt: headNegativePrompt,
        keep_preview_ids: keepPreviewIds,
        preserve_existing: preserveExisting,
        batch_size: 20,
        ...overrides,
      });
      if (result?.batch?.previews) {
        setHeadSeedBatchKeepIds(
          asArray(result.batch.previews)
            .filter((preview) => Boolean(preview?.kept))
            .map((preview) => String(preview?.preview_id || ""))
            .filter(Boolean)
        );
      }
      if (result) {
        setLocalStatus(result.status || "seed_batch_submitted");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  function toggleHeadSeedBatchKeep(previewId) {
    const normalized = String(previewId || "").trim();
    if (!normalized) {
      return;
    }
    setHeadSeedBatchKeepIds((current) =>
      current.includes(normalized)
        ? current.filter((item) => item !== normalized)
        : [...current, normalized]
    );
  }

  function regenerateRejectedHeadSeedBatch() {
    if (headSeedBatchNeedsMore) {
      submitHeadSeedBatch(headSeedBatchKeepIds, true);
      return;
    }
    submitHeadSeedBatch(headSeedBatchKeepIds, false);
  }

  function updateHeadSeedBatchManualSeed(previewId, value) {
    const normalized = String(previewId || "").trim();
    if (!normalized) {
      return;
    }
    setHeadSeedBatchManualSeeds((current) => ({
      ...current,
      [normalized]: String(value || "").replace(/[^0-9]/g, ""),
    }));
  }

  async function regenerateHeadSeedBatchCandidateWithSeed(previewId) {
    const normalized = String(previewId || "").trim();
    const manualSeed = String(headSeedBatchManualSeeds[normalized] || "").trim();
    if (!normalized || !manualSeed) {
      return;
    }
    const result = await submitHeadSeedBatch(headSeedBatchKeepIds, true, {
      manual_seed_preview_id: normalized,
      manual_seed: manualSeed,
    });
    if (result) {
      setHeadSeedBatchManualSeeds((current) => ({ ...current, [normalized]: "" }));
    }
  }

  async function selectHeadSeedBatchCandidateForJitter(previewId) {
    const normalized = String(previewId || "").trim();
    if (!normalized) {
      return;
    }
    await submitHeadSeedBatch(headSeedBatchKeepIds, true, {
      selected_preview_id: normalized,
    });
  }

  async function submitHeadJitterBatch(overrides = {}) {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const anchorSeed = String(headSeedBatch.selected_seed || "").trim();
    if (!profileId || !headPrompt.trim() || !anchorSeed || busy) {
      return null;
    }
    setShowHeadJitterBatch(true);
    setActiveReferenceAction("jitter_batch:head_face");
    setLocalStatus("");
    try {
      const result = await onCreateHeadJitterBatch?.(profileId, {
        prompt: headPrompt,
        prompt_parts: headPromptParts,
        locked_prompt_parts: headLockedPromptParts,
        negative_prompt: headNegativePrompt,
        anchor_preview_id: headSeedBatch.selected_preview_id || null,
        anchor_seed: anchorSeed,
        batch_size: 20,
        ...overrides,
      });
      if (result) {
        setLocalStatus(result.status || "jitter_batch_queued");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  function openHeadJitterBatch() {
    if (headJitterBatchPreviews.length) {
      setShowHeadJitterBatch(true);
      return;
    }
    submitHeadJitterBatch();
  }

  function toggleHeadJitterCandidateApproval(previewId) {
    const normalized = String(previewId || "").trim();
    if (!normalized) {
      return;
    }
    const approved = new Set(headJitterApprovedIds);
    if (approved.has(normalized)) {
      approved.delete(normalized);
    } else {
      approved.add(normalized);
    }
    submitHeadJitterBatch({
      preserve_existing: true,
      approved_preview_ids: Array.from(approved),
    });
  }

  function regenerateRejectedHeadJitterCandidates() {
    const rejected = headJitterBatchPreviews
      .map((preview) => String(preview?.preview_id || ""))
      .filter((previewId) => previewId && !headJitterApprovedIds.has(previewId));
    submitHeadJitterBatch({
      preserve_existing: true,
      approved_preview_ids: Array.from(headJitterApprovedIds),
      rejected_preview_ids: rejected,
    });
  }

  function rejectHeadJitterCandidate(previewId) {
    const normalized = String(previewId || "").trim();
    if (!normalized) {
      return;
    }
    submitHeadJitterBatch({
      preserve_existing: true,
      approved_preview_ids: Array.from(headJitterApprovedIds),
      rejected_preview_ids: [normalized],
    });
  }

  async function saveHeadLoraSeeds() {
    const result = await submitHeadJitterBatch({
      preserve_existing: true,
      approved_preview_ids: Array.from(headJitterApprovedIds),
      save_lora_seeds: true,
    });
    if (result) {
      setShowHeadLoraPopup(true);
    }
  }

  async function updateHeadLoraDataset(overrides = {}) {
    const profileId = String(routeProfile?.profile_id || "").trim();
    if (!profileId || busy || !headLoraAvailable) {
      return null;
    }
    setActiveReferenceAction("lora_dataset:head_face");
    setLocalStatus("");
    try {
      const result = await onUpdateHeadLoraDataset?.(profileId, {
        prompt: headPrompt,
        prompt_parts: headPromptParts,
        locked_prompt_parts: headLockedPromptParts,
        negative_prompt: headNegativePrompt,
        ...overrides,
      });
      if (result) {
        setLocalStatus(result.status || "lora_dataset_updated");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function uploadHeadLoraDatasetFromFolder() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const sourceDir = String(headLoraDatasetSourceDir || "").trim();
    if (!profileId || !sourceDir || busy) {
      return null;
    }
    setActiveReferenceAction("upload_lora_dataset:head_face");
    setLocalStatus("");
    try {
      const result = await onUploadHeadLoraDataset?.(profileId, {
        source_dir: sourceDir,
        replace: true,
      });
      if (result) {
        setLocalStatus(result.status || "lora_dataset_uploaded");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function uploadHeadExternalLoraFromFile() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const sourcePath = String(headLoraExternalPath || "").trim();
    if (!profileId || !sourcePath || busy) {
      return null;
    }
    setActiveReferenceAction("upload_lora:head_face");
    setLocalStatus("");
    try {
      const result = await onUploadHeadLora?.(profileId, {
        source_path: sourcePath,
        source_label: "external",
        activate: true,
      });
      if (result) {
        setLocalStatus(result.status || "lora_uploaded");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function uploadUpperTorsoLoraDatasetFromFolder() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const sourceDir = String(upperTorsoLoraDatasetSourceDir || "").trim();
    if (!profileId || !sourceDir || busy) {
      return null;
    }
    setActiveReferenceAction("upload_lora_dataset:upper_torso");
    setLocalStatus("");
    try {
      const result = await onUploadUpperTorsoLoraDataset?.(profileId, {
        source_dir: sourceDir,
        replace: true,
      });
      if (result) {
        setLocalStatus(result.status || "lora_dataset_uploaded");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function uploadUpperTorsoExternalLoraFromFile() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const sourcePath = String(upperTorsoLoraExternalPath || "").trim();
    if (!profileId || !sourcePath || busy) {
      return null;
    }
    setActiveReferenceAction("upload_lora:upper_torso");
    setLocalStatus("");
    try {
      const result = await onUploadUpperTorsoLora?.(profileId, {
        source_path: sourcePath,
        source_label: "external",
        activate: true,
      });
      if (result) {
        setLocalStatus(result.status || "lora_uploaded");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function startUpperTorsoLoraTraining() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    if (!profileId || busy || !upperTorsoReadyForTraining || upperTorsoTrainingRunning) {
      return null;
    }
    setActiveReferenceAction("lora_dataset:upper_torso");
    setLocalStatus("");
    try {
      const result = await onUpdateUpperTorsoLoraDataset?.(profileId, {
        action: "train_lora",
        prompt: upperTorsoPrompt,
        prompt_parts: upperTorsoPromptParts,
        negative_prompt: upperTorsoNegativePrompt,
      });
      if (result) {
        setLocalStatus(result.status || "upper_torso_lora_training_started");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function generateUpperTorsoLoraEpochReview() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    if (!profileId || busy || !upperTorsoTrainingJob.output_model) {
      return null;
    }
    setActiveReferenceAction("epoch_review:upper_torso");
    setLocalStatus("");
    try {
      const result = await onUpdateUpperTorsoLoraDataset?.(profileId, {
        action: "generate_epoch_review",
        prompt: upperTorsoPrompt,
        prompt_parts: upperTorsoPromptParts,
        negative_prompt: upperTorsoNegativePrompt,
      });
      if (result) {
        setLocalStatus(result.status || "upper_torso_lora_epoch_review_queued");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function selectUpperTorsoLoraEpochReview(previewId) {
    const profileId = String(routeProfile?.profile_id || "").trim();
    const itemId = String(previewId || "").trim();
    if (!profileId || !itemId || busy) {
      return null;
    }
    setActiveReferenceAction("epoch_review:upper_torso");
    setLocalStatus("");
    try {
      const result = await onUpdateUpperTorsoLoraDataset?.(profileId, {
        action: "select_epoch_review",
        item_id: itemId,
      });
      if (result) {
        setLocalStatus(result.status || "upper_torso_lora_epoch_review_selected");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function createUpperTorsoPreview() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    if (!profileId || busy) {
      return null;
    }
    setActiveReferenceAction("preview:upper_torso");
    setLocalStatus("");
    try {
      const result = await onCreateUpperTorsoPreview?.(profileId, {
        prompt: upperTorsoPrompt,
        prompt_parts: upperTorsoPromptParts,
        negative_prompt: upperTorsoNegativePrompt,
      });
      if (result) {
        setLocalStatus(result.status || "upper_torso_preview_submitted");
      }
      return result;
    } finally {
      setActiveReferenceAction("");
    }
  }

  function openHeadLoraDataset() {
    setShowHeadLoraPopup(true);
    if (!headLoraDatasetPoses.length) {
      updateHeadLoraDataset({ action: "ensure" });
    }
  }

  function reviewHeadLoraDatasetItem(itemId, action) {
    updateHeadLoraDataset({ action, item_id: itemId });
  }

  function nextHeadLoraDatasetPose() {
    updateHeadLoraDataset({ action: "next" });
  }

  function retryHeadLoraVision() {
    updateHeadLoraDataset({ action: "retry_vision" });
  }

  function resetHeadLoraPose() {
    const label = headLoraActivePose.label || "current pose";
    if (!window.confirm(`Delete generated images for ${label} and start this pose over?`)) {
      return;
    }
    updateHeadLoraDataset({ action: "reset_pose" });
  }

  function startHeadLoraTraining() {
    updateHeadLoraDataset({ action: "train_lora" });
  }

  function generateHeadLoraEpochReview() {
    updateHeadLoraDataset({ action: "generate_epoch_review" });
  }

  function selectHeadLoraEpochReview(previewId) {
    updateHeadLoraDataset({ action: "select_epoch_review", item_id: previewId });
  }

  async function submitGeneration(event) {
    event.preventDefault();
    if (!routeProfile?.profile_id || busy || generationBusy) {
      return;
    }
    const prompt = buildAvatarGenerationPrompt(generationState);
    const templateId = String(generationState.template_id || "").trim() || AVATAR_PROFILE_TEMPLATE_ID;
    const faceReferenceImage = String(generationState.face_reference_image || "").trim();
    const bodyReferenceImage = String(generationState.body_reference_image || "").trim();
    const bodyDepthImage = String(generationState.body_depth_image || "").trim();
    const poseReferenceImage = String(generationState.pose_reference_image || "").trim();
    if (!prompt || !faceReferenceImage) {
      return;
    }
    if (templateId === AVATAR_PROFILE_TEMPLATE_ID && (!bodyDepthImage || !poseReferenceImage)) {
      return;
    }
    if (templateId === AVATAR_BODY_REFERENCE_TEMPLATE_ID && !bodyReferenceImage) {
      return;
    }
    const integerValue = (value, fallback = undefined) => {
      const text = String(value ?? "").trim();
      if (!text) {
        return fallback;
      }
      const parsed = Number.parseInt(text, 10);
      return Number.isFinite(parsed) ? parsed : fallback;
    };
    const numberValue = (value, fallback = undefined) => {
      const text = String(value ?? "").trim();
      if (!text) {
        return fallback;
      }
      const parsed = Number.parseFloat(text);
      return Number.isFinite(parsed) ? parsed : fallback;
    };
    const templateVariables = {
      avatar_name: profileName(routeProfile),
      face_reference_image: faceReferenceImage,
      face_strength: numberValue(generationState.face_strength, 0.8),
      body_depth_strength: numberValue(generationState.body_depth_strength, 0.8),
      body_depth_start: numberValue(generationState.body_depth_start, 0),
      body_depth_end: numberValue(generationState.body_depth_end, 0.9),
    };
    if (templateId === AVATAR_PROFILE_TEMPLATE_ID) {
      templateVariables.body_depth_image = bodyDepthImage;
      templateVariables.pose_reference_image = poseReferenceImage;
      templateVariables.pose_strength = numberValue(generationState.pose_strength, 0.65);
      templateVariables.pose_start = numberValue(generationState.pose_start, 0);
      templateVariables.pose_end = numberValue(generationState.pose_end, 0.8);
    } else {
      templateVariables.body_reference_image = bodyReferenceImage;
    }
    setActiveReferenceAction("generate:avatar");
    setLocalStatus("");
    try {
      const result = await onSubmitGeneration?.({
        template_id: templateId,
        mode: "txt2img",
        prompt,
        negative_prompt: generationState.negative,
        width: integerValue(generationState.width, 768),
        height: integerValue(generationState.height, 1152),
        seed: String(generationState.seed || "").trim() || null,
        steps: integerValue(generationState.steps, 4),
        cfg: numberValue(generationState.cfg, 1.2),
        denoise: numberValue(generationState.denoise, 1),
        batch_count: integerValue(generationState.batch_count, 1),
        randomize_seed: Boolean(generationState.randomize_seed),
        randomize_reference_strengths: Boolean(generationState.randomize_reference_strengths),
        reference_strength_jitter: numberValue(generationState.reference_strength_jitter, 0.05),
        create_lora_metadata: Boolean(generationState.create_lora_metadata),
        template_variables: templateVariables,
      });
      if (result) {
        setLocalStatus("generation_submitted");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  function renderReferenceCards(role, references = profileReferences(routeProfile, role)) {
    if (!references.length) {
      return <p className="muted tiny">No saved references.</p>;
    }
    return (
      <div className="avatar-reference-card-grid">
        {references.map((reference) => {
          const filename = String(reference.filename || "").trim();
          return (
            <article className="avatar-reference-card" key={`${role}:${filename}`}>
              {reference.url ? (
                <a href={profileImageUrl(apiBase, reference.url)} target="_blank" rel="noreferrer">
                  <img src={profileImageUrl(apiBase, reference.url)} alt={reference.name || filename} />
                </a>
              ) : null}
              <div>
                <strong>{reference.name || filename}</strong>
                <span>{reference.created_at || filename}</span>
                {role === "face" && reference.primary ? <StatusBadge value="primary" /> : null}
              </div>
              {role === "face" && !reference.primary ? (
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={() => setPrimaryFace(filename)}
                >
                  {activeReferenceAction === `primary:face:${filename}` ? "Selecting..." : "Set Primary"}
                </button>
              ) : null}
              <button
                className="btn btn-danger"
                type="button"
                disabled={busy}
                onClick={() => deleteReference(role, filename)}
              >
                {activeReferenceAction === `delete:${role}:${filename}` ? "Deleting..." : "Delete"}
              </button>
            </article>
          );
        })}
      </div>
    );
  }

  if (detailMode) {
    if (!routeProfile) {
      return (
        <article className="card operational-card-full-span">
          <div className="avatar-profile-detail-header">
            <CardHeader title="Avatar Generation" subtitle="Profile not found." />
            <div className="avatar-profile-detail-controls">
              <button className="btn" type="button" onClick={onBackToProfiles}>
                Back
              </button>
              <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
                Refresh
              </button>
            </div>
          </div>
        </article>
      );
    }

    const generationFaceOptions = faceReferenceOptions(routeProfile);
    const generationBodyOptions = bodyReferenceOptions(routeProfile);
    const generationDepthOptions = bodyDepthMapOptions(routeProfile);
    const generationPoseOptions = poseReferenceOptions(routeProfile);
    const selectedFaceOption = selectedReferenceOption(generationFaceOptions, generationState.face_reference_image);
    const selectedBodyOption = selectedReferenceOption(generationBodyOptions, generationState.body_reference_image);
    const selectedDepthOption = selectedReferenceOption(generationDepthOptions, generationState.body_depth_image);
    const selectedPoseOption = selectedReferenceOption(generationPoseOptions, generationState.pose_reference_image);
    const generationPrompt = buildAvatarGenerationPrompt(generationState);
    const usesProfileDepthTemplate = generationState.template_id === AVATAR_PROFILE_TEMPLATE_ID;
    const canSubmitGeneration =
      Boolean(generationPrompt) &&
      Boolean(generationState.face_reference_image) &&
      (usesProfileDepthTemplate
        ? Boolean(generationState.body_depth_image) && Boolean(generationState.pose_reference_image)
        : Boolean(generationState.body_reference_image)) &&
      !busy &&
      !generationBusy;
    const renderGenerationPreview = (option, label) => (
      <div className={option?.inputImage ? "manual-reference-summary-item is-ready" : "manual-reference-summary-item"} key={label}>
        <span>{label}</span>
        {option?.url ? (
          <a href={profileImageUrl(apiBase, option.url)} target="_blank" rel="noreferrer">
            <img src={profileImageUrl(apiBase, option.url)} alt={option.label || label} />
          </a>
        ) : null}
        <code>{option?.label || "none"}</code>
      </div>
    );

    return (
      <article className="card operational-card-full-span avatar-profile-detail">
        <div className="avatar-profile-detail-header">
          <div className="avatar-profile-detail-title">
            <CardHeader title={profileName(routeProfile)} subtitle="Avatar Generation" />
            {localStatus ? <StatusBadge value={localStatus} /> : null}
          </div>
          <div className="avatar-profile-detail-controls">
            <button className="btn" type="button" onClick={onBackToProfiles}>
              Back
            </button>
            <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
              Refresh
            </button>
            <div className="avatar-generation-tabs" role="tablist" aria-label="Avatar profile tabs">
              {AVATAR_PROFILE_DETAIL_TABS.map((tab) => (
                <button
                  className={activeDetailTab === tab.id ? "btn btn-primary" : "btn"}
                  key={tab.id}
                  onClick={() => selectDetailTab(tab.id)}
                  role="tab"
                  type="button"
                  aria-selected={activeDetailTab === tab.id}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {selectedHeadPreview ? (
          <section
            className="modal-overlay avatar-preview-modal-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="Head face preview details"
            onClick={() => setSelectedHeadPreview(null)}
          >
            <article className="card modal-card avatar-preview-modal-card" onClick={(event) => event.stopPropagation()}>
              <div className="avatar-preview-modal-header">
                <CardHeader title="Head / Face Preview" subtitle={selectedHeadPreview.preview?.created_at || "preview metadata"} />
                <button className="btn" type="button" onClick={() => setSelectedHeadPreview(null)}>
                  Close
                </button>
              </div>
              <div className="avatar-preview-modal-body">
                <div className="avatar-preview-modal-image-panel">
                  {selectedHeadPreview.output ? (
                    <>
                      <img
                        src={`${apiBase}${selectedHeadPreview.output.url}`}
                        alt={selectedHeadPreview.output.filename || selectedHeadPreview.output.relative_path}
                      />
                      <a className="btn" href={`${apiBase}${selectedHeadPreview.output.url}`} target="_blank" rel="noreferrer">
                        Open Image
                      </a>
                    </>
                  ) : (
                    <div className="avatar-head-face-preview-placeholder">
                      <StatusBadge value={selectedHeadPreview.preview?.status || "submitted"} />
                    </div>
                  )}
                </div>
                <div className="avatar-preview-modal-data">
                  <div className="avatar-preview-modal-meta">
                    <div>
                      <span>Status</span>
                      <code>{selectedHeadPreview.preview?.status || "submitted"}</code>
                    </div>
                    <div>
                      <span>Prompt</span>
                      <code>{selectedHeadPreview.preview?.prompt_id || "pending"}</code>
                    </div>
                    <div>
                      <span>Seed</span>
                      <code>{selectedHeadPreview.preview?.seed || "pending"}</code>
                    </div>
                    <div>
                      <span>Created</span>
                      <code>{selectedHeadPreview.preview?.created_at || "not_saved"}</code>
                    </div>
                  </div>
                  <div className="avatar-preview-modal-prompt-parts">
                    {HEAD_FACE_PROMPT_PARTS.map((part) => {
                      const previewValue = compactPromptText(selectedHeadPreviewPromptParts[part.id]);
                      const isLockedToPreview =
                        Boolean(headLockedPromptParts[part.id]) &&
                        compactPromptText(headPromptParts[part.id]) === previewValue;
                      return (
                        <div
                          className={`avatar-head-face-part-field avatar-head-face-part-${part.id}`}
                          key={part.id}
                        >
                          <div className="avatar-head-face-part-title">
                            <label htmlFor={`avatar-head-face-preview-${part.id}`}>{part.label}</label>
                            <button
                              className={`avatar-head-face-lock-button${isLockedToPreview ? " is-locked" : ""}`}
                              type="button"
                              onClick={() => applyHeadPreviewPromptPartLock(part.id)}
                              disabled={busy || !previewValue || isLockedToPreview}
                              aria-pressed={isLockedToPreview}
                              aria-label={`Use and lock ${part.label} from this preview`}
                              title="Use this preview value and lock it"
                            >
                              {activeReferenceAction === `lock:head_face:${part.id}`
                                ? "Saving..."
                                : isLockedToPreview
                                  ? "Locked"
                                  : "Use & Lock"}
                            </button>
                          </div>
                          <textarea
                            id={`avatar-head-face-preview-${part.id}`}
                            rows={part.rows}
                            readOnly
                            value={String(selectedHeadPreviewPromptParts[part.id] || "")}
                          />
                        </div>
                      );
                    })}
                  </div>
                  <label className="avatar-generation-wide-field">
                    Negative Prompt
                    <textarea rows={4} readOnly value={selectedHeadPreviewNegativePrompt} />
                  </label>
                </div>
              </div>
            </article>
          </section>
        ) : null}

        {showHeadSeedBatch ? (
          <section
            className="modal-overlay avatar-preview-modal-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="Head face seed batch"
            onClick={() => setShowHeadSeedBatch(false)}
          >
            <article className="card modal-card avatar-seed-batch-modal-card" onClick={(event) => event.stopPropagation()}>
              <div className="avatar-preview-modal-header">
                <CardHeader
                  title="Seed Batch"
                  subtitle={`${headSeedBatchReadyPreviews.length}/${headSeedBatchTargetCount} ready, ${headSeedBatchKeptCount} kept`}
                />
                <div className="row">
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || (!headSeedBatchPreviews.length && !headSeedBatchNeedsMore) || (!headSeedBatchNeedsMore && headSeedBatchKeptCount >= headSeedBatchTargetCount)}
                    onClick={regenerateRejectedHeadSeedBatch}
                  >
                    {activeReferenceAction === "seed_batch:head_face"
                      ? "Submitting..."
                      : headSeedBatchNeedsMore
                        ? "Generate More"
                        : "Regenerate Rejected"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || !headSeedBatch.selected_seed}
                    onClick={openHeadJitterBatch}
                  >
                    {activeReferenceAction === "jitter_batch:head_face" ? "Submitting..." : "LoRA Seed Map"}
                  </button>
                  <button className="btn" type="button" onClick={() => setShowHeadSeedBatch(false)}>
                    Close
                  </button>
                </div>
              </div>
              <div className="avatar-seed-batch-summary">
                <span>Batch</span>
                <code>{headSeedBatch.batch_id || "not_started"}</code>
                <span>Status</span>
                <StatusBadge value={headSeedBatch.status || "ready"} />
                <span>Remaining</span>
                <code>{Math.max(headSeedBatchTargetCount - headSeedBatchReadyPreviews.length, 0)}</code>
                <span>Selected</span>
                <code>{headSeedBatch.selected_seed ? `seed ${headSeedBatch.selected_seed}` : "none"}</code>
                <span>Prompt</span>
                <code>{compactPromptText(headSeedBatch.prompt || headPrompt).slice(0, 140)}</code>
              </div>
              {headSeedBatchPreviews.length ? (
                <div className="avatar-seed-batch-grid">
                  {headSeedBatchPreviews.map((preview, index) => {
                    const previewId = String(preview?.preview_id || `slot-${index}`);
                    const kept = headSeedBatchKeepSet.has(previewId);
                    const selectedForJitter = previewId === headSeedBatchSelectedPreviewId || Boolean(preview?.selected);
                    const output = headFacePreviewOutput(preview, manualOutputs, routeProfile);
                    return (
                      <article className={`avatar-seed-batch-card${kept ? " is-kept" : ""}${selectedForJitter ? " is-selected" : ""}`} key={previewId}>
                        {output ? (
                          <button
                            className="avatar-head-face-preview-button"
                            type="button"
                            onClick={() => openHeadPreviewDetails(preview, output)}
                            aria-label="Open seed batch preview details"
                          >
                            <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
                          </button>
                        ) : (
                          <div className="avatar-head-face-preview-placeholder avatar-head-face-preview-placeholder-small">
                            <StatusBadge value={preview?.status || "submitted"} />
                          </div>
                        )}
                        <div className="avatar-seed-batch-card-meta">
                          <strong>Slot {index + 1}</strong>
                          <code>{preview?.seed ? `seed ${preview.seed}` : "seed pending"}</code>
                          <StatusBadge value={preview?.status || "submitted"} />
                        </div>
                        <div className="row">
                          <button
                            className={kept ? "btn btn-primary" : "btn"}
                            type="button"
                            onClick={() => toggleHeadSeedBatchKeep(previewId)}
                          >
                            {kept ? "Kept" : "Keep"}
                          </button>
                          <button
                            className="btn"
                            type="button"
                            disabled={!preview?.seed || busy}
                            onClick={() => selectHeadSeedBatchCandidateForJitter(previewId)}
                          >
                            {selectedForJitter ? "Jitter Anchor" : "Select Jitter"}
                          </button>
                        </div>
                        <div className="avatar-seed-batch-manual-seed">
                          <label htmlFor={`avatar-seed-batch-manual-${previewId}`}>Manual Seed</label>
                          <div className="row">
                            <input
                              id={`avatar-seed-batch-manual-${previewId}`}
                              type="text"
                              inputMode="numeric"
                              value={headSeedBatchManualSeeds[previewId] || ""}
                              onChange={(event) => updateHeadSeedBatchManualSeed(previewId, event.target.value)}
                              placeholder="Seed"
                            />
                            <button
                              className="btn"
                              type="button"
                              disabled={busy || kept || !String(headSeedBatchManualSeeds[previewId] || "").trim()}
                              onClick={() => regenerateHeadSeedBatchCandidateWithSeed(previewId)}
                            >
                              Replace
                            </button>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <div className="empty-state">
                  <p>No seed batch yet.</p>
                  <button className="btn btn-primary" type="button" disabled={busy || !headPrompt.trim()} onClick={() => submitHeadSeedBatch([])}>
                    Start 20 Random Seeds
                  </button>
                </div>
              )}
            </article>
          </section>
        ) : null}

        {showHeadJitterBatch ? (
          <section
            className="modal-overlay avatar-preview-modal-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="Head face jitter batch"
            onClick={() => setShowHeadJitterBatch(false)}
          >
            <article className="card modal-card avatar-seed-batch-modal-card" onClick={(event) => event.stopPropagation()}>
              <div className="avatar-preview-modal-header">
                <CardHeader
                  title="LoRA Seed Map"
                  subtitle={`${headJitterApprovedCount}/${headJitterRequiredCount} approved, ${headJitterReadyPreviews.length}/${Number(headJitterBatch.target_count || 20)} ready`}
                />
                <div className="row">
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || !headSeedBatch.selected_seed}
                    onClick={() => submitHeadJitterBatch()}
                  >
                    {activeReferenceAction === "jitter_batch:head_face" ? "Submitting..." : "Start Map"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || !headJitterBatchPreviews.length}
                    onClick={regenerateRejectedHeadJitterCandidates}
                  >
                    Regenerate Rejected
                  </button>
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={busy || headJitterApprovedCount < headJitterRequiredCount}
                    onClick={saveHeadLoraSeeds}
                  >
                    Save LoRA Seeds
                  </button>
                  <button className="btn" type="button" onClick={() => setShowHeadJitterBatch(false)}>
                    Close
                  </button>
                </div>
              </div>
              <div className="avatar-seed-batch-summary avatar-jitter-batch-summary">
                <span>Batch</span>
                <code>{headJitterBatch.batch_id || "not_started"}</code>
                <span>Status</span>
                <StatusBadge value={headJitterBatch.status || "ready"} />
                <span>Remaining</span>
                <code>{Math.max(Number(headJitterBatch.target_count || 20) - headJitterReadyPreviews.length, 0)}</code>
                <span>Approved</span>
                <code>{headJitterApprovedCount}/{headJitterRequiredCount}</code>
                <span>Anchor</span>
                <code>{headJitterBatch.anchor_seed || headSeedBatch.selected_seed || "none"}</code>
              </div>
              {headJitterBatchPreviews.length ? (
                <div className="avatar-lora-seed-map-layout">
                  {[
                    ["Approved", headLoraSeedMapGroups.approved, "approved"],
                    ["Original", headLoraSeedMapGroups.original?.preview_id ? [headLoraSeedMapGroups.original] : [], "original"],
                    ["Pending Approval", headLoraSeedMapGroups.pending, "pending"],
                  ].map(([label, group, groupId]) => (
                    <section className={`avatar-lora-seed-map-column avatar-lora-seed-map-column-${groupId}`} key={groupId}>
                      <div className="avatar-lora-seed-map-column-title">
                        <span>{label}</span>
                        <code>{groupId === "pending" ? `${group.length}/${headLoraSeedMapGroups.pending_total}` : group.length}</code>
                      </div>
                      <div className="avatar-lora-seed-map-column-grid">
                        {group.map((preview, index) => {
                          const previewId = String(preview?.preview_id || `${groupId}-${index}`);
                          const approved = headJitterApprovedIds.has(previewId) || Boolean(preview?.approved);
                          const isOriginal = groupId === "original";
                          const output = headFacePreviewOutput(preview, manualOutputs, routeProfile);
                          return (
                            <article
                              className={`avatar-seed-batch-card${approved ? " is-acceptable" : ""}${isOriginal ? " is-selected" : ""}`}
                              key={previewId}
                            >
                              {output ? (
                                <button
                                  className="avatar-head-face-preview-button"
                                  type="button"
                                  onClick={() => openHeadPreviewDetails(preview, output)}
                                  aria-label="Open LoRA seed candidate details"
                                >
                                  <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
                                </button>
                              ) : (
                                <div className="avatar-head-face-preview-placeholder avatar-head-face-preview-placeholder-small">
                                  <StatusBadge value={preview?.status || "submitted"} />
                                </div>
                              )}
                              <div className="avatar-seed-batch-card-meta">
                                <strong>{isOriginal ? "Selected Seed" : `Candidate ${index + 1}`}</strong>
                                <code>{preview?.seed ? `seed ${preview.seed}` : "seed pending"}</code>
                                <StatusBadge value={preview?.status || "submitted"} />
                              </div>
                              {isOriginal ? null : (
                                <div className="row">
                                  <button
                                    className={approved ? "btn btn-primary" : "btn"}
                                    type="button"
                                    disabled={busy}
                                    onClick={() => toggleHeadJitterCandidateApproval(previewId)}
                                  >
                                    {approved ? "Approved" : "Approve"}
                                  </button>
                                  {!approved ? (
                                    <button
                                      className="btn"
                                      type="button"
                                      disabled={busy}
                                      onClick={() => rejectHeadJitterCandidate(previewId)}
                                    >
                                      Reject
                                    </button>
                                  ) : null}
                                </div>
                              )}
                            </article>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>
              ) : (
                <div className="empty-state">
                  <p>No LoRA seed map yet.</p>
                  <button className="btn btn-primary" type="button" disabled={busy || !headSeedBatch.selected_seed} onClick={() => submitHeadJitterBatch()}>
                    Start LoRA Seed Map
                  </button>
                </div>
              )}
            </article>
          </section>
        ) : null}

        {showHeadLoraPopup ? (
          <section
            className="modal-overlay avatar-preview-modal-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="Face LoRA seed set"
            onClick={() => setShowHeadLoraPopup(false)}
          >
            <article className="card modal-card avatar-seed-batch-modal-card" onClick={(event) => event.stopPropagation()}>
              <div className="avatar-preview-modal-header">
                <CardHeader
                  title="Face LoRA"
                  subtitle={`Pose ${headLoraActivePoseIndex + 1}/${Math.max(headLoraDatasetPoses.length, 1)}`}
                />
                <div className="row">
                  <button className="btn btn-primary" type="button" disabled={busy || !headLoraReadyForTraining || headLoraTrainingRunning} onClick={startHeadLoraTraining}>
                    {activeReferenceAction === "lora_dataset:head_face" ? "Starting..." : headLoraTrainingRunning ? "Training..." : "Train LoRA"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || headLoraTrainingRunning || !headLoraTrainingCompleted}
                    onClick={generateHeadLoraEpochReview}
                  >
                    Review Epochs
                  </button>
                  <button className="btn" type="button" onClick={() => setShowHeadLoraPopup(false)}>
                    Close
                  </button>
                </div>
              </div>
              <section className="avatar-lora-dataset-section avatar-lora-upload-section">
                <div className="avatar-lora-dataset-section-title">
                  <span>Uploaded Dataset</span>
                  <StatusBadge value={headLoraUploadedValidation.status || headLoraUploadedDataset.status || "not_uploaded"} />
                </div>
                <div className="avatar-lora-upload-row">
                  <label>
                    Dataset Folder
                    <input
                      type="text"
                      value={headLoraDatasetSourceDir}
                      onChange={(event) => setHeadLoraDatasetSourceDir(event.target.value)}
                      placeholder="/path/to/face/lora/dataset"
                    />
                  </label>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || !headLoraDatasetSourceDir.trim()}
                    onClick={uploadHeadLoraDatasetFromFolder}
                  >
                    {activeReferenceAction === "upload_lora_dataset:head_face" ? "Uploading..." : "Upload Dataset"}
                  </button>
                </div>
                <div className="avatar-lora-training-progress-grid">
                  <span>Images</span>
                  <code>{Number(headLoraUploadedDataset.image_count || headLoraUploadedItems.length || 0)}</code>
                  <span>Reference</span>
                  <code>{headLoraUploadedDataset.reference_image || "none"}</code>
                  <span>Warnings</span>
                  <code>{asArray(headLoraUploadedValidation.warnings).join(", ") || "none"}</code>
                  <span>Errors</span>
                  <code>{asArray(headLoraUploadedValidation.errors).join(", ") || "none"}</code>
                </div>
              </section>
              <section className="avatar-lora-dataset-section avatar-lora-upload-section">
                <div className="avatar-lora-dataset-section-title">
                  <span>Existing LoRA</span>
                  <StatusBadge value={headLoraExternalManifest.status || "not_uploaded"} />
                </div>
                <div className="avatar-lora-upload-row">
                  <label>
                    LoRA File
                    <input
                      type="text"
                      value={headLoraExternalPath}
                      onChange={(event) => setHeadLoraExternalPath(event.target.value)}
                      placeholder="/path/to/avatar_face.safetensors"
                    />
                  </label>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || !headLoraExternalPath.trim()}
                    onClick={uploadHeadExternalLoraFromFile}
                  >
                    {activeReferenceAction === "upload_lora:head_face" ? "Uploading..." : "Upload Existing LoRA"}
                  </button>
                </div>
                <div className="avatar-lora-training-progress-grid">
                  <span>Uploaded</span>
                  <code>{headLoraExternalItems.length}</code>
                  <span>Active</span>
                  <code>{headLoraActiveExternal.filename || headLoraExternalManifest.active_lora_id || "none"}</code>
                </div>
              </section>
              <div className="avatar-seed-batch-summary">
                <span>Status</span>
                <StatusBadge value={headLoraDataset.status || headLoraSeedSet.status || "ready"} />
                <span>Dataset Source</span>
                <code>{headLoraDataset.source || "upload_required"}</code>
                <span>Uploaded Images</span>
                <code>{Number(headLoraUploadedDataset.image_count || headLoraUploadedItems.length || 0)}</code>
                <span>External LoRAs</span>
                <code>{headLoraExternalItems.length}</code>
                <span>Training</span>
                <StatusBadge value={headLoraTrainingStatus.status || "waiting"} />
                <span>Train PID</span>
                <code>{headLoraTrainingStatus.pid || "none"}</code>
                <span>Train Log</span>
                <code>{headLoraTrainingStatus.logLabel}</code>
                <span>Epoch Review</span>
                <StatusBadge value={headLoraEpochReview.status || "not_started"} />
                <span>Review Images</span>
                <code>{Number(headLoraEpochReview.completed_count || 0)}/{Number(headLoraEpochReview.preview_count || 0)}</code>
              </div>
              <div className="avatar-lora-training-progress">
                <div className="avatar-lora-training-progress-title">
                  <span>LoRA Training</span>
                  <StatusBadge value={headLoraTrainingStatus.status || "waiting"} />
                </div>
                <div className="avatar-lora-training-progress-grid">
                  <span>Phase</span>
                  <code>{headLoraTrainingStatus.phase || "waiting"}</code>
                  <span>Detail</span>
                  <code>{headLoraTrainingStatus.detail || (headLoraReadyForTraining ? "Ready to train" : "Waiting for prepared dataset")}</code>
                  <span>Output</span>
                  <code>{headLoraTrainingStatus.outputLabel}</code>
                </div>
              </div>
              <div className="avatar-lora-bg-progress">
                <div className="avatar-lora-bg-progress-title">
                  <span>BG Removal</span>
                  <StatusBadge
                    value={
                      headLoraBgStatusSummary.overall.failed
                        ? "failed"
                        : headLoraBgStatusSummary.overall.ready >= headLoraBgStatusSummary.overall.total && headLoraBgStatusSummary.overall.total
                          ? "ready"
                          : headLoraBgStatusSummary.overall.submitted
                            ? "running"
                            : headLoraBgStatusSummary.overall.pending
                              ? "pending"
                              : "not_started"
                    }
                  />
                </div>
                <div className="avatar-lora-bg-progress-grid">
                  <span>Pose Ready</span>
                  <code>{headLoraBgStatusSummary.activePose.ready}/{headLoraBgStatusSummary.activePose.total}</code>
                  <span>All Ready</span>
                  <code>{headLoraBgStatusSummary.overall.ready}/{headLoraBgStatusSummary.overall.total}</code>
                  <span>Submitted</span>
                  <code>{headLoraBgStatusSummary.overall.submitted}</code>
                  <span>Pending</span>
                  <code>{headLoraBgStatusSummary.overall.pending}</code>
                  <span>Failed</span>
                  <code>{headLoraBgStatusSummary.overall.failed}</code>
                  <span>Active</span>
                  <code>{headLoraBgStatusSummary.activePose.activeName || headLoraBgStatusSummary.overall.activeName || "none"}</code>
                </div>
              </div>
              {headLoraEpochReviewGroups.length ? (
                <section className="avatar-lora-dataset-section">
                  <div className="avatar-lora-dataset-section-title">
                    <span>Epoch Review</span>
                    <StatusBadge value={headLoraEpochReview.status || "queued"} />
                  </div>
                  <div className="avatar-lora-epoch-review-list">
                    {headLoraEpochReviewGroups.map((group) => (
                      <article className="avatar-lora-epoch-review-row" key={group.epoch}>
                        <div className="avatar-lora-epoch-review-title">
                          <span>Epoch {group.epoch}</span>
                        </div>
                        <div className="avatar-lora-epoch-review-grid">
                          {group.previews.map((item, index) => {
                            const output = headFacePreviewOutput(item, manualOutputs, routeProfile);
                            return (
                              <article className={`avatar-seed-batch-card${item.selected ? " is-acceptable" : ""}`} key={item.preview_id || index}>
                                {output ? (
                                  <button className="avatar-head-face-preview-button" type="button" onClick={() => openHeadPreviewDetails(item, output)}>
                                    <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
                                  </button>
                                ) : (
                                  <div className="avatar-head-face-preview-placeholder avatar-head-face-preview-placeholder-small">
                                    <StatusBadge value={item.status || "pending"} />
                                  </div>
                                )}
                                <div className="avatar-seed-batch-card-meta">
                                  <strong>Sample {Number(item.sample_index || index + 1)}</strong>
                                  <code>seed {item.seed || "pending"}</code>
                                  <StatusBadge value={item.selected ? "selected" : item.status || "pending"} />
                                </div>
                                <div className="row">
                                  <button
                                    className="btn"
                                    type="button"
                                    disabled={busy || !output || item.selected}
                                    onClick={() => selectHeadLoraEpochReview(item.preview_id)}
                                  >
                                    Use This
                                  </button>
                                </div>
                              </article>
                            );
                          })}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}
              <section className="avatar-lora-dataset-section">
                <div className="avatar-lora-dataset-section-title">
                  <span>Uploaded Training Images</span>
                  <StatusBadge value={headLoraUploadedReady ? "ready" : "upload_required"} />
                </div>
                {headLoraUploadedItems.length ? (
                  <div className="avatar-lora-uploaded-grid">
                    {headLoraUploadedItems.map((item, index) => {
                      return (
                        <article className="avatar-seed-batch-card" key={item.item_id || item.filename || index}>
                          {item.url ? (
                            <a className="avatar-head-face-preview-button" href={`${apiBase}${item.url}`} target="_blank" rel="noreferrer">
                              <img src={`${apiBase}${item.url}`} alt={item.filename || item.name || `dataset ${index + 1}`} />
                            </a>
                          ) : (
                            <div className="avatar-head-face-preview-placeholder avatar-head-face-preview-placeholder-small">
                              <StatusBadge value="missing" />
                            </div>
                          )}
                          <div className="avatar-seed-batch-card-meta">
                            <strong>Dataset {index + 1}</strong>
                            <code>{item.filename || item.input_image || "uploaded"}</code>
                            <StatusBadge value="uploaded" />
                          </div>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <p className="muted tiny">Upload a prepared Face LoRA dataset folder to enable training.</p>
                )}
              </section>
            </article>
          </section>
        ) : null}

        {activeDetailTab === "profile" ? (
          <section className="setup-form avatar-extraction-form">
            <div className="state-grid compact-grid">
              <span>Gender</span>
              <code>{routeProfile.gender || "unset"}</code>
              <span>Skin</span>
              <code>{routeProfile.skin_color || "unset"}</code>
              <span>Hair</span>
              <code>{routeProfile.hair_color || "unset"}</code>
              <span>Type</span>
              <code>{routeProfile.character_type || "unset"}</code>
              <span>Style</span>
              <code>{routeProfile.visual_style || "unset"}</code>
              <span>NSFW</span>
              <StatusBadge value={routeProfile.nsfw ? "enabled" : "disabled"} />
            </div>
            <label className="avatar-generation-wide-field avatar-generation-compiled-prompt">
              General Initial Prompt
              <textarea rows={5} readOnly value={String(routeProfile.general_prompt || "")} />
            </label>
            <div className="avatar-profile-images avatar-profile-detail-images">
              {routeProfile.face_url ? (
                <a href={profileImageUrl(apiBase, routeProfile.face_url)} target="_blank" rel="noreferrer">
                  <img src={profileImageUrl(apiBase, routeProfile.face_url)} alt={`${profileName(routeProfile)} face`} />
                </a>
              ) : null}
              {routeProfile.body_url ? (
                <a href={profileImageUrl(apiBase, routeProfile.body_url)} target="_blank" rel="noreferrer">
                  <img src={profileImageUrl(apiBase, routeProfile.body_url)} alt={`${profileName(routeProfile)} body`} />
                </a>
              ) : null}
            </div>
          </section>
        ) : null}

        {activeDetailTab === "head_face" ? (
          <section className="setup-form avatar-reference-upload-panel avatar-generation-panel">
            <div className="avatar-head-face-workspace">
              <form className="setup-form avatar-extraction-form avatar-head-face-editor" onSubmit={refineHeadPrompt}>
                <div className="avatar-head-face-stats">
                  <div>
                    <span>Workspace</span>
                    <StatusBadge value="head_face" />
                  </div>
                  <div>
                    <span>Conversation</span>
                    <code>{asArray(promptWorkspace(routeProfile, "head_face").conversation).length}</code>
                  </div>
                  <div>
                    <span>Previews</span>
                    <code>{headPreviewHistory.length}</code>
                  </div>
                </div>
                <label className="avatar-generation-wide-field">
                  Adjustment Request
                  <textarea
                    rows={5}
                    value={headInstruction}
                    onChange={(event) => updateHeadInstruction(event.target.value)}
                    onKeyDown={submitHeadPromptShortcut}
                    placeholder={'Use "Eyes: description" to apply directly, or write a freeform request for the local LLM.'}
                  />
                </label>
                <div className="row">
                  <button
                    className="btn btn-primary"
                    type="submit"
                    disabled={busy || !headInstruction.trim() || hasHeadTaggedAdjustments}
                  >
                    {activeReferenceAction === "refine:head_face"
                      ? "Refining..."
                      : activeReferenceAction === "preview:head_face"
                        ? "Creating Preview..."
                        : "Refine Prompt"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy || !hasApplicableHeadTaggedAdjustments}
                    onClick={applyHeadTaggedAdjustments}
                  >
                    {activeReferenceAction === "adjust:head_face" ? "Applying..." : "Apply Tags"}
                  </button>
	                  <button className="btn" type="button" disabled={busy || !headPrompt.trim()} onClick={createHeadPreview}>
	                    {activeReferenceAction === "preview:head_face" ? "Requesting..." : "Create Preview"}
	                  </button>
                  <button className="btn" type="button" disabled={busy || !headPrompt.trim()} onClick={() => submitHeadSeedBatch([])}>
                    {activeReferenceAction === "seed_batch:head_face" ? "Submitting..." : "Seed Batch"}
                  </button>
                  <button className="btn btn-primary" type="button" onClick={openHeadLoraDataset}>
                    Face LoRA
                  </button>
                  <button className="btn" type="button" disabled={busy || !headLoraReadyForTraining || headLoraTrainingRunning} onClick={startHeadLoraTraining}>
                    {activeReferenceAction === "lora_dataset:head_face" ? "Starting..." : headLoraTrainingRunning ? "Training..." : "Train LoRA"}
                  </button>
	                  <label className="avatar-head-face-seed-lock">
	                    <input
	                      type="checkbox"
	                      checked={headPreviewSeedLocked}
	                      onChange={(event) => toggleHeadPreviewSeedLock(event.target.checked)}
	                      disabled={busy || activeReferenceAction === "seed:head_face"}
	                    />
                    Lock Seed
                  </label>
                  <input
                    className="avatar-head-face-seed-input"
	                    type="text"
	                    value={headPreviewSeed}
	                    onChange={(event) => setHeadPreviewSeed(event.target.value.replace(/[^0-9]/g, ""))}
	                    onBlur={() =>
	                      headPreviewSeedLocked
	                        ? saveHeadPreviewSeedSettings({ locked: true, seed: headPreviewSeed })
	                        : undefined
	                    }
	                    placeholder={latestHeadPreview?.seed ? `latest ${latestHeadPreview.seed}` : "seed"}
	                    disabled={!headPreviewSeedLocked || busy || activeReferenceAction === "seed:head_face"}
	                  />
                </div>
                {headAssistantReply ? (
                  <div className="avatar-head-face-assistant-reply">
                    <span>LLM Reply</span>
                    <p>{headAssistantReply}</p>
                  </div>
                ) : null}
                <div className="avatar-head-face-prompt-parts">
                  {HEAD_FACE_PROMPT_PARTS.map((part) => (
                    <div
                      className={`avatar-head-face-part-field avatar-head-face-part-${part.id}`}
                      key={part.id}
                    >
                      <div className="avatar-head-face-part-title">
                        <label htmlFor={`avatar-head-face-${part.id}`}>{part.label}</label>
                        <div className="avatar-head-face-part-actions">
                          <button
                            className="avatar-head-face-part-refine-button"
                            type="button"
                            onClick={() => insertHeadPromptPartTag(part.id)}
                            disabled={busy}
                            aria-label={`Add ${part.label} tag to adjustment request`}
                            title={`Add ${part.label}: to Adjustment Request`}
                          >
                            Tag
                          </button>
                          <button
	                            className={`avatar-head-face-lock-button${headLockedPromptParts[part.id] ? " is-locked" : ""}`}
	                            type="button"
	                            onClick={() => toggleHeadPromptPartLock(part.id)}
	                            disabled={busy || activeReferenceAction === `lock:head_face:${part.id}`}
	                            aria-pressed={Boolean(headLockedPromptParts[part.id])}
                            aria-label={`${headLockedPromptParts[part.id] ? "Unlock" : "Lock"} ${part.label}`}
                            title={`${headLockedPromptParts[part.id] ? "Unlock" : "Lock"} ${part.label}`}
                          >
                            {headLockedPromptParts[part.id] ? "Locked" : "Lock"}
                          </button>
                        </div>
                      </div>
                      <textarea
                        id={`avatar-head-face-${part.id}`}
                        rows={part.rows}
                        readOnly={Boolean(headLockedPromptParts[part.id])}
                        value={String(headPromptParts[part.id] || "")}
                        onChange={(event) => updateHeadPromptPart(part.id, event.target.value)}
                      />
                    </div>
                  ))}
                </div>
                <label className="avatar-generation-wide-field avatar-generation-compiled-prompt">
                  Compiled Head / Face Prompt
                  <textarea rows={5} readOnly value={headPrompt} />
                </label>
                <label className="avatar-generation-wide-field">
                  Negative Prompt
                  <textarea rows={4} value={headNegativePrompt} onChange={(event) => setHeadNegativePrompt(event.target.value)} />
                </label>
              </form>

              <aside className="avatar-head-face-latest-preview">
                <h3 className="avatar-head-face-latest-preview-title">Latest Preview</h3>
                {latestHeadPreview ? (
                  <>
                    {latestHeadPreviewOutput ? (
                      <button
                        className="avatar-head-face-preview-button"
                        type="button"
                        onClick={() => openHeadPreviewDetails(latestHeadPreview, latestHeadPreviewOutput)}
                        aria-label="Open latest head face preview details"
                      >
                        <img
                          src={`${apiBase}${latestHeadPreviewOutput.url}`}
                          alt={latestHeadPreviewOutput.filename || latestHeadPreviewOutput.relative_path}
                        />
                      </button>
                    ) : (
                      <div className="avatar-head-face-preview-placeholder">
                        <StatusBadge value={latestHeadPreview.status || "submitted"} />
                      </div>
                    )}
                    <div className="state-grid compact-grid avatar-head-face-preview-meta">
                      <span>Status</span>
                      <code>{latestHeadPreview.status || "submitted"}</code>
                      <span>Prompt</span>
                      <code>{latestHeadPreview.prompt_id || "pending"}</code>
                      <span>Seed</span>
                      <code>{latestHeadPreview.seed || "pending"}</code>
                      <span>Created</span>
                      <code>{latestHeadPreview.created_at || "not_saved"}</code>
                    </div>
                  </>
                ) : (
                  <p className="muted tiny">No preview yet.</p>
                )}
              </aside>
            </div>

            <div className="avatar-reference-section">
              <h3>Preview History</h3>
              {olderHeadPreviewHistory.length ? (
                <div className="avatar-reference-card-grid avatar-head-face-preview-history">
                  {olderHeadPreviewHistory.map((preview) => {
                    const output = headFacePreviewOutput(preview, manualOutputs, routeProfile);
                    return (
                      <article className="avatar-reference-card" key={preview.preview_id || preview.created_at}>
                        {output ? (
                          <button
                            className="avatar-head-face-preview-button"
                            type="button"
                            onClick={() => openHeadPreviewDetails(preview, output)}
                            aria-label="Open head face preview details"
                          >
                            <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
                          </button>
                        ) : (
                          <div className="avatar-head-face-preview-placeholder avatar-head-face-preview-placeholder-small">
                            <StatusBadge value={preview.status || "submitted"} />
                          </div>
                        )}
                        <div>
                          <strong>{preview.status || "requested"}</strong>
                          <span>{preview.created_at || "not_saved"}</span>
                          <code>{preview.prompt_id || preview.note || preview.template_id || "preview"}</code>
                          <code>{preview.seed ? `seed ${preview.seed}` : "seed pending"}</code>
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : (
                <p className="muted tiny">No previews requested yet.</p>
              )}
            </div>
          </section>
        ) : null}

        {activeDetailTab === "upper_torso" ? (
          <section className="setup-form avatar-reference-upload-panel avatar-generation-panel">
            <div className="avatar-head-face-stats">
              <div>
                <span>Workspace</span>
                <StatusBadge value="upper_torso" />
              </div>
              <div>
                <span>Dataset</span>
                <StatusBadge value={upperTorsoUploadedValidation.status || upperTorsoUploadedDataset.status || "not_uploaded"} />
              </div>
              <div>
                <span>Existing LoRAs</span>
                <code>{upperTorsoExternalItems.length}</code>
              </div>
            </div>
            <label className="avatar-generation-wide-field avatar-generation-compiled-prompt">
              Baseline Clothing
              <textarea
                rows={4}
                readOnly
                value="Use a fitted bodysuit as the baseline upper torso clothing. Keep the body shape, shoulder width, chest form, waist transition, and arm proportions readable. Avoid loose clothing, heavy folds, jackets, armor, or anything that hides torso proportions; normal clothing will be added later with inpainting."
              />
            </label>
            <div className="avatar-head-face-workspace">
              <div className="setup-form avatar-extraction-form avatar-head-face-editor">
                <div className="avatar-head-face-prompt-grid">
                  {UPPER_TORSO_PROMPT_PARTS.map((part) => (
                    <label className={part.id === "general" || part.id === "style_lighting" ? "avatar-generation-wide-field" : ""} key={part.id}>
                      {part.label}
                      <textarea
                        rows={part.rows}
                        value={upperTorsoPromptParts[part.id] || ""}
                        onChange={(event) =>
                          setUpperTorsoPromptParts((current) => ({
                            ...current,
                            [part.id]: event.target.value,
                          }))
                        }
                        placeholder={part.id === "clothing_outfit" ? "fitted bodysuit baseline, body shape readable" : ""}
                      />
                    </label>
                  ))}
                </div>
                <label className="avatar-generation-wide-field avatar-generation-compiled-prompt">
                  Composed Upper Torso Prompt
                  <textarea rows={4} readOnly value={upperTorsoPrompt} />
                </label>
                <label className="avatar-generation-wide-field">
                  Negative Prompt
                  <textarea
                    rows={4}
                    value={upperTorsoNegativePrompt}
                    onChange={(event) => setUpperTorsoNegativePrompt(event.target.value)}
                  />
                </label>
                <div className="row">
                  <button className="btn" type="button" disabled={busy || !upperTorsoPrompt.trim()} onClick={createUpperTorsoPreview}>
                    {activeReferenceAction === "preview:upper_torso" ? "Requesting..." : "Create Preview"}
                  </button>
                </div>
              </div>
              <aside className="avatar-head-face-latest-preview">
                <h3 className="avatar-head-face-latest-preview-title">Latest Preview</h3>
                {latestUpperTorsoPreview ? (
                  <>
                    {latestUpperTorsoPreviewOutput ? (
                      <button
                        className="avatar-head-face-preview-button"
                        type="button"
                        onClick={() => openHeadPreviewDetails(latestUpperTorsoPreview, latestUpperTorsoPreviewOutput)}
                        aria-label="Open latest upper torso preview details"
                      >
                        <img
                          src={`${apiBase}${latestUpperTorsoPreviewOutput.url}`}
                          alt={latestUpperTorsoPreviewOutput.filename || latestUpperTorsoPreviewOutput.relative_path}
                        />
                      </button>
                    ) : (
                      <div className="avatar-head-face-preview-placeholder">
                        <StatusBadge value={latestUpperTorsoPreview.status || "submitted"} />
                      </div>
                    )}
                    <div className="state-grid compact-grid avatar-head-face-preview-meta">
                      <span>Status</span>
                      <code>{latestUpperTorsoPreview.status || "submitted"}</code>
                      <span>Prompt</span>
                      <code>{latestUpperTorsoPreview.prompt_id || "pending"}</code>
                      <span>Seed</span>
                      <code>{latestUpperTorsoPreview.seed || "pending"}</code>
                      <span>Created</span>
                      <code>{latestUpperTorsoPreview.created_at || "not_saved"}</code>
                    </div>
                  </>
                ) : (
                  <p className="muted tiny">No preview yet.</p>
                )}
              </aside>
            </div>
            <section className="avatar-lora-dataset-section avatar-lora-upload-section">
              <div className="avatar-lora-dataset-section-title">
                <span>Uploaded Upper Torso Dataset</span>
                <StatusBadge value={upperTorsoUploadedValidation.status || upperTorsoUploadedDataset.status || "not_uploaded"} />
              </div>
              <div className="avatar-lora-upload-row">
                <label>
                  Dataset Folder
                  <input
                    type="text"
                    value={upperTorsoLoraDatasetSourceDir}
                    onChange={(event) => setUpperTorsoLoraDatasetSourceDir(event.target.value)}
                    placeholder="/path/to/upper/torso/lora/dataset"
                  />
                </label>
                <button
                  className="btn"
                  type="button"
                  disabled={busy || !upperTorsoLoraDatasetSourceDir.trim()}
                  onClick={uploadUpperTorsoLoraDatasetFromFolder}
                >
                  {activeReferenceAction === "upload_lora_dataset:upper_torso" ? "Uploading..." : "Upload Dataset"}
                </button>
              </div>
              <div className="avatar-lora-training-progress-grid">
                <span>Images</span>
                <code>{Number(upperTorsoUploadedDataset.image_count || upperTorsoUploadedItems.length || 0)}</code>
                <span>Reference</span>
                <code>{upperTorsoUploadedDataset.reference_image || "none"}</code>
                <span>Training</span>
                <StatusBadge value={upperTorsoTrainingJob.status || upperTorsoTrainingManifest.status || "waiting"} />
                <span>Warnings</span>
                <code>{asArray(upperTorsoUploadedValidation.warnings).join(", ") || "none"}</code>
                <span>Errors</span>
                <code>{asArray(upperTorsoUploadedValidation.errors).join(", ") || "none"}</code>
              </div>
              <div className="row">
                <button
                  className="btn btn-primary"
                  type="button"
                  disabled={busy || !upperTorsoReadyForTraining || upperTorsoTrainingRunning}
                  onClick={startUpperTorsoLoraTraining}
                >
                  {activeReferenceAction === "lora_dataset:upper_torso" ? "Starting..." : upperTorsoTrainingRunning ? "Training..." : "Train Upper Torso LoRA"}
                </button>
                <code>{upperTorsoTrainingJob.log ? String(upperTorsoTrainingJob.log).split("/").slice(-3).join("/") : "no training log"}</code>
              </div>
              <div className="avatar-lora-dataset-section-title">
                <span>Epoch Review</span>
                <StatusBadge value={upperTorsoEpochReview.status || "not_started"} />
              </div>
              <div className="avatar-lora-training-progress-grid">
                <span>Review Images</span>
                <code>{Number(upperTorsoEpochReview.completed_count || 0)}/{Number(upperTorsoEpochReview.preview_count || 0)}</code>
                <span>Selected</span>
                <code>{upperTorsoEpochReview.selected_epoch ? `epoch ${upperTorsoEpochReview.selected_epoch}` : "none"}</code>
              </div>
              <div className="row">
                <button
                  className="btn"
                  type="button"
                  disabled={busy || upperTorsoTrainingRunning || !upperTorsoTrainingJob.output_model}
                  onClick={generateUpperTorsoLoraEpochReview}
                >
                  {activeReferenceAction === "epoch_review:upper_torso" ? "Working..." : "Generate Epoch Review"}
                </button>
              </div>
              {upperTorsoEpochReviewGroups.length ? (
                <div className="avatar-lora-epoch-review-list">
                  {upperTorsoEpochReviewGroups.map((group) => (
                    <article className="avatar-lora-epoch-review-row" key={group.epoch}>
                      <div className="avatar-lora-epoch-review-title">
                        <span>Epoch {group.epoch}</span>
                      </div>
                      <div className="avatar-lora-epoch-review-grid">
                        {group.previews.map((item, index) => {
                          const output = headFacePreviewOutput(item, manualOutputs, routeProfile);
                          return (
                            <article className={`avatar-seed-batch-card${item.selected ? " is-acceptable" : ""}`} key={item.preview_id || index}>
                              {output ? (
                                <button className="avatar-head-face-preview-button" type="button" onClick={() => openHeadPreviewDetails(item, output)}>
                                  <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
                                </button>
                              ) : (
                                <div className="avatar-head-face-preview-placeholder avatar-head-face-preview-placeholder-small">
                                  <StatusBadge value={item.status || "pending"} />
                                </div>
                              )}
                              <div className="avatar-seed-batch-card-meta">
                                <strong>Sample {Number(item.sample_index || index + 1)}</strong>
                                <code>seed {item.seed || "pending"}</code>
                                <StatusBadge value={item.selected ? "selected" : item.status || "pending"} />
                              </div>
                              <div className="row">
                                <button
                                  className="btn"
                                  type="button"
                                  disabled={busy || !output || item.selected}
                                  onClick={() => selectUpperTorsoLoraEpochReview(item.preview_id)}
                                >
                                  Select
                                </button>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    </article>
                  ))}
                </div>
              ) : null}
            </section>
            <section className="avatar-lora-dataset-section avatar-lora-upload-section">
              <div className="avatar-lora-dataset-section-title">
                <span>Existing Upper Torso LoRA</span>
                <StatusBadge value={upperTorsoExternalManifest.status || "not_uploaded"} />
              </div>
              <div className="avatar-lora-upload-row">
                <label>
                  LoRA File
                  <input
                    type="text"
                    value={upperTorsoLoraExternalPath}
                    onChange={(event) => setUpperTorsoLoraExternalPath(event.target.value)}
                    placeholder="/path/to/upper_torso.safetensors"
                  />
                </label>
                <button
                  className="btn"
                  type="button"
                  disabled={busy || !upperTorsoLoraExternalPath.trim()}
                  onClick={uploadUpperTorsoExternalLoraFromFile}
                >
                  {activeReferenceAction === "upload_lora:upper_torso" ? "Uploading..." : "Upload Existing LoRA"}
                </button>
              </div>
              <div className="avatar-lora-training-progress-grid">
                <span>Uploaded</span>
                <code>{upperTorsoExternalItems.length}</code>
                <span>Active</span>
                <code>{upperTorsoActiveExternal.filename || upperTorsoExternalManifest.active_lora_id || "none"}</code>
              </div>
            </section>
          </section>
        ) : null}

        {["lower_torso", "full_body"].includes(activeDetailTab) ? (
          <section className="setup-form avatar-reference-upload-panel">
            <div className="state-grid compact-grid">
              <span>Workspace</span>
              <StatusBadge value={activeDetailTab} />
              <span>Status</span>
              <code>not_started</code>
            </div>
          </section>
        ) : null}

        {activeDetailTab === "body_depth" ? (
          <section className="setup-form avatar-reference-upload-panel">
            <div className="row">
              <label className="avatar-upload-control">
                <span className="btn btn-primary">{activeReferenceAction === "upload:body_depth" ? "Uploading..." : "Upload Body Images"}</span>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={(event) => {
                    const files = Array.from(event.target.files || []);
                    setBodyDepthFiles(files);
                    uploadReferenceFiles("body_depth", files);
                  }}
                />
              </label>
              <button className="btn" type="button" disabled={busy} onClick={generateBodyDepthProfile}>
                {activeReferenceAction === "generate:body_depth" ? "Generating..." : "Generate Depth Profile"}
              </button>
            </div>
            <div className="state-grid compact-grid">
              <span>Queued</span>
              <code>{bodyDepthFiles.length}</code>
              <span>Files</span>
              <code>{selectedFileNames(bodyDepthFiles)}</code>
              <span>Raw Bodies</span>
              <code>{rawBodyReferences(routeProfile).length}</code>
              <span>No-BG Bodies</span>
              <code>{noBgBodyReferences(routeProfile).length}</code>
              <span>Depth Maps</span>
              <code>{profileReferences(routeProfile, "body_depth_map").length}</code>
              <span>Depth Profile</span>
              <StatusBadge value={bodyDepthProfile(routeProfile).status || "not_started"} />
              <span>Generated</span>
              <code>{bodyDepthProfile(routeProfile).generated_count ?? 0}</code>
            </div>
            <div className="avatar-reference-section">
              <h3>Raw Body Images</h3>
              {renderReferenceCards("body_depth", rawBodyReferences(routeProfile))}
            </div>
            <div className="avatar-reference-section">
              <h3>No-BG Body Images</h3>
              {renderReferenceCards("body_depth", noBgBodyReferences(routeProfile))}
            </div>
            <div className="avatar-reference-section">
              <h3>Depth Maps</h3>
              {renderReferenceCards("body_depth_map")}
            </div>
          </section>
        ) : null}

        {activeDetailTab === "face" ? (
          <section className="setup-form avatar-reference-upload-panel">
            <div className="row">
              <label className="avatar-upload-control">
                <span className="btn btn-primary">{activeReferenceAction === "upload:face" ? "Uploading..." : "Upload Face Images"}</span>
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  onChange={(event) => {
                    const files = Array.from(event.target.files || []);
                    setFaceAnalysisFiles(files);
                    uploadReferenceFiles("face", files);
                  }}
                />
              </label>
            </div>
            <div className="state-grid compact-grid">
              <span>Queued</span>
              <code>{faceAnalysisFiles.length}</code>
              <span>Files</span>
              <code>{selectedFileNames(faceAnalysisFiles)}</code>
              <span>Saved</span>
              <code>{profileReferences(routeProfile, "face").length}</code>
              <span>Primary</span>
              <code>{routeProfile.primary_face_reference_filename || routeProfile.face_image || "base face"}</code>
              <span>PuLID Face</span>
              <code>{routeProfile.pulid_face_reference_image || routeProfile.face_input_image || "none"}</code>
              <span>Face Profile</span>
              <StatusBadge value={faceProfile(routeProfile).status || "not_started"} />
              <span>References</span>
              <code>{faceProfile(routeProfile).reference_count ?? 0}</code>
            </div>
            {faceProfile(routeProfile).structured ? (
              <div className="form-grid two-column-form-grid">
                <label>
                  Identity Prompt
                  <textarea rows={5} readOnly value={String(faceProfile(routeProfile).structured.identity_prompt || "")} />
                </label>
                <label>
                  Face Prompt
                  <textarea rows={5} readOnly value={String(faceProfile(routeProfile).structured.face_prompt || "")} />
                </label>
                <label>
                  Hair Prompt
                  <textarea rows={4} readOnly value={String(faceProfile(routeProfile).structured.hair_prompt || "")} />
                </label>
                <label>
                  Negative Identity
                  <textarea rows={4} readOnly value={String(faceProfile(routeProfile).structured.negative_identity_prompt || "")} />
                </label>
              </div>
            ) : null}
            {renderReferenceCards("face")}
          </section>
        ) : null}

        {activeDetailTab === "poses" ? (
          <section className="setup-form avatar-reference-upload-panel">
            <label className="avatar-upload-control">
              <span className="btn btn-primary">{activeReferenceAction === "upload:pose" ? "Uploading..." : "Upload Pose Images"}</span>
              <input
                type="file"
                accept="image/*"
                multiple
                onChange={(event) => {
                  const files = Array.from(event.target.files || []);
                  setPoseFiles(files);
                  uploadReferenceFiles("pose", files);
                }}
              />
            </label>
            <label>
              Pose Notes
              <textarea rows={8} value={poseText} onChange={(event) => setPoseText(event.target.value)} />
            </label>
            <div className="state-grid compact-grid">
              <span>Queued</span>
              <code>{poseFiles.length}</code>
              <span>Files</span>
              <code>{selectedFileNames(poseFiles)}</code>
              <span>Saved</span>
              <code>{profileReferences(routeProfile, "pose").length}</code>
            </div>
            {renderReferenceCards("pose")}
          </section>
        ) : null}

        {activeDetailTab === "generation" ? (
          <form className="setup-form avatar-reference-upload-panel avatar-generation-panel" onSubmit={submitGeneration}>
            <div className="state-grid compact-grid">
              <span>Profile</span>
              <code>{routeProfile.profile_id}</code>
              <span>Selected</span>
              <StatusBadge value={routeProfile.selected || routeProfile.profile_id === selectedProfileId ? "selected" : "ready"} />
              <span>Extraction</span>
              <StatusBadge value={hasExtraction(routeProfile) ? "ready" : "missing"} />
              <span>Face Profile</span>
              <StatusBadge value={faceProfile(routeProfile).status || "missing"} />
              <span>Depth Profile</span>
              <StatusBadge value={bodyDepthProfile(routeProfile).status || "missing"} />
              <span>Depth Maps</span>
              <code>{generationDepthOptions.length}</code>
              <span>Pose Refs</span>
              <code>{generationPoseOptions.length}</code>
              <span>Pose Control</span>
              <StatusBadge value={!usesProfileDepthTemplate ? "not_used" : generationState.pose_reference_image ? "ready" : "missing"} />
            </div>

            <div className="form-grid avatar-generation-reference-grid">
              <label>
                Template
                <select value={generationState.template_id} onChange={(event) => updateGenerationField("template_id", event.target.value)}>
                  <option value={AVATAR_PROFILE_TEMPLATE_ID} disabled={!generationDepthOptions.length}>
                    Avatar Profile Generation
                  </option>
                  <option value={AVATAR_BODY_REFERENCE_TEMPLATE_ID}>Simple Avatar Generation</option>
                </select>
              </label>
              <label>
                Face Reference
                <select
                  value={generationState.face_reference_image}
                  onChange={(event) => updateGenerationField("face_reference_image", event.target.value)}
                >
                  {generationFaceOptions.map((option) => (
                    <option value={option.inputImage} key={option.inputImage}>
                      {option.primary ? `${option.label} (primary)` : option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Body Depth Map
                <select
                  value={generationState.body_depth_image}
                  onChange={(event) => updateGenerationField("body_depth_image", event.target.value)}
                  disabled={!generationDepthOptions.length}
                >
                  <option value="">No saved depth map</option>
                  {generationDepthOptions.map((option) => (
                    <option value={option.inputImage} key={option.inputImage}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Body Reference
                <select
                  value={generationState.body_reference_image}
                  onChange={(event) => updateGenerationField("body_reference_image", event.target.value)}
                  disabled={!generationBodyOptions.length}
                >
                  <option value="">No body reference</option>
                  {generationBodyOptions.map((option) => (
                    <option value={option.inputImage} key={option.inputImage}>
                      {option.backgroundRemoved ? `${option.label} (no BG)` : option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Pose Control Image
                <select value={generationState.pose_reference_image} onChange={(event) => updateGenerationField("pose_reference_image", event.target.value)}>
                  <option value="">No pose control image</option>
                  {generationPoseOptions.map((option) => (
                    <option value={option.inputImage} key={option.inputImage}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="avatar-generation-preview-grid">
              {renderGenerationPreview(selectedFaceOption, "Face")}
              {renderGenerationPreview(selectedDepthOption, "Depth")}
              {renderGenerationPreview(selectedBodyOption, "Body")}
              {renderGenerationPreview(selectedPoseOption, "Pose")}
            </div>

            <div className="form-grid two-column-form-grid avatar-generation-prompt-grid">
              <label>
                Identity
                <textarea rows={4} value={generationState.identity} onChange={(event) => updateGenerationField("identity", event.target.value)} />
              </label>
              <label>
                Face
                <textarea rows={4} value={generationState.face} onChange={(event) => updateGenerationField("face", event.target.value)} />
              </label>
              <label>
                Hair
                <textarea rows={3} value={generationState.hair} onChange={(event) => updateGenerationField("hair", event.target.value)} />
              </label>
              <label>
                Body Shape
                <textarea rows={5} value={generationState.body_shape} onChange={(event) => updateGenerationField("body_shape", event.target.value)} />
              </label>
              <label>
                Pose
                <textarea rows={4} value={generationState.pose} onChange={(event) => updateGenerationField("pose", event.target.value)} />
              </label>
              <label>
                Clothing
                <textarea rows={4} value={generationState.clothing} onChange={(event) => updateGenerationField("clothing", event.target.value)} />
              </label>
              <label>
                Accessories
                <textarea rows={3} value={generationState.accessories} onChange={(event) => updateGenerationField("accessories", event.target.value)} />
              </label>
              <label>
                Scene
                <textarea rows={3} value={generationState.scene} onChange={(event) => updateGenerationField("scene", event.target.value)} />
              </label>
              <label>
                Style
                <textarea rows={3} value={generationState.style} onChange={(event) => updateGenerationField("style", event.target.value)} />
              </label>
              <label>
                Preservation
                <textarea rows={3} value={generationState.preservation} onChange={(event) => updateGenerationField("preservation", event.target.value)} />
              </label>
              <label className="avatar-generation-wide-field">
                Negative Prompt
                <textarea rows={4} value={generationState.negative} onChange={(event) => updateGenerationField("negative", event.target.value)} />
              </label>
              <label className="avatar-generation-wide-field avatar-generation-compiled-prompt">
                Compiled Prompt
                <textarea rows={7} readOnly value={generationPrompt} />
              </label>
            </div>

            <div className="form-grid avatar-generation-settings-grid">
              <label>
                Width
                <input type="number" min="256" max="1920" step="64" value={generationState.width} onChange={(event) => updateGenerationField("width", event.target.value)} />
              </label>
              <label>
                Height
                <input type="number" min="256" max="1920" step="64" value={generationState.height} onChange={(event) => updateGenerationField("height", event.target.value)} />
              </label>
              <label>
                Seed
                <input type="text" value={generationState.seed} onChange={(event) => updateGenerationField("seed", event.target.value)} placeholder="random" />
              </label>
              <label>
                Batch Count
                <input type="number" min="1" max="25" step="1" value={generationState.batch_count} onChange={(event) => updateGenerationField("batch_count", event.target.value)} />
              </label>
              <label>
                Steps
                <input type="number" min="1" max="60" step="1" value={generationState.steps} onChange={(event) => updateGenerationField("steps", event.target.value)} />
              </label>
              <label>
                CFG
                <input type="number" min="0" max="20" step="0.1" value={generationState.cfg} onChange={(event) => updateGenerationField("cfg", event.target.value)} />
              </label>
              <label>
                Denoise
                <input type="number" min="0" max="1" step="0.01" value={generationState.denoise} onChange={(event) => updateGenerationField("denoise", event.target.value)} />
              </label>
              <label>
                Face Strength
                <input type="number" min="0" max="1" step="0.01" value={generationState.face_strength} onChange={(event) => updateGenerationField("face_strength", event.target.value)} />
              </label>
              <label>
                Body Strength
                <input type="number" min="0" max="1.5" step="0.01" value={generationState.body_depth_strength} onChange={(event) => updateGenerationField("body_depth_strength", event.target.value)} />
              </label>
              <label>
                Body Start
                <input type="number" min="0" max="1" step="0.01" value={generationState.body_depth_start} onChange={(event) => updateGenerationField("body_depth_start", event.target.value)} />
              </label>
              <label>
                Body End
                <input type="number" min="0" max="1" step="0.01" value={generationState.body_depth_end} onChange={(event) => updateGenerationField("body_depth_end", event.target.value)} />
              </label>
              <label>
                Pose Strength
                <input type="number" min="0" max="1.5" step="0.01" value={generationState.pose_strength} onChange={(event) => updateGenerationField("pose_strength", event.target.value)} />
              </label>
              <label>
                Pose Start
                <input type="number" min="0" max="1" step="0.01" value={generationState.pose_start} onChange={(event) => updateGenerationField("pose_start", event.target.value)} />
              </label>
              <label>
                Pose End
                <input type="number" min="0" max="1" step="0.01" value={generationState.pose_end} onChange={(event) => updateGenerationField("pose_end", event.target.value)} />
              </label>
              <label>
                Strength Jitter
                <input type="number" min="0" max="1" step="0.01" value={generationState.reference_strength_jitter} onChange={(event) => updateGenerationField("reference_strength_jitter", event.target.value)} />
              </label>
            </div>

            <div className="row">
              <label className="manual-lora-metadata-toggle">
                <input
                  type="checkbox"
                  checked={generationState.randomize_seed}
                  onChange={(event) => updateGenerationField("randomize_seed", event.target.checked)}
                />
                Randomize Seed
              </label>
              <label className="manual-lora-metadata-toggle">
                <input
                  type="checkbox"
                  checked={generationState.randomize_reference_strengths}
                  onChange={(event) => updateGenerationField("randomize_reference_strengths", event.target.checked)}
                />
                Randomize Strengths
              </label>
              <label className="manual-lora-metadata-toggle">
                <input
                  type="checkbox"
                  checked={generationState.create_lora_metadata}
                  onChange={(event) => updateGenerationField("create_lora_metadata", event.target.checked)}
                />
                Create LoRA Metadata
              </label>
            </div>

            <div className="row">
              <button className="btn btn-primary" type="submit" disabled={!canSubmitGeneration}>
                {activeReferenceAction === "generate:avatar" || generationBusy ? "Generating..." : "Generate Avatar"}
              </button>
              <button className="btn" type="button" disabled={busy || generationBusy} onClick={resetGenerationDefaults}>
                Reload Profile Defaults
              </button>
              {generationResult?.prompt_id ? <code>{`Prompt ${generationResult.prompt_id}`}</code> : null}
            </div>
          </form>
        ) : null}
      </article>
    );
  }

  return (
    <article className="card operational-card-full-span">
      <CardHeader title="Avatar Generation" subtitle="Create avatar profiles and manage saved profile assets." />

      <div className="avatar-generation-tabs" role="tablist" aria-label="Avatar generation tabs">
        {AVATAR_GENERATION_TABS.map((tab) => (
          <button
            className={activeTab === tab.id ? "btn btn-primary" : "btn"}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            role="tab"
            type="button"
            aria-selected={activeTab === tab.id}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "profile" ? (
        <form className="setup-form avatar-profile-form" onSubmit={saveProfile}>
          <div className="form-grid two-column-form-grid">
            <label>
              Character Name
              <input
                type="text"
                value={characterName}
                onChange={(event) => setCharacterName(event.target.value)}
                placeholder="Hexe"
              />
            </label>
            <label>
              Gender
              <select value={gender} onChange={(event) => setGender(event.target.value)}>
                <option value="">Unspecified</option>
                <option value="female">Female</option>
                <option value="male">Male</option>
                <option value="nonbinary">Nonbinary</option>
              </select>
            </label>
            <label>
              Skin Color
              <select value={skinColor} onChange={(event) => setSkinColor(event.target.value)}>
                <option value="">Unspecified</option>
                <option value="fair">Fair</option>
                <option value="light">Light</option>
                <option value="olive">Olive</option>
                <option value="tan">Tan</option>
                <option value="brown">Brown</option>
                <option value="dark-brown">Dark Brown</option>
                <option value="deep">Deep</option>
              </select>
            </label>
            <label>
              Hair Color
              <select value={hairColor} onChange={(event) => setHairColor(event.target.value)}>
                <option value="">Unspecified</option>
                <option value="black">Black</option>
                <option value="brown">Brown</option>
                <option value="blonde">Blonde</option>
                <option value="auburn">Auburn</option>
                <option value="red">Red</option>
                <option value="gray">Gray</option>
                <option value="white">White</option>
                <option value="silver">Silver</option>
                <option value="blue">Blue</option>
                <option value="pink">Pink</option>
                <option value="purple">Purple</option>
                <option value="green">Green</option>
                <option value="none">None / Bald</option>
              </select>
            </label>
            <label>
              Character Type
              <select value={characterType} onChange={(event) => setCharacterType(event.target.value)}>
                <option value="human">Human</option>
                <option value="humanlike">Humanlike</option>
                <option value="non-human">Non-human</option>
              </select>
            </label>
            <label>
              Visual Style
              <select value={visualStyle} onChange={(event) => setVisualStyle(event.target.value)}>
                <option value="cartoon">Cartoon</option>
                <option value="manga">Manga</option>
                <option value="stylized-realistic">Stylized Realistic</option>
                <option value="real">Real</option>
              </select>
            </label>
            <label className="manual-lora-metadata-toggle">
              <input
                type="checkbox"
                checked={nsfw}
                onChange={(event) => setNsfw(event.target.checked)}
              />
              NSFW
            </label>
          </div>

          <div className="row">
            <button className="btn btn-primary" type="submit" disabled={!canSave}>
              {busy ? "Saving..." : "Save Profile"}
            </button>
            <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
              Refresh
            </button>
            {localStatus ? <StatusBadge value={localStatus} /> : null}
          </div>
        </form>
      ) : null}

      {activeTab === "saved_profiles" ? (
        <section className="avatar-profile-library">
          <div className="manual-generation-status-grid">
            <div className="status-tile">
              <span>Profiles</span>
              <strong>{profiles.length}</strong>
            </div>
            <div className="status-tile">
              <span>Latest</span>
              <strong>{profileName(latestProfile)}</strong>
            </div>
          </div>

          {profiles.length ? (
            <div className="avatar-profile-list">
              {profiles.map((profile) => (
                <article className="avatar-profile-card" key={profile.profile_id}>
                  <div className="avatar-profile-card-header">
                    <div>
                      <strong>{profileName(profile)}</strong>
                      <span>{profile.updated_at || profile.created_at || "not_saved"}</span>
                    </div>
                    {profile.selected || profile.profile_id === selectedProfileId ? <StatusBadge value="selected" /> : null}
                  </div>
                  <div className="avatar-profile-images">
                    {profile.face_url ? (
                      <a href={profileImageUrl(apiBase, profile.face_url)} target="_blank" rel="noreferrer">
                        <img src={profileImageUrl(apiBase, profile.face_url)} alt={`${profileName(profile)} face`} />
                      </a>
                    ) : null}
                    {profile.body_url ? (
                      <a href={profileImageUrl(apiBase, profile.body_url)} target="_blank" rel="noreferrer">
                        <img src={profileImageUrl(apiBase, profile.body_url)} alt={`${profileName(profile)} body`} />
                      </a>
                    ) : null}
                  </div>
                  {profile.description ? <p className="muted tiny">{profile.description}</p> : null}
                  <div className="state-grid compact-grid">
                    <span>Gender</span>
                    <code>{profile.gender || "unset"}</code>
                    <span>Skin</span>
                    <code>{profile.skin_color || "unset"}</code>
                    <span>Hair</span>
                    <code>{profile.hair_color || "unset"}</code>
                    <span>Type</span>
                    <code>{profile.character_type || "unset"}</code>
                    <span>Style</span>
                    <code>{profile.visual_style || "unset"}</code>
                    <span>NSFW</span>
                    <StatusBadge value={profile.nsfw ? "enabled" : "disabled"} />
                  </div>
                  {profile.extraction?.structured ? (
                    <details className="avatar-profile-json">
                      <summary>Extracted JSON</summary>
                      <pre>{JSON.stringify(profile.extraction.structured, null, 2)}</pre>
                    </details>
                  ) : null}
                  <div className="row avatar-profile-actions">
                    <button
                      className="btn"
                      type="button"
                      disabled={busy}
                      onClick={() => runProfileAction("selected", profile.profile_id, onSelectProfile)}
                    >
                      {activeProfileAction === `selected:${profile.profile_id}`
                        ? "Selecting..."
                        : profile.selected || profile.profile_id === selectedProfileId
                          ? "Open"
                          : "Select"}
                    </button>
                    <button
                      className="btn btn-danger"
                      type="button"
                      disabled={busy}
                      onClick={() => runProfileAction("deleted", profile.profile_id, onDeleteProfile)}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted tiny">No avatar profiles saved.</p>
          )}
        </section>
      ) : null}
    </article>
  );
}
