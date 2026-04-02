import json
from datetime import datetime, timezone
from pathlib import Path

from ai_node.security.redaction import redact_dict


class OnboardingDiagnosticsLogger:
    def __init__(self, logger, *, json_log_path: str = "logs/onboarding.json") -> None:
        self._logger = logger
        self._json_log_path = Path(json_log_path)

    def _append_json_event(self, *, event: str, payload: dict) -> None:
        try:
            self._json_log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "payload": redact_dict(payload),
            }
            self._json_log_path.write_text(json.dumps(entry, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[diag.onboarding_json_write_failed] %s",
                    {"path": str(self._json_log_path)},
                )

    def state_transition(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.state_transition] %s", redact_dict(payload))

    def bootstrap_connect(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.bootstrap_connect] %s", redact_dict(payload))

    def bootstrap_disconnect(self, payload: dict) -> None:
        if hasattr(self._logger, "warning"):
            self._logger.warning("[diag.bootstrap_disconnect] %s", redact_dict(payload))

    def payload_validation(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.payload_validation] %s", redact_dict(payload))

    def registration_attempt(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.registration_attempt] %s", redact_dict(payload))
        self._append_json_event(event="registration_attempt", payload=payload)

    def approval_wait(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.approval_wait] %s", redact_dict(payload))

    def trust_persistence(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.trust_persistence] %s", redact_dict(payload))
