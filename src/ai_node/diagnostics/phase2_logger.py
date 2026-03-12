from ai_node.security.redaction import redact_dict


class Phase2DiagnosticsLogger:
    def __init__(self, logger) -> None:
        self._logger = logger

    def post_trust_activation(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.phase2.post_trust_activation] %s", redact_dict(payload))

    def provider_selection(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.phase2.provider_selection] %s", redact_dict(payload))

    def capability_manifest(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.phase2.capability_manifest] %s", redact_dict(payload))

    def capability_submission(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.phase2.capability_submission] %s", redact_dict(payload))

    def governance_sync(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.phase2.governance_sync] %s", redact_dict(payload))

    def governance_freshness(self, payload: dict) -> None:
        if hasattr(self._logger, "info"):
            self._logger.info("[diag.phase2.governance_freshness] %s", redact_dict(payload))

    def degraded_recovery(self, payload: dict) -> None:
        if hasattr(self._logger, "warning"):
            self._logger.warning("[diag.phase2.degraded_recovery] %s", redact_dict(payload))
