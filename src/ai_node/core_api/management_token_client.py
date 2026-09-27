from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


DEFAULT_MANAGEMENT_TOKEN_INTROSPECTION_PATH = "/api/system/nodes/management/introspect"


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_url(*, core_api_endpoint: str, path: str) -> str:
    base = _required_string(core_api_endpoint, "core_api_endpoint")
    relative_path = _required_string(path, "path").lstrip("/")
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("core_api_endpoint must be a valid URL")
    base_path = parsed.path.strip("/")
    if base_path and (relative_path == base_path or relative_path.startswith(f"{base_path}/")):
        relative_path = relative_path[len(base_path) :].lstrip("/")
    return urljoin(f"{base.rstrip('/')}/", relative_path)


@dataclass(frozen=True)
class ManagementTokenIntrospectionResult:
    active: bool
    claims: dict | None
    error_code: str | None
    retryable: bool
    http_status: int


class HttpxManagementTokenIntrospectionAdapter:
    async def post_json(self, url: str, payload: dict, headers: dict) -> tuple[int, dict]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {"error_code": "invalid_json_response"}
        if not isinstance(body, dict):
            body = {"error_code": "invalid_json_response"}
        return response.status_code, body


class ManagementTokenIntrospectionClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxManagementTokenIntrospectionAdapter()

    async def introspect(
        self,
        *,
        core_api_endpoint: str,
        node_id: str,
        trust_token: str,
        management_token: str,
        required_scopes: list[str] | None = None,
        introspection_path: str = DEFAULT_MANAGEMENT_TOKEN_INTROSPECTION_PATH,
    ) -> ManagementTokenIntrospectionResult:
        payload = {
            "token": _required_string(management_token, "management_token"),
            "required_scopes": [_required_string(scope, "required_scope") for scope in list(required_scopes or [])],
        }
        try:
            status_code, body = await self._http_adapter.post_json(
                _build_url(core_api_endpoint=core_api_endpoint, path=introspection_path),
                payload,
                {
                    "X-Node-Id": _required_string(node_id, "node_id"),
                    "X-Node-Trust-Token": _required_string(trust_token, "trust_token"),
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError:
            return ManagementTokenIntrospectionResult(
                active=False,
                claims=None,
                error_code="management_validation_unavailable",
                retryable=True,
                http_status=503,
            )
        active = status_code == 200 and body.get("active") is True and isinstance(body.get("claims"), dict)
        return ManagementTokenIntrospectionResult(
            active=active,
            claims=dict(body["claims"]) if active else None,
            error_code=None if active else str(body.get("error_code") or body.get("detail") or f"http_{status_code}"),
            retryable=status_code >= 500 or status_code in {408, 425, 429},
            http_status=status_code,
        )
