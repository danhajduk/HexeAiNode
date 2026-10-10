"""Backend-owned prompt compilation for Image Studio body references."""

BODY_FEATURE_DESCRIPTIONS = {
    "body_traits": {
        "pronounced feminine": "pronounced feminine body traits with a fuller natural chest silhouette, narrow defined waist, rounded wider hips, fuller thighs, and soft body contours",
        "feminine": "feminine body traits with a natural chest silhouette, defined waist, rounded hips, and softly curved body contours",
        "androgynous": "androgynous body traits with a neutral chest silhouette, balanced shoulders and hips, subtle waist definition, and even body contours",
        "masculine": "masculine body traits with broader shoulders, a flatter chest silhouette, straighter waist, narrower hips, and firmer body contours",
        "pronounced masculine": "pronounced masculine body traits with broad shoulders and chest, strong upper-body taper, straight narrow waist and hips, and angular muscular contours",
    },
    "height": {value: text for value, text in (
        ("short", "short stature with compact vertical proportions"), ("below average", "below-average stature with slightly compact vertical proportions"),
        ("average", "average stature with balanced vertical proportions"), ("tall", "tall stature with elongated vertical proportions and a longer leg line"),
        ("very tall", "very tall stature with strongly elongated but anatomically coherent proportions"),
    )},
    "build": {value: f"{value} build with natural, anatomically coherent body mass and contours" for value in ("slender", "lean", "average", "athletic", "curvy", "stocky", "heavyset")},
    "shoulders": {value: f"{value} shoulder shape relative to the torso and hips" for value in ("narrow", "balanced", "broad", "softly rounded", "angular")},
    "torso": {value: f"{value} with anatomically coherent ribcage-to-pelvis proportions" for value in ("short torso", "balanced torso", "long torso", "straight torso", "tapered torso")},
    "waist": {value: f"{value} relative to the ribcage and hips" for value in ("subtle waist", "defined waist", "narrow waist", "straight waist", "broad waist")},
    "hips": {value: f"{value} with a natural pelvis and outer hip contour" for value in ("narrow hips", "balanced hips", "wide hips", "rounded hips", "angular hips")},
    "limbs": {value: f"{value} with anatomically coherent arm, leg, and torso balance" for value in ("short limbs", "balanced limbs", "long legs", "long arms", "long limbs")},
    "musculature": {value: f"{value} visible muscle volume and definition across the torso and limbs" for value in ("soft definition", "lightly toned", "athletic definition", "muscular", "strongly muscular")},
    "body_hair": {
        "none": "no visible body hair anywhere on the torso, arms, or legs",
        **{value: f"{value} natural body hair distribution across the torso, arms, and legs" for value in ("very light", "light", "natural", "moderate", "heavy")},
    },
    "breast_size": {value: f"{value} adult breast volume with realistic weight and proportions" for value in ("flat chest", "small", "medium", "large", "very large")},
    "breast_shape": {value: f"{value} adult breast contour with realistic soft-tissue behavior" for value in ("shallow", "round", "teardrop", "wide-set", "close-set", "pendulous")},
    "butt_size": {value: f"{value} gluteal volume proportionate to the pelvis and thighs" for value in ("flat", "small", "moderate", "full", "very full")},
    "butt_shape": {value: f"{value} gluteal contour with realistic soft-tissue anatomy" for value in ("square", "round", "heart-shaped", "V-shaped", "athletic")},
    "pubic_hair": {
        "none": "no visible pubic hair",
        **{value: f"{value} adult pubic-hair amount and grooming" for value in ("closely trimmed", "trimmed", "natural", "full")},
    },
    "pubic_hair_color": {value: f"{value} pubic hair color" for value in ("black", "dark brown", "brown", "auburn", "copper", "red", "blonde", "platinum", "gray", "white")},
    "vulva_description": {value: f"{value} realistic adult external vulvar anatomy with natural variation" for value in ("subtle", "natural", "prominent")},
    "penis_description": {value: f"{value}-size flaccid adult penis with realistic external anatomy" for value in ("small", "average", "large")},
    "misc": {"no tattoos": "completely tattoo-free skin across the entire visible body"},
}

MAGNITUDE_DESCRIPTIONS = {
    "height": ("very short", "short", "average", "tall", "very tall", "overall stature and vertical proportions"),
    "body_mass": ("very slender", "slender", "average", "full", "very heavy", "natural body mass and soft-tissue volume"),
    "shoulder_width": ("very narrow", "narrow", "balanced", "broad", "very broad", "shoulder span relative to the torso and hips"),
    "torso_length": ("very short", "short", "balanced", "long", "very long", "ribcage-to-pelvis torso length"),
    "waist_width": ("very narrow", "narrow", "balanced", "broad", "very broad", "waist width relative to ribcage and hips"),
    "hip_width": ("very narrow", "narrow", "balanced", "wide", "very wide", "pelvis and outer hip width"),
    "limb_length": ("very short", "short", "balanced", "long", "very long", "arm and leg length relative to the torso"),
    "musculature": ("very soft", "soft", "moderate", "muscular", "very muscular", "visible natural muscle volume and definition"),
    "butt_size": ("very flat", "small", "moderate", "full", "very full", "gluteal volume relative to pelvis and thighs"),
    "penis_size": ("very small", "small", "average", "large", "very large", "flaccid adult penis size with realistic external anatomy"),
}

STYLE_PROMPTS = {
    "realistic": "Photograph of a real living human person, natural skin pores and fine texture, subtle blemishes and tonal variation, realistic soft-tissue transitions, professional studio photography without a mannequin or CGI appearance.",
    "semi-realistic": "Polished semi-realistic human character body, intact natural-looking skin, believable human joints and proportions, softly stylized forms, high-quality character concept art.",
    "anime": "Clean anime character body design, intact continuous skin, coherent anime anatomy and proportions, smooth cel-shaded rendering, polished character reference art.",
}


def body_preview_checkpoint(selections: dict | None) -> str:
    selections = selections if isinstance(selections, dict) else {}
    if selections.get("vulva_description") or selections.get("penis_description"):
        return "lustifySDXLNSFWSFW_v20.safetensors"
    return "RealVisXL_V5.0_fp16.safetensors"


def body_preview_sampling_settings(selections: dict | None) -> dict:
    explicit_adult_anatomy = body_preview_checkpoint(selections) == "lustifySDXLNSFWSFW_v20.safetensors"
    return {
        "steps": 28 if explicit_adult_anatomy else 4,
        "cfg": 5.5 if explicit_adult_anatomy else 1.2,
        "lightning_strength": 0.0 if explicit_adult_anatomy else 1.0,
        "sampler_name": "dpmpp_2m_sde" if explicit_adult_anatomy else "euler",
        "scheduler": "karras" if explicit_adult_anatomy else "sgm_uniform",
    }


def compile_body_preview_prompt(*, selections: dict | None, face_selections: dict | None, custom_details: str | None, context: dict | None, magnitudes: dict | None = None) -> str:
    selections = selections if isinstance(selections, dict) else {}
    face_selections = face_selections if isinstance(face_selections, dict) else {}
    context = context if isinstance(context, dict) else {}
    magnitudes = magnitudes if isinstance(magnitudes, dict) else {}
    if selections.get("vulva_description") and (selections.get("penis_description") or "penis_size" in magnitudes):
        raise ValueError("body_feature_anatomy_conflict")

    normalized_magnitudes = {}
    for magnitude_id, raw_value in magnitudes.items():
        if magnitude_id != "breast_size" and magnitude_id not in MAGNITUDE_DESCRIPTIONS:
            raise ValueError(f"body_feature_magnitude_invalid:{magnitude_id}")
        value = float(raw_value)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"body_feature_magnitude_out_of_range:{magnitude_id}")
        normalized_magnitudes[magnitude_id] = value

    details = []
    for group_id, values in selections.items():
        if group_id not in BODY_FEATURE_DESCRIPTIONS:
            raise ValueError(f"body_feature_group_invalid:{group_id}")
        if not isinstance(values, list):
            raise ValueError(f"body_feature_values_invalid:{group_id}")
        for value in values[:1]:
            description = BODY_FEATURE_DESCRIPTIONS[group_id].get(str(value))
            if description is None:
                if group_id == "pubic_hair_color" and value == "inherit from head hair":
                    continue
                raise ValueError(f"body_feature_option_invalid:{group_id}:{value}")
            if group_id == "pubic_hair_color" and (selections.get("pubic_hair") or [None])[0] == "none":
                continue
            if group_id in {"breast_size", "breast_shape"} and "breast_size" in normalized_magnitudes:
                continue
            if group_id == "penis_description" and "penis_size" in normalized_magnitudes:
                continue
            emphasis = "1.45" if group_id in {"body_traits", "build", "breast_size", "breast_shape", "vulva_description", "penis_description"} else "1.25"
            details.append(f"({group_id.replace('_', ' ')}: {description}:{emphasis})")

    if "breast_size" in normalized_magnitudes:
        value = normalized_magnitudes["breast_size"]
        label = "very small" if value < 0.2 else "small" if value < 0.4 else "moderate" if value <= 0.6 else "large" if value <= 0.8 else "very large"
        shape_values = selections.get("breast_shape") or []
        shape = BODY_FEATURE_DESCRIPTIONS["breast_shape"].get(str(shape_values[0])) if shape_values else None
        shape_instruction = shape or "natural adult breast contour with realistic soft-tissue behavior"
        details.append(f"(breast anatomy: size magnitude {value:.2f} on a 0-to-1 scale, {label} adult breast volume with realistic weight and proportions; shape: {shape_instruction}:1.50)")

    for magnitude_id, value in normalized_magnitudes.items():
        if magnitude_id == "breast_size":
            continue
        bands = MAGNITUDE_DESCRIPTIONS[magnitude_id]
        band_index = min(4, int(value * 5))
        label = bands[band_index]
        details.append(f"({magnitude_id.replace('_', ' ')} magnitude: {value:.2f} on a 0-to-1 scale, {label} {bands[5]}:1.40)")

    pubic_hair = selections.get("pubic_hair") or []
    explicit_pubic_color = selections.get("pubic_hair_color") or []
    head_hair_color = face_selections.get("hair color") or []
    if pubic_hair and pubic_hair[0] != "none" and not explicit_pubic_color and head_hair_color:
        details.append(f"pubic hair color: {head_hair_color[0]} pubic hair color, inherited from head hair")
    skin_tone = face_selections.get("skin tone") or []
    skin_instruction = f"INHERITED FACE SKIN TONE: {skin_tone[0]} natural skin tone with realistic tonal variation. Match this tone across the neck and entire body." if skin_tone else ""
    if str(custom_details or "").strip():
        details.append(str(custom_details).strip())

    style = str(context.get("visual_style") or "semi-realistic").strip().lower()
    return "\n".join(filter(None, (
        "Studio image of exactly one living human person. The camera frame begins at the collarbones and base of the neck; the person's head is naturally above and fully outside the image boundary.",
        f"Character body: {context.get('age_group', '')} {context.get('gender_identity', '')}.",
        f"SELECTED BODY TRAITS — MUST MATCH EXACTLY: {'; '.join(details)}.",
        skin_instruction,
        "STRICT CAMERA FRAMING: neck-down full-body reference, portrait orientation, zoomed out. Top edge crosses the base of the neck above both collarbones. Both shoulders, entire torso, pelvis, both complete legs, ankles, and both complete feet are inside the frame. Feet sit near the bottom margin. No head, scalp, face, facial hair, beard, mustache, sideburns, or head hair is visible anywhere in the image; no hair hangs down from outside the frame. No waist crop, no knee crop, no missing feet.",
        "DEFINED REFERENCE POSE: relaxed anatomical A-pose facing the camera squarely. Stand upright with the spine and pelvis neutral, shoulders level and relaxed, feet hip-width apart and fully planted, toes pointing forward with only a slight natural outward angle, body weight distributed evenly across both legs, and knees straight but not locked. Hold both arms naturally 10 to 15 degrees away from the torso with soft elbows, palms facing inward toward the thighs, wrists neutral, and fingers gently separated. Keep the torso, waist, hips, hands, and inner leg contours clearly visible and unobscured.",
        "Clean healthy intact living skin with natural pores, subtle tonal variation, and uninterrupted soft-tissue transitions. Uniform natural skin surface without embedded objects, debris, colored spots, lesions, mosaic texture, or body paint. Normal human joints with no panel lines.",
        "Plain seamless neutral-gray studio background, visually separate from the body, no patterned wall, no camouflage, no reflected texture on skin.",
        STYLE_PROMPTS.get(style, STYLE_PROMPTS["semi-realistic"]),
    )))
