from ai_node.providers.model_feature_schema import create_default_feature_flags


LOCAL_MODEL_FEATURE_CLASSIFIER = "local_llm_deterministic_rules"


def build_local_model_feature_entries(*, model_ids: list[str]) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for model_id in model_ids:
        normalized = str(model_id or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        entries.append(
            {
                "model_id": normalized,
                "provider": "local",
                "features": local_model_feature_flags(model_id=normalized),
                "classification_model": LOCAL_MODEL_FEATURE_CLASSIFIER,
            }
        )
        seen.add(normalized)
    return entries


def local_model_feature_flags(*, model_id: str) -> dict[str, bool]:
    normalized = str(model_id or "").strip().lower()
    features = create_default_feature_flags()

    for key in (
        "chat",
        "instruction_following",
        "reasoning",
        "classification",
        "summarization",
        "information_extraction",
        "translation",
        "sentiment_analysis",
        "structured_output",
        "json_output",
        "schema_output",
        "planning",
        "streaming_output",
    ):
        features[key] = True

    if _looks_code_capable(normalized):
        for key in ("code_generation", "code_review", "code_debugging", "code_explanation"):
            features[key] = True

    if _looks_long_context_capable(normalized):
        features["long_context"] = True

    return features


def _looks_code_capable(model_id: str) -> bool:
    return any(token in model_id for token in ("coder", "code", "codestral", "deepseek-coder"))


def _looks_long_context_capable(model_id: str) -> bool:
    return any(token in model_id for token in ("32k", "64k", "128k", "long"))
