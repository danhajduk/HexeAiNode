from dataclasses import dataclass
from urllib.parse import urlencode, urljoin, urlparse

import httpx


DEFAULT_GOVERNANCE_SYNC_PATH = "/api/system/nodes/governance/current"


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_governance_url(*, core_api_endpoint: str, governance_path: str, node_id: str) -> str:
    base = _require_non_empty_string(core_api_endpoint, "core_api_endpoint")
    path = _require_non_empty_string(governance_path, "governance_path")
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("core_api_endpoint must be a valid URL")
    normalized_base = f"{base.rstrip('/')}/"
    relative_path = path[1:] if path.startswith("/") else path
    base_path = parsed.path.strip("/")
    if base_path and (relative_path == base_path or relative_path.startswith(f"{base_path}/")):
        relative_path = relative_path[len(base_path) :].lstrip("/")
    base_url = urljoin(normalized_base, relative_path)
    return f"{base_url}?{urlencode({'node_id': _require_non_empty_string(node_id, 'node_id')})}"


@dataclass(frozen=True)
class GovernanceSyncResult:
    status: str
    payload: dict
    retryable: bool
    error: str | None = None


class HttpxGovernanceAdapter:
    async def get_json(self, url: str, headers: dict) -> tuple[int, dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text.strip() or "invalid_json_response"}
        if not isinstance(body, dict):
            body = {"detail": "response must be a json object"}
        return response.status_code, body


class GovernanceSyncClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxGovernanceAdapter()

    async def fetch_baseline_governance(
        self,
        *,
        core_api_endpoint: str,
        trust_token: str,
        node_id: str,
        governance_path: str = DEFAULT_GOVERNANCE_SYNC_PATH,
    ) -> GovernanceSyncResult:
        url = _build_governance_url(
            core_api_endpoint=core_api_endpoint,
            governance_path=governance_path,
            node_id=node_id,
        )
        headers = {
            "X-Node-Trust-Token": _require_non_empty_string(trust_token, "trust_token"),
            "Authorization": f"Bearer {_require_non_empty_string(trust_token, 'trust_token')}",
            "X-Synthia-Node-Id": _require_non_empty_string(node_id, "node_id"),
        }
        if hasattr(self._logger, "info"):
            self._logger.info("[governance-sync-request] %s", {"url": url, "node_id": node_id})
        status_code, payload = await self._http_adapter.get_json(url, headers)
        result = _classify_governance_sync_response(status_code=status_code, payload=payload)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[governance-sync-response] %s",
                {"status": result.status, "retryable": result.retryable, "http_status": status_code},
            )
        return result


def _classify_governance_sync_response(*, status_code: int, payload: dict) -> GovernanceSyncResult:
    if status_code >= 500 or status_code in {408, 425, 429}:
        return GovernanceSyncResult(
            status="retryable_failure",
            payload=payload,
            retryable=True,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    if status_code >= 400:
        return GovernanceSyncResult(
            status="rejected",
            payload=payload,
            retryable=False,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    return GovernanceSyncResult(status="synced", payload=payload, retryable=False, error=None)
