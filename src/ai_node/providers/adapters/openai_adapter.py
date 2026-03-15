import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ai_node.providers.base import ProviderAdapter
from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.providers.openai_catalog import OpenAIPricingCatalogService, get_openai_model_pricing


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenAIProviderAdapter(ProviderAdapter):
    provider_id = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        default_model_id: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 20.0,
        pricing_catalog_service: OpenAIPricingCatalogService | None = None,
    ) -> None:
        self._api_key = str(api_key or "").strip()
        self._default_model_id = str(default_model_id or "").strip() or "gpt-4o-mini"
        self._base_url = str(base_url or "https://api.openai.com/v1").rstrip("/")
        self._timeout_seconds = float(timeout_seconds)
        self._pricing_catalog_service = pricing_catalog_service
        self._metrics = {
            "health": {"reachable": False, "auth_valid": False, "last_successful_check": None, "last_error": None},
            "calls": 0,
            "failures": 0,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def health_check(self) -> dict[str, Any]:
        if not self._api_key:
            self._metrics["health"] = {
                "reachable": False,
                "auth_valid": False,
                "last_successful_check": self._metrics["health"].get("last_successful_check"),
                "last_error": "missing_api_key",
            }
            return {"provider_id": self.provider_id, "availability": "unavailable", **self._metrics["health"]}

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(f"{self._base_url}/models", headers=self._headers())
            if response.status_code == 401:
                self._metrics["health"] = {
                    "reachable": True,
                    "auth_valid": False,
                    "last_successful_check": self._metrics["health"].get("last_successful_check"),
                    "last_error": "invalid_auth",
                }
                return {"provider_id": self.provider_id, "availability": "degraded", **self._metrics["health"]}
            if response.status_code >= 400:
                self._metrics["health"] = {
                    "reachable": False,
                    "auth_valid": True,
                    "last_successful_check": self._metrics["health"].get("last_successful_check"),
                    "last_error": f"http_{response.status_code}",
                }
                return {"provider_id": self.provider_id, "availability": "degraded", **self._metrics["health"]}
            self._metrics["health"] = {
                "reachable": True,
                "auth_valid": True,
                "last_successful_check": _iso_now(),
                "last_error": None,
            }
            return {"provider_id": self.provider_id, "availability": "available", **self._metrics["health"]}
        except Exception as exc:
            self._metrics["health"] = {
                "reachable": False,
                "auth_valid": bool(self._api_key),
                "last_successful_check": self._metrics["health"].get("last_successful_check"),
                "last_error": str(exc),
            }
            return {"provider_id": self.provider_id, "availability": "unavailable", **self._metrics["health"]}

    async def list_models(self) -> list[ModelCapability]:
        if not self._api_key:
            return []
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(f"{self._base_url}/models", headers=self._headers())
        if response.status_code >= 400:
            return []
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        models = payload.get("data") if isinstance(payload, dict) else []
        out: list[ModelCapability] = []
        if not isinstance(models, list):
            return out
        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            out.append(
                ModelCapability(
                    model_id=model_id,
                    display_name=model_id,
                    created=int(model.get("created")) if isinstance(model.get("created"), int) else None,
                    input_modalities=["text"],
                    output_modalities=["text"],
                    context_window=None,
                    max_output_tokens=None,
                    supports_streaming=True,
                    supports_tools=False,
                    supports_vision=("vision" in model_id or "gpt-4o" in model_id),
                    supports_json_mode=True,
                    pricing_status="unknown",
                    status="available",
                )
            )
        if self._pricing_catalog_service is None:
            return out
        merged, unknown_models = self._pricing_catalog_service.merge_model_capabilities(out)
        if unknown_models and hasattr(self._logger if hasattr(self, "_logger") else None, "warning"):
            self._logger.warning("[openai-pricing-unknown-models] %s", {"models": unknown_models})
        return merged

    async def get_model_capabilities(self, model_id: str) -> ModelCapability | None:
        model_value = str(model_id or "").strip()
        if not model_value:
            return None
        models = await self.list_models()
        for item in models:
            if item.model_id == model_value:
                return item
        return None

    async def execute_prompt(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        started = time.perf_counter()
        model = str(request.requested_model or "").strip() or self._default_model_id
        # Classification calls are batch-oriented and often exceed the regular request timeout.
        request_timeout = max(self._timeout_seconds, 90.0) if request.task_family == "task.classification.text" else self._timeout_seconds
        messages = list(request.messages or [])
        if not messages:
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            if request.prompt:
                messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        try:
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                response = await client.post(f"{self._base_url}/chat/completions", headers=self._headers(), json=payload)
            self._metrics["calls"] += 1
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            if response.status_code >= 400:
                self._metrics["failures"] += 1
                error_detail = data.get("error") if isinstance(data, dict) else None
                message = str(error_detail or f"http_{response.status_code}")
                raise RuntimeError(message)

            choices = data.get("choices") if isinstance(data, dict) else []
            first = choices[0] if isinstance(choices, list) and choices else {}
            msg = first.get("message") if isinstance(first, dict) else {}
            usage_raw = data.get("usage") if isinstance(data, dict) else {}
            usage = UnifiedExecutionUsage(
                prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
                completion_tokens=int(usage_raw.get("completion_tokens") or 0),
                total_tokens=int(usage_raw.get("total_tokens") or 0),
            )
            estimated_cost = self.estimate_cost(
                model_id=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            )
            latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            return UnifiedExecutionResponse(
                provider_id=self.provider_id,
                model_id=model,
                output_text=str(msg.get("content") or ""),
                finish_reason=str(first.get("finish_reason") or "").strip() or None,
                usage=usage,
                latency_ms=latency_ms,
                estimated_cost=estimated_cost,
                raw_provider_response_ref=f"openai:{data.get('id') or _iso_now()}",
            )
        except Exception as exc:
            self._metrics["calls"] += 1
            self._metrics["failures"] += 1
            raise RuntimeError(str(exc).strip() or "openai_execute_failed") from exc

    def estimate_cost(self, *, model_id: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        pricing = get_openai_model_pricing(model_id, pricing_service=self._pricing_catalog_service)
        if not isinstance(pricing, dict):
            return None
        if str(pricing.get("pricing_status") or "").strip() not in {"ok", "manual"}:
            return None
        in_rate = pricing.get("input_per_1m_tokens")
        out_rate = pricing.get("output_per_1m_tokens")
        if not isinstance(in_rate, (int, float)) or not isinstance(out_rate, (int, float)):
            return None
        estimated = ((prompt_tokens / 1_000_000.0) * in_rate) + ((completion_tokens / 1_000_000.0) * out_rate)
        return round(estimated, 8)

    def collect_metrics(self) -> dict[str, Any]:
        calls = int(self._metrics.get("calls") or 0)
        failures = int(self._metrics.get("failures") or 0)
        successes = max(calls - failures, 0)
        return {
            "provider_id": self.provider_id,
            "total_requests": calls,
            "successful_requests": successes,
            "failed_requests": failures,
            "success_rate": round((successes / calls), 4) if calls else 0.0,
            "health": dict(self._metrics.get("health") or {}),
        }
