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
    .sort((left, right) => previewTimestamp(right) - previewTimestamp(left));
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
  const expected = `hexe/avatar_head_face_preview/${safeName}_seed${seed}`;
  return asArray(outputs).find((output) => String(output?.relative_path || "").startsWith(expected)) || null;
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

function promptWorkspace(profile, section) {
  return objectValue(objectValue(profile?.prompt_workspaces)[section]);
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
  onCreateHeadPreview,
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
  const [headNegativePrompt, setHeadNegativePrompt] = useState(() => promptWorkspace(routeProfile, "head_face").negative_prompt || "");
  const [headInstruction, setHeadInstruction] = useState("");
  const generationProfileIdRef = useRef("");
  const generationProfileSignature = avatarGenerationProfileSignature(routeProfile);
  const latestProfile = result?.profile || profiles[0] || null;
  const canSave = Boolean(characterName.trim()) && !busy;
  const detailMode = Boolean(routeProfileId);
  const headPreviewHistory = useMemo(() => headFacePreviewHistory(routeProfile), [routeProfile]);
  const latestHeadPreview = headPreviewHistory[0] || null;
  const latestHeadPreviewOutput = headFacePreviewOutput(latestHeadPreview, manualOutputs, routeProfile);
  const headPrompt = useMemo(() => composeHeadFacePrompt(headPromptParts), [headPromptParts]);

  useEffect(() => {
    if (AVATAR_PROFILE_DETAIL_TABS.some((tab) => tab.id === initialDetailTab)) {
      setActiveDetailTab(initialDetailTab);
    }
  }, [initialDetailTab]);

  useEffect(() => {
    if (routeProfile) {
      setEditorState(extractionEditorState(routeProfile));
      const workspace = promptWorkspace(routeProfile, "head_face");
      setHeadPromptParts(headFacePromptParts(routeProfile));
      setHeadNegativePrompt(String(workspace.negative_prompt || ""));
      setHeadInstruction("");
    }
  }, [routeProfile]);

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

  async function refineHeadPrompt(event) {
    event.preventDefault();
    const profileId = String(routeProfile?.profile_id || "").trim();
    const userMessage = headInstruction.trim();
    if (!profileId || !userMessage || busy) {
      return;
    }
    setActiveReferenceAction("refine:head_face");
    setLocalStatus("");
    try {
      const result = await onRefineHeadPrompt?.(profileId, {
        current_prompt: headPrompt,
        prompt_parts: headPromptParts,
        negative_prompt: headNegativePrompt,
        user_message: userMessage,
      });
      if (result?.prompt) {
        setHeadPromptParts((current) => ({ ...current, general: String(result.prompt) }));
      }
      if (result?.negative_prompt !== undefined) {
        setHeadNegativePrompt(String(result.negative_prompt || ""));
      }
      if (result) {
        setHeadInstruction("");
        setLocalStatus("head_prompt_refined");
      }
    } finally {
      setActiveReferenceAction("");
    }
  }

  async function createHeadPreview() {
    const profileId = String(routeProfile?.profile_id || "").trim();
    if (!profileId || !headPrompt.trim() || busy) {
      return;
    }
    setActiveReferenceAction("preview:head_face");
    setLocalStatus("");
    try {
      const result = await onCreateHeadPreview?.(profileId, {
        prompt: headPrompt,
        prompt_parts: headPromptParts,
        negative_prompt: headNegativePrompt,
      });
      if (result) {
        setLocalStatus(result.status || "preview_submitted");
      }
    } finally {
      setActiveReferenceAction("");
    }
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
          <CardHeader title="Avatar Generation" subtitle="Profile not found." />
          <div className="row">
            <button className="btn" type="button" onClick={onBackToProfiles}>
              Back
            </button>
            <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
              Refresh
            </button>
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
        <CardHeader title={profileName(routeProfile)} subtitle="Avatar Generation" />
        <div className="row avatar-profile-detail-actions">
          <button className="btn" type="button" onClick={onBackToProfiles}>
            Back
          </button>
          <button className="btn" type="button" onClick={onRefresh} disabled={busy}>
            Refresh
          </button>
          {localStatus ? <StatusBadge value={localStatus} /> : null}
        </div>

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
                <div className="state-grid compact-grid">
                  <span>Workspace</span>
                  <StatusBadge value="head_face" />
                  <span>Conversation</span>
                  <code>{asArray(promptWorkspace(routeProfile, "head_face").conversation).length}</code>
                  <span>Previews</span>
                  <code>{headPreviewHistory.length}</code>
                </div>
                <div className="avatar-head-face-prompt-parts">
                  {HEAD_FACE_PROMPT_PARTS.map((part) => (
                    <label
                      className={`avatar-generation-wide-field avatar-head-face-part-field avatar-head-face-part-${part.id}`}
                      key={part.id}
                    >
                      {part.label}
                      <textarea
                        rows={part.rows}
                        value={String(headPromptParts[part.id] || "")}
                        onChange={(event) => updateHeadPromptPart(part.id, event.target.value)}
                      />
                    </label>
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
                <label className="avatar-generation-wide-field">
                  Adjustment Request
                  <textarea
                    rows={5}
                    value={headInstruction}
                    onChange={(event) => setHeadInstruction(event.target.value)}
                    placeholder="Tell the local LLM what to change about the head, face, hair, expression, or portrait style."
                  />
                </label>
                <div className="row">
                  <button className="btn btn-primary" type="submit" disabled={busy || !headInstruction.trim()}>
                    {activeReferenceAction === "refine:head_face" ? "Refining..." : "Refine Prompt"}
                  </button>
                  <button className="btn" type="button" disabled={busy || !headPrompt.trim()} onClick={createHeadPreview}>
                    {activeReferenceAction === "preview:head_face" ? "Requesting..." : "Create Preview"}
                  </button>
                </div>
              </form>

              <aside className="avatar-head-face-latest-preview">
                <h3>Latest Preview</h3>
                {latestHeadPreview ? (
                  <>
                    {latestHeadPreviewOutput ? (
                      <a href={`${apiBase}${latestHeadPreviewOutput.url}`} target="_blank" rel="noreferrer">
                        <img
                          src={`${apiBase}${latestHeadPreviewOutput.url}`}
                          alt={latestHeadPreviewOutput.filename || latestHeadPreviewOutput.relative_path}
                        />
                      </a>
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
              {headPreviewHistory.length ? (
                <div className="avatar-reference-card-grid avatar-head-face-preview-history">
                  {headPreviewHistory.map((preview) => {
                    const output = headFacePreviewOutput(preview, manualOutputs, routeProfile);
                    return (
                      <article className="avatar-reference-card" key={preview.preview_id || preview.created_at}>
                        {output ? (
                          <a href={`${apiBase}${output.url}`} target="_blank" rel="noreferrer">
                            <img src={`${apiBase}${output.url}`} alt={output.filename || output.relative_path} />
                          </a>
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

        {["upper_torso", "lower_torso", "full_body"].includes(activeDetailTab) ? (
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
