from datetime import datetime, timezone

from ai_node.runtime.trusted_status_telemetry import TrustedStatusTelemetryPublisher


EXECUTION_TELEMETRY_EVENTS = {
    "task_received",
    "task_rejected",
    "task_started",
    "task_progress",
    "task_completed",
    "task_failed",
    "provider_selected",
    "provider_fallback",
    "execution_timeout",
    "budget_policy_refresh",
    "budget_reservation",
    "budget_denial",
    "budget_finalized",
    "budget_reset",
}


class ExecutionTelemetryPublisher:
    def __init__(
        self,
        *,
        logger,
        node_id: str,
        trust_state_provider,
        status_publisher: TrustedStatusTelemetryPublisher | None = None,
    ) -> None:
        self._logger = logger
        self._node_id = str(node_id or "").strip()
        self._trust_state_provider = trust_state_provider
        self._status_publisher = status_publisher or TrustedStatusTelemetryPublisher(logger=logger)

    def status_payload(self) -> dict:
        if hasattr(self._status_publisher, "status_payload"):
            return self._status_publisher.status_payload()
        return {"published": False, "last_error": "status_payload_unavailable"}

    async def publish_event(self, *, event_type: str, payload: dict | None = None) -> dict:
        normalized_event = str(event_type or "").strip()
        if normalized_event not in EXECUTION_TELEMETRY_EVENTS:
            raise ValueError("unsupported_execution_telemetry_event")
        trust_state = self._trust_state_provider() if callable(self._trust_state_provider) else {}
        trust_payload = trust_state if isinstance(trust_state, dict) else {}
        enriched_payload = {
            "event_type": normalized_event,
            "emitted_at": datetime.now(timezone.utc).isoformat(),
            **(payload if isinstance(payload, dict) else {}),
        }
        return await self._status_publisher.publish_status(
            trust_state=trust_payload,
            node_id=self._node_id,
            payload=enriched_payload,
        )
