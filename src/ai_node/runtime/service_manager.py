import json
import os
import shlex
import socket
import subprocess
import time


LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID = "qwen3-8b-q4_k_m"
LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS = 900


def _env_int(name: str, *, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or "").strip() or default)
    except Exception:
        return default


class UserSystemdServiceManager:
    def __init__(self, *, logger) -> None:
        self._logger = logger
        self._backend_unit = "hexe-ai-node-backend.service"
        self._frontend_unit = "hexe-ai-node-frontend.service"
        self._local_llm_control_script = str(
            os.environ.get("HEXE_LOCAL_LLM_CONTROL_SCRIPT") or "scripts/llamacpp-control.sh"
        ).strip()
        self._local_llm_socket = str(
            os.environ.get("HEXE_PROVIDER_LOCAL_SOCKET") or os.environ.get("LLAMACPP_SOCKET_PATH") or "/run/hexe/ai-node/llamacpp.sock"
        ).strip()
        self._local_llm_health_socket = str(
            os.environ.get("LLAMACPP_HEALTH_SOCKET") or "/run/hexe/ai-node/llamacpp-health.sock"
        ).strip()
        self._local_llm_container_name = str(
            os.environ.get("LLAMACPP_CONTAINER_NAME") or "hexe-ai-node-llamacpp"
        ).strip()
        self._local_llm_models_config = str(
            os.environ.get("HEXE_LOCAL_LLM_MODELS_CONFIG") or "config/local-llm-models.json"
        ).strip()
        self._docker_bin = str(os.environ.get("DOCKER_BIN") or "docker").strip() or "docker"
        self._local_llm_default_model_id = (
            str(
                os.environ.get("HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID")
                or os.environ.get("HEXE_LOCAL_LLM_DEFAULT_MODEL_ID")
                or LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID
            ).strip()
            or LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID
        )
        self._local_llm_default_revert_idle_seconds = max(
            _env_int(
                "HEXE_LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS",
                default=LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS,
            ),
            0,
        )
        self._local_llm_last_non_default_model_id: str | None = None
        self._local_llm_last_non_default_used_at: float | None = None
        self._local_llm_revert_in_progress = False
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
            "local_llm": self._local_llm_status(),
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
        if value == "local_llm":
            self._run_local_llm_control("restart")
            return {"target": "local_llm", "result": "restarted"}
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
        if value == "local_llm":
            self._run_local_llm_control("start")
            return {"target": "local_llm", "result": "started"}
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
        if value == "local_llm":
            self._run_local_llm_control("stop")
            return {"target": "local_llm", "result": "stopped"}
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

    def is_local_llm_model(self, *, model_id: str | None) -> bool:
        normalized = str(model_id or "").strip()
        return bool(normalized and normalized in self._local_llm_model_map())

    def ensure_local_llm_model(self, *, model_id: str | None) -> dict:
        normalized = str(model_id or "").strip()
        if not normalized:
            raise ValueError("local llm model is required")
        model = self._local_llm_model_map().get(normalized)
        if model is None:
            raise ValueError("local llm model is not configured")
        active_models = self._active_local_llm_model_ids()
        if normalized in active_models:
            self.record_local_llm_model_use(model_id=normalized)
            return {
                "model_id": normalized,
                "switched": False,
                "load_seconds": 0.0,
                "active_model_ids": active_models,
            }

        env = dict(os.environ)
        env["LLAMACPP_MODEL_HF"] = f"{model['repo']}:{model['quantization']}"
        env["LLAMACPP_MODEL_ALIAS"] = normalized
        if model.get("ctx_size") is not None:
            env["LLAMACPP_CTX_SIZE"] = str(model["ctx_size"])
        started = time.perf_counter()
        self._run_local_llm_control("ready", env=env)
        load_seconds = round(time.perf_counter() - started, 3)
        active_after = self._active_local_llm_model_ids()
        if normalized not in active_after:
            raise RuntimeError("local llm model did not become active after switch")
        self.record_local_llm_model_use(model_id=normalized)
        return {
            "model_id": normalized,
            "switched": True,
            "load_seconds": load_seconds,
            "active_model_ids": active_after,
        }

    def record_local_llm_model_use(self, *, model_id: str | None) -> dict:
        normalized = str(model_id or "").strip()
        if not normalized:
            return self.local_llm_default_revert_status()
        if normalized == self._local_llm_default_model_id:
            self._local_llm_last_non_default_model_id = None
            self._local_llm_last_non_default_used_at = None
        else:
            self._local_llm_last_non_default_model_id = normalized
            self._local_llm_last_non_default_used_at = time.monotonic()
        return self.local_llm_default_revert_status(active_model_ids=[normalized])

    def local_llm_default_revert_status(
        self,
        *,
        active_model_ids: list[str] | None = None,
        local_in_flight: int = 0,
        queued_model_ids: list[str] | None = None,
    ) -> dict:
        active_models = list(active_model_ids) if isinstance(active_model_ids, list) else self._active_local_llm_model_ids()
        non_default_active = next(
            (model_id for model_id in active_models if str(model_id or "").strip() and model_id != self._local_llm_default_model_id),
            None,
        )
        if not non_default_active:
            self._local_llm_last_non_default_model_id = None
            self._local_llm_last_non_default_used_at = None
        elif self._local_llm_last_non_default_model_id != non_default_active or self._local_llm_last_non_default_used_at is None:
            self._local_llm_last_non_default_model_id = non_default_active
            self._local_llm_last_non_default_used_at = time.monotonic()

        idle_seconds = None
        if self._local_llm_last_non_default_used_at is not None:
            idle_seconds = max(time.monotonic() - self._local_llm_last_non_default_used_at, 0.0)
        queued_models = [str(item or "").strip() for item in list(queued_model_ids or []) if str(item or "").strip()]
        queued_needs_active = bool(non_default_active and non_default_active in set(queued_models))
        revert_enabled = self._local_llm_default_revert_idle_seconds > 0
        revert_due = bool(
            revert_enabled
            and non_default_active
            and idle_seconds is not None
            and idle_seconds >= self._local_llm_default_revert_idle_seconds
            and max(int(local_in_flight), 0) == 0
            and not queued_needs_active
            and not self._local_llm_revert_in_progress
        )
        reason = None
        if not revert_enabled:
            reason = "disabled"
        elif not non_default_active:
            reason = "default_active"
        elif max(int(local_in_flight), 0) > 0:
            reason = "local_work_in_flight"
        elif queued_needs_active:
            reason = "queued_work_needs_active_model"
        elif self._local_llm_revert_in_progress:
            reason = "revert_in_progress"
        elif not revert_due:
            reason = "idle_threshold_not_reached"
        return {
            "default_model_id": self._local_llm_default_model_id,
            "active_model_ids": active_models,
            "active_non_default_model_id": non_default_active,
            "idle_seconds": round(idle_seconds, 3) if idle_seconds is not None else None,
            "idle_threshold_seconds": self._local_llm_default_revert_idle_seconds,
            "revert_enabled": revert_enabled,
            "revert_due": revert_due,
            "revert_in_progress": self._local_llm_revert_in_progress,
            "local_in_flight": max(int(local_in_flight), 0),
            "queued_model_ids": queued_models,
            "reason": reason,
        }

    def local_llm_model_states_payload(
        self,
        *,
        active_model_ids: list[str] | None = None,
    ) -> dict:
        configured_models = self._local_llm_model_map()
        active_models = [
            str(item or "").strip()
            for item in (list(active_model_ids) if isinstance(active_model_ids, list) else self._active_local_llm_model_ids())
            if str(item or "").strip()
        ]
        active_set = set(active_models)
        runtime_ready = bool(
            self._local_llm_socket
            and self._local_llm_health_socket
            and os.path.exists(self._local_llm_socket)
            and os.path.exists(self._local_llm_health_socket)
        )
        models = []
        for model_id, model in configured_models.items():
            is_loaded = model_id in active_set
            if is_loaded:
                warmth_state = "loaded"
            elif active_set:
                warmth_state = "swap_required"
            elif runtime_ready and model_id == self._local_llm_default_model_id:
                warmth_state = "warm"
            else:
                warmth_state = "cold"
            health_state = "available" if model else "unavailable"
            if not runtime_ready and not is_loaded:
                health_state = "cold"
            models.append(
                {
                    "model_id": model_id,
                    "default": model_id == self._local_llm_default_model_id,
                    "health_state": health_state,
                    "warmth_state": warmth_state,
                    "loaded": is_loaded,
                    "swap_required": warmth_state == "swap_required",
                    "repo": model.get("repo"),
                    "quantization": model.get("quantization"),
                    "ctx_size": model.get("ctx_size"),
                }
            )
        return {
            "configured": bool(configured_models),
            "runtime_ready": runtime_ready,
            "active_model_ids": active_models,
            "default_model_id": self._local_llm_default_model_id,
            "models": models,
        }

    def revert_local_llm_to_default_if_idle(
        self,
        *,
        local_in_flight: int = 0,
        queued_model_ids: list[str] | None = None,
    ) -> dict:
        status = self.local_llm_default_revert_status(
            local_in_flight=local_in_flight,
            queued_model_ids=queued_model_ids,
        )
        if not status.get("revert_due"):
            return {"switched": False, **status}
        self._local_llm_revert_in_progress = True
        try:
            result = self.ensure_local_llm_model(model_id=self._local_llm_default_model_id)
        finally:
            self._local_llm_revert_in_progress = False
        return {"switched": bool(result.get("switched")), "switch_result": result, **self.local_llm_default_revert_status()}

    def _local_llm_status(self) -> dict:
        service_id = "local_llm"
        script_exists = os.path.exists(self._local_llm_control_script)
        llama_socket_ready = bool(self._local_llm_socket and os.path.exists(self._local_llm_socket))
        health_socket_ready = bool(self._local_llm_health_socket and os.path.exists(self._local_llm_health_socket))
        state = "running" if llama_socket_ready and health_socket_ready else "stopped"
        if not script_exists:
            state = "unknown"
        pid = self._query_local_llm_pid() if script_exists else 0
        cpu_percent = self._process_cpu_percent(service_id, pid)
        mem_percent = self._process_mem_percent(pid)
        active_model_ids = self._active_local_llm_model_ids()
        return {
            "service_id": service_id,
            "service_name": service_id,
            "state": state,
            "cpu_percent": cpu_percent,
            "mem_percent": mem_percent,
            "pid": pid or None,
            "boot_order": 30,
            "managed_by": "llamacpp-control",
            "control_script": self._local_llm_control_script,
            "container_name": self._local_llm_container_name or None,
            "socket_path": self._local_llm_socket or None,
            "health_socket_path": self._local_llm_health_socket or None,
            "default_model_id": self._local_llm_default_model_id,
            "default_revert": self.local_llm_default_revert_status(active_model_ids=active_model_ids),
            "model_states": self.local_llm_model_states_payload(active_model_ids=active_model_ids),
        }

    def _query_local_llm_pid(self) -> int:
        if not self._local_llm_container_name:
            return 0
        try:
            result = subprocess.run(
                [self._docker_bin, "inspect", "--format", "{{.State.Pid}}", self._local_llm_container_name],
                check=False,
                capture_output=True,
                text=True,
            )
            raw = str(result.stdout or "").strip()
            return max(int(raw or 0), 0)
        except Exception:
            return 0

    def _local_llm_model_map(self) -> dict[str, dict]:
        try:
            with open(self._local_llm_models_config, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return {}
        models = payload.get("models") if isinstance(payload, dict) else []
        out: dict[str, dict] = {}
        for item in models if isinstance(models, list) else []:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            repo = str(item.get("repo") or "").strip()
            quantization = str(item.get("quantization") or "").strip()
            if not model_id or not repo or not quantization:
                continue
            out[model_id] = {
                "repo": repo,
                "quantization": quantization,
                "ctx_size": item.get("ctx_size") if isinstance(item.get("ctx_size"), int) else None,
            }
        return out

    def _active_local_llm_model_ids(self) -> list[str]:
        if not self._local_llm_socket:
            return []
        try:
            request = b"GET /v1/models HTTP/1.1\r\nHost: llamacpp\r\nConnection: close\r\n\r\n"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5)
                client.connect(self._local_llm_socket)
                client.sendall(request)
                chunks: list[bytes] = []
                while True:
                    chunk = client.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
            raw = b"".join(chunks)
            _, _, body = raw.partition(b"\r\n\r\n")
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return []
        out: list[str] = []
        for key in ("models", "data"):
            entries = payload.get(key) if isinstance(payload, dict) else None
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                model_id = str(entry.get("id") or entry.get("model") or entry.get("name") or "").strip()
                if model_id and model_id not in out:
                    out.append(model_id)
        return out

    def _run_local_llm_control(self, command: str, *, env: dict | None = None) -> None:
        if not os.path.exists(self._local_llm_control_script):
            raise ValueError("local llm control script is not configured")
        subprocess.run(
            [self._local_llm_control_script, command],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

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
            "boot_order": 10 if service_id == "backend" else 20,
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
        subprocess.Popen(
            ["systemctl", "--user", "restart", unit],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self._systemd_env(),
            start_new_session=True,
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
        return {"backend": "unknown", "frontend": "unknown", "local_llm": "unknown", "node": "unknown"}

    def restart(self, *, target: str) -> dict:
        raise ValueError("service manager is not configured")

    def start(self, *, target: str) -> dict:
        raise ValueError("service manager is not configured")

    def stop(self, *, target: str) -> dict:
        raise ValueError("service manager is not configured")

    def schedule_restart(self, *, target: str, delay_seconds: int) -> dict:
        raise ValueError("service manager is not configured")

    def is_local_llm_model(self, *, model_id: str | None) -> bool:
        return False

    def ensure_local_llm_model(self, *, model_id: str | None) -> dict:
        raise ValueError("service manager is not configured")

    def record_local_llm_model_use(self, *, model_id: str | None) -> dict:
        return self.local_llm_default_revert_status()

    def local_llm_default_revert_status(
        self,
        *,
        active_model_ids: list[str] | None = None,
        local_in_flight: int = 0,
        queued_model_ids: list[str] | None = None,
    ) -> dict:
        return {
            "default_model_id": LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID,
            "active_model_ids": list(active_model_ids or []),
            "active_non_default_model_id": None,
            "idle_seconds": None,
            "idle_threshold_seconds": 0,
            "revert_enabled": False,
            "revert_due": False,
            "revert_in_progress": False,
            "local_in_flight": max(int(local_in_flight), 0),
            "queued_model_ids": list(queued_model_ids or []),
            "reason": "service_manager_unconfigured",
        }

    def local_llm_model_states_payload(
        self,
        *,
        active_model_ids: list[str] | None = None,
    ) -> dict:
        return {
            "configured": False,
            "runtime_ready": False,
            "active_model_ids": list(active_model_ids or []),
            "default_model_id": LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID,
            "models": [],
        }

    def revert_local_llm_to_default_if_idle(
        self,
        *,
        local_in_flight: int = 0,
        queued_model_ids: list[str] | None = None,
    ) -> dict:
        return {"switched": False, **self.local_llm_default_revert_status(local_in_flight=local_in_flight, queued_model_ids=queued_model_ids)}
