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

const BODY_FEATURE_GROUPS = [
  { id: "height", label: "Height", options: ["short", "below average", "average", "tall", "very tall"] },
  { id: "build", label: "Overall build", options: ["slender", "lean", "average", "athletic", "curvy", "stocky", "heavyset"] },
  { id: "shoulders", label: "Shoulders", options: ["narrow", "balanced", "broad", "softly rounded", "angular"] },
  { id: "torso", label: "Torso", options: ["short torso", "balanced torso", "long torso", "straight torso", "tapered torso"] },
  { id: "waist", label: "Waist", options: ["subtle waist", "defined waist", "narrow waist", "straight waist", "broad waist"] },
  { id: "hips", label: "Hips", options: ["narrow hips", "balanced hips", "wide hips", "rounded hips", "angular hips"] },
  { id: "limbs", label: "Limb proportions", options: ["short limbs", "balanced limbs", "long legs", "long arms", "long limbs"] },
  { id: "musculature", label: "Musculature", options: ["soft definition", "lightly toned", "athletic definition", "muscular", "strongly muscular"] },
];

function composeBodyDescription(selections = {}, customDetails = "") {
  const parts = BODY_FEATURE_GROUPS.flatMap((group) => (selections[group.id] || []).map((value) => `${group.label.toLowerCase()}: ${value}`));
  if (String(customDetails || "").trim()) parts.push(String(customDetails).trim());
  return parts.join("; ");
}

function buildBodyPreviewPrompt(characterBrief) {
  return [
    "EXACTLY ONE ADULT BODY. Neck-down full-body anatomy reference, no head and no face, never a collage or character sheet.",
    `Character body: ${characterBrief.age_group} ${characterBrief.gender_identity}.`,
    `BODY PROPORTIONS: ${characterBrief.body}.`,
    "Frame from the base of the neck through both feet. Entire shoulders, torso, arms, hands, hips, legs, and feet visible; head completely outside the top of the frame.",
    "Neutral standing body-reference posture, shoulders level, arms relaxed and separated from torso, legs and proportions clearly visible.",
    "Simple close-fitting neutral bodysuit, no loose layers, clean studio background, even lighting, realistic anatomy.",
    `Visual style: ${characterBrief.visual_style}.`,
  ].filter(Boolean).join("\n");
}

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

const FACE_FEATURE_PROMPT_DESCRIPTIONS = {
  "apparent age": {
    teen: "teenage facial appearance with youthful proportions, smooth skin, and minimal age lines",
    "young adult": "young-adult facial appearance with mature proportions, smooth skin, and subtle natural definition",
    adult: "adult facial appearance with fully mature proportions and natural facial definition",
    mature: "mature facial appearance with subtle expression lines, defined contours, and natural age texture",
    elderly: "elderly facial appearance with visible age lines, softened contours, and realistic mature skin texture",
  },
  "face shape": {
    oval: "oval face, gently rounded forehead and jaw, balanced length, cheekbones slightly wider than the jaw",
    round: "round face, similar width and length, full cheeks, softly curved jawline, rounded chin",
    square: "square face, broad forehead, strong straight jawline, similar forehead and jaw width",
    "heart-shaped": "heart-shaped face, broad forehead and cheekbones tapering toward a narrow pointed chin",
    diamond: "diamond-shaped face, prominent wide cheekbones, narrower forehead and jaw, tapered chin",
    oblong: "oblong face, noticeably longer than wide, straight cheek lines, softly rounded forehead and jaw",
    triangular: "triangular face, narrower forehead widening toward a broad strong jawline",
    "soft angular": "softly angular face, defined cheekbones and jaw transitions with gently rounded edges",
  },
  "skin tone": Object.fromEntries([
    "porcelain", "fair", "light", "light-medium", "medium", "olive", "tan", "brown", "deep brown", "ebony",
  ].map((value) => [value, `${value} natural skin tone with realistic tonal variation`])),
  complexion: {
    clear: "clear even complexion with minimal visible blemishes",
    dewy: "dewy complexion with soft hydrated skin and a subtle natural sheen",
    matte: "matte complexion with soft diffused skin texture and minimal shine",
    "sun-kissed": "sun-kissed complexion with warm natural color across cheeks and nose",
    freckled: "naturally freckled complexion with fine irregular freckles across cheeks and nose",
    "rosy cheeks": "natural rosy color concentrated softly across the cheeks",
    weathered: "weathered complexion with realistic texture, fine lines, and subtle sun exposure",
    vitiligo: "visible vitiligo with natural irregular areas of depigmentation across the face",
  },
  "eye shape": {
    almond: "almond-shaped eyes, gently tapered inner and outer corners, softly curved eyelids, balanced proportions, iris partially covered by the upper and lower lids",
    round: "round eyes, visibly curved upper and lower lids, open circular appearance, more sclera visible above and below the iris",
    hooded: "hooded eyes, upper eyelid fold descending over and partially concealing the natural crease, softly shaded lid space",
    monolid: "monolid eyes, smooth upper eyelids without a prominent visible crease, clean uninterrupted lid contour",
    upturned: "upturned eyes, outer corners sitting slightly higher than the inner corners, gently rising lower lash line",
    downturned: "downturned eyes, outer corners sitting slightly lower than the inner corners, softly descending outer lash line",
    "deep-set": "deep-set eyes positioned beneath a prominent brow ridge, recessed eyelids with natural shadow around the eye socket",
    "wide-set": "wide-set eyes with greater than one eye-width of space between the inner corners, balanced symmetrical placement",
    "close-set": "close-set eyes with less than one eye-width of space between the inner corners, balanced symmetrical placement",
  },
  "eye color": {
    "dark brown": "dark-brown irises with rich near-black depth",
    brown: "warm brown irises with natural tonal variation",
    hazel: "hazel irises blending green, brown, and golden tones",
    amber: "amber irises with clear golden copper coloration",
    green: "green irises with natural radial detail and tonal variation",
    blue: "blue irises with natural radial detail and darker limbal rings",
    gray: "gray irises with cool silver tonal variation",
    violet: "violet irises with believable purple-blue tonal variation",
    heterochromia: "complete heterochromia, each iris a distinctly different natural color",
    "unnatural glowing": "unnaturally luminous irises emitting a subtle colored glow",
  },
  eyebrows: {
    straight: "straight eyebrows with minimal arch and an even horizontal line",
    "softly arched": "softly arched eyebrows with a gentle gradual curve",
    "high arched": "high-arched eyebrows with a pronounced elevated peak",
    thick: "thick full eyebrows with dense natural hair coverage",
    thin: "thin refined eyebrows with sparse narrow hair coverage",
    bushy: "bushy textured eyebrows with dense individually visible hairs",
    defined: "cleanly defined eyebrows with precise edges and balanced shape",
    "scar through brow": "natural eyebrow interrupted by a visible narrow scar through the hair",
  },
  nose: {
    small: "small proportionate nose with a short bridge and compact nostrils",
    straight: "straight nose with an even bridge and balanced tip projection",
    button: "button nose with a short bridge, small rounded tip, and compact nostrils",
    upturned: "upturned nose with a gently raised tip and subtly visible nostrils",
    broad: "broad nose with a wide bridge, rounded tip, and wider nostril base",
    aquiline: "aquiline nose with a prominent gently curved bridge and downward-defined tip",
    Roman: "Roman nose with a strong high bridge and slightly convex profile",
    "flat bridge": "nose with a low flat bridge and softly widened nasal base",
    prominent: "prominent nose with a strong projected bridge and clearly defined tip",
  },
  lips: {
    thin: "thin lips with low vertical volume and a restrained natural contour",
    medium: "medium-full lips with balanced upper and lower volume",
    full: "full lips with generous natural volume and softly rounded contours",
    wide: "wide mouth with horizontally extended lip corners and balanced volume",
    small: "small compact mouth with short width and delicate lip contours",
    "defined Cupid's bow": "lips with a sharply defined Cupid's bow and clear central upper-lip peaks",
    "soft Cupid's bow": "lips with a softly rounded Cupid's bow and gentle upper-lip peaks",
    asymmetrical: "naturally asymmetrical lips with subtle believable variation between the two sides",
  },
  "hair texture": {
    straight: "naturally straight hair with smooth strands and minimal wave",
    wavy: "wavy hair with loose flowing S-shaped bends",
    curly: "curly hair with defined springing ringlets",
    coily: "coily hair with dense small spiral curls and natural volume",
    kinky: "tightly kinked hair with compact angular curls and dense texture",
    silky: "silky smooth hair with fine reflective strands and soft movement",
    coarse: "coarse hair with thick visible strands and substantial texture",
    shaved: "closely shaved hair with short even stubble following the scalp",
  },
  "hair length": {
    bald: "fully bald scalp with no visible head hair",
    "buzz cut": "very short uniform buzz cut close to the scalp",
    short: "short hair ending above the ears or near the nape",
    "chin-length": "chin-length hair ending around the jawline",
    "shoulder-length": "shoulder-length hair ending at the shoulders",
    long: "long hair extending below the shoulders",
    "waist-length": "very long hair extending to the waist",
  },
  "hair color": Object.fromEntries([
    "black", "dark brown", "brown", "auburn", "copper", "red", "strawberry blonde", "blonde", "platinum", "gray", "white", "blue", "pink", "multicolored",
  ].map((value) => [value, `${value} hair with natural strand-level tonal variation`])),
  hairstyle: {
    loose: "hair worn loose and naturally falling around the head and shoulders",
    layered: "layered haircut with visibly graduated lengths and natural movement",
    bob: "clean bob haircut ending between the jaw and shoulders",
    "pixie cut": "short pixie cut with closely tapered sides and textured top",
    pompadour: "pompadour hairstyle swept upward and back with volume above the forehead",
    undercut: "undercut hairstyle with closely clipped sides and longer hair on top",
    braids: "neatly defined braids with visible woven strand structure",
    cornrows: "close-to-scalp cornrows arranged in clean defined rows",
    locs: "well-defined natural locs with individual cylindrical sections",
    afro: "rounded natural afro with dense coiled volume",
    ponytail: "hair gathered and secured into a ponytail behind the head",
    bun: "hair gathered into a tidy bun at the back of the head",
    bangs: "visible bangs framing or crossing the forehead",
    "side part": "clear side part with hair directed to opposite sides",
  },
  "distinctive features": {
    dimples: "visible natural cheek dimples",
    "beauty mark": "single small natural beauty mark on the face",
    "facial freckles": "scattered natural facial freckles across cheeks and nose",
    birthmark: "distinct natural facial birthmark",
    "facial scar": "visible healed facial scar with realistic skin texture",
    tattoo: "clearly visible facial tattoo integrated with the skin",
    "ear piercings": "visible ear piercings with small jewelry",
    "nose piercing": "visible nose piercing with subtle jewelry",
    "lip piercing": "visible lip piercing with subtle jewelry",
    "pointed ears": "distinctly pointed ear tips with natural anatomy",
    "gap tooth": "visible natural gap between the front teeth",
    "prosthetic eye": "clearly artificial prosthetic eye with realistic surrounding anatomy",
    "facial cybernetics": "integrated facial cybernetic components following natural facial anatomy",
  },
  "facial hair": {
    "clean-shaven": "clean-shaven face with no visible facial hair",
    stubble: "short even facial stubble across the jaw, chin, and upper lip",
    mustache: "defined mustache following the upper-lip contour",
    goatee: "trimmed goatee centered around the mouth and chin",
    "short beard": "short neatly trimmed beard following the jaw and chin",
    "full beard": "full dense beard covering the jaw, chin, and lower cheeks",
    sideburns: "defined sideburns extending down in front of the ears",
    "shaped beard": "carefully shaped beard with clean intentional edges",
  },
};

function faceFeaturePromptDescription(groupId, value) {
  return FACE_FEATURE_PROMPT_DESCRIPTIONS[groupId]?.[value] || value;
}

function faceFeatureGroupsFromCatalog(catalog) {
  if (!Array.isArray(catalog?.groups)) return FACE_FEATURE_OPTION_GROUPS;
  return catalog.groups.map((group) => ({
    id: String(group?.id || ""),
    label: String(group?.label || group?.id || ""),
    multiple: Boolean(group?.multiple),
    options: Object.keys(group?.options && typeof group.options === "object" ? group.options : {}),
    optionDefinitions: group?.options && typeof group.options === "object" ? group.options : {},
  })).filter((group) => group.id && group.options.length);
}

function catalogFeaturePromptDescription(catalog, groupId, value) {
  const group = Array.isArray(catalog?.groups) ? catalog.groups.find((item) => item?.id === groupId) : null;
  return String(group?.options?.[value]?.description || faceFeaturePromptDescription(groupId, value));
}

function inferFaceFeatureSelections(appearance, catalog = null) {
  const text = String(appearance || "").toLowerCase();
  const groups = faceFeatureGroupsFromCatalog(catalog);
  return groups.reduce((selections, group) => {
    const matches = group.options.filter((value) => {
      const description = catalogFeaturePromptDescription(catalog, group.id, value).toLowerCase();
      return text.includes(description) || text.includes(`${group.id}: ${value}`);
    });
    return matches.length ? { ...selections, [group.id]: group.multiple ? matches : matches.slice(0, 1) } : selections;
  }, {});
}

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

function composeFaceDescription(selections, customDetails, catalog = null) {
  const selectedDetails = faceFeatureGroupsFromCatalog(catalog).flatMap((group) => {
    const values = selections[group.id] || [];
    const descriptions = values.map((value) => catalogFeaturePromptDescription(catalog, group.id, value));
    return descriptions.length ? [`${group.id}: ${descriptions.join(", ")}`] : [];
  });
  const custom = String(customDetails || "").trim();
  return [...selectedDetails, ...(custom ? [custom] : [])].join("; ");
}

const FACE_PREVIEW_NEGATIVE_PROMPT = [
  "multiple people", "more than one person", "two people", "multiple faces", "more than one face",
  "two faces", "duplicate face", "extra face", "face collage", "portrait collage", "diptych", "triptych",
  "contact sheet", "character sheet", "split screen", "side-by-side portraits", "mirrored face", "reflection",
  "profile view", "three-quarter view", "tilted head", "cropped forehead", "cropped chin",
  "closed eyes", "asymmetrical eyes", "distorted face", "duplicate features", "exaggerated expression",
  "heavy makeup", "dramatic lighting", "harsh shadows", "accessories covering the face",
  "text", "watermark", "blurry", "low detail", "child", "teen", "underage",
].join(", ");

function buildFacePreviewPrompt(brief, selections = {}, refinement = "") {
  const identity = [brief?.age_group, brief?.gender_identity].filter(Boolean).join(" ");
  const faceShape = selections["face shape"]?.[0];
  const faceShapeDescription = faceShape ? faceFeaturePromptDescription("face shape", faceShape) : "";
  const hairColor = selections["hair color"]?.[0];
  const hairColorDescription = hairColor ? faceFeaturePromptDescription("hair color", hairColor) : "";
  const hairLength = selections["hair length"]?.[0];
  const hairLengthDescription = hairLength ? faceFeaturePromptDescription("hair length", hairLength) : "";
  let safeRefinement = String(refinement || "").trim();
  if (safeRefinement.startsWith("{")) {
    try {
      const parsed = JSON.parse(safeRefinement);
      safeRefinement = typeof parsed?.prompt === "string" ? parsed.prompt.trim() : "";
    } catch {
      safeRefinement = "";
    }
  }
  return [
    "EXACTLY ONE PERSON. EXACTLY ONE FACE. Single centered identity portrait; never a collage, grid, comparison, or character sheet.",
    `Character identity reference portrait of ${brief?.name || "an unnamed character"}${identity ? `, ${identity}` : ""}.`,
    brief?.concept ? `Character concept: ${brief.concept}.` : "",
    faceShapeDescription ? `PRIMARY FACE SHAPE REQUIREMENT: (${faceShapeDescription}:1.35). The facial silhouette must be unmistakably ${faceShape}.` : "",
    hairColorDescription ? `PRIMARY HAIR COLOR REQUIREMENT: (${hairColorDescription}:1.45). The hair must read clearly and unmistakably as ${hairColor}, including at the roots and in shadow.` : "",
    hairLengthDescription ? `PRIMARY HAIR LENGTH REQUIREMENT: (${hairLengthDescription}:1.40). The visible hair ends must unmistakably match ${hairLength}; keep the full hair silhouette and its endpoints visible in frame.` : "",
    brief?.appearance ? `Face and hair: ${brief.appearance}.` : "",
    brief?.expression ? `Expression: ${brief.expression}.` : "Expression: neutral and relaxed.",
    "Front-facing head-and-shoulders composition, eyes looking directly at camera, symmetrical neutral pose, centered face, entire head visible.",
    "Realistic facial proportions, detailed natural skin texture, soft even studio lighting, plain neutral-gray background, identity reference sheet, sharp focus.",
    brief?.visual_style ? `Visual style: ${brief.visual_style}.` : "",
    safeRefinement ? `LLM REFINEMENT LAYER: ${safeRefinement}` : "",
  ].filter(Boolean).join("\n");
}

function buildFacePreviewNegativePrompt(selections = {}) {
  const faceShape = selections["face shape"]?.[0];
  const hairColor = selections["hair color"]?.[0];
  const hairLength = selections["hair length"]?.[0];
  const conflictingShapes = {
    round: ["square face", "long face", "oblong face", "angular jaw", "narrow face", "pointed chin"],
    oval: ["square face", "extremely round face", "very long face", "angular jaw"],
    square: ["round jaw", "pointed chin", "narrow jaw", "heart-shaped face"],
    "heart-shaped": ["broad square jaw", "round face", "wide chin"],
    diamond: ["round face", "broad forehead", "broad jaw"],
    oblong: ["round face", "short face", "wide square face"],
    triangular: ["broad forehead", "narrow jaw", "heart-shaped face"],
    "soft angular": ["extremely round face", "harsh square jaw", "pointed chin"],
  };
  const conflictingHairColors = {
    black: ["blonde hair", "platinum hair", "white hair", "red hair", "light hair"],
    "dark brown": ["blonde hair", "platinum hair", "white hair", "red hair", "black hair"],
    brown: ["blonde hair", "platinum hair", "white hair", "red hair", "black hair"],
    auburn: ["blonde hair", "platinum hair", "white hair", "black hair", "plain brown hair"],
    copper: ["blonde hair", "platinum hair", "white hair", "black hair", "brown hair"],
    red: ["blonde hair", "platinum hair", "white hair", "black hair", "brown hair"],
    "strawberry blonde": ["brunette", "dark brown hair", "black hair", "platinum hair", "deep red hair"],
    blonde: ["brunette", "brown hair", "dark brown hair", "black hair", "auburn hair", "red hair"],
    platinum: ["brunette", "brown hair", "dark brown hair", "black hair", "golden blonde hair", "red hair"],
    gray: ["blonde hair", "brown hair", "black hair", "red hair", "saturated hair color"],
    white: ["blonde hair", "brown hair", "black hair", "red hair", "gray hair"],
    blue: ["blonde hair", "brown hair", "black hair", "red hair", "natural hair color"],
    pink: ["blonde hair", "brown hair", "black hair", "red hair", "natural hair color"],
    multicolored: ["single-color hair", "uniform hair color", "monochrome hair"],
  };
  const conflictingHairLengths = {
    bald: ["visible head hair", "long hair", "short hair", "hair strands"],
    "buzz cut": ["bald head", "long hair", "chin-length hair", "shoulder-length hair", "hair covering ears"],
    short: ["bald head", "buzz cut", "chin-length hair", "shoulder-length hair", "long hair", "waist-length hair"],
    "chin-length": ["bald head", "buzz cut", "pixie cut", "cropped short hair", "shoulder-length hair", "long hair", "waist-length hair"],
    "shoulder-length": ["bald head", "buzz cut", "pixie cut", "cropped hair", "short hair", "chin-length hair", "long hair", "waist-length hair", "hair ending above the jaw", "hair extending below the shoulders"],
    long: ["bald head", "buzz cut", "pixie cut", "cropped hair", "short hair", "chin-length hair", "shoulder-length hair", "waist-length hair"],
    "waist-length": ["bald head", "buzz cut", "pixie cut", "cropped hair", "short hair", "chin-length hair", "shoulder-length hair", "mid-back hair"],
  };
  return [
    ...FACE_PREVIEW_NEGATIVE_PROMPT.split(", "),
    ...(conflictingShapes[faceShape] || []),
    ...(conflictingHairColors[hairColor] || []),
    ...(conflictingHairLengths[hairLength] || []),
  ].join(", ");
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

function characterDraftFeatureCatalog(profile) {
  try {
    const initialData = JSON.parse(String(profile?.initial_data || ""));
    const catalog = initialData?.face_feature_catalog;
    return catalog && typeof catalog === "object" ? catalog : null;
  } catch {
    return null;
  }
}

function characterDraftBodyFeatureCatalog(profile) {
  try {
    const initialData = JSON.parse(String(profile?.initial_data || ""));
    const catalog = initialData?.body_feature_catalog;
    return catalog && typeof catalog === "object" ? catalog : null;
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

export function latestSavedFacePreview(characterProfiles = [], profileId = "") {
  const matchingProfiles = profileId
    ? characterProfiles.filter((profile) => String(profile?.profile_id || "") === String(profileId))
    : characterProfiles;
  return matchingProfiles
    .flatMap((profile) => profile?.prompt_workspaces?.head_face?.preview_history || [])
    .filter((preview) => (
      preview
      && preview.url
      && !preview.placeholder
      && ["completed", "completed_with_fallback"].includes(String(preview.status || "").toLowerCase())
    ))
    .sort((left, right) => String(
      right.imported_at || right.completed_at || right.created_at || ""
    ).localeCompare(String(
      left.imported_at || left.completed_at || left.created_at || ""
    )))[0] || null;
}

export function ImageStudio({
  templates = [],
  faceFeatureCatalog = null,
  initialCreationType = "",
  initialCharacterPath = "",
  initialSelectedTemplateId = "",
  initialCreativeSetupOpen = false,
  initialInterviewOpen = false,
  initialInterviewStep = 0,
  initialFaceSeedReviewOpen = false,
  runtimeStatus = null,
  generationActivity = null,
  facePreviewResult = null,
  facePreviewTracking = false,
  bodyPreviewResult = null,
  bodyPreviewTracking = false,
  faceSeedBatchResult = null,
  faceSeedBatchTracking = false,
  apiBase = "",
  dataLoading = false,
  dataError = "",
  promptHelperBusy = false,
  interviewBusy = false,
  characterProfiles = [],
  characterSaveBusy = false,
  onImprovePrompt,
  onInterviewQuestion,
  onSaveCharacterDraft,
  onGenerateFacePreview,
  onGenerateBodyPreview,
  onCreateFaceSeedBatch,
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
  const [characterProfileId, setCharacterProfileId] = useState("");
  const [facePromptDraft, setFacePromptDraft] = useState("");
  const [faceTweakInstruction, setFaceTweakInstruction] = useState("");
  const [faceSeedLocked, setFaceSeedLocked] = useState(false);
  const [faceRefinementStatus, setFaceRefinementStatus] = useState("");
  const [faceRefinementError, setFaceRefinementError] = useState("");
  const [bodyFeatureSelections, setBodyFeatureSelections] = useState({});
  const [bodyCustomDetails, setBodyCustomDetails] = useState("");
  const [faceSeedReviewOpen, setFaceSeedReviewOpen] = useState(initialFaceSeedReviewOpen);
  const [faceSeedReviewSelections, setFaceSeedReviewSelections] = useState([]);
  const [faceSeedReviewBatchId, setFaceSeedReviewBatchId] = useState("");
  const matchingTemplates = useMemo(
    () => templates.filter((template) => {
      if (templateCreationType(template) !== creationType) {
        return false;
      }
      return creationType !== "character" || (characterPath && templateCharacterPath(template) === characterPath);
    }),
    [characterPath, creationType, templates]
  );
  const faceFeatureGroups = useMemo(() => faceFeatureGroupsFromCatalog(faceFeatureCatalog), [faceFeatureCatalog]);
  const facePreviewTemplate = useMemo(
    () => templates.find((template) => template?.template_id === "template.avatar_head_face_preview.realvisxl.v1") || null,
    [templates]
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
  const savedFacePreview = useMemo(
    () => latestSavedFacePreview(characterProfiles, characterProfileId),
    [characterProfiles, characterProfileId]
  );
  const facePreview = facePreviewResult?.preview || savedFacePreview;
  const displayedFacePreview = facePreview?.url ? facePreview : savedFacePreview;
  const activeCharacterProfile = characterProfiles.find(
    (profile) => String(profile?.profile_id || "") === String(characterProfileId || "")
  );
  const faceSeedBatch = faceSeedBatchResult?.batch || activeCharacterProfile?.prompt_workspaces?.head_face?.seed_batch || null;
  const faceSeedBatchPreviews = Array.isArray(faceSeedBatch?.previews) ? faceSeedBatch.previews : [];
  const faceSeedBatchReadyCount = faceSeedBatchPreviews.filter(
    (preview) => ["completed", "completed_with_fallback"].includes(String(preview?.status || "").toLowerCase()) && preview?.url
  ).length;
  const faceSeedBatchComplete = faceSeedBatchPreviews.length === 15 && Number(faceSeedBatch?.remaining_count || 0) === 0;
  const savedBodyPreview = activeCharacterProfile?.prompt_workspaces?.upper_torso?.preview_history?.slice(-1)[0] || null;
  const bodyPreview = bodyPreviewResult?.preview || savedBodyPreview;
  const bodyPreviewSeed = bodyPreview?.seed_text || bodyPreview?.seed;
  const bodyPreviewStatus = String(bodyPreview?.status || (bodyPreviewTracking ? "preparing" : "not started"));
  const bodyPreviewCompleted = ["completed", "completed_with_fallback"].includes(bodyPreviewStatus.toLowerCase());
  const bodyPreviewImageUrl = bodyPreview?.url ? `${apiBase}${bodyPreview.url}` : "";
  const facePreviewSeed = facePreview?.seed_text || facePreview?.seed;
  const generationProgress = generationActivity?.generation_status?.progress || {};
  const generationSession = generationActivity?.generation_status?.session || generationActivity?.service?.session || {};
  const generationJob = generationActivity?.latest_job || {};
  const previewPromptId = String(facePreview?.prompt_id || "").trim();
  const jobPromptIds = [generationJob?.prompt_id, ...(generationJob?.prompt_ids || [])].map((value) => String(value || "").trim()).filter(Boolean);
  const activityMatchesPreview = Boolean(previewPromptId && jobPromptIds.includes(previewPromptId));
  const progressDetail = activityMatchesPreview ? (generationJob?.progress_detail || {}) : {};
  const comfyService = runtimeStatus?.services?.comfyui_gpu || {};
  const comfyResidency = comfyService?.model_residency_status || comfyService?.model_residency || {};
  const previewStatus = String(
    progressDetail?.status
      || (activityMatchesPreview ? generationJob?.status : "")
      || facePreview?.status
      || (facePreviewTracking ? "preparing" : "not started")
  );
  const previewPercent = Number(progressDetail?.percent ?? (activityMatchesPreview ? generationProgress?.percent : undefined));
  const progressValue = Number(progressDetail?.value ?? (activityMatchesPreview ? generationProgress?.value : undefined));
  const progressMax = Number(progressDetail?.max ?? (activityMatchesPreview ? generationProgress?.max : undefined));
  const queueRunning = Number(generationSession?.running_count || generationJob?.running_count || 0);
  const queuePending = Number(generationSession?.pending_count || generationJob?.pending_count || 0);
  const modelName = facePreviewTemplate?.model_requirements?.checkpoint || comfyResidency.loaded_model || "Image model";
  const modelState = String(comfyResidency.model_state || "unloaded");
  const previewFailed = ["failed", "error", "cancelled"].includes(previewStatus.toLowerCase());
  const previewCompleted = ["completed", "completed_with_fallback"].includes(previewStatus.toLowerCase());
  let currentGenerationOperation = "Ready to generate";
  if (previewFailed) {
    currentGenerationOperation = "Generation failed";
  } else if (previewCompleted) {
    currentGenerationOperation = "Preview completed and imported";
  } else if (facePreviewTracking) {
    if (String(comfyService.state || "").toLowerCase() !== "running") {
      currentGenerationOperation = "Starting the ComfyUI runtime";
    } else if (modelState !== "loaded") {
      currentGenerationOperation = `Loading ${modelName} into VRAM`;
    } else if (queuePending > 0 && queueRunning === 0) {
      currentGenerationOperation = `Waiting in the ComfyUI queue (${queuePending} pending)`;
    } else if (Number.isFinite(progressValue) && Number.isFinite(progressMax) && progressMax > 0 && progressValue < progressMax) {
      currentGenerationOperation = `Rendering image — step ${progressValue} of ${progressMax}`;
    } else if (Number.isFinite(previewPercent) && previewPercent >= 100) {
      currentGenerationOperation = "Saving and importing the completed preview";
    } else if (queueRunning > 0) {
      currentGenerationOperation = "ComfyUI is processing the workflow";
    } else {
      currentGenerationOperation = "Preparing the workflow and image model";
    }
  }
  const generationMessage = String(
    progressDetail?.message
      || progressDetail?.failure_detail
      || progressDetail?.failure_reason
      || (facePreviewTracking ? "Live status refreshes automatically." : "Generate a preview to see live model and rendering details.")
  );
  const previewImageUrl = displayedFacePreview?.url ? `${apiBase}${displayedFacePreview.url}` : "";

  useEffect(() => {
    const batchId = String(faceSeedBatch?.batch_id || "");
    if (!batchId || batchId === faceSeedReviewBatchId) return;
    setFaceSeedReviewBatchId(batchId);
    setFaceSeedReviewSelections(faceSeedBatchPreviews
      .filter((preview, index) => index === 0 || preview?.identity_anchor || preview?.kept)
      .map((preview) => String(preview?.preview_id || ""))
      .filter(Boolean));
  }, [faceSeedBatch?.batch_id, faceSeedBatchPreviews, faceSeedReviewBatchId]);

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
    updateCharacterBrief("appearance", composeFaceDescription(next, faceCustomDetails, faceFeatureCatalog));
  }

  function selectBodyFeature(group, option) {
    const next = { ...bodyFeatureSelections, [group.id]: [option] };
    setBodyFeatureSelections(next);
    updateCharacterBrief("body", composeBodyDescription(next, bodyCustomDetails));
  }

  function updateBodyCustomDetails(value) {
    setBodyCustomDetails(value);
    updateCharacterBrief("body", composeBodyDescription(bodyFeatureSelections, value));
  }

  function updateFaceCustomDetails(value) {
    setFaceCustomDetails(value);
    updateCharacterBrief("appearance", composeFaceDescription(faceFeatureSelections, value, faceFeatureCatalog));
  }

  async function saveCharacterProgress({ closeAfter = false } = {}) {
    if (!nameConceptComplete || characterSaveBusy || !onSaveCharacterDraft) {
      return null;
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
        face_feature_catalog: {
          schema_version: "1.0",
          selections: faceFeatureSelections,
          custom_details: faceCustomDetails,
          expanded_description: characterBrief.appearance,
          llm_refinement: facePromptDraft,
        },
        body_feature_catalog: {
          schema_version: "1.0",
          selections: bodyFeatureSelections,
          custom_details: bodyCustomDetails,
          expanded_description: characterBrief.body,
        },
        identity_seeds: {
          face: facePreviewSeed ?? null,
          body: bodyPreviewSeed ?? null,
        },
      }),
    });
    if (!result?.profile) {
      return null;
    }
    setCharacterProfileId(result.profile.profile_id || characterProfileId);
    setDraftSaveMessage("Saved as an incomplete character.");
    if (closeAfter) {
      setInterviewOpen(false);
      setCreativeSetupOpen(false);
    }
    return result.profile;
  }

  function continueIncompleteCharacter(profile) {
    const savedBrief = characterDraftBrief(profile);
    const savedFeatures = characterDraftFeatureCatalog(profile);
    const savedBodyFeatures = characterDraftBodyFeatureCatalog(profile);
    if (!savedBrief) {
      return;
    }
    const candidateTemplate = selectedTemplate || matchingTemplates[0];
    if (candidateTemplate) {
      setSelectedTemplateId(candidateTemplate.template_id);
    }
    setCharacterBrief((current) => ({ ...current, ...savedBrief }));
    setFaceFeatureSelections(savedFeatures?.selections || inferFaceFeatureSelections(savedBrief.appearance, faceFeatureCatalog));
    setFaceCustomDetails(savedFeatures?.custom_details || "");
    setFacePromptDraft(savedFeatures?.llm_refinement || "");
    setBodyFeatureSelections(savedBodyFeatures?.selections || {});
    setBodyCustomDetails(savedBodyFeatures?.custom_details || "");
    setCharacterProfileId(profile.profile_id || "");
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

  async function openFaceSeedReview(savedProfile) {
    const profileId = savedProfile?.profile_id || characterProfileId;
    if (!profileId || facePreviewSeed === undefined || facePreviewSeed === null || !previewCompleted) {
      setDraftSaveMessage("Generate and finish a face preview before continuing to identity review.");
      return false;
    }
    setInterviewOpen(false);
    setFaceSeedReviewOpen(true);
    const sourcePreviewId = String(facePreview?.preview_id || "");
    const batchMatchesSavedPreview = sourcePreviewId
      && String(faceSeedBatch?.anchor_source_preview_id || "") === sourcePreviewId;
    if (!faceSeedBatch || faceSeedBatchPreviews.length !== 15 || !batchMatchesSavedPreview) {
      setDraftSaveMessage("Starting 15 identity seeds. The saved face seed is slot 1.");
      const result = await onCreateFaceSeedBatch?.(profileId, {
        anchor_preview_id: sourcePreviewId,
        anchor_seed: facePreviewSeed,
        batch_size: 15,
        preserve_existing: false,
      });
      if (!result) {
        setFaceSeedReviewOpen(false);
        setInterviewOpen(true);
        return false;
      }
    }
    return true;
  }

  function toggleFaceSeedReview(preview, index) {
    const previewId = String(preview?.preview_id || "");
    if (!previewId || index === 0 || preview?.identity_anchor || !preview?.url) return;
    setFaceSeedReviewSelections((current) => current.includes(previewId)
      ? current.filter((item) => item !== previewId)
      : [...current, previewId]);
  }

  async function confirmFaceSeedReview() {
    if (!faceSeedBatchComplete || characterSaveBusy) return;
    const anchor = faceSeedBatchPreviews[0];
    const anchorId = String(anchor?.preview_id || "");
    const keepIds = Array.from(new Set([anchorId, ...faceSeedReviewSelections].filter(Boolean)));
    const result = await onCreateFaceSeedBatch?.(characterProfileId, {
      batch_size: 15,
      preserve_existing: true,
      keep_preview_ids: keepIds,
      selected_preview_id: anchorId,
    });
    if (!result) return;
    setCompletedInterviewSteps((current) => ({ ...current, face_features: true }));
    setFaceSeedReviewOpen(false);
    setInterviewOpen(true);
    moveCharacterInterview(1);
    setDraftSaveMessage(`${keepIds.length} visually consistent face seeds saved.`);
  }

  async function completeCurrentInterviewStep() {
    const savedProfile = await saveCharacterProgress();
    if (!savedProfile) return;
    if (activeInterviewStep.id === "body_proportions" && !bodyPreviewCompleted) {
      setDraftSaveMessage("Generate and finish a body reference preview before continuing.");
      return;
    }
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
    const savedProfile = await saveCharacterProgress();
    if (!savedProfile) return;
    if (!interviewLlmEnabled || !textModelLoaded || !onInterviewQuestion) {
      await completeCurrentInterviewStep();
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

  async function generateFacePreview({ promptOverride = "", forceLockedSeed = false } = {}) {
    if (!characterBrief.appearance.trim() || characterSaveBusy || facePreviewTracking || !onGenerateFacePreview) return null;
    const savedProfile = await saveCharacterProgress();
    const profileId = savedProfile?.profile_id || characterProfileId;
    if (!profileId) return null;
    setDraftSaveMessage("Character saved. Submitting face preview…");
    const locked = forceLockedSeed || faceSeedLocked;
    const seed = facePreview?.seed_text || facePreview?.seed;
    const refinement = promptOverride || facePromptDraft;
    const result = await onGenerateFacePreview(profileId, {
      refinement,
      seed: locked && seed !== undefined && seed !== null ? seed : null,
      lock_seed: locked && seed !== undefined && seed !== null,
    });
    if (result) setDraftSaveMessage("Face preview submitted.");
    return result;
  }

  async function generateBodyPreview() {
    if (!characterBrief.body.trim() || characterSaveBusy || bodyPreviewTracking || !onGenerateBodyPreview) return null;
    const savedProfile = await saveCharacterProgress();
    const profileId = savedProfile?.profile_id || characterProfileId;
    if (!profileId) return null;
    setDraftSaveMessage("Character saved. Submitting body reference preview…");
    const result = await onGenerateBodyPreview(profileId, {
      prompt: buildBodyPreviewPrompt(characterBrief),
      negative_prompt: "head, face, eyes, mouth, facial features, portrait, visible head, partial head, multiple people, duplicate body, extra limbs, missing limbs, malformed anatomy, cropped shoulders, cropped waist, cropped legs, cropped feet, loose clothing, bulky clothing, dramatic pose, text, watermark, child, teen, underage",
      seed: bodyPreviewSeed ?? null,
      lock_seed: bodyPreviewSeed !== undefined && bodyPreviewSeed !== null,
      width: 768,
      height: 1152,
    });
    if (result) setDraftSaveMessage("Body preview submitted. Its seed will be saved with the character.");
    return result;
  }

  async function refineAndRegenerateFacePreview() {
    if (!faceTweakInstruction.trim() || facePreviewSeed === undefined || facePreviewSeed === null || promptHelperBusy || facePreviewTracking) return;
    setFaceRefinementError("");
    setFaceRefinementStatus("Asking the local text LLM to refine the prompt…");
    const currentPrompt = String(facePreview?.prompt || characterBrief.appearance || "").trim();
    const refined = await onImprovePrompt?.({
      template_id: "template.avatar_head_face_preview.realvisxl.v1",
      mode: "txt2img",
      prompt: currentPrompt,
      negative_prompt: String(facePreview?.negative_prompt || ""),
      width: 512,
      height: 512,
      reference_image_provided: false,
      instruction: faceTweakInstruction.trim(),
    });
    if (!refined?.prompt) {
      setFaceRefinementStatus("");
      setFaceRefinementError(
        refined?._error
          ? `Refinement failed: ${refined._error}`
          : "Refinement failed: the local text LLM did not return an updated prompt. No image was submitted."
      );
      return;
    }
    setFacePromptDraft(String(refined.prompt));
    setFaceSeedLocked(true);
    setFaceTweakInstruction("");
    setFaceRefinementStatus("Prompt refined. Saving the character and submitting the same seed to ComfyUI…");
    const generated = await generateFacePreview({ promptOverride: String(refined.prompt), forceLockedSeed: true });
    if (!generated) {
      setFaceRefinementStatus("");
      setFaceRefinementError("The prompt was refined, but the preview could not be submitted to ComfyUI. Your refined prompt was preserved.");
      return;
    }
    setFaceRefinementStatus("Refined preview submitted. Generation progress appears above.");
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
              </div>
            ) : activeInterviewStep.id === "face_features" ? (
              <div className="image-studio-face-workspace">
                <div className="image-studio-face-builder">
                  <p>Select the traits that should stay consistent. Choose one per group unless the group allows multiple.</p>
                  <div className="image-studio-face-options">
                    {faceFeatureGroups.map((group) => (
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
                                title={catalogFeaturePromptDescription(faceFeatureCatalog, group.id, option)}
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
                    {previewImageUrl ? (
                      <img src={previewImageUrl} alt={`Generated face preview for ${characterBrief.name || "character"}`} />
                    ) : (
                      <><span>Portrait preview</span><p>Your selected face traits will be rendered here.</p></>
                    )}
                  </div>
                  <button className="btn btn-primary" type="button" onClick={generateFacePreview} disabled={!nameConceptComplete || !characterBrief.appearance.trim() || characterSaveBusy || facePreviewTracking}>
                    {facePreviewTracking ? "Generating preview…" : previewImageUrl ? "Generate another preview" : "Generate face preview"}
                  </button>
                  <div className="image-studio-face-preview-status" aria-live="polite">
                    <div className={`image-studio-generation-summary ${previewFailed ? "is-error" : previewCompleted ? "is-complete" : ""}`}>
                      <span>Current operation</span>
                      <strong>{currentGenerationOperation}</strong>
                      <small>{generationMessage}</small>
                    </div>
                    <div className="image-studio-generation-progress" aria-label={`Generation progress ${Number.isFinite(previewPercent) ? previewPercent : 0}%`}>
                      <i style={{ width: `${Math.max(0, Math.min(100, Number.isFinite(previewPercent) ? previewPercent : 0))}%` }} />
                    </div>
                    <div><span>Status</span><strong>{previewStatus.replaceAll("_", " ")}</strong></div>
                    <div><span>Progress</span><strong>{Number.isFinite(previewPercent) ? `${previewPercent.toFixed(1)}%${Number.isFinite(progressValue) && Number.isFinite(progressMax) ? ` (${progressValue}/${progressMax})` : ""}` : facePreviewTracking ? "Preparing…" : "—"}</strong></div>
                    <div><span>Stage</span><code>{progressDetail.label || progressDetail.phase || "—"}</code></div>
                    <div><span>Active node</span><code>{progressDetail.node_class ? `${progressDetail.node_class} (#${progressDetail.node_id || "?"})` : generationProgress.node || "—"}</code></div>
                    <div><span>Queue</span><code>{queueRunning ? `${queueRunning} running` : queuePending ? `${queuePending} pending` : "Idle"}</code></div>
                    <div><span>Elapsed</span><code>{Number.isFinite(Number(progressDetail.elapsed_seconds)) ? `${Number(progressDetail.elapsed_seconds).toFixed(1)} s` : "—"}</code></div>
                    <div><span>Runtime</span><code>{comfyService.state || "unknown"}</code></div>
                    <div><span>Model state</span><code>{modelState}</code></div>
                    <div className="image-studio-status-wide"><span>Model</span><code title={modelName}>{modelName}</code></div>
                    <div><span>VRAM</span><code>{comfyService.vram_mib !== undefined ? `${comfyService.vram_mib} MiB` : "—"}</code></div>
                    <div><span>Seed</span><code>{facePreviewSeed ?? "—"}</code></div>
                    <div className="image-studio-status-wide"><span>Prompt ID</span><code title={previewPromptId || generationProgress.prompt_id || ""}>{previewPromptId || generationProgress.prompt_id || "—"}</code></div>
                  </div>
                  {facePreviewSeed !== undefined && facePreviewSeed !== null ? (
                    <div className="image-studio-seed-controls">
                      <label>
                        <input type="checkbox" checked={faceSeedLocked} onChange={(event) => setFaceSeedLocked(event.target.checked)} />
                        Lock seed <code>{facePreviewSeed}</code>
                      </label>
                      <p>Locking preserves the starting noise so prompt adjustments can be compared more directly.</p>
                    </div>
                  ) : null}
                  <div className="image-studio-face-tweak">
                    <label>
                      Refine this result with the local LLM
                      <textarea
                        rows={3}
                        value={faceTweakInstruction}
                        onChange={(event) => setFaceTweakInstruction(event.target.value)}
                        placeholder="For example: slightly narrower jaw, softer eyebrows, preserve everything else."
                      />
                    </label>
                    <button
                      className="btn"
                      type="button"
                      onClick={refineAndRegenerateFacePreview}
                      disabled={!faceTweakInstruction.trim() || facePreviewSeed === undefined || facePreviewSeed === null || promptHelperBusy || facePreviewTracking || characterSaveBusy}
                    >
                      {promptHelperBusy ? "Refining prompt…" : "Refine & regenerate same seed"}
                    </button>
                    {faceRefinementStatus ? <p className="image-studio-refinement-status" role="status">{faceRefinementStatus}</p> : null}
                    {faceRefinementError ? <p className="error image-studio-refinement-error" role="alert">{faceRefinementError}</p> : null}
                  </div>
                </aside>
                </div>
            ) : activeInterviewStep.id === "body_proportions" ? (
              <div className="image-studio-face-workspace">
                <div className="image-studio-face-builder">
                  <p>Define the body foundation. Pose variations will be created later and will not change these proportions.</p>
                  <div className="image-studio-face-options">
                    {BODY_FEATURE_GROUPS.map((group) => (
                      <fieldset key={group.id}>
                        <legend>{group.label}</legend>
                        <div className="image-studio-option-chips">
                          {group.options.map((option) => {
                            const selected = (bodyFeatureSelections[group.id] || []).includes(option);
                            return <button className={selected ? "is-selected" : ""} type="button" aria-pressed={selected} key={option} onClick={() => selectBodyFeature(group, option)}>{option}</button>;
                          })}
                        </div>
                      </fieldset>
                    ))}
                  </div>
                  <label className="image-studio-full-field">Additional body details<textarea rows={3} value={bodyCustomDetails} onChange={(event) => updateBodyCustomDetails(event.target.value)} /></label>
                  <div className="image-studio-face-summary"><span>Combined body description</span><p>{characterBrief.body || "Choose body characteristics to build the reference description."}</p></div>
                </div>
                <aside className="image-studio-face-preview">
                  <span className="image-studio-eyebrow">Neck-down full-body foundation</span>
                  <div className="image-studio-face-preview-canvas">
                    {bodyPreviewImageUrl ? <img src={bodyPreviewImageUrl} alt={`Generated body reference for ${characterBrief.name || "character"}`} /> : <><span>Body reference</span><p>Your selected proportions will be rendered here.</p></>}
                  </div>
                  <button className="btn btn-primary" type="button" onClick={generateBodyPreview} disabled={!characterBrief.body.trim() || characterSaveBusy || bodyPreviewTracking}>
                    {bodyPreviewTracking ? "Generating body preview…" : bodyPreviewImageUrl ? "Generate again with saved seed" : "Generate body preview"}
                  </button>
                  <div className={`image-studio-generation-summary ${bodyPreviewCompleted ? "is-complete" : ""}`} aria-live="polite">
                    <span>Status</span><strong>{bodyPreviewStatus.replaceAll("_", " ")}</strong>
                    <small>{bodyPreviewTracking ? "Generation status refreshes automatically." : bodyPreviewCompleted ? `Body identity seed ${bodyPreviewSeed} saved.` : "Generate one neutral reference before continuing."}</small>
                  </div>
                  <div className="image-studio-seed-controls"><p>Body seed: <code>{bodyPreviewSeed ?? "not generated"}</code></p></div>
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
                <button className="btn" type="button" onClick={() => saveCharacterProgress()} disabled={!nameConceptComplete || characterSaveBusy}>
                  {characterSaveBusy ? "Saving…" : "Save progress"}
                </button>
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
            {draftSaveMessage ? <p className="image-studio-interview-save-status success">{draftSaveMessage}</p> : null}
          </section>
        </div>
      ) : null}
      {faceSeedReviewOpen ? (
        <div className="image-studio-modal-backdrop" role="presentation">
          <section className="image-studio-interview-modal image-studio-seed-review-modal" role="dialog" aria-modal="true" aria-labelledby="face-seed-review-title">
            <header>
              <div>
                <span className="image-studio-eyebrow">Character identity check</span>
                <h2 id="face-seed-review-title">Choose every face that looks like the same character</h2>
                <p>Slot 1 uses your saved face seed and stays selected. Select any other results that preserve the same identity.</p>
              </div>
              <button className="btn" type="button" onClick={() => { setFaceSeedReviewOpen(false); setInterviewOpen(true); }}>Back to face setup</button>
            </header>
            <div className="image-studio-seed-review-summary" aria-live="polite">
              <div><span>Generated</span><strong>{`${faceSeedBatchReadyCount} / 15`}</strong></div>
              <div><span>Selected as same character</span><strong>{faceSeedReviewSelections.length}</strong></div>
              <div><span>Status</span><strong>{faceSeedBatchTracking ? "Generating identity candidates…" : faceSeedBatchComplete ? "Ready for review" : "Preparing…"}</strong></div>
            </div>
            <div className="image-studio-seed-review-grid">
              {Array.from({ length: 15 }, (_, index) => {
                const preview = faceSeedBatchPreviews[index];
                const previewId = String(preview?.preview_id || `pending-${index}`);
                const selected = Boolean(preview && faceSeedReviewSelections.includes(String(preview.preview_id || "")));
                const anchor = index === 0 || Boolean(preview?.identity_anchor);
                return (
                  <button
                    className={`image-studio-seed-review-card${selected ? " is-selected" : ""}${anchor ? " is-anchor" : ""}`}
                    type="button"
                    key={previewId}
                    disabled={!preview?.url || anchor}
                    aria-pressed={selected}
                    onClick={() => toggleFaceSeedReview(preview, index)}
                  >
                    {preview?.url ? <img src={`${apiBase}${preview.url}`} alt={`Identity seed candidate ${index + 1}`} /> : <span className="image-studio-seed-review-placeholder">{preview?.status ? String(preview.status).replaceAll("_", " ") : "Waiting"}</span>}
                    <span className="image-studio-seed-review-card-meta">
                      <strong>{anchor ? "1 · Saved seed" : `Seed ${index + 1}`}</strong>
                      <code>{preview?.seed ?? "pending"}</code>
                      <small>{anchor ? "Identity anchor" : selected ? "Same character" : preview?.url ? "Click if same character" : "Generating…"}</small>
                    </span>
                  </button>
                );
              })}
            </div>
            <footer>
              <button className="btn" type="button" onClick={() => { setFaceSeedReviewOpen(false); setInterviewOpen(true); }}>Back</button>
              <span>{faceSeedBatchComplete ? "Review all 15 candidates" : `Generating ${faceSeedBatchReadyCount} of 15`}</span>
              <button className="btn btn-primary" type="button" disabled={!faceSeedBatchComplete || characterSaveBusy} onClick={confirmFaceSeedReview}>
                {characterSaveBusy ? "Saving selection…" : "Save selection & continue"}
              </button>
            </footer>
          </section>
        </div>
      ) : null}
    </section>
  );
}

export { applyCharacterFoundation, buildBodyPreviewPrompt, buildFacePreviewNegativePrompt, buildFacePreviewPrompt, characterDraftBodyFeatureCatalog, characterDraftBrief, characterDraftFeatureCatalog, composeFaceDescription, faceFeaturePromptDescription, inferFaceFeatureSelections, nextIncompleteInterviewStep, templateCharacterPath, templateCreationType };
