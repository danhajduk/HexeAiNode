from ai_node.bootstrap.bootstrap_parser import build_registration_url, resolve_registration_endpoint_path
from ai_node.diagnostics.onboarding_logger import OnboardingDiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


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

        self._lifecycle.transition_to(NodeLifecycleState.REGISTRATION_PENDING)
        self._diag.registration_attempt(
            {
                "url": resolved_url,
                "node_id": payload["node_id"],
                "node_name": payload["node_name"],
                "protocol_version": payload["protocol_version"],
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
                },
            )
        return await self._http_adapter.post_json(resolved_url, payload)
