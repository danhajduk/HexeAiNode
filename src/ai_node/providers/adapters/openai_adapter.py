import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ai_node.providers.base import ProviderAdapter
from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage
from ai_node.providers.openai_catalog import OpenAIPricingCatalogService, get_openai_model_pricing
from ai_node.capabilities.task_families import TASK_CLASSIFICATION, TASK_CLASSIFICATION_TEXT


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
        debug_aopenai: bool = False,
        debug_aopenai_log_path: str | None = None,
        timeout_seconds: float = 20.0,
        pricing_catalog_service: OpenAIPricingCatalogService | None = None,
    ) -> None:
        self._api_key = str(api_key or "").strip()
        self._default_model_id = str(default_model_id or "").strip() or "gpt-4o-mini"
        self._base_url = str(base_url or "https://api.openai.com/v1").rstrip("/")
        self._debug_aopenai = bool(debug_aopenai)
        self._debug_aopenai_log_path = (
            Path(str(debug_aopenai_log_path).strip())
            if str(debug_aopenai_log_path or "").strip()
            else Path("logs/openai_debug.jsonl")
        )
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

    def _write_debug_aopenai_log(
        self,
        *,
        request: UnifiedExecutionRequest,
        url: str,
        request_headers: dict[str, str],
        request_payload: dict[str, Any],
        response_status: int | None = None,
        response_payload: Any = None,
        error: str | None = None,
    ) -> None:
        if not self._debug_aopenai:
            return
        redacted_headers = dict(request_headers)
        if "Authorization" in redacted_headers:
            redacted_headers["Authorization"] = "***REDACTED***"
        record = {
            "recorded_at": _iso_now(),
            "provider_id": self.provider_id,
            "task_family": request.task_family,
            "prompt_id": str((request.metadata or {}).get("prompt_id") or "").strip() or None,
            "prompt_version": str((request.metadata or {}).get("prompt_version") or "").strip() or None,
            "requested_model": str(request.requested_model or "").strip() or None,
            "url": url,
            "request_headers": redacted_headers,
            "request_payload": request_payload,
            "response_status": response_status,
            "response_payload": response_payload,
            "error": error,
        }
        self._debug_aopenai_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._debug_aopenai_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")

    @staticmethod
    def _structured_output_schema(request: UnifiedExecutionRequest) -> dict[str, Any] | None:
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        schema = metadata.get("structured_output_schema")
        return schema if isinstance(schema, dict) else None

    @classmethod
    def _response_format_payload(cls, request: UnifiedExecutionRequest) -> dict[str, Any] | None:
        schema = cls._structured_output_schema(request)
        if isinstance(schema, dict):
            prompt_id = str((request.metadata or {}).get("prompt_id") or "structured_output").strip().replace(".", "_")
            version = str((request.metadata or {}).get("prompt_version") or "").strip().replace(".", "_")
            schema_name = f"{prompt_id}_{version}" if version else prompt_id
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name[:64] or "structured_output",
                    "strict": True,
                    "schema": schema,
                },
            }
        if request.task_family in {TASK_CLASSIFICATION, TASK_CLASSIFICATION_TEXT}:
            return {"type": "json_object"}
        return None

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
        request_timeout = max(self._timeout_seconds, 90.0) if request.task_family in {TASK_CLASSIFICATION, TASK_CLASSIFICATION_TEXT} else self._timeout_seconds
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
        response_format = self._response_format_payload(request)
        if response_format is not None:
            payload["response_format"] = response_format
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        try:
            request_headers = self._headers()
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                url = f"{self._base_url}/chat/completions"
                response = await client.post(url, headers=request_headers, json=payload)
            self._metrics["calls"] += 1
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            self._write_debug_aopenai_log(
                request=request,
                url=url,
                request_headers=request_headers,
                request_payload=payload,
                response_status=response.status_code,
                response_payload=data,
            )
            if response.status_code >= 400:
                self._metrics["failures"] += 1
                error_detail = data.get("error") if isinstance(data, dict) else None
                message = str(error_detail or f"http_{response.status_code}")
                raise RuntimeError(message)

            choices = data.get("choices") if isinstance(data, dict) else []
            first = choices[0] if isinstance(choices, list) and choices else {}
            msg = first.get("message") if isinstance(first, dict) else {}
            usage_raw = data.get("usage") if isinstance(data, dict) else {}
            prompt_details = usage_raw.get("prompt_tokens_details") if isinstance(usage_raw, dict) else {}
            usage = UnifiedExecutionUsage(
                prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
                cached_input_tokens=int((prompt_details or {}).get("cached_tokens") or 0),
                completion_tokens=int(usage_raw.get("completion_tokens") or 0),
                total_tokens=int(usage_raw.get("total_tokens") or 0),
            )
            estimated_cost = self.estimate_cost(
                model_id=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cached_input_tokens=usage.cached_input_tokens,
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
            self._write_debug_aopenai_log(
                request=request,
                url=f"{self._base_url}/chat/completions",
                request_headers=self._headers(),
                request_payload=payload,
                error=str(exc).strip() or type(exc).__name__,
            )
            raise RuntimeError(str(exc).strip() or "openai_execute_failed") from exc

    def estimate_cost(
        self,
        *,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_input_tokens: int = 0,
    ) -> float | None:
        pricing = get_openai_model_pricing(model_id, pricing_service=self._pricing_catalog_service)
        if not isinstance(pricing, dict):
            return None
        if str(pricing.get("pricing_status") or "").strip() not in {"ok", "manual"}:
            return None
        in_rate = pricing.get("input_per_1m_tokens")
        cached_in_rate = pricing.get("cached_input_per_1m_tokens")
        out_rate = pricing.get("output_per_1m_tokens")
        if not isinstance(in_rate, (int, float)) or not isinstance(out_rate, (int, float)):
            return None
        total_input_tokens = max(int(prompt_tokens), 0)
        cached_tokens = max(min(int(cached_input_tokens), total_input_tokens), 0)
        uncached_tokens = max(total_input_tokens - cached_tokens, 0)
        estimated = (uncached_tokens * float(in_rate)) / 1_000_000.0
        if cached_tokens > 0 and isinstance(cached_in_rate, (int, float)):
            estimated += (cached_tokens * float(cached_in_rate)) / 1_000_000.0
        else:
            estimated += (cached_tokens * float(in_rate)) / 1_000_000.0
        estimated += (max(int(completion_tokens), 0) * float(out_rate)) / 1_000_000.0
        return estimated

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
