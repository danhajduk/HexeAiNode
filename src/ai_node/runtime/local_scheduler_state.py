import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Iterable

from ai_node.persistence.file_storage_lock import file_storage_lock, locked_json_temp_path
from ai_node.runtime.local_scheduler_policy import local_scheduler_policy_payload, plan_local_scheduler_request
from ai_node.time_utils import local_now_iso


LOCAL_SCHEDULER_STATE_SCHEMA_VERSION = "1.0"
LOCAL_SCHEDULER_STATS_SCHEMA_VERSION = "1.0"
LOCAL_SCHEDULER_STATS_EMA_ALPHA = 0.2
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
        "component_id": "visual_gpu",
        "display_name": "Visual Runtime GPU",
        "adapter_id": "comfyui_gpu",
        "state_filename": "visual_gpu.state.json",
        "legacy_state_filenames": ("visual_runtime.state.json", "comfyui.state.json"),
        "legacy_component_ids": ("visual_runtime", "comfyui"),
        "priority": 30,
    },
    {
        "component_id": "visual_cpu",
        "display_name": "Visual Runtime CPU",
        "adapter_id": "comfyui_cpu",
        "state_filename": "visual_cpu.state.json",
        "priority": 35,
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
        "usage_statistics": {},
        "last_transition": None,
        "last_error": None,
        "updated_at": _now_iso(),
    }


def create_local_scheduler_stats_state() -> dict:
    return {
        "schema_version": LOCAL_SCHEDULER_STATS_SCHEMA_VERSION,
        "components": {},
        "updated_at": _now_iso(),
    }


def _normalize_metric_map(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, raw in value.items():
        if isinstance(raw, bool):
            out[str(key)] = int(raw)
        elif isinstance(raw, (int, float)):
            out[str(key)] = raw
        elif raw is None:
            out[str(key)] = None
    return out


def _normalize_timing_stats(value: object) -> dict:
    if not isinstance(value, dict):
        return {"task_families": {}}
    task_families = value.get("task_families") if isinstance(value.get("task_families"), dict) else {}
    normalized_families = {}
    for task_family, entry in task_families.items():
        if not isinstance(entry, dict):
            continue
        normalized_families[str(task_family)] = {
            "sample_count": max(int(entry.get("sample_count") or 0), 0),
            "rolling_average_ms": _normalize_metric_map(entry.get("rolling_average_ms")),
            "rolling_max_ms": _normalize_metric_map(entry.get("rolling_max_ms")),
            "last_sample_ms": _normalize_metric_map(entry.get("last_sample_ms")),
            "last_updated_at": str(entry.get("last_updated_at") or "").strip() or None,
        }
    return {"task_families": normalized_families}


def normalize_local_scheduler_stats_state(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid_local_scheduler_stats_state")
    if str(data.get("schema_version") or "").strip() != LOCAL_SCHEDULER_STATS_SCHEMA_VERSION:
        raise ValueError("invalid_local_scheduler_stats_schema")
    components = data.get("components")
    if not isinstance(components, dict):
        raise ValueError("invalid_local_scheduler_stats_components")
    normalized_components = {}
    for component_id, entry in components.items():
        if not isinstance(entry, dict):
            continue
        normalized_components[str(component_id)] = {
            "component_id": str(entry.get("component_id") or component_id),
            "sample_count": max(int(entry.get("sample_count") or 0), 0),
            "current": _normalize_metric_map(entry.get("current")),
            "rolling_average": _normalize_metric_map(entry.get("rolling_average")),
            "rolling_max": _normalize_metric_map(entry.get("rolling_max")),
            "timing": _normalize_timing_stats(entry.get("timing")),
            "last_updated_at": str(entry.get("last_updated_at") or "").strip() or None,
        }
    return {
        "schema_version": LOCAL_SCHEDULER_STATS_SCHEMA_VERSION,
        "components": normalized_components,
        "updated_at": str(data.get("updated_at") or _now_iso()).strip() or _now_iso(),
    }


def normalize_local_scheduler_component_state(data: object, *, component: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid_local_scheduler_component_state")
    if str(data.get("schema_version") or "").strip() != LOCAL_SCHEDULER_STATE_SCHEMA_VERSION:
        raise ValueError("invalid_local_scheduler_component_state_schema")
    component_id = str(component.get("component_id") or "").strip()
    legacy_component_ids = {str(item or "").strip() for item in tuple(component.get("legacy_component_ids") or ())}
    if str(data.get("component_id") or "").strip() not in {"", component_id, *legacy_component_ids}:
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
            "usage_statistics": _safe_dict(data.get("usage_statistics")),
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

    def component_definition(self, component_id: str) -> dict | None:
        normalized = str(component_id or "").strip()
        return next((dict(component) for component in LOCAL_SCHEDULER_COMPONENTS if component["component_id"] == normalized), None)

    def update_desired_state(
        self,
        *,
        component_id: str,
        desired_state: str,
        request_metadata: dict | None = None,
        last_transition: dict | None = None,
        last_error: str | None = None,
    ) -> dict:
        component = self.component_definition(component_id)
        if component is None:
            raise ValueError("unknown_local_scheduler_component")
        payload = self.load_or_create_component(component)
        payload["desired_state"] = _safe_state(desired_state, default="unloaded")
        if request_metadata is not None:
            payload["request_metadata"] = _safe_dict(request_metadata)
        if last_transition is not None:
            payload["last_transition"] = _safe_dict(last_transition)
        payload["last_error"] = str(last_error or "").strip() or None
        return self.save_component(component, payload)

    def append_event(self, event: dict) -> None:
        path = self._state_dir / "events.log"
        payload = {**_safe_dict(event), "created_at": _now_iso()}
        with file_storage_lock(path):
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def status_from_services(self, *, services: dict) -> dict:
        stats = self.load_or_create_stats()
        components = []
        for component in LOCAL_SCHEDULER_COMPONENTS:
            persisted = self.load_or_create_component(component)
            observed = observed_component_state(component_id=str(component["component_id"]), services=services)
            component_stats = self.update_component_stats(
                stats=stats,
                component_id=str(component["component_id"]),
                sample=metrics_sample_from_observed(observed),
            )
            merged = {
                **persisted,
                "display_name": str(component.get("display_name") or persisted.get("display_name") or component["component_id"]),
                "adapter_id": str(component.get("adapter_id") or persisted.get("adapter_id") or "") or None,
                "desired_state": _policy_desired_state(
                    component_id=str(component["component_id"]),
                    persisted_desired=str(persisted.get("desired_state") or "unloaded"),
                    services=services,
                ),
                "observed_state": observed["observed_state"],
                "phase": observed["phase"],
                "blockers": observed["blockers"],
                "idle": {**persisted.get("idle", {}), **observed["idle"]},
                "resource_snapshot": observed["resource_snapshot"],
                "usage_statistics": component_stats,
            }
            components.append(self.save_component(component, merged))
        stats = self.save_stats(stats)
        payload = {
            "schema_version": LOCAL_SCHEDULER_STATE_SCHEMA_VERSION,
            "state_dir": str(self._state_dir),
            "components": components,
            "statistics": stats,
            "gpu_resources": _safe_dict(services.get("gpu_resources")),
            "updated_at": _now_iso(),
        }
        payload["policy"] = local_scheduler_policy_payload()
        payload["request_previews"] = {
            str(component["component_id"]): plan_local_scheduler_request(
                scheduler_status=payload,
                component_id=str(component["component_id"]),
            )
            for component in LOCAL_SCHEDULER_COMPONENTS
        }
        return payload

    @property
    def stats_path(self) -> Path:
        return self._state_dir / "stats.json"

    def load_stats(self) -> dict | None:
        path = self.stats_path
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return normalize_local_scheduler_stats_state(payload)
        except Exception as exc:
            if self._logger is not None:
                self._logger.warning("invalid local scheduler stats file %s: %s", path, exc)
            return None

    def save_stats(self, payload: dict) -> dict:
        normalized = normalize_local_scheduler_stats_state(payload)
        normalized["updated_at"] = _now_iso()
        path = self.stats_path
        with file_storage_lock(path):
            self._state_dir.mkdir(parents=True, exist_ok=True)
            temp_path = locked_json_temp_path(path)
            temp_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temp_path.replace(path)
        return normalized

    def load_or_create_stats(self) -> dict:
        payload = self.load_stats()
        if isinstance(payload, dict):
            return payload
        payload = create_local_scheduler_stats_state()
        return self.save_stats(payload)

    def update_component_stats(self, *, stats: dict, component_id: str, sample: dict) -> dict:
        normalized_stats = normalize_local_scheduler_stats_state(stats)
        components = normalized_stats.setdefault("components", {})
        existing = components.get(component_id)
        if not isinstance(existing, dict):
            existing = {
                "component_id": component_id,
                "sample_count": 0,
                "current": {},
                "rolling_average": {},
                "rolling_max": {},
                "timing": {"task_families": {}},
                "last_updated_at": None,
            }
        sample_count = max(int(existing.get("sample_count") or 0), 0) + 1
        previous_average = _normalize_metric_map(existing.get("rolling_average"))
        previous_max = _normalize_metric_map(existing.get("rolling_max"))
        current = _normalize_metric_map(sample)
        rolling_average = {}
        rolling_max = {}
        for key, value in current.items():
            if value is None:
                rolling_average[key] = previous_average.get(key)
                rolling_max[key] = previous_max.get(key)
                continue
            previous = previous_average.get(key)
            rolling_average[key] = value if not isinstance(previous, (int, float)) else round(
                (previous * (1.0 - LOCAL_SCHEDULER_STATS_EMA_ALPHA)) + (value * LOCAL_SCHEDULER_STATS_EMA_ALPHA),
                3,
            )
            previous_peak = previous_max.get(key)
            rolling_max[key] = value if not isinstance(previous_peak, (int, float)) else max(previous_peak, value)
        updated = {
            **existing,
            "component_id": component_id,
            "sample_count": sample_count,
            "current": current,
            "rolling_average": rolling_average,
            "rolling_max": rolling_max,
            "last_updated_at": _now_iso(),
        }
        components[component_id] = updated
        stats.clear()
        stats.update(normalized_stats)
        return updated

    def record_execution_timing(
        self,
        *,
        component_id: str,
        task_family: str,
        queued_duration_ms: float | int | None = None,
        execution_duration_ms: float | int | None = None,
        total_duration_ms: float | int | None = None,
    ) -> dict:
        stats = self.load_or_create_stats()
        component_key = str(component_id or "").strip()
        task_key = str(task_family or "unknown").strip() or "unknown"
        components = stats.setdefault("components", {})
        component = components.setdefault(
            component_key,
            {
                "component_id": component_key,
                "sample_count": 0,
                "current": {},
                "rolling_average": {},
                "rolling_max": {},
                "timing": {"task_families": {}},
                "last_updated_at": None,
            },
        )
        timing = component.setdefault("timing", {"task_families": {}})
        families = timing.setdefault("task_families", {})
        entry = families.setdefault(
            task_key,
            {
                "sample_count": 0,
                "rolling_average_ms": {},
                "rolling_max_ms": {},
                "last_sample_ms": {},
                "last_updated_at": None,
            },
        )
        sample = _normalize_metric_map(
            {
                "queued_duration_ms": queued_duration_ms,
                "execution_duration_ms": execution_duration_ms,
                "total_duration_ms": total_duration_ms,
            }
        )
        previous_average = _normalize_metric_map(entry.get("rolling_average_ms"))
        previous_max = _normalize_metric_map(entry.get("rolling_max_ms"))
        rolling_average = {}
        rolling_max = {}
        for key, value in sample.items():
            if value is None:
                continue
            previous = previous_average.get(key)
            rolling_average[key] = value if not isinstance(previous, (int, float)) else round(
                (previous * (1.0 - LOCAL_SCHEDULER_STATS_EMA_ALPHA)) + (value * LOCAL_SCHEDULER_STATS_EMA_ALPHA),
                3,
            )
            previous_peak = previous_max.get(key)
            rolling_max[key] = value if not isinstance(previous_peak, (int, float)) else max(previous_peak, value)
        entry.update(
            {
                "sample_count": max(int(entry.get("sample_count") or 0), 0) + 1,
                "rolling_average_ms": {**previous_average, **rolling_average},
                "rolling_max_ms": {**previous_max, **rolling_max},
                "last_sample_ms": sample,
                "last_updated_at": _now_iso(),
            }
        )
        component["last_updated_at"] = _now_iso()
        return self.save_stats(stats)


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
        "vram_mib": _numeric(service.get("vram_mib")),
        "gpu_util_percent": _numeric(service.get("gpu_util_percent")),
        "gpu_mem_util_percent": _numeric(service.get("gpu_mem_util_percent")),
    }


def _aggregate_resource_metrics(entries: list[dict]) -> dict:
    resources = []
    seen_pids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        resource = _resource_from_service(entry)
        pid = resource.get("pid")
        if isinstance(pid, int) and pid > 0:
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
        resources.append(resource)
    vram_values = [value for value in (resource.get("vram_mib") for resource in resources) if isinstance(value, (int, float))]
    gpu_values = [
        value for value in (resource.get("gpu_util_percent") for resource in resources) if isinstance(value, (int, float))
    ]
    gpu_mem_values = [
        value for value in (resource.get("gpu_mem_util_percent") for resource in resources) if isinstance(value, (int, float))
    ]
    cpu_values = [value for value in (resource.get("cpu_percent") for resource in resources) if isinstance(value, (int, float))]
    mem_values = [value for value in (resource.get("mem_percent") for resource in resources) if isinstance(value, (int, float))]
    metrics = {}
    if vram_values:
        metrics["vram_mib"] = sum(vram_values)
    if gpu_values:
        metrics["gpu_util_percent"] = max(gpu_values)
    if gpu_mem_values:
        metrics["gpu_mem_util_percent"] = max(gpu_mem_values)
    if cpu_values:
        metrics["cpu_percent"] = min(sum(cpu_values), 100.0)
    if mem_values:
        metrics["mem_percent"] = min(sum(mem_values), 100.0)
    return metrics


def _policy_desired_state(*, component_id: str, persisted_desired: str, services: dict) -> str:
    normalized = _safe_state(persisted_desired, default="unloaded")
    if component_id == "text_llm":
        service = services.get("local_llm") if isinstance(services.get("local_llm"), dict) else {}
        always_on = service.get("always_on") if isinstance(service.get("always_on"), dict) else {}
        if always_on.get("enabled"):
            return "running"
    if component_id == "vision_llm":
        service = services.get("vision_llm") if isinstance(services.get("vision_llm"), dict) else {}
        residency = service.get("residency") if isinstance(service.get("residency"), dict) else {}
        if residency.get("enabled"):
            return "running"
    return normalized


def metrics_sample_from_observed(observed: dict) -> dict:
    resource = observed.get("resource_snapshot") if isinstance(observed.get("resource_snapshot"), dict) else {}
    idle = observed.get("idle") if isinstance(observed.get("idle"), dict) else {}
    return {
        "vram_mib": resource.get("vram_mib"),
        "gpu_util_percent": resource.get("gpu_util_percent"),
        "gpu_mem_util_percent": resource.get("gpu_mem_util_percent"),
        "cpu_percent": resource.get("cpu_percent"),
        "ram_percent": resource.get("mem_percent") if resource.get("mem_percent") is not None else resource.get("ram_percent"),
        "active": 1 if bool(idle.get("active")) else 0,
        "in_flight": idle.get("in_flight") if isinstance(idle.get("in_flight"), (int, float)) else 0,
        "queued": idle.get("queued") if isinstance(idle.get("queued"), (int, float)) else 0,
    }


def _aggregate_visual_runtime(services: dict, *, runtime: str) -> tuple[str, str, list, dict]:
    runtime_key = "cpu" if str(runtime or "").strip().lower() == "cpu" else "gpu"
    service_key = f"comfyui_{runtime_key}"
    webui = services.get("comfyui_webui") if isinstance(services.get("comfyui_webui"), dict) else {}
    webui_session = webui.get("session") if isinstance(webui.get("session"), dict) else {}
    webui_runtime = str(webui_session.get("runtime") or webui.get("runtime") or "").strip().lower()
    entries = [
        services.get(service_key) if isinstance(services.get(service_key), dict) else {},
    ]
    if webui_runtime == runtime_key:
        entries.append(webui)
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
    running_count = 0
    pending_count = 0
    queue_active = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        session = entry.get("session") if isinstance(entry.get("session"), dict) else {}
        try:
            running_count = max(running_count, int(session.get("running_count") or 0))
        except Exception:
            pass
        try:
            pending_count = max(pending_count, int(session.get("pending_count") or 0))
        except Exception:
            pass
        queue_active = queue_active or bool(session.get("queue_active"))
    return observed, "runtime_observed", [], {
        "runtimes": active_entries,
        "queue_active": queue_active,
        "running_count": running_count,
        "pending_count": pending_count,
        **_aggregate_resource_metrics(entries),
    }


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
    if component_id in {"visual_gpu", "visual_cpu"}:
        observed, phase, blockers, resource_snapshot = _aggregate_visual_runtime(
            services,
            runtime="cpu" if component_id == "visual_cpu" else "gpu",
        )
        return {
            "observed_state": observed,
            "phase": phase,
            "blockers": blockers,
            "idle": {
                "active": observed in {"running", "starting"} or bool(resource_snapshot.get("queue_active")),
                "in_flight": resource_snapshot.get("running_count") if isinstance(resource_snapshot.get("running_count"), int) else 0,
                "queued": resource_snapshot.get("pending_count") if isinstance(resource_snapshot.get("pending_count"), int) else 0,
            },
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
