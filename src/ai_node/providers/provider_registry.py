import json
from pathlib import Path

from ai_node.providers.base import ProviderAdapter
from ai_node.providers.models import ModelCapability


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderAdapter] = {}
        self._models_by_provider: dict[str, list[ModelCapability]] = {}
        self._health: dict[str, dict] = {}

    def register_provider(self, *, provider_id: str, adapter: ProviderAdapter) -> None:
        key = str(provider_id or "").strip()
        if not key:
            raise ValueError("provider_id is required")
        self._providers[key] = adapter

    def list_providers(self) -> list[str]:
        return sorted(self._providers.keys())

    def get_provider(self, provider_id: str) -> ProviderAdapter | None:
        key = str(provider_id or "").strip()
        return self._providers.get(key)

    def set_provider_health(self, *, provider_id: str, payload: dict) -> None:
        self._health[str(provider_id).strip()] = payload if isinstance(payload, dict) else {}

    def get_provider_health(self, provider_id: str) -> dict | None:
        return self._health.get(str(provider_id or "").strip())

    def set_models_for_provider(self, *, provider_id: str, models: list[ModelCapability]) -> None:
        self._models_by_provider[str(provider_id).strip()] = list(models or [])

    def list_models_by_provider(self, provider_id: str) -> list[ModelCapability]:
        return list(self._models_by_provider.get(str(provider_id or "").strip()) or [])

    def get_model(self, *, provider_id: str, model_id: str) -> ModelCapability | None:
        pid = str(provider_id or "").strip()
        mid = str(model_id or "").strip()
        if not pid or not mid:
            return None
        for model in self._models_by_provider.get(pid) or []:
            if model.model_id == mid:
                return model
        return None

    def snapshot(self) -> dict:
        providers: list[dict] = []
        for provider_id in self.list_providers():
            providers.append(
                {
                    "provider_id": provider_id,
                    "availability": str((self.get_provider_health(provider_id) or {}).get("availability") or "unavailable"),
                    "health": self.get_provider_health(provider_id) or {},
                    "models": [model.model_dump() for model in self.list_models_by_provider(provider_id)],
                }
            )
        return {"providers": providers}

    def persist(self, *, path: str) -> None:
        payload = self.snapshot()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f"{target.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(target)

    def load(self, *, path: str) -> dict | None:
        target = Path(path)
        if not target.exists():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        providers = payload.get("providers")
        if not isinstance(providers, list):
            return payload
        for entry in providers:
            if not isinstance(entry, dict):
                continue
            provider_id = str(entry.get("provider_id") or "").strip()
            if not provider_id:
                continue
            self._health[provider_id] = entry.get("health") if isinstance(entry.get("health"), dict) else {}
            models = []
            for item in entry.get("models") or []:
                if not isinstance(item, dict):
                    continue
                try:
                    models.append(ModelCapability.model_validate(item))
                except Exception:
                    continue
            self._models_by_provider[provider_id] = models
        return payload
