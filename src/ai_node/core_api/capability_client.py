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

        status_code, payload = await self._http_adapter.post_json(
            url,
            {"provider_intelligence": provider_intelligence_report},
            headers,
        )
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
