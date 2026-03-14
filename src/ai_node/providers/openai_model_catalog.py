import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from ai_node.providers.openai_catalog import is_openai_date_versioned_model_id


OPENAI_PROVIDER_MODEL_CATALOG_SCHEMA_VERSION = "1.0"
DEFAULT_OPENAI_PROVIDER_MODEL_CATALOG_PATH = "data/provider_models.json"
_PREVIEW_TAGS = ("preview", "latest")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


class OpenAIProviderModelCatalogEntry(BaseModel):
    model_id: str
    family: str
    discovered_at: str
    enabled: bool = False


class OpenAIProviderModelCatalogSnapshot(BaseModel):
    schema_version: str = OPENAI_PROVIDER_MODEL_CATALOG_SCHEMA_VERSION
    provider_id: str = "openai"
    updated_at: str = Field(default_factory=_iso_now)
    models: list[OpenAIProviderModelCatalogEntry] = Field(default_factory=list)


def _is_filtered_out(model_id: str) -> bool:
    normalized = _normalize_string(model_id).lower()
    if not normalized:
        return True
    if normalized.startswith("omni-moderation-"):
        return any(tag in normalized for tag in _PREVIEW_TAGS)
    if is_openai_date_versioned_model_id(normalized):
        return True
    return any(tag in normalized for tag in _PREVIEW_TAGS)


def classify_openai_model_family(model_id: str) -> str | None:
    normalized = _normalize_string(model_id).lower()
    if _is_filtered_out(normalized):
        return None
    if re.fullmatch(r"gpt-\d+(?:\.\d+)?(?:-(?:pro|mini|nano))?", normalized):
        return "llm"
    if re.fullmatch(r"gpt-image-[a-z0-9.-]+(?:-mini)?", normalized):
        return "image_generation"
    if re.fullmatch(r"sora-[a-z0-9.-]+", normalized):
        return "video_generation"
    if re.fullmatch(r"gpt-realtime-[a-z0-9.-]+", normalized):
        return "realtime_voice"
    if re.fullmatch(r"whisper-[a-z0-9.-]+", normalized):
        return "speech_to_text"
    if re.fullmatch(r"tts(?:-hd)?-[a-z0-9.-]+", normalized):
        return "text_to_speech"
    if re.fullmatch(r"text-embedding-[a-z0-9.-]+-small", normalized):
        return "embeddings"
    if re.fullmatch(r"omni-moderation-[a-z0-9.-]+", normalized):
        return "moderation"
    return None


def build_openai_provider_model_catalog(*, model_ids: list[str], existing_snapshot: OpenAIProviderModelCatalogSnapshot | None = None) -> OpenAIProviderModelCatalogSnapshot:
    existing_by_id = {}
    if existing_snapshot is not None:
        existing_by_id = {entry.model_id: entry for entry in existing_snapshot.models}
    discovered_at = _iso_now()
    entries: list[OpenAIProviderModelCatalogEntry] = []
    seen: set[str] = set()
    for model_id in model_ids:
        normalized = _normalize_string(model_id).lower()
        family = classify_openai_model_family(normalized)
        if family is None or normalized in seen:
            continue
        seen.add(normalized)
        existing = existing_by_id.get(normalized)
        entries.append(
            OpenAIProviderModelCatalogEntry(
                model_id=normalized,
                family=family,
                discovered_at=existing.discovered_at if existing is not None else discovered_at,
                enabled=bool(existing.enabled) if existing is not None else False,
            )
        )
    entries.sort(key=lambda item: (item.family, item.model_id))
    return OpenAIProviderModelCatalogSnapshot(updated_at=discovered_at, models=entries)


class OpenAIProviderModelCatalogStore:
    def __init__(self, *, path: str = DEFAULT_OPENAI_PROVIDER_MODEL_CATALOG_PATH, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def load(self) -> OpenAIProviderModelCatalogSnapshot | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return OpenAIProviderModelCatalogSnapshot.model_validate(payload)
        except Exception:
            return None

    def save_from_model_ids(self, *, model_ids: list[str]) -> OpenAIProviderModelCatalogSnapshot:
        snapshot = build_openai_provider_model_catalog(model_ids=model_ids, existing_snapshot=self.load())
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(snapshot.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
        if hasattr(self._logger, "info"):
            self._logger.info("[openai-provider-model-catalog-saved] %s", {"path": str(self._path), "count": len(snapshot.models)})
        return snapshot
