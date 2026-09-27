from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


DEFAULT_SERVICE_TOKEN_INTROSPECTION_PATH = "/api/system/nodes/services/introspect"


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_introspection_url(*, core_api_endpoint: str, introspection_path: str) -> str:
    base = _require_non_empty_string(core_api_endpoint, "core_api_endpoint")
    path = _require_non_empty_string(introspection_path, "introspection_path")
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
class ServiceTokenIntrospectionResult:
    active: bool
    claims: dict | None
    error_code: str | None
    retryable: bool
    http_status: int


class HttpxServiceTokenIntrospectionAdapter:
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


class ServiceTokenIntrospectionClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxServiceTokenIntrospectionAdapter()

    async def introspect(
        self,
        *,
        core_api_endpoint: str,
        node_id: str,
        trust_token: str,
        service_token: str,
        expected_audience: str | None = None,
        required_scopes: list[str] | None = None,
        introspection_path: str = DEFAULT_SERVICE_TOKEN_INTROSPECTION_PATH,
    ) -> ServiceTokenIntrospectionResult:
        normalized_node_id = _require_non_empty_string(node_id, "node_id")
        normalized_trust_token = _require_non_empty_string(trust_token, "trust_token")
        payload = {
            "token": _require_non_empty_string(service_token, "service_token"),
            "required_scopes": [
                _require_non_empty_string(scope, "required_scope") for scope in list(required_scopes or [])
            ],
        }
        if expected_audience is not None:
            payload["expected_audience"] = _require_non_empty_string(expected_audience, "expected_audience")
        url = _build_introspection_url(
            core_api_endpoint=core_api_endpoint,
            introspection_path=introspection_path,
        )
        status_code, body = await self._http_adapter.post_json(
            url,
            payload,
            {
                "X-Node-Id": normalized_node_id,
                "X-Node-Trust-Token": normalized_trust_token,
                "Content-Type": "application/json",
            },
        )
        active = status_code == 200 and body.get("active") is True and isinstance(body.get("claims"), dict)
        error_code = None if active else str(body.get("error_code") or body.get("detail") or f"http_{status_code}")
        return ServiceTokenIntrospectionResult(
            active=active,
            claims=dict(body["claims"]) if active else None,
            error_code=error_code,
            retryable=status_code >= 500 or status_code in {408, 425, 429},
            http_status=status_code,
        )
