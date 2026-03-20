import hashlib
import json
import os
import re
import time
from datetime import datetime
from statistics import mean

import httpx

from ai_node.config.provider_credentials_config import ProviderCredentialsStore
from ai_node.providers.openai_catalog import get_openai_model_pricing
from ai_node.time_utils import local_now, local_now_iso


PROVIDER_INTELLIGENCE_SCHEMA_VERSION = "1.0"
DEFAULT_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS = 4 * 60 * 60
_LATENCY_SAMPLE_WINDOW = 20


def _iso_now() -> str:
    return local_now_iso()


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if _is_non_empty_string(item):
            normalized.append(str(item).strip())
    return sorted(set(normalized))


def _extract_enabled_providers(provider_selection_config: dict | None) -> list[str]:
    if not isinstance(provider_selection_config, dict):
        return []
    providers = provider_selection_config.get("providers")
    if not isinstance(providers, dict):
        return []
    return _normalize_string_list(providers.get("enabled"))


def _normalize_model_identifier(provider: str, model_id: str) -> str:
    normalized_provider = re.sub(r"[^a-z0-9]+", "-", provider.strip().lower()).strip("-")
    normalized_model = re.sub(r"[^a-z0-9._/-]+", "-", model_id.strip().lower()).strip("-")
    return f"{normalized_provider}:{normalized_model}" if normalized_provider and normalized_model else ""


def _extract_context_window(model: dict) -> int | None:
    for key in ("context_window", "context_length", "input_token_limit", "max_input_tokens", "max_context_tokens"):
        value = model.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _extract_modalities(model: dict) -> list[str]:
    modalities = []
    if isinstance(model.get("modalities"), list):
        modalities.extend([str(item).strip().lower() for item in model.get("modalities") if _is_non_empty_string(item)])
    if isinstance(model.get("input_modalities"), list):
        modalities.extend(
            [str(item).strip().lower() for item in model.get("input_modalities") if _is_non_empty_string(item)]
        )
    if isinstance(model.get("output_modalities"), list):
        modalities.extend(
            [str(item).strip().lower() for item in model.get("output_modalities") if _is_non_empty_string(item)]
        )
    return sorted(set(modalities))


def _extract_pricing(model: dict) -> dict | None:
    pricing = model.get("pricing")
    if isinstance(pricing, dict):
        return {
            "currency": str(pricing.get("currency") or "usd").strip().lower(),
            "input_per_1m_tokens": pricing.get("input_per_1m_tokens"),
            "output_per_1m_tokens": pricing.get("output_per_1m_tokens"),
        }
    return None


def _normalize_model_entry(provider: str, model: dict) -> dict | None:
    model_id = str(model.get("id") or "").strip()
    if not model_id:
        return None
    pricing = _extract_pricing(model)
    if pricing is None and provider == "openai":
        pricing = get_openai_model_pricing(model_id)
    return {
        "id": model_id,
        "normalized_id": _normalize_model_identifier(provider, model_id),
        "created": model.get("created") if isinstance(model.get("created"), int) else None,
        "context_window": _extract_context_window(model),
        "modalities": _extract_modalities(model),
        "pricing": pricing,
    }


def _compute_latency_metrics(samples: list[dict]) -> dict:
    if not isinstance(samples, list):
        samples = []
    normalized_samples = [item for item in samples if isinstance(item, dict)]
    successes = [item for item in normalized_samples if bool(item.get("success"))]
    success_durations = [float(item.get("duration_ms")) for item in successes if isinstance(item.get("duration_ms"), (int, float))]
    all_success_flags = [bool(item.get("success")) for item in normalized_samples]

    if success_durations:
        sorted_values = sorted(success_durations)
        p95_index = max(0, int(round(0.95 * len(sorted_values))) - 1)
        average_ms = round(float(mean(sorted_values)), 3)
        p95_ms = round(float(sorted_values[p95_index]), 3)
        last_ms = round(float(sorted_values[-1]), 3)
    else:
        average_ms = None
        p95_ms = None
        last_ms = None

    success_rate = 0.0
    if all_success_flags:
        success_rate = round(sum(1 for item in all_success_flags if item) / len(all_success_flags), 4)

    return {
        "sample_count": len(normalized_samples),
        "average_ms": average_ms,
        "p95_ms": p95_ms,
        "success_rate": success_rate,
        "last_ms": last_ms,
        "last_checked_at": _iso_now(),
    }


def _fingerprint_provider_payload(report: dict) -> str:
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProviderDiscoveryAdapter:
    async def fetch_openai_models(self, *, api_key: str, base_url: str) -> tuple[list[dict], dict]:
        url = f"{base_url.rstrip('/')}/models"
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        if response.status_code >= 400:
            detail = response.text.strip() or f"http_{response.status_code}"
            raise RuntimeError(detail)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("provider_models_response_not_object")
        models = payload.get("data")
        if not isinstance(models, list):
            models = []
        return models, {"success": True, "duration_ms": elapsed_ms, "timestamp": _iso_now()}


class ProviderIntelligenceService:
    def __init__(
        self,
        *,
        logger,
        cache_store=None,
        adapter=None,
        provider_credentials_store: ProviderCredentialsStore | None = None,
        refresh_interval_seconds: int = DEFAULT_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        self._logger = logger
        self._cache_store = cache_store
        self._adapter = adapter or ProviderDiscoveryAdapter()
        self._provider_credentials_store = provider_credentials_store
        self._refresh_interval_seconds = int(refresh_interval_seconds)
        if self._refresh_interval_seconds <= 0:
            self._refresh_interval_seconds = DEFAULT_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS

    async def build_provider_capability_report(
        self,
        *,
        provider_selection_config: dict | None,
        force_refresh: bool = False,
    ) -> tuple[dict, bool]:
        enabled_providers = _extract_enabled_providers(provider_selection_config)
        cached = self._cache_store.load() if self._cache_store is not None and hasattr(self._cache_store, "load") else None
        if (
            not force_refresh
            and isinstance(cached, dict)
            and self._is_cache_fresh(cached)
            and _normalize_string_list(cached.get("enabled_providers")) == enabled_providers
        ):
            return cached, False

        cached_providers = {}
        if isinstance(cached, dict):
            for provider_payload in cached.get("providers") or []:
                if isinstance(provider_payload, dict) and _is_non_empty_string(provider_payload.get("provider")):
                    cached_providers[str(provider_payload.get("provider")).strip()] = provider_payload

        providers = []
        for provider in enabled_providers:
            previous = cached_providers.get(provider)
            if provider == "openai":
                providers.append(await self._discover_openai(previous))
                continue
            providers.append(
                self._unsupported_provider_payload(
                    provider=provider,
                    previous=previous,
                    error="provider_discovery_not_implemented",
                )
            )

        report = {
            "schema_version": PROVIDER_INTELLIGENCE_SCHEMA_VERSION,
            "report_version": "1.0",
            "generated_at": _iso_now(),
            "refresh_interval_seconds": self._refresh_interval_seconds,
            "enabled_providers": enabled_providers,
            "providers": providers,
        }
        compact = compact_provider_intelligence_report(report)
        report["fingerprint"] = _fingerprint_provider_payload(compact)
        if self._cache_store is not None and hasattr(self._cache_store, "save"):
            self._cache_store.save(report)
        return report, True

    def _is_cache_fresh(self, payload: dict) -> bool:
        generated_at = str(payload.get("generated_at") or "").strip()
        if not generated_at:
            return False
        try:
            generated_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except Exception:
            return False
        age_seconds = (local_now() - generated_time).total_seconds()
        return age_seconds < self._refresh_interval_seconds

    async def _discover_openai(self, previous: dict | None) -> dict:
        api_key = self._resolve_openai_api_key()
        base_url = str(os.environ.get("SYNTHIA_OPENAI_BASE_URL") or "https://api.openai.com/v1").strip()
        if not api_key:
            return self._unsupported_provider_payload(
                provider="openai",
                previous=previous,
                error="missing_openai_api_key",
            )
        try:
            models, latency_sample = await self._adapter.fetch_openai_models(api_key=api_key, base_url=base_url)
            normalized_models = []
            for item in models:
                if not isinstance(item, dict):
                    continue
                normalized = _normalize_model_entry("openai", item)
                if normalized is not None:
                    normalized_models.append(normalized)
            normalized_models.sort(
                key=lambda item: (int(item.get("created") or 0), str(item.get("id") or "")),
                reverse=True,
            )
            samples = self._merge_latency_samples(previous=previous, new_sample=latency_sample)
            return {
                "provider": "openai",
                "status": "available",
                "discovery_source": "provider_api",
                "models": normalized_models,
                "latency": _compute_latency_metrics(samples),
                "_latency_samples": samples,
                "last_error": None,
            }
        except Exception as exc:
            samples = self._merge_latency_samples(
                previous=previous,
                new_sample={"success": False, "duration_ms": None, "timestamp": _iso_now()},
            )
            return {
                "provider": "openai",
                "status": "degraded",
                "discovery_source": "provider_api",
                "models": [],
                "latency": _compute_latency_metrics(samples),
                "_latency_samples": samples,
                "last_error": str(exc).strip() or type(exc).__name__,
            }

    @staticmethod
    def _merge_latency_samples(*, previous: dict | None, new_sample: dict) -> list[dict]:
        samples = []
        if isinstance(previous, dict) and isinstance(previous.get("_latency_samples"), list):
            samples.extend([item for item in previous.get("_latency_samples") if isinstance(item, dict)])
        samples.append(new_sample)
        return samples[-_LATENCY_SAMPLE_WINDOW:]

    def _unsupported_provider_payload(self, *, provider: str, previous: dict | None, error: str) -> dict:
        samples = self._merge_latency_samples(
            previous=previous,
            new_sample={"success": False, "duration_ms": None, "timestamp": _iso_now()},
        )
        return {
            "provider": provider,
            "status": "unavailable",
            "discovery_source": "none",
            "models": [],
            "latency": _compute_latency_metrics(samples),
            "_latency_samples": samples,
            "last_error": error,
        }

    def _resolve_openai_api_key(self) -> str:
        env_value = str(os.environ.get("OPENAI_API_KEY") or "").strip()
        if env_value:
            return env_value
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "load"):
            return ""
        payload = self._provider_credentials_store.load()
        if not isinstance(payload, dict):
            return ""
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return ""
        openai_payload = providers.get("openai")
        if not isinstance(openai_payload, dict):
            return ""
        return str(openai_payload.get("api_token") or openai_payload.get("api_key") or "").strip()


def compact_provider_intelligence_report(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {
            "schema_version": PROVIDER_INTELLIGENCE_SCHEMA_VERSION,
            "report_version": "1.0",
            "generated_at": _iso_now(),
            "enabled_providers": [],
            "providers": [],
        }
    compact_providers = []
    for provider_payload in payload.get("providers") or []:
        if not isinstance(provider_payload, dict):
            continue
        compact_providers.append(
            {
                "provider": str(provider_payload.get("provider") or "").strip(),
                "status": str(provider_payload.get("status") or "").strip(),
                "discovery_source": str(provider_payload.get("discovery_source") or "").strip(),
                "models": provider_payload.get("models") if isinstance(provider_payload.get("models"), list) else [],
                "latency": provider_payload.get("latency") if isinstance(provider_payload.get("latency"), dict) else {},
                "last_error": str(provider_payload.get("last_error") or "").strip() or None,
            }
        )
    return {
        "schema_version": str(payload.get("schema_version") or PROVIDER_INTELLIGENCE_SCHEMA_VERSION).strip(),
        "report_version": str(payload.get("report_version") or "1.0").strip(),
        "generated_at": str(payload.get("generated_at") or _iso_now()).strip(),
        "enabled_providers": _normalize_string_list(payload.get("enabled_providers")),
        "providers": compact_providers,
        "fingerprint": str(payload.get("fingerprint") or "").strip() or _fingerprint_provider_payload(
            {
                "enabled_providers": _normalize_string_list(payload.get("enabled_providers")),
                "providers": compact_providers,
            }
        ),
    }
