from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


DEFAULT_BUDGET_DECLARATION_PATH = "/api/system/nodes/budgets/declaration"


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _build_budget_declaration_url(*, core_api_endpoint: str, declaration_path: str) -> str:
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
class BudgetDeclarationResult:
    status: str
    payload: dict
    retryable: bool
    error: str | None = None


class HttpxBudgetDeclarationAdapter:
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


class BudgetDeclarationClient:
    def __init__(self, *, logger, http_adapter=None) -> None:
        self._logger = logger
        self._http_adapter = http_adapter or HttpxBudgetDeclarationAdapter()

    async def submit_declaration(
        self,
        *,
        core_api_endpoint: str,
        trust_token: str,
        node_id: str,
        declaration_payload: dict,
        declaration_path: str = DEFAULT_BUDGET_DECLARATION_PATH,
    ) -> BudgetDeclarationResult:
        if not isinstance(declaration_payload, dict):
            raise ValueError("declaration_payload must be a dict")
        normalized_node_id = _require_non_empty_string(node_id, "node_id")
        request_payload = {**declaration_payload, "node_id": normalized_node_id}
        url = _build_budget_declaration_url(
            core_api_endpoint=core_api_endpoint,
            declaration_path=declaration_path,
        )
        normalized_token = _require_non_empty_string(trust_token, "trust_token")
        headers = {
            "Authorization": f"Bearer {normalized_token}",
            "X-Node-Trust-Token": normalized_token,
            "X-Synthia-Node-Id": normalized_node_id,
            "Content-Type": "application/json",
        }
        if hasattr(self._logger, "info"):
            self._logger.info("[budget-declare-request] %s", {"url": url, "node_id": normalized_node_id})
        status_code, payload = await self._http_adapter.post_json(url, request_payload, headers)
        result = _classify_budget_declaration_response(status_code=status_code, payload=payload)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[budget-declare-response] %s",
                {"status": result.status, "retryable": result.retryable, "http_status": status_code},
            )
        return result


def _classify_budget_declaration_response(*, status_code: int, payload: dict) -> BudgetDeclarationResult:
    if status_code >= 500 or status_code in {408, 425, 429}:
        return BudgetDeclarationResult(
            status="retryable_failure",
            payload=payload,
            retryable=True,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    if status_code >= 400:
        return BudgetDeclarationResult(
            status="rejected",
            payload=payload,
            retryable=False,
            error=str(payload.get("detail") or payload.get("error") or f"http_{status_code}"),
        )
    response_status = str(payload.get("status") or payload.get("result") or "accepted").strip().lower()
    if response_status in {"accepted", "ok", "success"}:
        return BudgetDeclarationResult(status="accepted", payload=payload, retryable=False, error=None)
    if response_status in {"rejected", "invalid"}:
        return BudgetDeclarationResult(
            status="rejected",
            payload=payload,
            retryable=False,
            error=str(payload.get("detail") or payload.get("error") or response_status),
        )
    if response_status in {"retryable_failure", "retry", "temporary_error"}:
        return BudgetDeclarationResult(
            status="retryable_failure",
            payload=payload,
            retryable=True,
            error=str(payload.get("detail") or payload.get("error") or response_status),
        )
    return BudgetDeclarationResult(status="accepted", payload=payload, retryable=False, error=None)
