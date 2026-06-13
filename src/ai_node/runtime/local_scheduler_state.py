import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Iterable

from ai_node.persistence.file_storage_lock import file_storage_lock, locked_json_temp_path
from ai_node.time_utils import local_now_iso


LOCAL_SCHEDULER_STATE_SCHEMA_VERSION = "1.0"
LOCAL_SCHEDULER_COMPONENTS = (
    {
        "component_id": "text_llm",
        "display_name": "Text LLM",
        "adapter_id": "llamacpp",
        "state_filename": "text_llm.state.json",
        "priority": 10,
    },
    {
        "component_id": "vision_llm",
        "display_name": "Vision LLM",
        "adapter_id": "llamacpp_vision",
        "state_filename": "vision_llm.state.json",
        "priority": 20,
    },
    {
        "component_id": "visual_runtime",
        "display_name": "Visual Runtime",
        "adapter_id": "comfyui",
        "state_filename": "visual_runtime.state.json",
        "legacy_state_filenames": ("comfyui.state.json",),
        "priority": 30,
    },
    {
        "component_id": "training_runtime",
        "display_name": "Training Runtime",
        "adapter_id": "sd_scripts",
        "state_filename": "training_runtime.state.json",
        "legacy_state_filenames": ("sd_scripts.state.json",),
        "priority": 40,
    },
)
LOCAL_SCHEDULER_ALLOWED_STATES = {
    "requested",
    "starting",
    "running",
    "idle",
    "pausing",
    "paused",
    "unloading",
    "unloaded",
    "stopped",
    "failed",
    "blocked",
    "unknown",
}


def default_local_scheduler_state_dir() -> Path:
    return Path(str(os.environ.get("HEXE_LOCAL_SCHEDULER_STATE_DIR") or ".run/local-scheduler")).resolve()


def _now_iso() -> str:
    return local_now_iso()


def _safe_state(value: object, *, default: str = "unknown") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in LOCAL_SCHEDULER_ALLOWED_STATES else default


def _safe_dict(value: object) -> dict:
    return deepcopy(value) if isinstance(value, dict) else {}


def _safe_list(value: object) -> list:
    return deepcopy(value) if isinstance(value, list) else []


def component_definitions() -> list[dict]:
    return [dict(item) for item in LOCAL_SCHEDULER_COMPONENTS]


def create_local_scheduler_component_state(
    *,
    component: dict,
    desired_state: str = "unloaded",
    observed_state: str = "unknown",
    phase: str = "unknown",
) -> dict:
    component_id = str(component.get("component_id") or "").strip()
    display_name = str(component.get("display_name") or component_id).strip() or component_id
    return {
        "schema_version": LOCAL_SCHEDULER_STATE_SCHEMA_VERSION,
        "component_id": component_id,
        "component_name": component_id,
        "display_name": display_name,
        "adapter_id": str(component.get("adapter_id") or "").strip() or None,
        "desired_state": _safe_state(desired_state, default="unloaded"),
        "observed_state": _safe_state(observed_state),
        "phase": str(phase or "unknown").strip() or "unknown",
        "request_metadata": {},
        "blockers": [],
        "idle": {
            "active": False,
            "in_flight": 0,
            "queued": 0,
            "last_active_at": None,
        },
        "resource_snapshot": {},
        "last_transition": None,
        "last_error": None,
        "updated_at": _now_iso(),
    }


def normalize_local_scheduler_component_state(data: object, *, component: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid_local_scheduler_component_state")
    if str(data.get("schema_version") or "").strip() != LOCAL_SCHEDULER_STATE_SCHEMA_VERSION:
        raise ValueError("invalid_local_scheduler_component_state_schema")
    component_id = str(component.get("component_id") or "").strip()
    if str(data.get("component_id") or "").strip() not in {"", component_id}:
        raise ValueError("local_scheduler_component_mismatch")
    normalized = create_local_scheduler_component_state(component=component)
    normalized.update(
        {
            "component_id": component_id,
            "component_name": str(data.get("component_name") or component_id).strip() or component_id,
            "display_name": str(data.get("display_name") or component.get("display_name") or component_id).strip()
            or component_id,
            "adapter_id": str(data.get("adapter_id") or component.get("adapter_id") or "").strip() or None,
            "desired_state": _safe_state(data.get("desired_state"), default="unloaded"),
            "observed_state": _safe_state(data.get("observed_state")),
            "phase": str(data.get("phase") or "unknown").strip() or "unknown",
            "request_metadata": _safe_dict(data.get("request_metadata")),
            "blockers": _safe_list(data.get("blockers")),
            "idle": {**normalized["idle"], **_safe_dict(data.get("idle"))},
            "resource_snapshot": _safe_dict(data.get("resource_snapshot")),
            "last_transition": _safe_dict(data.get("last_transition")) or None,
            "last_error": str(data.get("last_error") or "").strip() or None,
            "updated_at": str(data.get("updated_at") or _now_iso()).strip() or _now_iso(),
        }
    )
    return normalized


def _state_path(state_dir: Path, component: dict) -> Path:
    return state_dir / str(component.get("state_filename") or f"{component.get('component_id')}.state.json")


def _legacy_state_paths(state_dir: Path, component: dict) -> Iterable[Path]:
    for filename in tuple(component.get("legacy_state_filenames") or ()):
        yield state_dir / str(filename)


class LocalSchedulerStateStore:
    def __init__(self, *, state_dir: str | Path | None = None, logger=None) -> None:
        self._state_dir = Path(state_dir).resolve() if state_dir is not None else default_local_scheduler_state_dir()
        self._logger = logger

    @property
    def state_dir(self) -> Path:
        return self._state_dir

    def load_component(self, component: dict) -> dict | None:
        for path in (_state_path(self._state_dir, component), *_legacy_state_paths(self._state_dir, component)):
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return normalize_local_scheduler_component_state(payload, component=component)
            except Exception as exc:
                if self._logger is not None:
                    self._logger.warning("invalid local scheduler state file %s: %s", path, exc)
                return None
        return None

    def save_component(self, component: dict, payload: dict) -> dict:
        normalized = normalize_local_scheduler_component_state(payload, component=component)
        normalized["updated_at"] = _now_iso()
        path = _state_path(self._state_dir, component)
        with file_storage_lock(path):
            self._state_dir.mkdir(parents=True, exist_ok=True)
            temp_path = locked_json_temp_path(path)
            temp_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temp_path.replace(path)
        return normalized

    def load_or_create_component(self, component: dict) -> dict:
        loaded = self.load_component(component)
        if isinstance(loaded, dict):
            return loaded
        payload = create_local_scheduler_component_state(component=component)
        return self.save_component(component, payload)

    def status_from_services(self, *, services: dict) -> dict:
        components = []
        for component in LOCAL_SCHEDULER_COMPONENTS:
            persisted = self.load_or_create_component(component)
            observed = observed_component_state(component_id=str(component["component_id"]), services=services)
            merged = {
                **persisted,
                "display_name": str(component.get("display_name") or persisted.get("display_name") or component["component_id"]),
                "adapter_id": str(component.get("adapter_id") or persisted.get("adapter_id") or "") or None,
                "observed_state": observed["observed_state"],
                "phase": observed["phase"],
                "blockers": observed["blockers"],
                "idle": {**persisted.get("idle", {}), **observed["idle"]},
                "resource_snapshot": observed["resource_snapshot"],
            }
            components.append(self.save_component(component, merged))
        return {
            "schema_version": LOCAL_SCHEDULER_STATE_SCHEMA_VERSION,
            "state_dir": str(self._state_dir),
            "components": components,
            "updated_at": _now_iso(),
        }


def _service_state(service: object) -> str:
    return str(service.get("state") or "unknown").strip().lower() if isinstance(service, dict) else "unknown"


def _observed_from_service_state(state: str) -> str:
    if state in {"running", "healthy"}:
        return "running"
    if state in {"starting", "loading", "activating"}:
        return "starting"
    if state in {"failed", "error"}:
        return "failed"
    if state in {"blocked"}:
        return "blocked"
    if state in {"stopped", "not-found", "inactive"}:
        return "unloaded"
    return "unknown"


def _numeric(value: object) -> float | int | None:
    return value if isinstance(value, (int, float)) else None


def _resource_from_service(service: object) -> dict:
    if not isinstance(service, dict):
        return {}
    return {
        "pid": service.get("pid"),
        "cpu_percent": _numeric(service.get("cpu_percent")),
        "mem_percent": _numeric(service.get("mem_percent")),
    }


def _aggregate_visual_runtime(services: dict) -> tuple[str, str, list, dict]:
    entries = [
        services.get("comfyui_gpu") if isinstance(services.get("comfyui_gpu"), dict) else {},
        services.get("comfyui_cpu") if isinstance(services.get("comfyui_cpu"), dict) else {},
        services.get("comfyui_webui") if isinstance(services.get("comfyui_webui"), dict) else {},
    ]
    states = [_observed_from_service_state(_service_state(entry)) for entry in entries]
    if "running" in states:
        observed = "running"
    elif "starting" in states:
        observed = "starting"
    elif "failed" in states:
        observed = "failed"
    elif all(state == "unloaded" for state in states):
        observed = "unloaded"
    else:
        observed = "unknown"
    active_entries = [
        {
            "service_id": entry.get("service_id"),
            "state": entry.get("state"),
            "pid": entry.get("pid"),
            "runtime": entry.get("service_id"),
        }
        for entry in entries
        if isinstance(entry, dict) and _observed_from_service_state(_service_state(entry)) in {"running", "starting"}
    ]
    return observed, "runtime_observed", [], {"runtimes": active_entries}


def observed_component_state(*, component_id: str, services: dict) -> dict:
    gpu_exclusive = services.get("gpu_exclusive") if isinstance(services.get("gpu_exclusive"), dict) else {}
    if component_id == "text_llm":
        service = services.get("local_llm") if isinstance(services.get("local_llm"), dict) else {}
        observed = _observed_from_service_state(_service_state(service))
        blockers = list(gpu_exclusive.get("reasons") or []) if gpu_exclusive.get("local_llm_blocked") else []
        return {
            "observed_state": observed,
            "phase": str(service.get("state") or observed),
            "blockers": blockers,
            "idle": {"active": observed in {"running", "starting"}},
            "resource_snapshot": _resource_from_service(service),
        }
    if component_id == "vision_llm":
        service = services.get("vision_llm") if isinstance(services.get("vision_llm"), dict) else {}
        observed = _observed_from_service_state(_service_state(service))
        blockers = list(gpu_exclusive.get("reasons") or []) if gpu_exclusive.get("vision_llm_blocked") else []
        return {
            "observed_state": observed,
            "phase": str(service.get("state") or observed),
            "blockers": blockers,
            "idle": {"active": observed in {"running", "starting"}},
            "resource_snapshot": _resource_from_service(service),
        }
    if component_id == "visual_runtime":
        observed, phase, blockers, resource_snapshot = _aggregate_visual_runtime(services)
        return {
            "observed_state": observed,
            "phase": phase,
            "blockers": blockers,
            "idle": {"active": observed in {"running", "starting"}},
            "resource_snapshot": resource_snapshot,
        }
    if component_id == "training_runtime":
        active = bool(gpu_exclusive.get("sd_scripts_training_active"))
        return {
            "observed_state": "running" if active else "unloaded",
            "phase": "sd_scripts_training_active" if active else "idle",
            "blockers": [],
            "idle": {"active": active},
            "resource_snapshot": {"marker_active": active},
        }
    return {
        "observed_state": "unknown",
        "phase": "unknown",
        "blockers": [],
        "idle": {"active": False},
        "resource_snapshot": {},
    }
