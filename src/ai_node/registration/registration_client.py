from ai_node.bootstrap.bootstrap_parser import build_registration_url, resolve_registration_endpoint_path
from ai_node.diagnostics.onboarding_logger import OnboardingDiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _normalize_ui_endpoint(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if not (normalized.startswith("http://") or normalized.startswith("https://")):
        raise ValueError("ui_endpoint must be an absolute http/https URL")
    return normalized


def _normalize_api_base_url(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if not (normalized.startswith("http://") or normalized.startswith("https://")):
        raise ValueError("api_base_url must be an absolute http/https URL")
    return normalized


class RegistrationClient:
    def __init__(self, *, lifecycle: NodeLifecycle, http_adapter, logger) -> None:
        if lifecycle is None:
            raise ValueError("registration client requires lifecycle")
        if http_adapter is None or not hasattr(http_adapter, "post_json"):
            raise ValueError("registration client requires http_adapter.post_json")
        self._lifecycle = lifecycle
        self._http_adapter = http_adapter
        self._logger = logger
        self._diag = OnboardingDiagnosticsLogger(logger)

    async def register(
        self,
        *,
        bootstrap_payload: dict,
        node_id: str,
        node_name: str,
        node_software_version: str,
        protocol_version: str,
        node_nonce: str,
        hostname: str | None = None,
        ui_endpoint: str | None = None,
        api_base_url: str | None = None,
    ) -> dict:
        if not isinstance(bootstrap_payload, dict):
            raise ValueError("bootstrap_payload is required")

        resolved_url = bootstrap_payload.get("registration_url")
        if not resolved_url:
            register_path = resolve_registration_endpoint_path(bootstrap_payload.get("onboarding_endpoints"))
            resolved_url = build_registration_url(
                _require_non_empty_string(bootstrap_payload.get("api_base"), "api_base"),
                _require_non_empty_string(register_path, "registration_endpoint_path"),
            )
        if not (resolved_url.startswith("http://") or resolved_url.startswith("https://")):
            raise ValueError("registration URL must be http/https")

        payload = {
            "node_id": _require_non_empty_string(node_id, "node_id"),
            "node_name": _require_non_empty_string(node_name, "node_name"),
            "node_type": "ai-node",
            "node_software_version": _require_non_empty_string(
                node_software_version, "node_software_version"
            ),
            "protocol_version": str(protocol_version).strip(),
            "node_nonce": _require_non_empty_string(node_nonce, "node_nonce"),
        }
        if hostname is not None and hostname.strip():
            payload["hostname"] = hostname.strip()
        normalized_ui_endpoint = _normalize_ui_endpoint(ui_endpoint)
        if normalized_ui_endpoint is not None:
            payload["ui_endpoint"] = normalized_ui_endpoint
        normalized_api_base_url = _normalize_api_base_url(api_base_url)
        if normalized_api_base_url is not None:
            payload["api_base_url"] = normalized_api_base_url

        self._lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)
        self._diag.registration_attempt(
            {
                "url": resolved_url,
                "node_id": payload["node_id"],
                "node_name": payload["node_name"],
                "protocol_version": payload["protocol_version"],
                "ui_endpoint": payload.get("ui_endpoint"),
                "api_base_url": payload.get("api_base_url"),
            }
        )
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[registration-request] %s",
                {
                    "url": resolved_url,
                    "node_id": payload["node_id"],
                    "node_name": payload["node_name"],
                    "node_type": payload["node_type"],
                    "protocol_version": payload["protocol_version"],
                    "ui_endpoint": payload.get("ui_endpoint"),
                    "api_base_url": payload.get("api_base_url"),
                },
            )
        return await self._http_adapter.post_json(resolved_url, payload)
