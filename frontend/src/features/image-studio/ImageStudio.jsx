import { useEffect, useMemo, useState } from "react";

const CREATION_TYPES = [
  {
    id: "character",
    title: "Character",
    description: "Create a reusable identity, portrait, full-body character, pose, or character edit.",
    icon: "◉",
  },
  {
    id: "location",
    title: "Location",
    description: "Create a reusable interior, exterior, or environmental reference without characters.",
    icon: "⌂",
  },
  {
    id: "scene",
    title: "Scene",
    description: "Compose characters, locations, actions, lighting, and camera direction into one image.",
    icon: "▣",
  },
];

const CHARACTER_PATHS = [
  {
    id: "create_new",
    title: "Create New Character",
    description: "Define a new reusable identity, appearance, body, and initial character reference from scratch.",
    icon: "+",
  },
  {
    id: "use_existing",
    title: "Use Existing Character",
    description: "Select a saved character and create a new pose, expression, outfit, or camera view.",
    icon: "◎",
  },
  {
    id: "edit_image",
    title: "Edit Character Image",
    description: "Modify an existing character image with inpainting or image-to-image workflows.",
    icon: "✎",
  },
];

const CHARACTER_INTERVIEW_STEPS = [
  { id: "name_concept", title: "Name & concept", field: "concept", question: "What is the character's name, and what is the central idea that makes them distinctive?" },
  { id: "face_features", title: "Face & features", field: "appearance", question: "How should the character's face, hair, eyes, and defining features look?" },
  { id: "body_proportions", title: "Body & proportions", field: "body", question: "What body shape, proportions, height, and physical qualities should remain consistent?" },
  { id: "initial_clothing", title: "Initial clothing", field: "clothing", question: "What should the character wear in their initial reference image?" },
  { id: "initial_pose", title: "Initial pose", field: "pose", question: "What clear, neutral pose should establish the character's body and silhouette?" },
  { id: "expression", title: "Expression", field: "expression", question: "What facial expression best establishes the character's personality?" },
];

const CHARACTER_FOUNDATION_GROUPS = [
  { id: "gender_identity", label: "Gender", options: [
    { value: "male", label: "Male" },
    { value: "female", label: "Female" },
    { value: "non-binary", label: "Non-binary" },
    { value: "unspecified", label: "Unspecified" },
  ] },
  { id: "visual_style", label: "Visual style", options: [
    { value: "realistic", label: "Realistic" },
    { value: "semi-realistic", label: "Semi-realistic" },
    { value: "anime", label: "Anime" },
  ] },
  { id: "age_group", label: "Age group", options: [
    { value: "adult (18+)", label: "Adult (18+)" },
    { value: "teen (13-17)", label: "Teen (13–17)" },
    { value: "child (under 13)", label: "Child (under 13)" },
  ] },
  { id: "content_rating", label: "Content rating", options: [
    { value: "SFW", label: "SFW" },
    { value: "NSFW adult content", label: "NSFW — adults only", adultOnly: true },
  ] },
];

const FACE_FEATURE_OPTION_GROUPS = [
  { id: "apparent age", label: "Apparent age", options: ["teen", "young adult", "adult", "mature", "elderly"] },
  { id: "face shape", label: "Face shape", options: ["oval", "round", "square", "heart-shaped", "diamond", "oblong", "triangular", "soft angular"] },
  { id: "skin tone", label: "Skin tone", options: ["porcelain", "fair", "light", "light-medium", "medium", "olive", "tan", "brown", "deep brown", "ebony"] },
  { id: "complexion", label: "Complexion", multiple: true, options: ["clear", "dewy", "matte", "sun-kissed", "freckled", "rosy cheeks", "weathered", "vitiligo"] },
  { id: "eye shape", label: "Eye shape", options: ["almond", "round", "hooded", "monolid", "upturned", "downturned", "deep-set", "wide-set", "close-set"] },
  { id: "eye color", label: "Eye color", options: ["dark brown", "brown", "hazel", "amber", "green", "blue", "gray", "violet", "heterochromia", "unnatural glowing"] },
  { id: "eyebrows", label: "Eyebrows", options: ["straight", "softly arched", "high arched", "thick", "thin", "bushy", "defined", "scar through brow"] },
  { id: "nose", label: "Nose", options: ["small", "straight", "button", "upturned", "broad", "aquiline", "Roman", "flat bridge", "prominent"] },
  { id: "lips", label: "Lips", options: ["thin", "medium", "full", "wide", "small", "defined Cupid's bow", "soft Cupid's bow", "asymmetrical"] },
  { id: "hair texture", label: "Hair texture", options: ["straight", "wavy", "curly", "coily", "kinky", "silky", "coarse", "shaved"] },
  { id: "hair length", label: "Hair length", options: ["bald", "buzz cut", "short", "chin-length", "shoulder-length", "long", "waist-length"] },
  { id: "hair color", label: "Hair color", options: ["black", "dark brown", "brown", "auburn", "copper", "red", "strawberry blonde", "blonde", "platinum", "gray", "white", "blue", "pink", "multicolored"] },
  { id: "hairstyle", label: "Hairstyle", multiple: true, options: ["loose", "layered", "bob", "pixie cut", "pompadour", "undercut", "braids", "cornrows", "locs", "afro", "ponytail", "bun", "bangs", "side part"] },
  { id: "distinctive features", label: "Distinctive features", multiple: true, options: ["dimples", "beauty mark", "facial freckles", "birthmark", "facial scar", "tattoo", "ear piercings", "nose piercing", "lip piercing", "pointed ears", "gap tooth", "prosthetic eye", "facial cybernetics"] },
  { id: "facial hair", label: "Facial hair", multiple: true, options: ["clean-shaven", "stubble", "mustache", "goatee", "short beard", "full beard", "sideburns", "shaped beard"] },
];

const OPTION_COLOR_SWATCHES = {
  "skin tone": {
    porcelain: "#f6dfd0", fair: "#edc8ad", light: "#dfb090", "light-medium": "#c9906b",
    medium: "#ad7654", olive: "#9a7651", tan: "#98603f", brown: "#75452f",
    "deep brown": "#4d2c22", ebony: "#261713",
  },
  "eye color": {
    "dark brown": "#3c2418", brown: "#704526", hazel: "#8d793f", amber: "#c88924",
    green: "#4f7b52", blue: "#4f83bd", gray: "#89939c", violet: "#7555a3",
    heterochromia: "linear-gradient(90deg, #4f83bd 0 50%, #8d793f 50%)",
    "unnatural glowing": "#62f4ed",
  },
  "hair color": {
    black: "#17171a", "dark brown": "#3b261d", brown: "#704629", auburn: "#79402e",
    copper: "#b75d32", red: "#a62f2f", "strawberry blonde": "#d9976a", blonde: "#d9bd72",
    platinum: "#e9e5dc", gray: "#8c9198", white: "#f5f5f2", blue: "#3a6fc4",
    pink: "#df78a8", multicolored: "linear-gradient(90deg, #e65b5b, #e1c85e, #56a87a, #5c7edc, #b45fbd)",
  },
};

const OPTION_PICTOGRAMS = {
  male: "♂", female: "♀", "non-binary": "⚧", unspecified: "○",
  realistic: "📷", "semi-realistic": "🎨", anime: "✨",
  "adult (18+)": "🧑", "teen (13-17)": "🧒", "child (under 13)": "👦",
  SFW: "🛡", "NSFW adult content": "18+",
  teen: "🧑", "young adult": "🧑", adult: "👤", mature: "🧔", elderly: "👵",
  oval: "⬭", round: "●", square: "■", "heart-shaped": "♥", diamond: "◆", oblong: "▯", triangular: "▲", "soft angular": "⬡",
  clear: "◌", dewy: "✦", matte: "●", "sun-kissed": "☀", freckled: "⠿", "rosy cheeks": "❀", weathered: "≋", vitiligo: "◐",
  almond: "◒", hooded: "◓", monolid: "━", upturned: "⌃", downturned: "⌄", "deep-set": "◉", "wide-set": "◉  ◉", "close-set": "◉◉",
  straight: "━", "softly arched": "⌒", "high arched": "︿", thick: "▬", thin: "─", bushy: "〰", defined: "⌁", "scar through brow": "╱",
  bald: "◯", "buzz cut": "▦", short: "▰", "chin-length": "◒", "shoulder-length": "◫", long: "▯", "waist-length": "▥",
};

const GROUP_PICTOGRAMS = {
  gender_identity: "⚧", visual_style: "◈", age_group: "◷", content_rating: "◆",
  eyebrows: "⌒", nose: "👃", lips: "👄", "hair texture": "〰", hairstyle: "💇",
  "distinctive features": "✦", "facial hair": "🧔", "eye shape": "◉",
};

const FACE_FEATURE_OPTION_SPRITES = {
  "face shape": { src: "/image-studio/guides/face-shape-options-v2.webp", columns: 4, rows: 2 },
  "eye shape": { src: "/image-studio/guides/eye-shape-options-v2.webp", columns: 3, rows: 3 },
  nose: { src: "/image-studio/guides/nose-shape-options-v2.webp", columns: 3, rows: 3 },
  lips: { src: "/image-studio/guides/lip-shape-options-v2.webp", columns: 4, rows: 2 },
};

function OptionVisual({ groupId, value }) {
  const swatch = OPTION_COLOR_SWATCHES[groupId]?.[value];
  if (swatch) {
    return <span className="image-studio-option-visual is-swatch" style={{ background: swatch }} aria-hidden="true" />;
  }
  return <span className="image-studio-option-visual" aria-hidden="true">{OPTION_PICTOGRAMS[value] || GROUP_PICTOGRAMS[groupId] || "◇"}</span>;
}

function FaceFeatureOptionVisual({ group, option }) {
  const sprite = FACE_FEATURE_OPTION_SPRITES[group.id];
  const optionIndex = group.options.indexOf(option);
  if (!sprite || optionIndex < 0) {
    return <OptionVisual groupId={group.id} value={option} />;
  }
  const column = optionIndex % sprite.columns;
  const row = Math.floor(optionIndex / sprite.columns);
  const x = sprite.columns === 1 ? 0 : (column / (sprite.columns - 1)) * 100;
  const y = sprite.rows === 1 ? 0 : (row / (sprite.rows - 1)) * 100;
  return (
    <span
      className="image-studio-feature-option-image"
      style={{
        backgroundImage: `url(${sprite.src})`,
        backgroundPosition: `${x}% ${y}%`,
        backgroundSize: `${sprite.columns * 100}% ${sprite.rows * 100}%`,
      }}
      aria-hidden="true"
    />
  );
}

function composeFaceDescription(selections, customDetails) {
  const selectedDetails = FACE_FEATURE_OPTION_GROUPS.flatMap((group) => {
    const values = selections[group.id] || [];
    return values.length ? [`${group.id}: ${values.join(", ")}`] : [];
  });
  const custom = String(customDetails || "").trim();
  return [...selectedDetails, ...(custom ? [custom] : [])].join("; ");
}

function applyCharacterFoundation(current, field, value) {
  const next = { ...current, [field]: value };
  if (field === "age_group" && value !== "adult (18+)" && next.content_rating === "NSFW adult content") {
    next.content_rating = "SFW";
  }
  return next;
}

function characterDraftBrief(profile) {
  try {
    const initialData = JSON.parse(String(profile?.initial_data || ""));
    return initialData?.source === "image_studio" && initialData.character_brief && typeof initialData.character_brief === "object"
      ? initialData.character_brief
      : null;
  } catch {
    return null;
  }
}

function nextIncompleteInterviewStep(brief) {
  if (!brief?.appearance) return 1;
  if (!brief?.body) return 2;
  if (!brief?.clothing) return 3;
  if (!brief?.pose) return 4;
  return 5;
}

function templateCreationType(template) {
  const domain = String(template?.metadata?.domain || "").trim().toLowerCase();
  const intent = String(template?.metadata?.edit_intent || "").trim().toLowerCase();
  const searchable = `${domain} ${intent}`;
  if (/scene|composition|cinematic/.test(searchable)) {
    return "scene";
  }
  if (/location|place|environment|interior|exterior/.test(searchable)) {
    return "location";
  }
  if (/avatar|character|portrait|face|body|clothing/.test(searchable)) {
    return "character";
  }
  return "unclassified";
}

function templateCharacterPath(template) {
  const name = String(template?.template_name || "").trim().toLowerCase();
  const domain = String(template?.metadata?.domain || "").trim().toLowerCase();
  const intent = String(template?.metadata?.edit_intent || "").trim().toLowerCase();
  const inputMode = String(template?.metadata?.input_mode || "").trim().toLowerCase();
  const searchable = `${name} ${domain} ${intent} ${inputMode}`;
  if (/simple avatar generation|body_depth_reference|create.new|from.scratch/.test(searchable)) {
    return "create_new";
  }
  if (/inpaint|img2img|image.to.image|clothing|unclothed/.test(searchable) || inputMode === "image") {
    return "edit_image";
  }
  return "use_existing";
}

export function ImageStudio({
  templates = [],
  initialCreationType = "",
  initialCharacterPath = "",
  initialSelectedTemplateId = "",
  initialCreativeSetupOpen = false,
  initialInterviewOpen = false,
  initialInterviewStep = 0,
  runtimeStatus = null,
  dataLoading = false,
  dataError = "",
  promptHelperBusy = false,
  interviewBusy = false,
  characterProfiles = [],
  characterSaveBusy = false,
  onImprovePrompt,
  onInterviewQuestion,
  onSaveCharacterDraft,
  onRefreshData,
  onOpenLegacy,
  onClose,
}) {
  const [creationType, setCreationType] = useState(initialCreationType);
  const [characterPath, setCharacterPath] = useState(initialCharacterPath);
  const [selectedTemplateId, setSelectedTemplateId] = useState(initialSelectedTemplateId);
  const [creativeSetupOpen, setCreativeSetupOpen] = useState(initialCreativeSetupOpen);
  const [characterBrief, setCharacterBrief] = useState({
    name: "",
    concept: "",
    gender_identity: "",
    visual_style: "",
    age_group: "",
    content_rating: "",
    appearance: "",
    body: "",
    clothing: "",
    pose: "",
    expression: "",
    background: "transparent background, isolated full-body character",
    quality: "consistent identity, detailed face, natural hands, high quality",
  });
  const [promptDraft, setPromptDraft] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("low quality, blurry, distorted face, extra limbs, malformed hands, watermark, text");
  const [interviewOpen, setInterviewOpen] = useState(initialInterviewOpen);
  const [interviewStep, setInterviewStep] = useState(initialInterviewStep);
  const [interviewLlmEnabled, setInterviewLlmEnabled] = useState(true);
  const [interviewQuestion, setInterviewQuestion] = useState(CHARACTER_INTERVIEW_STEPS[0].question);
  const [interviewGuidance, setInterviewGuidance] = useState("");
  const [interviewMissingDetails, setInterviewMissingDetails] = useState([]);
  const [interviewQuestionCounts, setInterviewQuestionCounts] = useState({});
  const [completedInterviewSteps, setCompletedInterviewSteps] = useState({});
  const [faceFeatureSelections, setFaceFeatureSelections] = useState({});
  const [faceCustomDetails, setFaceCustomDetails] = useState("");
  const [draftSaveMessage, setDraftSaveMessage] = useState("");
  const matchingTemplates = useMemo(
    () => templates.filter((template) => {
      if (templateCreationType(template) !== creationType) {
        return false;
      }
      return creationType !== "character" || (characterPath && templateCharacterPath(template) === characterPath);
    }),
    [characterPath, creationType, templates]
  );
  const incompleteCharacterProfiles = useMemo(
    () => characterProfiles.filter((profile) => profile?.completion_status === "incomplete"),
    [characterProfiles]
  );
  const selectedTemplate = matchingTemplates.find((template) => template.template_id === selectedTemplateId) || null;
  const composedCharacterPrompt = [
    characterBrief.gender_identity && `${characterBrief.gender_identity} character`,
    characterBrief.age_group,
    characterBrief.visual_style && `${characterBrief.visual_style} visual style`,
    characterBrief.content_rating,
    characterBrief.concept,
    characterBrief.appearance,
    characterBrief.body,
    characterBrief.clothing,
    characterBrief.pose,
    characterBrief.expression,
    characterBrief.background,
    characterBrief.quality,
  ].map((value) => String(value || "").trim()).filter(Boolean).join(", ");
  const effectiveCharacterPrompt = promptDraft || composedCharacterPrompt;
  const textService = runtimeStatus?.services?.local_llm || {};
  const textResidency = textService.model_residency || {};
  const textModelLoaded = textResidency.model_state === "loaded" || textService.always_on?.default_model_loaded === true;
  const activeInterviewStep = CHARACTER_INTERVIEW_STEPS[interviewStep];
  const characterFoundationComplete = CHARACTER_FOUNDATION_GROUPS.every((group) => Boolean(characterBrief[group.id]));
  const nameConceptComplete = Boolean(characterBrief.name.trim() && characterBrief.concept.trim() && characterFoundationComplete);
  const currentInterviewAnswer = activeInterviewStep.id === "name_concept"
    ? [
      characterBrief.name,
      characterBrief.concept,
      ...CHARACTER_FOUNDATION_GROUPS.map((group) => characterBrief[group.id]),
    ].filter(Boolean).join(" — ")
    : characterBrief[activeInterviewStep.field] || "";

  useEffect(() => {
    if (!interviewOpen) {
      return;
    }
    setInterviewQuestion(activeInterviewStep.question);
    setInterviewGuidance("");
    setInterviewMissingDetails([]);
    if (!interviewLlmEnabled || !textModelLoaded) {
      return;
    }
    let cancelled = false;
    const request = onInterviewQuestion?.({
      step_id: activeInterviewStep.id,
      character_brief: characterBrief,
      current_answer: currentInterviewAnswer,
      review_answer: false,
      questions_asked: interviewQuestionCounts[activeInterviewStep.id] || 0,
    });
    void request?.then((result) => {
      if (cancelled || !result) {
        return;
      }
      setInterviewQuestion(result.question || activeInterviewStep.question);
      setInterviewGuidance(result.guidance || "");
      setInterviewMissingDetails(Array.isArray(result.missing_details) ? result.missing_details : []);
    });
    return () => { cancelled = true; };
  }, [interviewOpen, interviewStep, interviewLlmEnabled]);

  function selectCreationType(type) {
    setCreationType(type);
    setCharacterPath("");
    setSelectedTemplateId("");
    setCreativeSetupOpen(false);
  }

  function selectCharacterPath(path) {
    setCharacterPath(path);
    setSelectedTemplateId("");
    setCreativeSetupOpen(false);
  }

  function updateCharacterBrief(field, value) {
    setCharacterBrief((current) => ({ ...current, [field]: value }));
    setPromptDraft("");
  }

  function selectCharacterFoundation(field, value) {
    setCharacterBrief((current) => applyCharacterFoundation(current, field, value));
    setPromptDraft("");
  }

  function toggleFaceFeature(group, option) {
    const selected = faceFeatureSelections[group.id] || [];
    const nextValues = group.multiple
      ? selected.includes(option) ? selected.filter((item) => item !== option) : [...selected, option]
      : selected.includes(option) ? [] : [option];
    const next = { ...faceFeatureSelections, [group.id]: nextValues };
    setFaceFeatureSelections(next);
    updateCharacterBrief("appearance", composeFaceDescription(next, faceCustomDetails));
  }

  function updateFaceCustomDetails(value) {
    setFaceCustomDetails(value);
    updateCharacterBrief("appearance", composeFaceDescription(faceFeatureSelections, value));
  }

  async function saveIncompleteCharacter() {
    if (!nameConceptComplete || characterSaveBusy || !onSaveCharacterDraft) {
      return;
    }
    setDraftSaveMessage("");
    const result = await onSaveCharacterDraft({
      name: characterBrief.name,
      description: characterBrief.concept,
      gender: characterBrief.gender_identity,
      character_type: characterBrief.age_group,
      visual_style: characterBrief.visual_style,
      nsfw: characterBrief.content_rating === "NSFW adult content",
      completion_status: "incomplete",
      initial_data: JSON.stringify({
        schema_version: "1.0",
        source: "image_studio",
        character_brief: characterBrief,
      }),
    });
    if (!result?.profile) {
      return;
    }
    setDraftSaveMessage("Saved as an incomplete character.");
    setInterviewOpen(false);
    setCreativeSetupOpen(false);
  }

  function continueIncompleteCharacter(profile) {
    const savedBrief = characterDraftBrief(profile);
    if (!savedBrief) {
      return;
    }
    const candidateTemplate = selectedTemplate || matchingTemplates[0];
    if (candidateTemplate) {
      setSelectedTemplateId(candidateTemplate.template_id);
    }
    setCharacterBrief((current) => ({ ...current, ...savedBrief }));
    setPromptDraft("");
    setInterviewStep(nextIncompleteInterviewStep(savedBrief));
    setCreativeSetupOpen(true);
    setInterviewOpen(true);
    setDraftSaveMessage("");
  }

  async function improveCharacterPrompt() {
    if (!effectiveCharacterPrompt || promptHelperBusy || !selectedTemplate) {
      return;
    }
    const result = await onImprovePrompt?.({
      template_id: selectedTemplate.template_id,
      mode: "txt2img",
      prompt: effectiveCharacterPrompt,
      negative_prompt: negativePrompt,
      width: Number(selectedTemplate.defaults?.width || 768),
      height: Number(selectedTemplate.defaults?.height || 1152),
      reference_image_provided: false,
    });
    if (result?.prompt) {
      setPromptDraft(String(result.prompt));
    }
    if (result?.negative_prompt) {
      setNegativePrompt(String(result.negative_prompt));
    }
  }

  function openCharacterInterview() {
    setInterviewStep(0);
    setInterviewOpen(true);
  }

  function moveCharacterInterview(direction) {
    const nextStep = Math.min(Math.max(interviewStep + direction, 0), CHARACTER_INTERVIEW_STEPS.length - 1);
    setInterviewStep(nextStep);
  }

  function completeCurrentInterviewStep() {
    setCompletedInterviewSteps((current) => ({ ...current, [activeInterviewStep.id]: true }));
    if (interviewStep < CHARACTER_INTERVIEW_STEPS.length - 1) {
      moveCharacterInterview(1);
    } else {
      setInterviewOpen(false);
    }
  }

  async function reviewCharacterInterviewAnswer() {
    if (!currentInterviewAnswer.trim() || interviewBusy) {
      return;
    }
    if (!interviewLlmEnabled || !textModelLoaded || !onInterviewQuestion) {
      if (interviewStep < CHARACTER_INTERVIEW_STEPS.length - 1) {
        moveCharacterInterview(1);
      } else {
        setInterviewOpen(false);
      }
      return;
    }
    const questionsAsked = (interviewQuestionCounts[activeInterviewStep.id] || 0) + 1;
    const result = await onInterviewQuestion({
      step_id: activeInterviewStep.id,
      character_brief: characterBrief,
      current_answer: currentInterviewAnswer,
      review_answer: true,
      questions_asked: questionsAsked,
    });
    if (!result) {
      completeCurrentInterviewStep();
      return;
    }
    setInterviewQuestionCounts((current) => ({ ...current, [activeInterviewStep.id]: questionsAsked }));
    setInterviewGuidance(result.guidance || "");
    setInterviewMissingDetails(Array.isArray(result.missing_details) ? result.missing_details : []);
    if (!result.complete) {
      setInterviewQuestion(result.question || activeInterviewStep.question);
      return;
    }
    completeCurrentInterviewStep();
  }

  const choosingCharacterPath = creationType === "character" && !characterPath;
  const studioSteps = creationType === "character"
    ? ["Creation type", "Character goal", "Template", "Creative setup", "Generate"]
    : ["Creation type", "Template", "Creative setup", "Generate"];
  const activeStep = !creationType ? 0 : choosingCharacterPath ? 1 : creativeSetupOpen ? 3 : creationType === "character" ? 2 : 1;

  return (
    <section className="image-studio-shell">
      <header className="image-studio-header">
        <div>
          <span className="image-studio-eyebrow">Hexe Image Studio</span>
          <h1>Create an image</h1>
          <p>Start with the kind of reusable asset or composed image you want to make.</p>
        </div>
        <div className="row">
          <button className="btn" type="button" onClick={onOpenLegacy}>Legacy Generator</button>
          <button className="btn" type="button" onClick={onClose}>Close Studio</button>
        </div>
      </header>

      {dataLoading ? <div className="image-studio-data-state">Loading Image Studio data…</div> : null}
      {dataError ? (
        <div className="image-studio-data-state is-error">
          <span>{dataError}</span>
          <button className="btn" type="button" onClick={onRefreshData}>Retry</button>
        </div>
      ) : null}

      <div className={`image-studio-progress ${studioSteps.length === 5 ? "has-five-steps" : ""}`} aria-label="Image Studio steps">
        {studioSteps.map((step, index) => (
          <div className={index <= activeStep ? "is-active" : ""} key={step}><span>{index + 1}</span><strong>{step}</strong></div>
        ))}
      </div>

      {!creationType ? (
        <div className="image-studio-stage">
          <div className="image-studio-stage-heading">
            <span>Step 1</span>
            <h2>What are you creating?</h2>
            <p>Choose the asset type first. The studio will only show workflows designed for that purpose.</p>
          </div>
          <div className="image-studio-type-grid">
            {CREATION_TYPES.map((type) => (
              <button className="image-studio-type-card" type="button" key={type.id} onClick={() => selectCreationType(type.id)}>
                <span className="image-studio-type-icon">{type.icon}</span>
                <strong>{type.title}</strong>
                <p>{type.description}</p>
                <span className="image-studio-card-action">Choose {type.title} →</span>
              </button>
            ))}
          </div>
        </div>
      ) : choosingCharacterPath ? (
        <div className="image-studio-stage">
          <div className="image-studio-stage-heading image-studio-stage-heading-row">
            <div>
              <span>Step 2</span>
              <h2>What would you like to do with the character?</h2>
              <p>Your answer determines which workflows and reference inputs the studio will offer.</p>
            </div>
            <button className="btn" type="button" onClick={() => selectCreationType("")}>← Change type</button>
          </div>
          <div className="image-studio-type-grid">
            {CHARACTER_PATHS.map((path) => (
              <button className="image-studio-type-card" type="button" key={path.id} onClick={() => selectCharacterPath(path.id)}>
                <span className="image-studio-type-icon">{path.icon}</span>
                <strong>{path.title}</strong>
                <p>{path.description}</p>
                <span className="image-studio-card-action">Choose {path.title} →</span>
              </button>
            ))}
          </div>
        </div>
      ) : creativeSetupOpen && creationType === "character" && characterPath === "create_new" ? (
        <div className="image-studio-stage">
          <div className="image-studio-stage-heading image-studio-stage-heading-row">
            <div>
              <span>Step 4</span>
              <h2>Define the new character</h2>
              <p>Create a reusable identity brief. The local text model can refine it into the final generation prompt.</p>
            </div>
            <button className="btn" type="button" onClick={() => setCreativeSetupOpen(false)}>← Change template</button>
          </div>

          <div className={`image-studio-llm-status ${textModelLoaded ? "is-ready" : ""}`}>
            <div><span>Prompt assistant</span><strong>{textModelLoaded ? "Local text LLM loaded" : "Local text LLM unavailable"}</strong></div>
            <code>{textResidency.loaded_model || textService.always_on?.default_model_id || "No resident model detected"}</code>
          </div>

          <div className="image-studio-interview-launch">
            <div>
              <strong>Prefer a guided conversation?</strong>
              <p>Answer six focused questions instead of filling the whole brief at once.</p>
            </div>
            <button className="btn btn-primary" type="button" onClick={openCharacterInterview}>Start Character Interview</button>
          </div>

          <div className="image-studio-brief-grid">
            <label>Character name<input value={characterBrief.name} onChange={(event) => updateCharacterBrief("name", event.target.value)} placeholder="A reusable profile name" /></label>
            <label>Core concept<input value={characterBrief.concept} onChange={(event) => updateCharacterBrief("concept", event.target.value)} placeholder="Who is this character?" /></label>
            <label>Face, hair, and features<textarea rows={4} value={characterBrief.appearance} onChange={(event) => updateCharacterBrief("appearance", event.target.value)} /></label>
            <label>Body and proportions<textarea rows={4} value={characterBrief.body} onChange={(event) => updateCharacterBrief("body", event.target.value)} /></label>
            <label>Initial clothing<textarea rows={3} value={characterBrief.clothing} onChange={(event) => updateCharacterBrief("clothing", event.target.value)} /></label>
            <label>Initial pose<textarea rows={3} value={characterBrief.pose} onChange={(event) => updateCharacterBrief("pose", event.target.value)} /></label>
            <label>Expression<input value={characterBrief.expression} onChange={(event) => updateCharacterBrief("expression", event.target.value)} /></label>
            <label>Background<input value={characterBrief.background} onChange={(event) => updateCharacterBrief("background", event.target.value)} /></label>
          </div>

          <label className="image-studio-full-field">
            Master prompt
            <textarea rows={7} value={effectiveCharacterPrompt} onChange={(event) => setPromptDraft(event.target.value)} />
          </label>
          <label className="image-studio-full-field">
            Avoid
            <textarea rows={3} value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} />
          </label>
          <div className="row">
            <button className="btn btn-primary" type="button" onClick={improveCharacterPrompt} disabled={!effectiveCharacterPrompt || promptHelperBusy || !textModelLoaded}>
              {promptHelperBusy ? "Drafting with local LLM..." : "Draft / Improve Master Prompt"}
            </button>
          </div>

          <div className="image-studio-requirement-note">
            <strong>Identity bootstrap required before generation</strong>
            <p>The selected local workflow currently requires face and body references. The next studio increment will create or collect those baseline assets before enabling Generate.</p>
          </div>
        </div>
      ) : (
        <div className="image-studio-stage">
          <div className="image-studio-stage-heading image-studio-stage-heading-row">
            <div>
              <span>{`Step ${creationType === "character" ? 3 : 2}`}</span>
              <h2>{`Choose a ${creationType} template`}</h2>
              <p>Templates define the required references, model workflow, and available controls.</p>
            </div>
            <button className="btn" type="button" onClick={() => creationType === "character" ? selectCharacterPath("") : selectCreationType("")}>
              {creationType === "character" ? "← Change character goal" : "← Change type"}
            </button>
          </div>
          {creationType === "character" && characterPath === "create_new" && incompleteCharacterProfiles.length ? (
            <section className="image-studio-draft-section">
              <div>
                <span>Saved progress</span>
                <h3>Incomplete characters</h3>
                <p>Continue a saved character or choose a template for a new one.</p>
              </div>
              <div className="image-studio-draft-grid">
                {incompleteCharacterProfiles.map((profile) => (
                  <button className="image-studio-draft-card" type="button" key={profile.profile_id} onClick={() => continueIncompleteCharacter(profile)}>
                    <span>Incomplete</span>
                    <strong>{profile.name || profile.profile_id}</strong>
                    <p>{profile.description || "Character identity saved; visual details are still in progress."}</p>
                    <small>{[profile.gender, profile.character_type, profile.visual_style].filter(Boolean).join(" · ")}</small>
                    <b>Continue character →</b>
                  </button>
                ))}
              </div>
            </section>
          ) : null}
          {matchingTemplates.length ? (
            <div className="image-studio-template-grid">
              {matchingTemplates.map((template) => {
                const selected = template.template_id === selectedTemplateId;
                return (
                  <button
                    className={`image-studio-template-card ${selected ? "is-selected" : ""}`}
                    type="button"
                    key={template.template_id}
                    onClick={() => { setSelectedTemplateId(template.template_id); setCreativeSetupOpen(false); }}
                  >
                    <span>{template.metadata?.input_mode || "image generation"}</span>
                    <strong>{template.template_name || template.template_id}</strong>
                    <p>{template.description || "No workflow description is available yet."}</p>
                    <small>{template.metadata?.edit_intent?.replaceAll("_", " ") || template.template_id}</small>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="image-studio-empty-state">
              <strong>{`No ${creationType} templates are installed yet.`}</strong>
              <p>This workspace is ready for the new template family. Existing character workflows remain safely available.</p>
              <button className="btn" type="button" onClick={() => selectCreationType("")}>Choose another type</button>
            </div>
          )}
          {selectedTemplate ? (
            <div className="image-studio-selection-bar">
              <div><span>Selected workflow</span><strong>{selectedTemplate.template_name || selectedTemplate.template_id}</strong></div>
              <button
                className="btn btn-primary"
                type="button"
                disabled={creationType !== "character" || characterPath !== "create_new"}
                onClick={() => setCreativeSetupOpen(true)}
              >
                Continue to creative setup
              </button>
            </div>
          ) : null}
        </div>
      )}

      {interviewOpen ? (
        <div className="image-studio-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setInterviewOpen(false); }}>
          <section className="image-studio-interview-modal" role="dialog" aria-modal="true" aria-labelledby="character-interview-title">
            <header>
              <div>
                <span className="image-studio-eyebrow">Character interview</span>
                <h2 id="character-interview-title">{activeInterviewStep.title}</h2>
              </div>
              <button className="btn" type="button" onClick={() => setInterviewOpen(false)}>Close</button>
            </header>
            <div className="image-studio-interview-progress">
              {CHARACTER_INTERVIEW_STEPS.map((step, index) => (
                <button className={index === interviewStep ? "is-active" : completedInterviewSteps[step.id] ? "is-complete" : ""} type="button" key={step.id} onClick={() => setInterviewStep(index)}>
                  <span>{index + 1}</span><small>{step.title}</small>
                </button>
              ))}
            </div>
            <label className="image-studio-llm-toggle">
              <input type="checkbox" checked={interviewLlmEnabled} onChange={(event) => setInterviewLlmEnabled(event.target.checked)} disabled={!textModelLoaded} />
              Let the local LLM ask guiding questions
            </label>
            <div className="image-studio-interview-question">
              <span>{interviewBusy ? "Local LLM is preparing the next question…" : interviewLlmEnabled && textModelLoaded ? "Local LLM asks" : "Guided question"}</span>
              <strong>{interviewQuestion}</strong>
              {interviewGuidance ? <p>{interviewGuidance}</p> : null}
              {interviewMissingDetails.length ? <p>{`Still useful: ${interviewMissingDetails.join(", ")}`}</p> : null}
            </div>
            {activeInterviewStep.id === "name_concept" ? (
              <div className="image-studio-foundation-builder">
                <div className="image-studio-brief-grid">
                  <label>Character name<input autoFocus value={characterBrief.name} onChange={(event) => updateCharacterBrief("name", event.target.value)} /></label>
                  <label>Character concept<input value={characterBrief.concept} onChange={(event) => updateCharacterBrief("concept", event.target.value)} /></label>
                </div>
                <div className="image-studio-foundation-options">
                  {CHARACTER_FOUNDATION_GROUPS.map((group) => (
                    <fieldset key={group.id}>
                      <legend>{group.label} <small>Required</small></legend>
                      <div className="image-studio-option-chips">
                        {group.options.map((option) => {
                          const disabled = option.adultOnly && characterBrief.age_group !== "adult (18+)";
                          const selected = characterBrief[group.id] === option.value;
                          return (
                            <button
                              className={selected ? "is-selected" : ""}
                              type="button"
                              aria-pressed={selected}
                              disabled={disabled}
                              title={disabled ? "NSFW is available only when Age group is Adult (18+)." : ""}
                              key={option.value}
                              onClick={() => selectCharacterFoundation(group.id, option.value)}
                            >
                              <OptionVisual groupId={group.id} value={option.value} />
                              {option.label}
                            </button>
                          );
                        })}
                      </div>
                    </fieldset>
                  ))}
                </div>
                {characterBrief.age_group && characterBrief.age_group !== "adult (18+)" ? (
                  <p className="image-studio-safety-note">Teen and child characters are restricted to SFW content.</p>
                ) : null}
                <div className="image-studio-draft-save">
                  <div>
                    <strong>Save your progress</strong>
                    <p>This stores the identity as an incomplete character and returns to Step 3.</p>
                  </div>
                  <button className="btn" type="button" onClick={saveIncompleteCharacter} disabled={!nameConceptComplete || characterSaveBusy}>
                    {characterSaveBusy ? "Saving character…" : "Save incomplete character"}
                  </button>
                </div>
                {draftSaveMessage ? <p className="success">{draftSaveMessage}</p> : null}
              </div>
            ) : activeInterviewStep.id === "face_features" ? (
              <div className="image-studio-face-workspace">
                <div className="image-studio-face-builder">
                  <p>Select the traits that should stay consistent. Choose one per group unless the group allows multiple.</p>
                  <div className="image-studio-face-options">
                    {FACE_FEATURE_OPTION_GROUPS.map((group) => (
                      <fieldset key={group.id}>
                        <legend>{group.label}{group.multiple ? <small> Select any</small> : null}</legend>
                        <div className={`image-studio-option-chips ${FACE_FEATURE_OPTION_SPRITES[group.id] ? "has-feature-images" : ""}`}>
                          {group.options.map((option) => {
                            const selected = (faceFeatureSelections[group.id] || []).includes(option);
                            return (
                              <button
                                className={selected ? "is-selected" : ""}
                                type="button"
                                aria-pressed={selected}
                                key={option}
                                onClick={() => toggleFaceFeature(group, option)}
                              >
                                <FaceFeatureOptionVisual group={group} option={option} />
                                <span>{option}</span>
                              </button>
                            );
                          })}
                        </div>
                      </fieldset>
                    ))}
                  </div>
                  <label className="image-studio-full-field">
                    Additional face details
                    <textarea rows={3} value={faceCustomDetails} onChange={(event) => updateFaceCustomDetails(event.target.value)} placeholder="Add features not covered above or expand on a selection." />
                  </label>
                  <div className="image-studio-face-summary">
                    <span>Combined face description</span>
                    <p>{characterBrief.appearance || "Choose options or add custom details to build the face description."}</p>
                  </div>
                </div>
                <aside className="image-studio-face-preview">
                  <span className="image-studio-eyebrow">Rendered preview</span>
                  <div className="image-studio-face-preview-canvas">
                    <span>Portrait preview</span>
                    <p>Your selected face traits will be rendered here.</p>
                  </div>
                  <button className="btn btn-primary" type="button" disabled title="CPU preview generation will be connected in the next generation step">
                    Generate face preview
                  </button>
                  <small>CPU preview workflow connection is the next step.</small>
                </aside>
                </div>
            ) : (
              <label className="image-studio-full-field">
                Your answer
                <textarea autoFocus rows={6} value={characterBrief[activeInterviewStep.field]} onChange={(event) => updateCharacterBrief(activeInterviewStep.field, event.target.value)} />
              </label>
            )}
            <footer>
              <button className="btn" type="button" onClick={() => moveCharacterInterview(-1)} disabled={interviewStep === 0}>Back</button>
              <span>{`${interviewStep + 1} of ${CHARACTER_INTERVIEW_STEPS.length}`}</span>
              <div className="row">
                {interviewLlmEnabled && textModelLoaded ? (
                  <button className="btn" type="button" onClick={completeCurrentInterviewStep} disabled={(activeInterviewStep.id === "name_concept" ? !nameConceptComplete : !currentInterviewAnswer.trim()) || interviewBusy}>
                    {interviewStep < CHARACTER_INTERVIEW_STEPS.length - 1 ? "Continue anyway" : "Finish anyway"}
                  </button>
                ) : null}
                <button className="btn btn-primary" type="button" onClick={reviewCharacterInterviewAnswer} disabled={(activeInterviewStep.id === "name_concept" ? !nameConceptComplete : !currentInterviewAnswer.trim()) || interviewBusy}>
                  {interviewBusy ? "Checking answer…" : interviewLlmEnabled && textModelLoaded ? "Check answer with LLM" : interviewStep < CHARACTER_INTERVIEW_STEPS.length - 1 ? "Next question" : "Finish interview"}
                </button>
              </div>
            </footer>
          </section>
        </div>
      ) : null}
    </section>
  );
}

export { applyCharacterFoundation, characterDraftBrief, nextIncompleteInterviewStep, templateCharacterPath, templateCreationType };
