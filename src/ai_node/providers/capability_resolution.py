from ai_node.providers.model_capability_catalog import ProviderModelCapabilitiesSnapshot


def _best_tier(values: list[str], *, default: str, order: dict[str, int]) -> str:
    best = default
    best_rank = order.get(default, 0)
    for value in values:
        rank = order.get(str(value or "").strip().lower(), -1)
        if rank > best_rank:
            best = str(value or "").strip().lower()
            best_rank = rank
    return best


def resolve_enabled_model_capabilities(*, snapshot: ProviderModelCapabilitiesSnapshot | None, enabled_model_ids: list[str]) -> dict:
    normalized_enabled = [str(model_id or "").strip().lower() for model_id in enabled_model_ids if str(model_id or "").strip()]
    enabled_set = set(normalized_enabled)
    entries = []
    if snapshot is not None:
        entries = [entry for entry in snapshot.entries if entry.model_id in enabled_set]
    families = sorted({entry.family for entry in entries if str(entry.family or "").strip()})
    return {
        "provider_id": "openai",
        "enabled_model_ids": normalized_enabled,
        "classification_model": snapshot.classification_model if snapshot is not None else None,
        "updated_at": snapshot.updated_at if snapshot is not None else None,
        "capabilities": {
            "text_generation": any(entry.text_generation for entry in entries),
            "reasoning": any(entry.reasoning for entry in entries),
            "vision": any(entry.vision for entry in entries),
            "image_generation": any(entry.image_generation for entry in entries),
            "audio_input": any(entry.audio_input for entry in entries),
            "audio_output": any(entry.audio_output for entry in entries),
            "realtime": any(entry.realtime for entry in entries),
            "tool_calling": any(entry.tool_calling for entry in entries),
            "structured_output": any(entry.structured_output for entry in entries),
            "long_context": any(entry.long_context for entry in entries),
            "embeddings": "embeddings" in families,
            "moderation": "moderation" in families,
            "coding_strength": _best_tier(
                [entry.coding_strength for entry in entries],
                default="none",
                order={"none": 0, "low": 1, "medium": 2, "high": 3},
            ),
            "speed_tier": _best_tier(
                [entry.speed_tier for entry in entries],
                default="slow",
                order={"slow": 0, "medium": 1, "fast": 2},
            ),
            "cost_tier": _best_tier(
                [entry.cost_tier for entry in entries],
                default="low",
                order={"low": 0, "medium": 1, "high": 2},
            ),
        },
        "enabled_models": [entry.model_dump() for entry in entries],
    }
