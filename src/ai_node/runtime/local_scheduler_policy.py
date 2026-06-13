from __future__ import annotations

from copy import deepcopy


LOCAL_SCHEDULER_PRIORITY_ORDER = ("text_llm", "vision_llm", "visual_runtime", "training_runtime")
LOCAL_SCHEDULER_PRIORITY = {component_id: index for index, component_id in enumerate(LOCAL_SCHEDULER_PRIORITY_ORDER)}
LOCAL_SCHEDULER_BACKGROUND_COMPONENTS = {"visual_runtime", "training_runtime"}
LOCAL_SCHEDULER_IMPORTANCE_VALUES = {"low", "normal", "high", "critical"}


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


def _is_resident(component: dict | None) -> bool:
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
    return bool(in_flight > 0 or queued > 0 or _observed_state(component) in {"starting", "pausing", "unloading"})


def _runtime_can_coexist_with_text(component_id: str, components: dict[str, dict]) -> bool:
    if component_id != "training_runtime":
        return True
    text = components.get("text_llm")
    stats = text.get("usage_statistics") if isinstance(text, dict) and isinstance(text.get("usage_statistics"), dict) else {}
    current = stats.get("current") if isinstance(stats.get("current"), dict) else {}
    vram = current.get("vram_mib")
    # No measured VRAM means "do not force text off"; Task 998 can make a more exact executor decision.
    return not isinstance(vram, (int, float)) or vram < 7000


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
            "Text LLM has highest priority and should remain resident when possible.",
            "Vision LLM unloads before GPU-heavy visual or training work when idle.",
            "Visual Runtime and Training Runtime are background workloads by default.",
            "Background visual/training work waits instead of preempting foreground text/vision work.",
            "Visual Runtime and Training Runtime do not run together unless a later policy explicitly allows it.",
            "Training Runtime may coexist with Text LLM only when remembered/current resource budget allows it.",
        ],
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

    visual = components.get("visual_runtime")
    training = components.get("training_runtime")
    vision = components.get("vision_llm")
    text = components.get("text_llm")

    def _require_unload(other_id: str, reason: str) -> None:
        other = components.get(other_id)
        if not _is_resident(other):
            return
        affected.append(other_id)
        if _is_busy(other):
            actions.append({"action": "wait_for_idle", "component_id": other_id, "reason": reason})
            reasons.append(f"{other_id}_busy")
        else:
            actions.append({"action": "unload", "component_id": other_id, "reason": reason})
            reasons.append(reason)

    if requested == "text_llm":
        if _is_resident(training) and _is_busy(training):
            actions.append({"action": "wait_for_idle", "component_id": "training_runtime", "reason": "text_llm_priority"})
            affected.append("training_runtime")
            reasons.append("training_runtime_busy")
    elif requested == "vision_llm":
        _require_unload("visual_runtime", "vision_requires_visual_runtime_unloaded")
        _require_unload("training_runtime", "vision_requires_training_runtime_unloaded")
    elif requested == "visual_runtime":
        if _is_resident(training):
            _require_unload("training_runtime", "visual_runtime_requires_training_runtime_unloaded")
        if _is_resident(vision):
            if normalized_importance in {"high", "critical"}:
                _require_unload("vision_llm", "visual_runtime_high_importance_requires_vision_unloaded")
            else:
                affected.append("vision_llm")
                actions.append(
                    {
                        "action": "queue_background",
                        "component_id": "visual_runtime",
                        "reason": "foreground_vision_llm_resident",
                    }
                )
                reasons.append("background_waits_for_vision")
    elif requested == "training_runtime":
        _require_unload("visual_runtime", "training_runtime_requires_visual_runtime_unloaded")
        if _is_resident(vision):
            if normalized_importance in {"high", "critical"}:
                _require_unload("vision_llm", "training_runtime_high_importance_requires_vision_unloaded")
            else:
                affected.append("vision_llm")
                actions.append(
                    {
                        "action": "queue_background",
                        "component_id": "training_runtime",
                        "reason": "foreground_vision_llm_resident",
                    }
                )
                reasons.append("background_waits_for_vision")
        if _is_resident(text) and not _runtime_can_coexist_with_text("training_runtime", components):
            affected.append("text_llm")
            actions.append({"action": "wait_for_resources", "component_id": "text_llm", "reason": "text_llm_resource_budget"})
            reasons.append("text_llm_resource_budget")

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
