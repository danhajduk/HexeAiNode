import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from ai_node.providers.model_feature_schema import create_default_feature_flags
from ai_node.providers.openai_model_catalog import (
    OpenAIProviderModelCatalogEntry,
    classify_openai_model_family,
    select_representative_openai_model_ids,
)


DEFAULT_PROVIDER_MODEL_CAPABILITIES_PATH = "providers/openai/provider_model_classifications.json"
LEGACY_PROVIDER_MODEL_CAPABILITIES_PATH = "data/provider_model_capabilities.json"
PROVIDER_MODEL_CAPABILITIES_SCHEMA_VERSION = "2.0"
_DETERMINISTIC_CLASSIFICATION_MODEL = "deterministic_rules"
_CANONICAL_FAMILIES = {
    "llm",
    "image_generation",
    "video_generation",
    "realtime_voice",
    "speech_to_text",
    "text_to_speech",
    "embeddings",
    "moderation",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


class ProviderModelCapabilityEntry(BaseModel):
    model_id: str
    family: str
    text_generation: bool = False
    reasoning: bool = False
    vision: bool = False
    image_generation: bool = False
    audio_input: bool = False
    audio_output: bool = False
    realtime: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    long_context: bool = False
    coding_strength: str = "none"
    speed_tier: str = "medium"
    cost_tier: str = "medium"
    feature_flags: dict[str, bool] = Field(default_factory=create_default_feature_flags)
    discovered_at: str | None = None
    classification_source: str = _DETERMINISTIC_CLASSIFICATION_MODEL


class ProviderModelCapabilitiesSnapshot(BaseModel):
    schema_version: str = PROVIDER_MODEL_CAPABILITIES_SCHEMA_VERSION
    provider_id: str = "openai"
    updated_at: str = Field(default_factory=_iso_now)
    classified_at: str | None = None
    classification_model: str | None = _DETERMINISTIC_CLASSIFICATION_MODEL
    entries: list[ProviderModelCapabilityEntry] = Field(default_factory=list)


def _defaults_for_family(family: str) -> dict:
    base = {
        "text_generation": False,
        "reasoning": False,
        "vision": False,
        "image_generation": False,
        "audio_input": False,
        "audio_output": False,
        "realtime": False,
        "tool_calling": False,
        "structured_output": False,
        "long_context": False,
    }
    if family == "llm":
        base.update(
            {
                "text_generation": True,
                "reasoning": True,
                "vision": True,
                "tool_calling": True,
                "structured_output": True,
                "long_context": True,
            }
        )
    elif family == "image_generation":
        base["image_generation"] = True
    elif family == "realtime_voice":
        base.update(
            {
                "text_generation": True,
                "reasoning": True,
                "audio_input": True,
                "audio_output": True,
                "realtime": True,
                "tool_calling": True,
                "structured_output": True,
            }
        )
    elif family == "speech_to_text":
        base["audio_input"] = True
    elif family == "text_to_speech":
        base["audio_output"] = True
    return base


def _tier_heuristics(*, model_id: str, family: str) -> tuple[str, str, str]:
    normalized = _normalize_string(model_id).lower()

    if family == "llm":
        coding_strength = "medium"
    else:
        coding_strength = "none"

    speed_tier = "medium"
    cost_tier = "medium"

    if normalized.endswith("-pro"):
        if family == "llm":
            coding_strength = "high"
        speed_tier = "slow"
        cost_tier = "high"
    elif normalized.endswith("-mini"):
        if family == "llm":
            coding_strength = "medium"
        speed_tier = "fast"
        cost_tier = "low"
    elif normalized.endswith("-nano"):
        if family == "llm":
            coding_strength = "low"
        speed_tier = "fast"
        cost_tier = "low"
    elif family in {"embeddings", "moderation", "speech_to_text", "text_to_speech"}:
        speed_tier = "fast"
        cost_tier = "low"

    return coding_strength, speed_tier, cost_tier


def _resolve_model_feature_flags(*, entry: ProviderModelCapabilityEntry) -> dict[str, bool]:
    feature_flags = create_default_feature_flags()
    family = entry.family

    if family == "llm":
        feature_flags.update(
            {
                "chat": True,
                "classification": True,
                "information_extraction": True,
                "instruction_following": True,
                "summarization": True,
                "translation": True,
                "sentiment_analysis": True,
                "reasoning": bool(entry.reasoning),
                "long_context": bool(entry.long_context),
                "planning": bool(entry.reasoning),
                "structured_output": bool(entry.structured_output),
                "json_output": bool(entry.structured_output),
                "schema_output": bool(entry.structured_output),
                "tool_calling": bool(entry.tool_calling),
                "function_calling": bool(entry.tool_calling),
            }
        )
        if entry.coding_strength in {"medium", "high"}:
            feature_flags["code_generation"] = True
            feature_flags["code_review"] = True
        if entry.coding_strength in {"low", "medium", "high"}:
            feature_flags["code_explanation"] = True
        if entry.coding_strength in {"medium", "high"} and entry.reasoning:
            feature_flags["code_debugging"] = True
        if entry.vision:
            feature_flags["vision_input"] = True
            feature_flags["image_understanding"] = True
            feature_flags["document_understanding"] = True
    elif family == "image_generation":
        feature_flags["image_generation"] = True
    elif family == "realtime_voice":
        feature_flags["realtime_interaction"] = True
        feature_flags["audio_input"] = True
        feature_flags["audio_output"] = True
        feature_flags["voice_conversation"] = True
        feature_flags["streaming_output"] = True
        feature_flags["low_latency"] = True
    elif family == "speech_to_text":
        feature_flags["audio_input"] = True
        feature_flags["speech_to_text"] = True
    elif family == "text_to_speech":
        feature_flags["audio_output"] = True
        feature_flags["text_to_speech"] = True
    elif family == "embeddings":
        feature_flags["embeddings"] = True
        feature_flags["semantic_search"] = True
        feature_flags["document_indexing"] = True
        feature_flags["knowledge_retrieval"] = True
    elif family == "moderation":
        feature_flags["moderation"] = True
        feature_flags["policy_check"] = True

    return feature_flags


def _build_entry(*, model_id: str, family: str, discovered_at: str | None = None) -> ProviderModelCapabilityEntry:
    defaults = _defaults_for_family(family)
    coding_strength, speed_tier, cost_tier = _tier_heuristics(model_id=model_id, family=family)
    entry = ProviderModelCapabilityEntry(
        model_id=model_id,
        family=family,
        text_generation=defaults["text_generation"],
        reasoning=defaults["reasoning"],
        vision=defaults["vision"],
        image_generation=defaults["image_generation"],
        audio_input=defaults["audio_input"],
        audio_output=defaults["audio_output"],
        realtime=defaults["realtime"],
        tool_calling=defaults["tool_calling"],
        structured_output=defaults["structured_output"],
        long_context=defaults["long_context"],
        coding_strength=coding_strength,
        speed_tier=speed_tier,
        cost_tier=cost_tier,
        discovered_at=discovered_at,
        classification_source=_DETERMINISTIC_CLASSIFICATION_MODEL,
    )
    entry.feature_flags = _resolve_model_feature_flags(entry=entry)
    return entry


def _filter_models_for_classification(
    *,
    models: list[OpenAIProviderModelCatalogEntry],
    preserve_model_ids: list[str] | None = None,
) -> list[OpenAIProviderModelCatalogEntry]:
    selected_ids = select_representative_openai_model_ids(
        [str(item.model_id or "").strip().lower() for item in models]
    )
    preserved_ids = {
        str(model_id or "").strip().lower()
        for model_id in (preserve_model_ids or [])
        if str(model_id or "").strip()
    }
    selected_ids.update(preserved_ids)
    seen: set[str] = set()
    filtered: list[OpenAIProviderModelCatalogEntry] = []
    for item in models:
        model_id = _normalize_string(item.model_id).lower()
        family = _normalize_string(item.family).lower()
        if not model_id or not family or model_id in seen or model_id not in selected_ids:
            continue
        seen.add(model_id)
        filtered.append(item)
    filtered.sort(key=lambda item: (item.family, item.model_id))
    return filtered


def build_deterministic_entries(
    *,
    models: list[OpenAIProviderModelCatalogEntry],
    preserve_model_ids: list[str] | None = None,
) -> list[ProviderModelCapabilityEntry]:
    filtered_models = _filter_models_for_classification(models=models, preserve_model_ids=preserve_model_ids)
    entries = [
        _build_entry(model_id=item.model_id, family=item.family, discovered_at=item.discovered_at)
        for item in filtered_models
        if _normalize_string(item.model_id) and _normalize_string(item.family)
    ]
    entries.sort(key=lambda item: item.model_id)
    return entries


class ProviderModelCapabilitiesStore:
    def __init__(
        self,
        *,
        path: str = DEFAULT_PROVIDER_MODEL_CAPABILITIES_PATH,
        logger,
        legacy_path: str = LEGACY_PROVIDER_MODEL_CAPABILITIES_PATH,
    ) -> None:
        self._path = Path(path)
        self._legacy_path = Path(legacy_path)
        self._logger = logger

    def _parse_snapshot(self, payload: dict) -> ProviderModelCapabilitiesSnapshot | None:
        try:
            return ProviderModelCapabilitiesSnapshot.model_validate(payload)
        except Exception:
            return None

    def _migrate_legacy_payload(self, payload: dict) -> ProviderModelCapabilitiesSnapshot | None:
        legacy_entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(legacy_entries, list):
            return None
        discovered_at = str(payload.get("classified_at") or payload.get("updated_at") or _iso_now()).strip() or _iso_now()
        entries: list[ProviderModelCapabilityEntry] = []
        seen: set[str] = set()
        for item in legacy_entries:
            if not isinstance(item, dict):
                continue
            model_id = _normalize_string(item.get("model_id")).lower()
            if not model_id or model_id in seen:
                continue
            family = classify_openai_model_family(model_id)
            if family is None:
                raw_family = _normalize_string(item.get("family")).lower()
                if raw_family in _CANONICAL_FAMILIES:
                    family = raw_family
            if family is None:
                continue
            entries.append(_build_entry(model_id=model_id, family=family, discovered_at=discovered_at))
            seen.add(model_id)

        snapshot = ProviderModelCapabilitiesSnapshot(
            updated_at=_iso_now(),
            classified_at=discovered_at,
            classification_model=_DETERMINISTIC_CLASSIFICATION_MODEL,
            entries=sorted(entries, key=lambda entry: entry.model_id),
        )
        self.save_snapshot(snapshot=snapshot)
        return snapshot

    def load(self) -> ProviderModelCapabilitiesSnapshot | None:
        if self._path.exists():
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                return None
            snapshot = self._parse_snapshot(payload)
            if snapshot is not None:
                return snapshot

        if not self._legacy_path.exists():
            return None
        try:
            legacy_payload = json.loads(self._legacy_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return self._migrate_legacy_payload(legacy_payload)

    def payload(self) -> dict:
        snapshot = self.load()
        if snapshot is None:
            return {
                "provider_id": "openai",
                "classification_model": _DETERMINISTIC_CLASSIFICATION_MODEL,
                "generated_at": _iso_now(),
                "classified_at": None,
                "entries": [],
                "source": "provider_model_classifications",
            }
        return {
            "provider_id": snapshot.provider_id,
            "classification_model": snapshot.classification_model,
            "generated_at": snapshot.updated_at,
            "classified_at": snapshot.classified_at or snapshot.updated_at,
            "entries": [entry.model_dump() for entry in snapshot.entries],
            "source": "provider_model_classifications",
        }

    def save_snapshot(self, *, snapshot: ProviderModelCapabilitiesSnapshot) -> ProviderModelCapabilitiesSnapshot:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(json.dumps(snapshot.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[provider-model-capabilities-saved] %s",
                {
                    "path": str(self._path),
                    "entries": len(snapshot.entries),
                    "classification_model": snapshot.classification_model,
                },
            )
        return snapshot

    def save(self, *, classification_model: str | None, entries: list[ProviderModelCapabilityEntry]) -> ProviderModelCapabilitiesSnapshot:
        timestamp = _iso_now()
        _ = classification_model
        snapshot = ProviderModelCapabilitiesSnapshot(
            classification_model=_DETERMINISTIC_CLASSIFICATION_MODEL,
            updated_at=timestamp,
            classified_at=timestamp,
            entries=entries,
        )
        return self.save_snapshot(snapshot=snapshot)


class OpenAIModelCapabilityClassifier:
    def __init__(
        self,
        *,
        logger,
        store: ProviderModelCapabilitiesStore,
        **_kwargs,
    ) -> None:
        self._logger = logger
        self._store = store

    async def classify_and_save(
        self,
        *,
        models: list[OpenAIProviderModelCatalogEntry],
        preserve_model_ids: list[str] | None = None,
    ) -> ProviderModelCapabilitiesSnapshot:
        entries = build_deterministic_entries(models=models, preserve_model_ids=preserve_model_ids)
        snapshot = self._store.save(classification_model=_DETERMINISTIC_CLASSIFICATION_MODEL, entries=entries)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[provider-model-capability-classification-deterministic] %s",
                {"count": len(snapshot.entries)},
            )
        return snapshot
