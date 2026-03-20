from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


DEFAULT_SCHEDULER_LEASE_REQUEST_PATH = "/api/system/scheduler/leases/request"
DEFAULT_SCHEDULER_LEASE_HEARTBEAT_PATH = "/api/system/scheduler/leases/{lease_id}/heartbeat"
DEFAULT_SCHEDULER_LEASE_REPORT_PATH = "/api/system/scheduler/leases/{lease_id}/report"
DEFAULT_SCHEDULER_LEASE_COMPLETE_PATH = "/api/system/scheduler/leases/{lease_id}/complete"


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_url(*, core_api_endpoint: str, path: str) -> str:
    base = _require_non_empty_string(core_api_endpoint, "core_api_endpoint")
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
class SchedulerLeaseResult:
    status: str
    payload: dict
    retryable: bool
    error: str | None = None


class HttpxSchedulerLeaseAdapter:
    async def post_json(self, url: str, headers: dict, body: dict) -> tuple[int, dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text.strip() or "invalid_json_response"}
        if not isinstance(payload, dict):
            payload = {"detail": "response must be a json object"}
        return response.status_code, payload


def _classify_scheduler_response(*, status_code: int, payload: dict) -> SchedulerLeaseResult:
    if status_code >= 500 or status_code in {408, 425, 429}:
        return SchedulerLeaseResult(
            status="retryable_failure",
            payload=payload,
            retryable=True,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    if status_code >= 400:
        return SchedulerLeaseResult(
            status="rejected",
            payload=payload,
            retryable=False,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    return SchedulerLeaseResult(status="ok", payload=payload, retryable=False, error=None)


class SchedulerLeaseClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxSchedulerLeaseAdapter()

    @staticmethod
    def _headers(*, trust_token: str | None = None, node_id: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if isinstance(trust_token, str) and trust_token.strip():
            headers["Authorization"] = f"Bearer {trust_token.strip()}"
            headers["X-Node-Trust-Token"] = trust_token.strip()
        if isinstance(node_id, str) and node_id.strip():
            headers["X-Synthia-Node-Id"] = node_id.strip()
        return headers

    async def request_lease(
        self,
        *,
        core_api_endpoint: str,
        worker_id: str,
        capabilities: list[str],
        max_units: int = 1,
        trust_token: str | None = None,
        node_id: str | None = None,
    ) -> SchedulerLeaseResult:
        url = _build_url(core_api_endpoint=core_api_endpoint, path=DEFAULT_SCHEDULER_LEASE_REQUEST_PATH)
        body = {
            "worker_id": _require_non_empty_string(worker_id, "worker_id"),
            "capabilities": [str(item).strip() for item in capabilities if str(item).strip()],
            "max_units": max(int(max_units), 1),
        }
        status_code, payload = await self._http_adapter.post_json(url, self._headers(trust_token=trust_token, node_id=node_id), body)
        return _classify_scheduler_response(status_code=status_code, payload=payload)

    async def heartbeat(
        self,
        *,
        core_api_endpoint: str,
        lease_id: str,
        worker_id: str,
        trust_token: str | None = None,
        node_id: str | None = None,
    ) -> SchedulerLeaseResult:
        path = DEFAULT_SCHEDULER_LEASE_HEARTBEAT_PATH.format(lease_id=_require_non_empty_string(lease_id, "lease_id"))
        url = _build_url(core_api_endpoint=core_api_endpoint, path=path)
        body = {"worker_id": _require_non_empty_string(worker_id, "worker_id")}
        status_code, payload = await self._http_adapter.post_json(url, self._headers(trust_token=trust_token, node_id=node_id), body)
        return _classify_scheduler_response(status_code=status_code, payload=payload)

    async def report_progress(
        self,
        *,
        core_api_endpoint: str,
        lease_id: str,
        worker_id: str,
        progress: float,
        metrics: dict | None = None,
        message: str | None = None,
        trust_token: str | None = None,
        node_id: str | None = None,
    ) -> SchedulerLeaseResult:
        path = DEFAULT_SCHEDULER_LEASE_REPORT_PATH.format(lease_id=_require_non_empty_string(lease_id, "lease_id"))
        url = _build_url(core_api_endpoint=core_api_endpoint, path=path)
        body = {
            "worker_id": _require_non_empty_string(worker_id, "worker_id"),
            "progress": float(progress),
            "metrics": metrics if isinstance(metrics, dict) else {},
            "message": str(message or "").strip() or None,
        }
        status_code, payload = await self._http_adapter.post_json(url, self._headers(trust_token=trust_token, node_id=node_id), body)
        return _classify_scheduler_response(status_code=status_code, payload=payload)

    async def complete(
        self,
        *,
        core_api_endpoint: str,
        lease_id: str,
        worker_id: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
        trust_token: str | None = None,
        node_id: str | None = None,
    ) -> SchedulerLeaseResult:
        path = DEFAULT_SCHEDULER_LEASE_COMPLETE_PATH.format(lease_id=_require_non_empty_string(lease_id, "lease_id"))
        url = _build_url(core_api_endpoint=core_api_endpoint, path=path)
        body = {
            "worker_id": _require_non_empty_string(worker_id, "worker_id"),
            "status": _require_non_empty_string(status, "status"),
            "result": result if isinstance(result, dict) else {},
            "error": str(error or "").strip() or None,
        }
        status_code, payload = await self._http_adapter.post_json(url, self._headers(trust_token=trust_token, node_id=node_id), body)
        return _classify_scheduler_response(status_code=status_code, payload=payload)
