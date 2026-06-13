from __future__ import annotations

from copy import deepcopy


LOCAL_SCHEDULER_PRIORITY_ORDER = ("text_llm", "vision_llm", "visual_gpu", "visual_cpu", "training_runtime")
LOCAL_SCHEDULER_PRIORITY = {component_id: index for index, component_id in enumerate(LOCAL_SCHEDULER_PRIORITY_ORDER)}
LOCAL_SCHEDULER_BACKGROUND_COMPONENTS = {"visual_gpu", "visual_cpu", "training_runtime"}
LOCAL_SCHEDULER_IMPORTANCE_VALUES = {"low", "normal", "high", "critical"}
LOCAL_SCHEDULER_RESERVED_VRAM_MIB = {
    "visual_gpu": 5 * 1024,
    "training_runtime": 9 * 1024,
}


def normalize_scheduler_importance(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in LOCAL_SCHEDULER_IMPORTANCE_VALUES else "normal"


def _components_by_id(scheduler_status: dict) -> dict[str, dict]:
    components = scheduler_status.get("components") if isinstance(scheduler_status, dict) else []
    out = {}
    for component in components if isinstance(components, list) else []:
        if isinstance(component, dict):
            component_id = str(component.get("component_id") or "").strip()
            if component_id:
                out[component_id] = component
    return out


def _observed_state(component: dict | None) -> str:
    return str((component or {}).get("observed_state") or "unknown").strip().lower()


def _model_state(component: dict | None) -> str:
    return str((component or {}).get("model_state") or "").strip().lower()


def _is_resident(component: dict | None) -> bool:
    model_state = _model_state(component)
    if model_state:
        return model_state in {"loaded", "loading", "unloading"}
    return _observed_state(component) in {"running", "starting", "idle", "paused", "pausing"}


def _is_busy(component: dict | None) -> bool:
    idle = (component or {}).get("idle") if isinstance((component or {}).get("idle"), dict) else {}
    try:
        in_flight = int(idle.get("in_flight") or 0)
    except Exception:
        in_flight = 0
    try:
        queued = int(idle.get("queued") or 0)
    except Exception:
        queued = 0
    return bool(
        in_flight > 0
        or queued > 0
        or _observed_state(component) in {"starting", "pausing", "unloading"}
        or _model_state(component) in {"loading", "unloading"}
    )


def _component_vram_mib(component: dict | None) -> float:
    stats = component.get("usage_statistics") if isinstance(component, dict) and isinstance(component.get("usage_statistics"), dict) else {}
    current = stats.get("current") if isinstance(stats.get("current"), dict) else {}
    value = current.get("vram_mib")
    return float(value) if isinstance(value, (int, float)) and value > 0 else 0.0


def _gpu_free_mib(scheduler_status: dict) -> float | None:
    resources = scheduler_status.get("gpu_resources") if isinstance(scheduler_status, dict) else {}
    value = resources.get("memory_free_mib") if isinstance(resources, dict) else None
    return float(value) if isinstance(value, (int, float)) and value >= 0 else None


def local_scheduler_policy_payload() -> dict:
    return {
        "priority_order": list(LOCAL_SCHEDULER_PRIORITY_ORDER),
        "background_components": sorted(LOCAL_SCHEDULER_BACKGROUND_COMPONENTS),
        "decision_outputs": [
            "allowed",
            "blocked",
            "needs_unload",
            "needs_pause",
            "waiting_for_idle",
            "insufficient_resources",
        ],
        "rules": [
            "Text LLM and Vision LLM are resident by default.",
            "Visual Runtime GPU reserves 5 GiB VRAM before job admission.",
            "Visual Runtime CPU does not reserve GPU VRAM unless a later template policy explicitly requires it.",
            "Training Runtime reserves 9 GiB VRAM before job admission.",
            "Vision LLM unloads before GPU-heavy visual or training work when more VRAM is needed.",
            "Text LLM unloads only as a last resort when the requested GPU runtime still cannot fit.",
            "Visual Runtime GPU, Visual Runtime CPU, and Training Runtime are background workloads by default.",
            "Visual Runtime GPU/CPU and Training Runtime do not run together unless a later policy explicitly allows it.",
        ],
        "reserved_vram_mib": dict(LOCAL_SCHEDULER_RESERVED_VRAM_MIB),
    }


def plan_local_scheduler_request(
    *,
    scheduler_status: dict,
    component_id: str,
    importance: str | None = None,
) -> dict:
    requested = str(component_id or "").strip()
    components = _components_by_id(scheduler_status)
    priority = LOCAL_SCHEDULER_PRIORITY.get(requested)
    if priority is None:
        return {
            "decision": "blocked",
            "component_id": requested,
            "importance": normalize_scheduler_importance(importance),
            "reason": "unknown_component",
            "affected_components": [],
            "actions": [],
        }
    normalized_importance = normalize_scheduler_importance(importance)
    affected = []
    actions = []
    reasons = []

    visual_gpu = components.get("visual_gpu")
    visual_cpu = components.get("visual_cpu")
    training = components.get("training_runtime")
    vision = components.get("vision_llm")
    text = components.get("text_llm")
    gpu_free_mib = _gpu_free_mib(scheduler_status)

    def _require_unload(other_id: str, reason: str) -> None:
        other = components.get(other_id)
        if not _is_resident(other) or other_id in affected:
            return
        affected.append(other_id)
        if _is_busy(other):
            actions.append({"action": "wait_for_idle", "component_id": other_id, "reason": reason})
            reasons.append(f"{other_id}_busy")
        else:
            actions.append({"action": "unload", "component_id": other_id, "reason": reason})
            reasons.append(reason)

    def _ensure_vram_for_runtime(runtime_id: str, unload_order: tuple[str, ...]) -> None:
        required = LOCAL_SCHEDULER_RESERVED_VRAM_MIB.get(runtime_id)
        if not isinstance(required, int):
            return
        if gpu_free_mib is None:
            reasons.append("gpu_free_vram_unknown")
            return
        planned_free = gpu_free_mib
        if planned_free >= required:
            reasons.append(f"{runtime_id}_vram_budget_available")
            return
        for other_id in unload_order:
            if planned_free >= required:
                break
            other = components.get(other_id)
            if not _is_resident(other):
                continue
            if other_id in affected:
                planned_free += _component_vram_mib(other)
                continue
            before_count = len(actions)
            _require_unload(other_id, f"{runtime_id}_requires_{other_id}_vram")
            if len(actions) > before_count:
                planned_free += _component_vram_mib(other)
        if planned_free < required:
            actions.append(
                {
                    "action": "wait_for_resources",
                    "component_id": runtime_id,
                    "reason": f"{runtime_id}_vram_budget_unavailable",
                    "required_vram_mib": required,
                    "planned_free_vram_mib": int(planned_free),
                }
            )
            reasons.append(f"{runtime_id}_vram_budget_unavailable")

    if requested == "text_llm":
        for visual_id, visual in (("visual_gpu", visual_gpu), ("visual_cpu", visual_cpu)):
            if _is_resident(visual):
                actions.append({"action": "wait_for_idle", "component_id": visual_id, "reason": f"text_llm_waits_for_{visual_id}"})
                affected.append(visual_id)
                reasons.append(f"{visual_id}_resident")
        if _is_resident(training) and _is_busy(training):
            actions.append({"action": "wait_for_idle", "component_id": "training_runtime", "reason": "text_llm_priority"})
            affected.append("training_runtime")
            reasons.append("training_runtime_busy")
    elif requested == "vision_llm":
        _require_unload("visual_gpu", "vision_requires_visual_gpu_unloaded")
        _require_unload("visual_cpu", "vision_requires_visual_cpu_unloaded")
        _require_unload("training_runtime", "vision_requires_training_runtime_unloaded")
    elif requested == "visual_gpu":
        if _is_resident(training):
            _require_unload("training_runtime", "visual_gpu_requires_training_runtime_unloaded")
        _ensure_vram_for_runtime("visual_gpu", ("vision_llm", "text_llm"))
    elif requested == "visual_cpu":
        if _is_resident(training):
            _require_unload("training_runtime", "visual_cpu_requires_training_runtime_unloaded")
    elif requested == "training_runtime":
        _require_unload("visual_gpu", "training_runtime_requires_visual_gpu_unloaded")
        _require_unload("visual_cpu", "training_runtime_requires_visual_cpu_unloaded")
        _require_unload("vision_llm", "training_runtime_requires_vision_llm_unloaded")
        _require_unload("text_llm", "training_runtime_requires_text_llm_unloaded")
        _ensure_vram_for_runtime("training_runtime", ("vision_llm", "visual_gpu", "text_llm"))

    if any(action.get("action") == "wait_for_idle" for action in actions):
        decision = "waiting_for_idle"
    elif any(action.get("action") == "wait_for_resources" for action in actions):
        decision = "insufficient_resources"
    elif any(action.get("action") == "queue_background" for action in actions):
        decision = "blocked"
    elif any(action.get("action") == "unload" for action in actions):
        decision = "needs_unload"
    else:
        decision = "allowed"
        reasons.append("compatible")

    return {
        "decision": decision,
        "component_id": requested,
        "importance": normalized_importance,
        "reason": reasons[0] if reasons else "compatible",
        "reasons": reasons,
        "affected_components": sorted(set(affected), key=lambda item: LOCAL_SCHEDULER_PRIORITY.get(item, 999)),
        "actions": deepcopy(actions),
    }
