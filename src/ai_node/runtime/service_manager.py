import os
import shlex
import subprocess


class UserSystemdServiceManager:
    def __init__(self, *, logger) -> None:
        self._logger = logger
        self._backend_unit = "synthia-ai-node-backend.service"
        self._frontend_unit = "synthia-ai-node-frontend.service"
        uid = os.getuid()
        self._runtime_dir = f"/run/user/{uid}"
        self._bus_address = f"unix:path={self._runtime_dir}/bus"

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

    def schedule_restart(self, *, target: str, delay_seconds: int) -> dict:
        value = str(target or "").strip().lower()
        delay = max(int(delay_seconds), 0)
        if value == "backend":
            unit = self._backend_unit
        elif value == "frontend":
            unit = self._frontend_unit
        else:
            raise ValueError("unsupported scheduled restart target")
        command = f"sleep {delay}; systemctl --user restart {shlex.quote(unit)}"
        subprocess.Popen(
            ["bash", "-lc", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self._systemd_env(),
            start_new_session=True,
        )
        return {"target": value, "result": "scheduled", "delay_seconds": delay}

    def _query_active(self, unit: str) -> str:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                check=False,
                capture_output=True,
                text=True,
                env=self._systemd_env(),
            )
            status = str((result.stdout or "").strip()).lower()
            if not status and "failed to connect to bus" in str((result.stderr or "")).lower():
                if hasattr(self._logger, "warning"):
                    self._logger.warning(
                        "[service-status-bus-unavailable] %s",
                        {"unit": unit, "stderr": str(result.stderr).strip()},
                    )
            if status == "active":
                return "running"
            if status == "activating":
                return "running"
            if status in {"inactive", "deactivating"}:
                return "stopped"
            if status in {"failed"}:
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
            env=self._systemd_env(),
        )

    def _systemd_env(self) -> dict:
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", self._runtime_dir)
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", self._bus_address)
        return env


class NullServiceManager:
    def get_status(self) -> dict:
        return {"backend": "unknown", "frontend": "unknown", "node": "unknown"}

    def restart(self, *, target: str) -> dict:
        raise ValueError("service manager is not configured")

    def schedule_restart(self, *, target: str, delay_seconds: int) -> dict:
        raise ValueError("service manager is not configured")
