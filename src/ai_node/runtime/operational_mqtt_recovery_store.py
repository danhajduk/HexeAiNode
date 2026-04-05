import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _future_iso(*, seconds: int) -> str:
    return (_utc_now() + timedelta(seconds=max(int(seconds), 0))).isoformat()


def _default_state() -> dict:
    return {
        "schema_version": "1.0",
        "active": False,
        "attempt_count": 0,
        "max_attempts": 3,
        "last_error": None,
        "last_checked_at": None,
        "last_restart_requested_at": None,
        "next_restart_not_before": None,
        "exhausted": False,
    }


class OperationalMqttRecoveryStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def snapshot(self) -> dict:
        if not self._path.exists():
            return _default_state()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[operational-mqtt-recovery-invalid] %s", {"path": str(self._path)})
            return _default_state()
        return self._normalize(payload)

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
        if hasattr(self._logger, "info"):
            self._logger.info("[operational-mqtt-recovery-cleared] %s", {"path": str(self._path)})

    def note_unhealthy(self, *, error: str | None, max_attempts: int) -> dict:
        state = self.snapshot()
        state["active"] = True
        state["exhausted"] = False
        state["max_attempts"] = max(int(max_attempts), 1)
        state["last_error"] = str(error or "operational_mqtt_unhealthy")
        state["last_checked_at"] = _utc_now_iso()
        self._save(state)
        return dict(state)

    def record_restart_requested(self, *, error: str | None, delay_seconds: int, max_attempts: int) -> dict:
        state = self.note_unhealthy(error=error, max_attempts=max_attempts)
        state["attempt_count"] = min(int(state.get("attempt_count") or 0) + 1, max(int(max_attempts), 1))
        state["last_restart_requested_at"] = _utc_now_iso()
        state["next_restart_not_before"] = _future_iso(seconds=delay_seconds)
        state["exhausted"] = int(state["attempt_count"]) >= int(state["max_attempts"])
        self._save(state)
        return dict(state)

    def mark_exhausted(self, *, error: str | None, max_attempts: int) -> dict:
        state = self.note_unhealthy(error=error, max_attempts=max_attempts)
        state["attempt_count"] = max(int(state.get("attempt_count") or 0), int(state["max_attempts"]))
        state["exhausted"] = True
        state["next_restart_not_before"] = None
        self._save(state)
        return dict(state)

    @staticmethod
    def _normalize(payload: object) -> dict:
        state = _default_state()
        if not isinstance(payload, dict):
            return state
        state["active"] = bool(payload.get("active"))
        state["attempt_count"] = max(int(payload.get("attempt_count") or 0), 0)
        state["max_attempts"] = max(int(payload.get("max_attempts") or state["max_attempts"]), 1)
        state["last_error"] = str(payload.get("last_error") or "").strip() or None
        state["last_checked_at"] = str(payload.get("last_checked_at") or "").strip() or None
        state["last_restart_requested_at"] = str(payload.get("last_restart_requested_at") or "").strip() or None
        state["next_restart_not_before"] = str(payload.get("next_restart_not_before") or "").strip() or None
        state["exhausted"] = bool(payload.get("exhausted"))
        return state

    def _save(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        normalized = self._normalize(payload)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[operational-mqtt-recovery-saved] %s", {"path": str(self._path), "state": normalized})
