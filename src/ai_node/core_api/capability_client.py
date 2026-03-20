from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


DEFAULT_CAPABILITY_DECLARATION_PATH = "/api/system/nodes/capabilities/declaration"
DEFAULT_PROVIDER_INTELLIGENCE_SUBMISSION_PATH = "/api/system/nodes/providers/capabilities/report"


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_capability_url(*, core_api_endpoint: str, declaration_path: str) -> str:
    base = _require_non_empty_string(core_api_endpoint, "core_api_endpoint")
    path = _require_non_empty_string(declaration_path, "declaration_path")
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("core_api_endpoint must be a valid URL")
    normalized_base = f"{base.rstrip('/')}/"
    relative_path = path[1:] if path.startswith("/") else path
    base_path = parsed.path.strip("/")
    if base_path and (relative_path == base_path or relative_path.startswith(f"{base_path}/")):
        relative_path = relative_path[len(base_path) :].lstrip("/")
    return urljoin(normalized_base, relative_path)


@dataclass(frozen=True)
class CapabilitySubmissionResult:
    status: str
    payload: dict
    retryable: bool
    error: str | None = None


class HttpxCapabilityAdapter:
    async def post_json(self, url: str, payload: dict, headers: dict) -> tuple[int, dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text.strip() or "invalid_json_response"}
        if not isinstance(body, dict):
            body = {"detail": "response must be a json object"}
        return response.status_code, body


class CapabilityDeclarationClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxCapabilityAdapter()

    async def submit_manifest(
        self,
        *,
        core_api_endpoint: str,
        trust_token: str,
        node_id: str,
        capability_manifest: dict,
        declaration_path: str = DEFAULT_CAPABILITY_DECLARATION_PATH,
    ) -> CapabilitySubmissionResult:
        if not isinstance(capability_manifest, dict):
            raise ValueError("capability_manifest must be a dict")
        url = _build_capability_url(core_api_endpoint=core_api_endpoint, declaration_path=declaration_path)
        headers = {
            "Authorization": f"Bearer {_require_non_empty_string(trust_token, 'trust_token')}",
            "X-Node-Trust-Token": _require_non_empty_string(trust_token, "trust_token"),
            "X-Synthia-Node-Id": _require_non_empty_string(node_id, "node_id"),
            "Content-Type": "application/json",
        }
        if hasattr(self._logger, "info"):
            self._logger.info("[capability-declare-request] %s", {"url": url, "node_id": node_id})

        status_code, payload = await self._http_adapter.post_json(
            url,
            {"manifest": capability_manifest},
            headers,
        )
        result = _classify_capability_submission_response(status_code=status_code, payload=payload)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[capability-declare-response] %s",
                {"status": result.status, "retryable": result.retryable, "http_status": status_code},
            )
        return result

    async def submit_provider_intelligence(
        self,
        *,
        core_api_endpoint: str,
        trust_token: str,
        node_id: str,
        provider_intelligence_report: dict,
        submission_path: str = DEFAULT_PROVIDER_INTELLIGENCE_SUBMISSION_PATH,
    ) -> CapabilitySubmissionResult:
        if not isinstance(provider_intelligence_report, dict):
            raise ValueError("provider_intelligence_report must be a dict")
        url = _build_capability_url(core_api_endpoint=core_api_endpoint, declaration_path=submission_path)
        headers = {
            "Authorization": f"Bearer {_require_non_empty_string(trust_token, 'trust_token')}",
            "X-Node-Trust-Token": _require_non_empty_string(trust_token, "trust_token"),
            "X-Synthia-Node-Id": _require_non_empty_string(node_id, "node_id"),
            "Content-Type": "application/json",
        }
        if hasattr(self._logger, "info"):
            self._logger.info("[provider-intelligence-submit-request] %s", {"url": url, "node_id": node_id})

        request_payload = _build_provider_intelligence_request_payload(
            node_id=node_id,
            report=provider_intelligence_report,
        )
        status_code, payload = await self._http_adapter.post_json(url, request_payload, headers)
        result = _classify_capability_submission_response(status_code=status_code, payload=payload)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[provider-intelligence-submit-response] %s",
                {"status": result.status, "retryable": result.retryable, "http_status": status_code},
            )
        return result


def _classify_capability_submission_response(*, status_code: int, payload: dict) -> CapabilitySubmissionResult:
    if status_code >= 500 or status_code in {408, 425, 429}:
        return CapabilitySubmissionResult(
            status="retryable_failure",
            payload=payload,
            retryable=True,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    if status_code >= 400:
        return CapabilitySubmissionResult(
            status="rejected",
            payload=payload,
            retryable=False,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )

    response_status = str(payload.get("status") or payload.get("result") or "accepted").strip().lower()
    if response_status in {"accepted", "ok", "success"}:
        return CapabilitySubmissionResult(status="accepted", payload=payload, retryable=False, error=None)
    if response_status in {"rejected", "invalid"}:
        return CapabilitySubmissionResult(
            status="rejected",
            payload=payload,
            retryable=False,
            error=str(payload.get("detail") or payload.get("error") or response_status),
        )
    if response_status in {"retryable_failure", "retry", "temporary_error"}:
        return CapabilitySubmissionResult(
            status="retryable_failure",
            payload=payload,
            retryable=True,
            error=str(payload.get("detail") or payload.get("error") or response_status),
        )
    return CapabilitySubmissionResult(status="accepted", payload=payload, retryable=False, error=None)


def _build_provider_intelligence_request_payload(*, node_id: str, report: dict) -> dict:
    normalized_node_id = _require_non_empty_string(node_id, "node_id")
    structured = _structured_payload_from_runtime_report(report=report)
    if structured is not None:
        provider_intelligence = _provider_intelligence_list_from_structured(structured=structured)
        payload = {
            "node_id": normalized_node_id,
            "provider_intelligence": provider_intelligence,
            "node_available": True,
        }
        if structured.get("metrics_snapshot"):
            payload["metrics_snapshot"] = structured.get("metrics_snapshot")
        if structured.get("observed_at"):
            payload["observed_at"] = structured.get("observed_at")
        return payload
    compatibility = _compatibility_payload_from_discovery_report(report=report)
    compatibility["node_id"] = normalized_node_id
    compatibility.setdefault("node_available", True)
    return compatibility


def _structured_payload_from_runtime_report(*, report: dict) -> dict | None:
    providers = report.get("providers")
    if not isinstance(providers, list):
        return None
    normalized_providers: list[dict] = []
    normalized_models: list[dict] = []
    metrics_snapshot: dict[str, list] = {"providers": []}
    for provider_entry in providers:
        if not isinstance(provider_entry, dict):
            continue
        provider_id = str(provider_entry.get("provider_id") or provider_entry.get("provider") or "").strip()
        if not provider_id:
            continue
        normalized_providers.append(
            {
                "provider_id": provider_id,
                "provider_type": str(provider_entry.get("provider_type") or "").strip() or None,
                "provider_availability_state": str(
                    provider_entry.get("availability")
                    or provider_entry.get("provider_availability_state")
                    or provider_entry.get("availability_state")
                    or "unknown"
                ).strip(),
            }
        )
        metrics_models: list[dict] = []
        for model_entry in provider_entry.get("models") or []:
            if not isinstance(model_entry, dict):
                continue
            model_id = str(model_entry.get("model_id") or "").strip()
            if not model_id:
                continue
            model_payload = {
                "model_id": model_id,
                "provider_id": provider_id,
                "display_name": model_entry.get("display_name"),
                "context_window": model_entry.get("context_window"),
                "max_output_tokens": model_entry.get("max_output_tokens"),
                "supports_streaming": bool(model_entry.get("supports_streaming")),
                "supports_tools": bool(model_entry.get("supports_tools")),
                "supports_vision": bool(model_entry.get("supports_vision")),
                "supports_json_mode": bool(model_entry.get("supports_json_mode")),
                "status": model_entry.get("status"),
            }
            pricing_input = model_entry.get("pricing_input")
            pricing_output = model_entry.get("pricing_output")
            if isinstance(pricing_input, (int, float)) and pricing_input >= 0:
                model_payload["pricing_input_tokens"] = float(pricing_input)
            if isinstance(pricing_output, (int, float)) and pricing_output >= 0:
                model_payload["pricing_output_tokens"] = float(pricing_output)
            normalized_models.append(model_payload)
            metrics_models.append(
                {
                    "model_id": model_id,
                    "latency_metrics": model_entry.get("latency_metrics") if isinstance(model_entry.get("latency_metrics"), dict) else {},
                    "success_metrics": model_entry.get("success_metrics") if isinstance(model_entry.get("success_metrics"), dict) else {},
                    "usage_metrics": model_entry.get("usage_metrics") if isinstance(model_entry.get("usage_metrics"), dict) else {},
                }
            )
        metrics_snapshot["providers"].append(
            {
                "provider_id": provider_id,
                "success_metrics": provider_entry.get("success_metrics")
                if isinstance(provider_entry.get("success_metrics"), dict)
                else {},
                "models": metrics_models,
            }
        )
    if not normalized_providers or not normalized_models:
        return None
    payload = {
        "providers": normalized_providers,
        "models": normalized_models,
        "metrics_snapshot": metrics_snapshot,
    }
    observed_at = str(report.get("generated_at") or "").strip()
    if observed_at:
        payload["observed_at"] = observed_at
    return payload


def _compatibility_payload_from_discovery_report(*, report: dict) -> dict:
    out: list[dict] = []
    for provider_entry in report.get("providers") or []:
        if not isinstance(provider_entry, dict):
            continue
        provider_id = str(provider_entry.get("provider") or provider_entry.get("provider_id") or "").strip()
        if not provider_id:
            continue
        available_models = []
        for model_entry in provider_entry.get("models") or []:
            if not isinstance(model_entry, dict):
                continue
            model_id = str(model_entry.get("id") or model_entry.get("model_id") or "").strip()
            if not model_id:
                continue
            if str(model_entry.get("status") or "available").strip().lower() not in {"available", "degraded"}:
                continue
            pricing = model_entry.get("pricing")
            latency = model_entry.get("latency_metrics")
            available_models.append(
                {
                    "model_id": model_id,
                    "pricing": pricing if isinstance(pricing, dict) else {},
                    "latency_metrics": latency if isinstance(latency, dict) else {},
                }
            )
        out.append({"provider": provider_id.lower(), "available_models": available_models})
    payload = {"provider_intelligence": out}
    observed_at = str(report.get("generated_at") or "").strip()
    if observed_at:
        payload["observed_at"] = observed_at
    if isinstance(report.get("metrics_snapshot"), dict):
        payload["metrics_snapshot"] = report.get("metrics_snapshot")
    return payload


def _provider_intelligence_list_from_structured(*, structured: dict) -> list[dict]:
    providers = structured.get("providers") if isinstance(structured.get("providers"), list) else []
    models = structured.get("models") if isinstance(structured.get("models"), list) else []
    out: list[dict] = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        provider_id = str(provider.get("provider_id") or "").strip().lower()
        if not provider_id:
            continue
        available_models = []
        for model in models:
            if not isinstance(model, dict):
                continue
            if str(model.get("provider_id") or "").strip().lower() != provider_id:
                continue
            model_id = str(model.get("model_id") or "").strip()
            if not model_id:
                continue
            if str(model.get("status") or "available").strip().lower() not in {"available", "degraded"}:
                continue
            pricing: dict = {}
            if isinstance(model.get("pricing_input_tokens"), (int, float)):
                pricing["input_per_1m_tokens"] = float(model["pricing_input_tokens"])
            if isinstance(model.get("pricing_output_tokens"), (int, float)):
                pricing["output_per_1m_tokens"] = float(model["pricing_output_tokens"])
            available_models.append(
                {
                    "model_id": model_id,
                    "pricing": pricing,
                    "latency_metrics": {},
                }
            )
        out.append({"provider": provider_id, "available_models": available_models})
    return out
