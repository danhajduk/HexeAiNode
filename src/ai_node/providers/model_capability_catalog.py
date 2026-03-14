import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel, Field

from ai_node.providers.openai_model_catalog import OpenAIProviderModelCatalogEntry


DEFAULT_PROVIDER_MODEL_CAPABILITIES_PATH = "data/provider_model_capabilities.json"
PROVIDER_MODEL_CAPABILITIES_SCHEMA_VERSION = "1.0"
RECOMMENDED_FOR_OPTIONS = [
    "chat",
    "agents",
    "automation",
    "reasoning",
    "coding",
    "structured_extraction",
    "summarization",
    "classification",
    "vision_analysis",
    "image_generation",
    "speech_recognition",
    "speech_generation",
    "realtime_voice",
    "embeddings",
    "moderation",
]
_TIER_OPTIONS = {"low", "medium", "high"}
_CODING_STRENGTH_OPTIONS = {"low", "medium", "high"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


class ProviderModelCapabilityEntry(BaseModel):
    model_id: str
    family: str
    reasoning: bool = False
    vision: bool = False
    image_generation: bool = False
    audio_input: bool = False
    audio_output: bool = False
    realtime: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    long_context: bool = False
    coding_strength: str = "low"
    speed_tier: str = "medium"
    cost_tier: str = "medium"
    recommended_for: list[str] = Field(default_factory=list)


class ProviderModelCapabilitiesSnapshot(BaseModel):
    schema_version: str = PROVIDER_MODEL_CAPABILITIES_SCHEMA_VERSION
    provider_id: str = "openai"
    updated_at: str = Field(default_factory=_iso_now)
    classification_model: str | None = None
    entries: list[ProviderModelCapabilityEntry] = Field(default_factory=list)


def select_openai_classification_model(models: list[OpenAIProviderModelCatalogEntry]) -> str | None:
    llm_models = [entry.model_id for entry in models if entry.family == "llm"]
    if not llm_models:
        return None

    def rank(model_id: str) -> tuple[int, int, int, str]:
        normalized = _normalize_string(model_id).lower()
        if normalized.endswith("-nano"):
            return (0, 0, 0, normalized)
        if normalized.endswith("-mini"):
            return (1, 0, 0, normalized)
        if normalized.endswith("-pro"):
            return (3, 0, 0, normalized)
        major = 999
        minor = 999
        version = normalized.removeprefix("gpt-").split("-", 1)[0]
        if version:
            pieces = version.split(".", 1)
            try:
                major = int(pieces[0])
            except ValueError:
                major = 999
            if len(pieces) > 1:
                try:
                    minor = int(pieces[1])
                except ValueError:
                    minor = 999
        return (2, major, minor, normalized)

    return sorted(llm_models, key=rank)[0]


def build_openai_capability_classification_prompt(*, models: list[OpenAIProviderModelCatalogEntry], classification_model: str) -> tuple[str, str]:
    model_lines = "\n".join(f"- {item.model_id} ({item.family})" for item in models)
    allowed = ", ".join(RECOMMENDED_FOR_OPTIONS)
    system_prompt = (
        "You are a model capability classifier for Synthia. "
        "Return JSON only. No markdown, no prose, no code fences. "
        "For each model, classify capabilities conservatively and keep recommended_for within the allowed vocabulary."
    )
    user_prompt = (
        f"Classification model: {classification_model}\n"
        "Return a JSON object with key 'models' containing one entry per input model.\n"
        "Each entry must include: model_id, family, reasoning, vision, image_generation, audio_input, "
        "audio_output, realtime, tool_calling, structured_output, long_context, coding_strength, speed_tier, "
        "cost_tier, recommended_for.\n"
        "coding_strength must be one of: low, medium, high.\n"
        "speed_tier must be one of: low, medium, high.\n"
        "cost_tier must be one of: low, medium, high.\n"
        f"recommended_for allowed values: {allowed}.\n"
        "Use booleans for capability flags and a list of strings for recommended_for.\n"
        "Input models:\n"
        f"{model_lines}\n"
    )
    return system_prompt, user_prompt


def _strip_json_fence(value: str) -> str:
    text = _normalize_string(value)
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def validate_provider_model_capability_payload(*, payload: object, expected_models: list[OpenAIProviderModelCatalogEntry]) -> list[ProviderModelCapabilityEntry]:
    if not isinstance(payload, dict):
        raise ValueError("classification_payload_invalid")
    raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        raise ValueError("classification_models_missing")
    expected_map = {entry.model_id: entry.family for entry in expected_models}
    validated: list[ProviderModelCapabilityEntry] = []
    seen: set[str] = set()
    for item in raw_models:
        if not isinstance(item, dict):
            raise ValueError("classification_entry_invalid")
        model_id = _normalize_string(item.get("model_id")).lower()
        if model_id not in expected_map or model_id in seen:
            raise ValueError(f"classification_model_unexpected:{model_id or 'missing'}")
        family = _normalize_string(item.get("family")).lower() or expected_map[model_id]
        entry = ProviderModelCapabilityEntry.model_validate(
            {
                **item,
                "model_id": model_id,
                "family": family,
                "recommended_for": sorted(set(str(value).strip() for value in item.get("recommended_for") or [] if str(value).strip())),
            }
        )
        if entry.family != expected_map[model_id]:
            raise ValueError(f"classification_family_mismatch:{model_id}")
        if entry.coding_strength not in _CODING_STRENGTH_OPTIONS:
            raise ValueError(f"classification_coding_strength_invalid:{model_id}")
        if entry.speed_tier not in _TIER_OPTIONS:
            raise ValueError(f"classification_speed_tier_invalid:{model_id}")
        if entry.cost_tier not in _TIER_OPTIONS:
            raise ValueError(f"classification_cost_tier_invalid:{model_id}")
        invalid_recommended = [value for value in entry.recommended_for if value not in RECOMMENDED_FOR_OPTIONS]
        if invalid_recommended:
            raise ValueError(f"classification_recommended_for_invalid:{model_id}")
        validated.append(entry)
        seen.add(model_id)
    if seen != set(expected_map):
        raise ValueError("classification_models_incomplete")
    validated.sort(key=lambda item: item.model_id)
    return validated


class ProviderModelCapabilitiesStore:
    def __init__(self, *, path: str = DEFAULT_PROVIDER_MODEL_CAPABILITIES_PATH, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def load(self) -> ProviderModelCapabilitiesSnapshot | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return ProviderModelCapabilitiesSnapshot.model_validate(payload)
        except Exception:
            return None

    def payload(self) -> dict:
        snapshot = self.load()
        if snapshot is None:
            return {
                "provider_id": "openai",
                "classification_model": None,
                "generated_at": _iso_now(),
                "entries": [],
                "source": "provider_model_capabilities",
            }
        return {
            "provider_id": snapshot.provider_id,
            "classification_model": snapshot.classification_model,
            "generated_at": snapshot.updated_at,
            "entries": [entry.model_dump() for entry in snapshot.entries],
            "source": "provider_model_capabilities",
        }

    def save(self, *, classification_model: str | None, entries: list[ProviderModelCapabilityEntry]) -> ProviderModelCapabilitiesSnapshot:
        snapshot = ProviderModelCapabilitiesSnapshot(
            classification_model=_normalize_string(classification_model) or None,
            updated_at=_iso_now(),
            entries=entries,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(snapshot.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[provider-model-capabilities-saved] %s",
                {"path": str(self._path), "entries": len(entries), "classification_model": snapshot.classification_model},
            )
        return snapshot


class OpenAIModelCapabilityClassifier:
    def __init__(
        self,
        *,
        logger,
        store: ProviderModelCapabilitiesStore,
        execute_batch: Callable[[str, str, str], Awaitable[str]],
    ) -> None:
        self._logger = logger
        self._store = store
        self._execute_batch = execute_batch

    async def classify_and_save(self, *, models: list[OpenAIProviderModelCatalogEntry]) -> ProviderModelCapabilitiesSnapshot | None:
        classification_model = select_openai_classification_model(models)
        if classification_model is None:
            return self._store.save(classification_model=None, entries=[])
        system_prompt, user_prompt = build_openai_capability_classification_prompt(
            models=models,
            classification_model=classification_model,
        )
        raw_output = await self._execute_batch(classification_model, system_prompt, user_prompt)
        parsed = json.loads(_strip_json_fence(raw_output))
        validated = validate_provider_model_capability_payload(payload=parsed, expected_models=models)
        return self._store.save(classification_model=classification_model, entries=validated)
