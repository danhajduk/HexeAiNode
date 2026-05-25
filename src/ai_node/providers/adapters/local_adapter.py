import time
from typing import Any

import httpx

from ai_node.providers.base import ProviderAdapter
from ai_node.providers.models import ModelCapability, UnifiedExecutionRequest, UnifiedExecutionResponse, UnifiedExecutionUsage


class LocalProviderAdapter(ProviderAdapter):
    provider_id = "local"

    def __init__(
        self,
        *,
        provider_id: str = "local",
        default_model_id: str | None = None,
        base_url: str = "http://127.0.0.1:8011/v1",
        transport: str = "socket",
        socket_path: str = "/run/hexe/ai-node/llamacpp.sock",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.provider_id = str(provider_id or "local").strip()
        self._default_model_id = str(default_model_id or "").strip() or "qwen3-14b-q4_k_m"
        self._base_url = str(base_url or "http://127.0.0.1:8011/v1").rstrip("/")
        self._transport = str(transport or "socket").strip().lower()
        self._socket_path = str(socket_path or "/run/hexe/ai-node/llamacpp.sock").strip()
        self._timeout_seconds = max(float(timeout_seconds), 1.0)
        self._metrics = {
            "health": {"reachable": False, "auth_valid": True, "last_successful_check": None, "last_error": None},
            "calls": 0,
            "failures": 0,
        }

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"timeout": self._timeout_seconds}
        if self._transport == "socket" and self._socket_path:
            kwargs["transport"] = httpx.AsyncHTTPTransport(uds=self._socket_path)
            kwargs["base_url"] = "http://llamacpp"
        return kwargs

    def _url(self, path: str) -> str:
        normalized_path = "/" + str(path or "").lstrip("/")
        if self._transport == "socket" and self._socket_path:
            return normalized_path
        return f"{self._base_url}{normalized_path}"

    def _v1_url(self, path: str) -> str:
        normalized_path = "/" + str(path or "").lstrip("/")
        if not normalized_path.startswith("/v1/") and normalized_path != "/v1":
            normalized_path = f"/v1{normalized_path}"
        if self._transport == "socket" and self._socket_path:
            return normalized_path
        base_url = self._base_url[:-3] if self._base_url.endswith("/v1") else self._base_url
        return f"{base_url}{normalized_path}"

    @staticmethod
    def _iso_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    async def health_check(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.get(self._v1_url("/models"))
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
                "last_successful_check": self._iso_now(),
                "last_error": None,
                "transport": self._transport,
                "socket_path": self._socket_path if self._transport == "socket" else None,
                "base_url": self._base_url if self._transport != "socket" else None,
            }
            return {"provider_id": self.provider_id, "availability": "available", **self._metrics["health"]}
        except Exception as exc:
            self._metrics["health"] = {
                "reachable": False,
                "auth_valid": True,
                "last_successful_check": self._metrics["health"].get("last_successful_check"),
                "last_error": str(exc).strip() or type(exc).__name__,
                "transport": self._transport,
                "socket_path": self._socket_path if self._transport == "socket" else None,
                "base_url": self._base_url if self._transport != "socket" else None,
            }
            return {"provider_id": self.provider_id, "availability": "unavailable", **self._metrics["health"]}

    async def list_models(self) -> list[ModelCapability]:
        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.get(self._v1_url("/models"))
        except Exception:
            return []
        if response.status_code >= 400:
            return []
        try:
            payload = response.json()
        except ValueError:
            payload = {}
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
                    supports_vision=False,
                    supports_json_mode=True,
                    pricing_input=0.0,
                    pricing_output=0.0,
                    pricing_status="local_zero_cost",
                    status="available",
                )
            )
        if not out and self._default_model_id:
            out.append(
                ModelCapability(
                    model_id=self._default_model_id,
                    display_name=self._default_model_id,
                    input_modalities=["text"],
                    output_modalities=["text"],
                    supports_streaming=True,
                    supports_json_mode=True,
                    pricing_input=0.0,
                    pricing_output=0.0,
                    pricing_status="local_zero_cost",
                    status="available",
                )
            )
        return out

    async def get_model_capabilities(self, model_id: str) -> ModelCapability | None:
        model_value = str(model_id or "").strip()
        if not model_value:
            return None
        for model in await self.list_models():
            if model.model_id == model_value:
                return model
        return None

    async def execute_prompt(self, request: UnifiedExecutionRequest) -> UnifiedExecutionResponse:
        started = time.perf_counter()
        model = str(request.requested_model or "").strip() or self._default_model_id
        messages = list(request.messages or [])
        if not messages:
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            if request.prompt:
                messages.append({"role": "user", "content": request.prompt})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        response_format = metadata.get("response_format")
        if isinstance(response_format, dict):
            payload["response_format"] = response_format

        try:
            async with httpx.AsyncClient(**self._client_kwargs()) as client:
                response = await client.post(self._v1_url("/chat/completions"), json=payload)
            self._metrics["calls"] += 1
            try:
                data = response.json()
            except ValueError:
                data = {}
            if response.status_code >= 400:
                raise RuntimeError(self._error_message_from_payload(data=data, status_code=response.status_code))
            choices = data.get("choices") if isinstance(data, dict) else []
            first = choices[0] if isinstance(choices, list) and choices else {}
            message = first.get("message") if isinstance(first, dict) else {}
            usage_raw = data.get("usage") if isinstance(data, dict) else {}
            usage = UnifiedExecutionUsage(
                prompt_tokens=int((usage_raw or {}).get("prompt_tokens") or 0),
                cached_input_tokens=0,
                completion_tokens=int((usage_raw or {}).get("completion_tokens") or 0),
                total_tokens=int((usage_raw or {}).get("total_tokens") or 0),
            )
            if usage.total_tokens == 0:
                usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
            return UnifiedExecutionResponse(
                provider_id=self.provider_id,
                model_id=model,
                output_text=str(message.get("content") or first.get("text") or ""),
                finish_reason=str(first.get("finish_reason") or "").strip() or None,
                usage=usage,
                latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
                estimated_cost=0.0,
                raw_provider_response_ref=f"local:{data.get('id') or self._iso_now()}" if isinstance(data, dict) else None,
            )
        except Exception as exc:
            self._metrics["failures"] += 1
            raise RuntimeError(str(exc).strip() or "local_execute_failed") from exc

    @staticmethod
    def _error_message_from_payload(*, data: Any, status_code: int) -> str:
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and str(error.get("message") or "").strip():
                return str(error.get("message")).strip()
            if error is not None:
                return str(error).strip() or f"http_{status_code}"
        return f"http_{status_code}"

    def estimate_cost(
        self,
        *,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_input_tokens: int = 0,
    ) -> float | None:
        return 0.0

    def collect_metrics(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "total_requests": int(self._metrics.get("calls") or 0),
            "successful_requests": max(int(self._metrics.get("calls") or 0) - int(self._metrics.get("failures") or 0), 0),
            "failed_requests": int(self._metrics.get("failures") or 0),
            "success_rate": (
                max(int(self._metrics.get("calls") or 0) - int(self._metrics.get("failures") or 0), 0)
                / int(self._metrics.get("calls") or 1)
            ),
            "health": {
                "availability": "available" if self._metrics["health"].get("reachable") else "unavailable",
                "last_error": self._metrics["health"].get("last_error"),
            },
        }
