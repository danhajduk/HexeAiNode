from dataclasses import dataclass
from typing import Optional

from ai_node.time_utils import local_now_iso


PHASE1_ALLOWED_STATUS_EVENTS = {
    "bootstrap_connected",
    "core_discovered",
    "registration_pending",
    "pending_approval",
    "trusted",
    "capability_setup_pending",
    "degraded",
}


@dataclass(frozen=True)
class StatusEvent:
    status: str
    emitted_at: str
    detail: Optional[dict]


class StatusEmitter:
    def __init__(self, *, sink, logger, channel: str) -> None:
        if sink is None or not hasattr(sink, "emit"):
            raise ValueError("status emitter requires sink.emit")
        if channel == "bootstrap":
            raise ValueError("status telemetry must not be routed over bootstrap MQTT")
        self._sink = sink
        self._logger = logger
        self._channel = channel

    async def emit(self, status: str, detail: Optional[dict] = None) -> StatusEvent:
        if status not in PHASE1_ALLOWED_STATUS_EVENTS:
            raise ValueError(f"unsupported phase1 status event: {status}")

        event = StatusEvent(
            status=status,
            emitted_at=local_now_iso(),
            detail=detail or None,
        )
        await self._sink.emit(
            {
                "status": event.status,
                "emitted_at": event.emitted_at,
                "detail": event.detail,
                "channel": self._channel,
            }
        )
        if hasattr(self._logger, "info"):
            self._logger.info("[status-event] %s", {"status": event.status, "channel": self._channel})
        return event
