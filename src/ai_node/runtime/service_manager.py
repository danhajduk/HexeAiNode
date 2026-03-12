import subprocess


class UserSystemdServiceManager:
    def __init__(self, *, logger) -> None:
        self._logger = logger
        self._backend_unit = "synthia-ai-node-backend.service"
        self._frontend_unit = "synthia-ai-node-frontend.service"

    def get_status(self) -> dict:
        backend = self._query_active(self._backend_unit)
        frontend = self._query_active(self._frontend_unit)
        node = "running" if backend == "running" and frontend == "running" else "degraded"
        if backend == "unknown" and frontend == "unknown":
            node = "unknown"
        return {
            "backend": backend,
            "frontend": frontend,
            "node": node,
        }

    def restart(self, *, target: str) -> dict:
        value = str(target or "").strip().lower()
        if value == "backend":
            self._restart_unit(self._backend_unit)
            return {"target": "backend", "result": "restarted"}
        if value == "frontend":
            self._restart_unit(self._frontend_unit)
            return {"target": "frontend", "result": "restarted"}
        if value == "node":
            self._restart_unit(self._backend_unit)
            self._restart_unit(self._frontend_unit)
            return {"target": "node", "result": "restarted"}
        raise ValueError("unsupported restart target")

    def _query_active(self, unit: str) -> str:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                check=False,
                capture_output=True,
                text=True,
            )
            status = str((result.stdout or "").strip()).lower()
            if status == "active":
                return "running"
            if status in {"inactive", "deactivating"}:
                return "stopped"
            if status in {"failed", "activating"}:
                return "failed"
            return "unknown"
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[service-status-check-failed] %s", {"unit": unit, "error": str(exc)})
            return "unknown"

    def _restart_unit(self, unit: str) -> None:
        subprocess.run(
            ["systemctl", "--user", "restart", unit],
            check=True,
            capture_output=True,
            text=True,
        )


class NullServiceManager:
    def get_status(self) -> dict:
        return {"backend": "unknown", "frontend": "unknown", "node": "unknown"}

    def restart(self, *, target: str) -> dict:
        raise ValueError("service manager is not configured")
