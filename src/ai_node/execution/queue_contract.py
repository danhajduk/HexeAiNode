from __future__ import annotations

from typing import Literal


QueueImportance = Literal["background", "low", "normal", "high", "critical"]
QueuePriority = Literal["background", "low", "normal", "high", "critical"]
QueueClass = Literal["interactive", "background", "scheduled"]
QueueRoutingPolicy = Literal["local_only", "local_preferred", "cloud_fallback", "cloud_only"]
RuntimeLane = Literal["cloud", "text_llm", "vision_llm", "visual_gpu", "visual_cpu", "training_runtime"]


RUNTIME_LANES: tuple[str, ...] = (
    "cloud",
    "text_llm",
    "vision_llm",
    "visual_gpu",
    "visual_cpu",
    "training_runtime",
)

LOCAL_RUNTIME_LANES: tuple[str, ...] = (
    "text_llm",
    "vision_llm",
    "visual_gpu",
    "visual_cpu",
    "training_runtime",
)

LANE_CAPACITY = {
    "cloud": {"max_active": 1, "max_staged": 1, "local_residency_required": False},
    "text_llm": {"max_active": 1, "max_staged": 1, "local_residency_required": True},
    "vision_llm": {"max_active": 1, "max_staged": 1, "local_residency_required": True},
    "visual_gpu": {"max_active": 1, "max_staged": 1, "local_residency_required": True},
    "visual_cpu": {"max_active": 1, "max_staged": 1, "local_residency_required": True},
    "training_runtime": {"max_active": 1, "max_staged": 1, "local_residency_required": True},
}

RESIDENCY_COMPONENT_BY_LANE = {
    "cloud": None,
    "text_llm": "text_llm",
    "vision_llm": "vision_llm",
    "visual_gpu": "visual_gpu",
    "visual_cpu": "visual_cpu",
    "training_runtime": "training_runtime",
}

QUEUE_LANE_ALIASES = {
    "cloud": "cloud",
    "cloud_queue": "cloud",
    "local": "text_llm",
    "text": "text_llm",
    "text_llm": "text_llm",
    "llamacpp": "text_llm",
    "llama_cpp": "text_llm",
    "vision": "vision_llm",
    "vision_llm": "vision_llm",
    "local_vision": "vision_llm",
    "visual": "visual_gpu",
    "visual_runtime": "visual_gpu",
    "visual_gpu": "visual_gpu",
    "comfyui": "visual_gpu",
    "comfyui_gpu": "visual_gpu",
    "gpu_comfyui": "visual_gpu",
    "visual_cpu": "visual_cpu",
    "comfyui_cpu": "visual_cpu",
    "cpu_comfyui": "visual_cpu",
    "training": "training_runtime",
    "training_runtime": "training_runtime",
    "sd_scripts": "training_runtime",
    "sd_scripts_training": "training_runtime",
}

TASK_FAMILY_DEFAULT_LANES = {
    "task.chat": "text_llm",
    "task.classification": "text_llm",
    "task.information_extraction": "text_llm",
    "task.reasoning": "text_llm",
    "task.sentiment_analysis": "text_llm",
    "task.streaming_response": "text_llm",
    "task.vision_analysis": "vision_llm",
    "task.image_generation": "visual_gpu",
    "task.generation.image": "visual_gpu",
    "task.avatar_generation": "visual_gpu",
    "task.lora_training": "training_runtime",
}


def normalize_runtime_lane(value: object, *, default: str = "text_llm") -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized:
        return default
    return QUEUE_LANE_ALIASES.get(normalized, normalized if normalized in RUNTIME_LANES else default)


def infer_runtime_lane(*, queue: object = None, task_family: object = None, requested_provider: object = None) -> str:
    queue_lane = normalize_runtime_lane(queue, default="")
    if queue_lane:
        if queue_lane == "text_llm" and str(task_family or "").strip().lower() == "task.vision_analysis":
            return "vision_llm"
        return queue_lane
    provider_lane = normalize_runtime_lane(requested_provider, default="")
    if provider_lane:
        return provider_lane
    task_key = str(task_family or "").strip().lower()
    return TASK_FAMILY_DEFAULT_LANES.get(task_key, "text_llm")


def lane_capacity(runtime_lane: object) -> dict:
    lane = normalize_runtime_lane(runtime_lane)
    return dict(LANE_CAPACITY.get(lane) or LANE_CAPACITY["text_llm"])


def residency_component_for_lane(runtime_lane: object) -> str | None:
    lane = normalize_runtime_lane(runtime_lane)
    return RESIDENCY_COMPONENT_BY_LANE.get(lane)


def lane_contract_snapshot() -> dict:
    return {
        lane: {
            "lane": lane,
            "residency_component_id": residency_component_for_lane(lane),
            **lane_capacity(lane),
        }
        for lane in RUNTIME_LANES
    }
