MODEL_FEATURE_SCHEMA_VERSION = "1.0"


MODEL_FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "core_cognition": (
        "chat",
        "reasoning",
        "instruction_following",
        "classification",
        "summarization",
        "information_extraction",
        "translation",
        "sentiment_analysis",
        "long_context",
    ),
    "automation_tools": (
        "structured_output",
        "json_output",
        "schema_output",
        "tool_calling",
        "function_calling",
        "planning",
        "automation_commands",
        "environment_control",
    ),
    "coding": (
        "code_generation",
        "code_review",
        "code_debugging",
        "code_explanation",
    ),
    "vision": (
        "vision_input",
        "image_understanding",
        "document_understanding",
        "ocr",
        "object_detection",
    ),
    "images": (
        "image_generation",
        "image_editing",
        "image_variation",
    ),
    "audio": (
        "audio_input",
        "speech_to_text",
        "audio_output",
        "text_to_speech",
        "voice_conversation",
        "audio_analysis",
    ),
    "realtime": (
        "realtime_interaction",
        "streaming_output",
        "low_latency",
    ),
    "knowledge": (
        "embeddings",
        "semantic_search",
        "document_indexing",
        "knowledge_retrieval",
    ),
    "safety": (
        "moderation",
        "policy_check",
    ),
}

MODEL_FEATURE_KEYS: tuple[str, ...] = tuple(
    feature
    for group_features in MODEL_FEATURE_GROUPS.values()
    for feature in group_features
)


def create_default_feature_flags() -> dict[str, bool]:
    return {feature: False for feature in MODEL_FEATURE_KEYS}


def normalize_feature_flags(*, feature_flags: object) -> dict[str, bool]:
    if not isinstance(feature_flags, dict):
        raise ValueError("classification_feature_flags_invalid")
    normalized = create_default_feature_flags()
    for key, value in feature_flags.items():
        feature = str(key or "").strip()
        if feature not in normalized:
            raise ValueError(f"classification_feature_unknown:{feature or 'missing'}")
        if not isinstance(value, bool):
            raise ValueError(f"classification_feature_value_invalid:{feature}")
        normalized[feature] = value
    return normalized
