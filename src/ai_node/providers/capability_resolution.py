from ai_node.providers.model_capability_catalog import ProviderModelCapabilitiesSnapshot


_TIER_ORDER = {"low": 0, "medium": 1, "high": 2}


def _best_tier(values: list[str], *, default: str = "low") -> str:
    best = default
    best_rank = _TIER_ORDER.get(default, 0)
    for value in values:
        rank = _TIER_ORDER.get(str(value or "").strip().lower(), -1)
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
    recommended = sorted({item for entry in entries for item in entry.recommended_for})
    return {
        "provider_id": "openai",
        "enabled_model_ids": normalized_enabled,
        "classification_model": snapshot.classification_model if snapshot is not None else None,
        "updated_at": snapshot.updated_at if snapshot is not None else None,
        "capabilities": {
            "reasoning": any(entry.reasoning for entry in entries),
            "vision": any(entry.vision for entry in entries),
            "image_generation": any(entry.image_generation for entry in entries),
            "audio_input": any(entry.audio_input for entry in entries),
            "audio_output": any(entry.audio_output for entry in entries),
            "realtime": any(entry.realtime for entry in entries),
            "tool_calling": any(entry.tool_calling for entry in entries),
            "structured_output": any(entry.structured_output for entry in entries),
            "long_context": any(entry.long_context for entry in entries),
            "coding_strength": _best_tier([entry.coding_strength for entry in entries], default="low"),
            "speed_tier": _best_tier([entry.speed_tier for entry in entries], default="low"),
            "cost_tier": _best_tier([entry.cost_tier for entry in entries], default="low"),
            "recommended_for": recommended,
        },
        "enabled_models": [entry.model_dump() for entry in entries],
    }
