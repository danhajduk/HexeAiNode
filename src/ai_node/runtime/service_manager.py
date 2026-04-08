import os
import shlex
import subprocess


class UserSystemdServiceManager:
    def __init__(self, *, logger) -> None:
        self._logger = logger
        self._backend_unit = "synthia-ai-node-backend.service"
        self._frontend_unit = "synthia-ai-node-frontend.service"
        self._cpu_samples: dict[str, tuple[float, float]] = {}
        uid = os.getuid()
        self._runtime_dir = f"/run/user/{uid}"
        self._bus_address = f"unix:path={self._runtime_dir}/bus"

    def get_status(self) -> dict:
        backend = self._unit_status(self._backend_unit, service_id="backend")
        frontend = self._unit_status(self._frontend_unit, service_id="frontend")
        backend_state = backend.get("state") if isinstance(backend, dict) else "unknown"
        frontend_state = frontend.get("state") if isinstance(frontend, dict) else "unknown"
        node = "running" if backend_state == "running" and frontend_state == "running" else "degraded"
        if backend_state == "unknown" and frontend_state == "unknown":
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

    def start(self, *, target: str) -> dict:
        value = str(target or "").strip().lower()
        if value == "backend":
            self._start_unit(self._backend_unit)
            return {"target": "backend", "result": "started"}
        if value == "frontend":
            self._start_unit(self._frontend_unit)
            return {"target": "frontend", "result": "started"}
        if value == "node":
            self._start_unit(self._backend_unit)
            self._start_unit(self._frontend_unit)
            return {"target": "node", "result": "started"}
        raise ValueError("unsupported start target")

    def stop(self, *, target: str) -> dict:
        value = str(target or "").strip().lower()
        if value == "backend":
            self._stop_unit(self._backend_unit)
            return {"target": "backend", "result": "stopped"}
        if value == "frontend":
            self._stop_unit(self._frontend_unit)
            return {"target": "frontend", "result": "stopped"}
        if value == "node":
            self._stop_unit(self._backend_unit)
            self._stop_unit(self._frontend_unit)
            return {"target": "node", "result": "stopped"}
        raise ValueError("unsupported stop target")

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

    def _query_pid(self, unit: str) -> int:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "show", unit, "-p", "MainPID"],
                check=False,
                capture_output=True,
                text=True,
                env=self._systemd_env(),
            )
            raw = str(result.stdout or "").strip()
            if raw.startswith("MainPID="):
                pid_raw = raw.split("=", 1)[1].strip()
            else:
                pid_raw = raw
            return max(int(pid_raw or 0), 0)
        except Exception:
            return 0

    def _unit_status(self, unit: str, *, service_id: str) -> dict:
        state = self._query_active(unit)
        pid = self._query_pid(unit)
        cpu_percent = self._process_cpu_percent(unit, pid)
        mem_percent = self._process_mem_percent(pid)
        return {
            "service_id": service_id,
            "service_name": service_id,
            "state": state,
            "cpu_percent": cpu_percent,
            "mem_percent": mem_percent,
            "pid": pid or None,
        }

    def _process_cpu_percent(self, unit: str, pid: int) -> float | None:
        if pid <= 0:
            return None
        total = self._read_cpu_total()
        proc = self._read_process_cpu(pid)
        if total is None or proc is None:
            return None
        last = self._cpu_samples.get(unit)
        self._cpu_samples[unit] = (total, proc)
        if last is None:
            return None
        delta_total = total - last[0]
        delta_proc = proc - last[1]
        if delta_total <= 0 or delta_proc < 0:
            return None
        percent = (delta_proc / delta_total) * 100.0
        return max(0.0, min(100.0, round(percent, 2)))

    def _process_mem_percent(self, pid: int) -> float | None:
        if pid <= 0:
            return None
        total = self._read_mem_total()
        rss = self._read_process_rss(pid)
        if total is None or rss is None or total <= 0:
            return None
        percent = (rss / total) * 100.0
        return max(0.0, min(100.0, round(percent, 2)))

    @staticmethod
    def _read_cpu_total() -> float | None:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as handle:
                line = handle.readline()
        except OSError:
            return None
        if not line.startswith("cpu "):
            return None
        parts = line.strip().split()
        if len(parts) < 5:
            return None
        try:
            values = [float(item) for item in parts[1:]]
        except ValueError:
            return None
        return float(sum(values))

    @staticmethod
    def _read_process_cpu(pid: int) -> float | None:
        try:
            with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
                raw = handle.readline()
        except OSError:
            return None
        if not raw:
            return None
        parts = raw.strip().split()
        if len(parts) < 17:
            return None
        try:
            utime = float(parts[13])
            stime = float(parts[14])
        except ValueError:
            return None
        return utime + stime

    @staticmethod
    def _read_mem_total() -> float | None:
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                raw = handle.readlines()
        except OSError:
            return None
        for line in raw:
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        return float(parts[1]) * 1024.0
                    except ValueError:
                        return None
        return None

    @staticmethod
    def _read_process_rss(pid: int) -> float | None:
        try:
            with open(f"/proc/{pid}/statm", "r", encoding="utf-8") as handle:
                raw = handle.readline()
        except OSError:
            return None
        if not raw:
            return None
        parts = raw.strip().split()
        if len(parts) < 2:
            return None
        try:
            rss_pages = float(parts[1])
        except ValueError:
            return None
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError):
            page_size = 4096
        return rss_pages * float(page_size)

    def _restart_unit(self, unit: str) -> None:
        subprocess.run(
            ["systemctl", "--user", "restart", unit],
            check=True,
            capture_output=True,
            text=True,
            env=self._systemd_env(),
        )

    def _start_unit(self, unit: str) -> None:
        subprocess.run(
            ["systemctl", "--user", "start", unit],
            check=True,
            capture_output=True,
            text=True,
            env=self._systemd_env(),
        )

    def _stop_unit(self, unit: str) -> None:
        subprocess.run(
            ["systemctl", "--user", "stop", unit],
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

    def start(self, *, target: str) -> dict:
        raise ValueError("service manager is not configured")

    def stop(self, *, target: str) -> dict:
        raise ValueError("service manager is not configured")

    def schedule_restart(self, *, target: str, delay_seconds: int) -> dict:
        raise ValueError("service manager is not configured")
