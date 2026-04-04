import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _ModelMetricState:
    latency_samples_ms: deque[float] = field(default_factory=lambda: deque(maxlen=50))
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    failure_classes: dict[str, int] = field(default_factory=dict)
    prompt_tokens: int = 0
    cached_input_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0


class ProviderMetricsCollector:
    def __init__(self, *, metrics_path: str, logger) -> None:
        self._path = Path(metrics_path)
        self._logger = logger
        self._state: dict[str, dict[str, _ModelMetricState]] = {}
        loaded = self.load()
        if isinstance(loaded, dict):
            self._hydrate(loaded)

    def record_success(
        self,
        *,
        provider_id: str,
        model_id: str,
        latency_ms: float,
        prompt_tokens: int,
        cached_input_tokens: int,
        completion_tokens: int,
        estimated_cost: float | None,
    ) -> None:
        state = self._ensure_model_state(provider_id=provider_id, model_id=model_id)
        state.total_requests += 1
        state.successful_requests += 1
        state.latency_samples_ms.append(max(float(latency_ms), 0.0))
        state.prompt_tokens += max(int(prompt_tokens), 0)
        state.cached_input_tokens += max(int(cached_input_tokens), 0)
        state.completion_tokens += max(int(completion_tokens), 0)
        state.total_tokens += max(int(prompt_tokens) + int(completion_tokens), 0)
        state.estimated_cost += max(float(estimated_cost or 0.0), 0.0)

    def record_failure(self, *, provider_id: str, model_id: str, error_class: str) -> None:
        state = self._ensure_model_state(provider_id=provider_id, model_id=model_id)
        state.total_requests += 1
        state.failed_requests += 1
        key = str(error_class or "unknown_error").strip() or "unknown_error"
        state.failure_classes[key] = state.failure_classes.get(key, 0) + 1

    def snapshot(self) -> dict:
        providers: dict[str, dict] = {}
        for provider_id, models in self._state.items():
            provider_payload = {"models": {}, "totals": {}}
            provider_success = 0
            provider_total = 0
            for model_id, state in models.items():
                provider_total += state.total_requests
                provider_success += state.successful_requests
                provider_payload["models"][model_id] = self._model_snapshot(state)
            provider_payload["totals"] = {
                "total_requests": provider_total,
                "successful_requests": provider_success,
                "failed_requests": provider_total - provider_success,
                "success_rate": round((provider_success / provider_total), 4) if provider_total else 0.0,
            }
            providers[provider_id] = provider_payload
        return {"providers": providers}

    def persist(self) -> None:
        payload = self.snapshot()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[provider-metrics-persisted] %s", {"path": str(self._path)})

    def load(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _hydrate(self, payload: dict) -> None:
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return
        for provider_id, provider_payload in providers.items():
            if not isinstance(provider_payload, dict):
                continue
            models = provider_payload.get("models")
            if not isinstance(models, dict):
                continue
            for model_id, model_payload in models.items():
                if not isinstance(model_payload, dict):
                    continue
                state = self._ensure_model_state(provider_id=str(provider_id), model_id=str(model_id))
                samples = model_payload.get("recent_rolling_samples")
                if isinstance(samples, list):
                    for value in samples:
                        if isinstance(value, (int, float)):
                            state.latency_samples_ms.append(float(value))
                state.total_requests = int(model_payload.get("total_requests") or 0)
                state.successful_requests = int(model_payload.get("successful_requests") or 0)
                state.failed_requests = int(model_payload.get("failed_requests") or 0)
                failures = model_payload.get("failure_classes")
                state.failure_classes = failures if isinstance(failures, dict) else {}
                state.prompt_tokens = int(model_payload.get("prompt_tokens") or 0)
                state.cached_input_tokens = int(model_payload.get("cached_input_tokens") or 0)
                state.completion_tokens = int(model_payload.get("completion_tokens") or 0)
                state.total_tokens = int(model_payload.get("total_tokens") or 0)
                state.estimated_cost = float(model_payload.get("estimated_cost") or 0.0)

    def _ensure_model_state(self, *, provider_id: str, model_id: str) -> _ModelMetricState:
        pid = str(provider_id or "").strip() or "unknown"
        mid = str(model_id or "").strip() or "unknown"
        provider_state = self._state.setdefault(pid, {})
        return provider_state.setdefault(mid, _ModelMetricState())

    @staticmethod
    def _model_snapshot(state: _ModelMetricState) -> dict:
        samples = sorted(float(item) for item in list(state.latency_samples_ms))
        p95 = None
        avg = None
        if samples:
            avg = round(sum(samples) / len(samples), 3)
            index = max(0, int(math.ceil(len(samples) * 0.95)) - 1)
            p95 = round(samples[index], 3)
        success_rate = round((state.successful_requests / state.total_requests), 4) if state.total_requests else 0.0
        return {
            "avg_latency": avg,
            "p95_latency": p95,
            "execution_count": state.total_requests,
            "recent_rolling_samples": [round(item, 3) for item in list(state.latency_samples_ms)],
            "total_requests": state.total_requests,
            "successful_requests": state.successful_requests,
            "failed_requests": state.failed_requests,
            "failure_classes": dict(state.failure_classes),
            "success_rate": success_rate,
            "prompt_tokens": state.prompt_tokens,
            "cached_input_tokens": state.cached_input_tokens,
            "completion_tokens": state.completion_tokens,
            "total_tokens": state.total_tokens,
            "estimated_cost": round(state.estimated_cost, 8),
            "cumulative_spend": round(state.estimated_cost, 8),
        }
