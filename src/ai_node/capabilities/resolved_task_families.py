from ai_node.capabilities.task_families import validate_task_family_capabilities


def derive_declared_task_families(*, resolved_capabilities: dict | None) -> list[str]:
    capabilities = resolved_capabilities.get("capabilities") if isinstance(resolved_capabilities, dict) else {}
    if not isinstance(capabilities, dict):
        capabilities = {}
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

    text_generation = bool(capabilities.get("text_generation"))
    add("task.classification", text_generation)
    add("task.summarization", text_generation)
    add("task.reasoning", bool(text_generation and capabilities.get("reasoning")))
    add(
        "task.coding",
        bool(text_generation and str(capabilities.get("coding_strength") or "").strip().lower() in {"medium", "high"}),
    )
    add("task.vision_analysis", bool(capabilities.get("vision")))
    add("task.image_generation", bool(capabilities.get("image_generation")) or "image_generation" in families)
    add("task.speech_to_text", bool(capabilities.get("audio_input")) or "speech_to_text" in families)
    add("task.text_to_speech", bool(capabilities.get("audio_output")) or "text_to_speech" in families)
    add(
        "task.realtime_voice",
        bool(capabilities.get("realtime") and capabilities.get("audio_input") and capabilities.get("audio_output"))
        or "realtime_voice" in families,
    )
    add("task.embedding_generation", bool(capabilities.get("embeddings")) or "embeddings" in families)
    add("task.moderation", bool(capabilities.get("moderation")) or "moderation" in families)

    is_valid, error = validate_task_family_capabilities(declared)
    if not is_valid:
        raise ValueError(f"invalid_derived_task_families:{error}")
    return declared
