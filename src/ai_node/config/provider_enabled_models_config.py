import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


PROVIDER_ENABLED_MODELS_SCHEMA_VERSION = "1.0"
DEFAULT_PROVIDER_ENABLED_MODELS_PATH = "data/provider_enabled_models.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


class ProviderEnabledModelEntry(BaseModel):
    model_id: str
    enabled: bool = True
    selected_at: str


class ProviderEnabledModelsSnapshot(BaseModel):
    schema_version: str = PROVIDER_ENABLED_MODELS_SCHEMA_VERSION
    provider_id: str = "openai"
    updated_at: str = Field(default_factory=_iso_now)
    models: list[ProviderEnabledModelEntry] = Field(default_factory=list)


class ProviderEnabledModelsStore:
    def __init__(self, *, path: str = DEFAULT_PROVIDER_ENABLED_MODELS_PATH, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def load(self) -> ProviderEnabledModelsSnapshot | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return ProviderEnabledModelsSnapshot.model_validate(payload)
        except Exception:
            return None

    def payload(self) -> dict:
        snapshot = self.load()
        if snapshot is None:
            return {
                "provider_id": "openai",
                "models": [],
                "generated_at": _iso_now(),
                "source": "provider_enabled_models",
            }
        return {
            "provider_id": snapshot.provider_id,
            "models": [entry.model_dump() for entry in snapshot.models],
            "generated_at": snapshot.updated_at,
            "source": "provider_enabled_models",
        }

    def save_enabled_model_ids(self, *, model_ids: list[str]) -> ProviderEnabledModelsSnapshot:
        now = _iso_now()
        normalized_ids: list[str] = []
        for model_id in model_ids:
            normalized = _normalize_string(model_id).lower()
            if normalized and normalized not in normalized_ids:
                normalized_ids.append(normalized)
        existing = self.load()
        existing_map = {entry.model_id: entry for entry in (existing.models if existing is not None else [])}
        entries = [
            ProviderEnabledModelEntry(
                model_id=model_id,
                enabled=True,
                selected_at=(existing_map.get(model_id).selected_at if existing_map.get(model_id) is not None else now),
            )
            for model_id in normalized_ids
        ]
        snapshot = ProviderEnabledModelsSnapshot(updated_at=now, models=entries)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(snapshot.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
        if hasattr(self._logger, "info"):
            self._logger.info("[provider-enabled-models-saved] %s", {"path": str(self._path), "count": len(entries)})
        return snapshot
