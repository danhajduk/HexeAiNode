from ai_node.capabilities.task_families import validate_task_family_capabilities


def _normalized_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def derive_declared_task_families(*, resolved_capabilities: dict | None) -> list[str]:
    capabilities = resolved_capabilities.get("capabilities") if isinstance(resolved_capabilities, dict) else {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    recommended = set(_normalized_list(capabilities.get("recommended_for")))
    enabled_models = resolved_capabilities.get("enabled_models") if isinstance(resolved_capabilities, dict) else []
    families = {
        str(item.get("family") or "").strip().lower()
        for item in enabled_models
        if isinstance(item, dict) and str(item.get("family") or "").strip()
    }

    declared: list[str] = []

    def add(task_family: str, condition: bool) -> None:
        if condition and task_family not in declared:
            declared.append(task_family)

    add("task.classification", bool(capabilities.get("structured_output")) or "classification" in recommended)
    add(
        "task.summarization",
        bool(capabilities.get("reasoning")) or bool(capabilities.get("long_context")) or "summarization" in recommended,
    )
    add("task.reasoning", bool(capabilities.get("reasoning")) or "reasoning" in recommended or "chat" in recommended)
    add(
        "task.coding",
        str(capabilities.get("coding_strength") or "").strip().lower() in {"medium", "high"} or "coding" in recommended,
    )
    add("task.vision_analysis", bool(capabilities.get("vision")) or "vision_analysis" in recommended)
    add(
        "task.image_generation",
        bool(capabilities.get("image_generation")) or "image_generation" in recommended or "image_generation" in families,
    )
    add(
        "task.speech_to_text",
        bool(capabilities.get("audio_input")) or "speech_recognition" in recommended or "speech_to_text" in families,
    )
    add(
        "task.text_to_speech",
        bool(capabilities.get("audio_output")) or "speech_generation" in recommended or "text_to_speech" in families,
    )
    add(
        "task.realtime_voice",
        bool(capabilities.get("realtime")) or "realtime_voice" in recommended or "realtime_voice" in families,
    )
    add("task.embedding_generation", "embeddings" in recommended or "embeddings" in families)
    add("task.moderation", "moderation" in recommended or "moderation" in families)

    is_valid, error = validate_task_family_capabilities(declared)
    if not is_valid:
        raise ValueError(f"invalid_derived_task_families:{error}")
    return declared
