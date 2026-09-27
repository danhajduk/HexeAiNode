from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


DEFAULT_BUDGET_USAGE_SUMMARY_PATH = "/api/system/nodes/budgets/usage-summary"


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_url(*, core_api_endpoint: str, path: str) -> str:
    base = _required_string(core_api_endpoint, "core_api_endpoint")
    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("core_api_endpoint must be a valid URL")
    relative_path = _required_string(path, "path").lstrip("/")
    base_path = parsed.path.strip("/")
    if base_path and (relative_path == base_path or relative_path.startswith(f"{base_path}/")):
        relative_path = relative_path[len(base_path) :].lstrip("/")
    return urljoin(f"{base.rstrip('/')}/", relative_path)


@dataclass(frozen=True)
class BudgetUsageSubmissionResult:
    accepted: bool
    retryable: bool
    payload: dict
    error: str | None = None


class HttpxBudgetUsageAdapter:
    async def post_json(self, url: str, payload: dict, headers: dict) -> tuple[int, dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text.strip() or "invalid_json_response"}
        return response.status_code, body if isinstance(body, dict) else {"detail": "invalid_json_response"}


class BudgetUsageSummaryClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxBudgetUsageAdapter()

    async def submit(
        self,
        *,
        core_api_endpoint: str,
        trust_token: str,
        node_id: str,
        summary: dict,
        path: str = DEFAULT_BUDGET_USAGE_SUMMARY_PATH,
    ) -> BudgetUsageSubmissionResult:
        if not isinstance(summary, dict):
            raise ValueError("summary must be a dict")
        normalized_node_id = _required_string(node_id, "node_id")
        payload = {key: value for key, value in summary.items() if key != "queued_at"}
        payload["node_id"] = normalized_node_id
        status_code, body = await self._http_adapter.post_json(
            _build_url(core_api_endpoint=core_api_endpoint, path=path),
            payload,
            {
                "X-Node-Trust-Token": _required_string(trust_token, "trust_token"),
                "Content-Type": "application/json",
            },
        )
        accepted = 200 <= status_code < 300
        retryable = status_code >= 500 or status_code in {408, 425, 429}
        error = None if accepted else str(body.get("detail") or body.get("error") or f"http_{status_code}")
        return BudgetUsageSubmissionResult(accepted=accepted, retryable=retryable, payload=body, error=error)
