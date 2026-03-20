from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


DEFAULT_TRUST_STATUS_PATH = "/api/system/nodes/trust-status"


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_trust_status_url(*, core_api_endpoint: str, trust_status_path: str, node_id: str) -> str:
    base = _require_non_empty_string(core_api_endpoint, "core_api_endpoint")
    path = _require_non_empty_string(trust_status_path, "trust_status_path")
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("core_api_endpoint must be a valid URL")
    normalized_base = f"{base.rstrip('/')}/"
    relative_path = path[1:] if path.startswith("/") else path
    base_path = parsed.path.strip("/")
    if base_path and (relative_path == base_path or relative_path.startswith(f"{base_path}/")):
        relative_path = relative_path[len(base_path) :].lstrip("/")
    return urljoin(normalized_base, f"{relative_path.rstrip('/')}/{_require_non_empty_string(node_id, 'node_id')}")


@dataclass(frozen=True)
class TrustStatusResult:
    status: str
    payload: dict
    retryable: bool
    error: str | None = None


class HttpxTrustStatusAdapter:
    def get_json(self, url: str, headers: dict) -> tuple[int, dict]:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text.strip() or "invalid_json_response"}
        if not isinstance(body, dict):
            body = {"detail": "response must be a json object"}
        return response.status_code, body


class TrustStatusClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxTrustStatusAdapter()

    def fetch(
        self,
        *,
        core_api_endpoint: str,
        trust_token: str,
        node_id: str,
        trust_status_path: str = DEFAULT_TRUST_STATUS_PATH,
    ) -> TrustStatusResult:
        url = _build_trust_status_url(
            core_api_endpoint=core_api_endpoint,
            trust_status_path=trust_status_path,
            node_id=node_id,
        )
        normalized_token = _require_non_empty_string(trust_token, "trust_token")
        headers = {
            "X-Node-Trust-Token": normalized_token,
            "Authorization": f"Bearer {normalized_token}",
            "X-Synthia-Node-Id": _require_non_empty_string(node_id, "node_id"),
        }
        if hasattr(self._logger, "info"):
            self._logger.info("[trust-status-request] %s", {"url": url, "node_id": node_id})
        status_code, payload = self._http_adapter.get_json(url, headers)
        result = _classify_trust_status_response(status_code=status_code, payload=payload)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[trust-status-response] %s",
                {
                    "status": result.status,
                    "retryable": result.retryable,
                    "http_status": status_code,
                    "support_state": payload.get("support_state"),
                },
            )
        return result


def _classify_trust_status_response(*, status_code: int, payload: dict) -> TrustStatusResult:
    if status_code >= 500 or status_code in {408, 425, 429}:
        return TrustStatusResult(
            status="retryable_failure",
            payload=payload,
            retryable=True,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    if status_code >= 400:
        return TrustStatusResult(
            status="rejected",
            payload=payload,
            retryable=False,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    support_state = str(payload.get("support_state") or "").strip().lower()
    if support_state == "removed":
        return TrustStatusResult(status="removed", payload=payload, retryable=False, error=None)
    if support_state == "revoked":
        return TrustStatusResult(status="revoked", payload=payload, retryable=False, error=None)
    return TrustStatusResult(status="supported", payload=payload, retryable=False, error=None)
