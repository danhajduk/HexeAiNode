from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


ContainerState = Literal["stopped", "starting", "running", "unhealthy", "unknown"]
ModelState = Literal["unloaded", "loading", "loaded", "unloading", "failed", "unsupported"]


def normalize_container_state(value: object) -> ContainerState:
    normalized = str(value or "").strip().lower()
    if normalized in {"running", "up", "healthy"}:
        return "running"
    if normalized in {"starting", "created", "restarting"}:
        return "starting"
    if normalized in {"unhealthy", "failed", "error"}:
        return "unhealthy"
    if normalized in {"stopped", "exited", "dead", "missing", "not_found"}:
        return "stopped"
    return "unknown"


def normalize_model_state(value: object) -> ModelState:
    normalized = str(value or "").strip().lower()
    if normalized in {"loaded", "model_loaded", "ready", "running"}:
        return "loaded"
    if normalized in {"loading", "model_loading", "starting"}:
        return "loading"
    if normalized in {"unloading", "model_unloading", "stopping"}:
        return "unloading"
    if normalized in {"failed", "error", "unhealthy"}:
        return "failed"
    if normalized in {"unsupported", "not_supported"}:
        return "unsupported"
    if normalized in {"unloaded", "model_unloaded", "stopped", "cold", "on_demand", ""}:
        return "unloaded"
    return "unsupported"


@dataclass(frozen=True)
class ModelResidencyStatus:
    component_id: str
    adapter_id: str
    container_state: ContainerState
    model_state: ModelState
    loaded_model: str | None = None
    loaded_models: list[str] = field(default_factory=list)
    observed_vram_mib: int | None = None
    active_jobs: int = 0
    can_load_model: bool = False
    can_unload_model: bool = False
    unload_model_mode: str | None = None
    last_transition_at: str | None = None
    last_transition_reason: str | None = None
    reason: str | None = None

    def to_payload(self) -> dict:
        loaded_models = [str(item) for item in self.loaded_models if str(item or "").strip()]
        loaded_model = self.loaded_model or (loaded_models[0] if loaded_models else None)
        return {
            "component_id": self.component_id,
            "adapter_id": self.adapter_id,
            "container_state": self.container_state,
            "model_state": self.model_state,
            "loaded_model": loaded_model,
            "loaded_models": loaded_models,
            "observed_vram_mib": self.observed_vram_mib,
            "active_jobs": max(int(self.active_jobs), 0),
            "can_load_model": bool(self.can_load_model),
            "can_unload_model": bool(self.can_unload_model),
            "unload_model_mode": self.unload_model_mode,
            "last_transition_at": self.last_transition_at,
            "last_transition_reason": self.last_transition_reason,
            "reason": self.reason,
        }


class ModelResidencyAdapter(Protocol):
    component_id: str

    def ensure_container_running(self, component_id: str) -> dict:
        ...

    def load_model(self, component_id: str, model_id: str | None = None, metadata: dict | None = None) -> dict:
        ...

    def unload_model(self, component_id: str, metadata: dict | None = None) -> dict:
        ...

    def model_residency_status(self, component_id: str) -> dict:
        ...
