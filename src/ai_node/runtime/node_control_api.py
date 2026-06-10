import asyncio
import base64
import binascii
import html
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import time
import zlib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from ai_node.config.bootstrap_config import BOOTSTRAP_PORT, BOOTSTRAP_TOPIC, create_bootstrap_config
from ai_node.execution.gateway import ExecutionGateway
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.config.provider_credentials_config import summarize_provider_credentials
from ai_node.core_api.budget_declaration_client import BudgetDeclarationClient
from ai_node.core_api.trust_status_client import TrustStatusClient
from ai_node.providers.models import UnifiedExecutionRequest
from ai_node.providers.openai_model_catalog import select_representative_openai_model_ids
from ai_node.prompts import PromptRegistry
from ai_node.persistence.image_generation_template_store import (
    create_image_generation_template_registration,
    create_image_generation_template_state,
    normalize_image_generation_template_state,
    normalize_template_version,
)
from ai_node.config.task_capability_selection_config import DECLARABLE_TASK_FAMILIES, create_task_capability_selection_config
from ai_node.capabilities.task_families import canonicalize_task_family
from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.provider_resolver import ProviderResolutionRequest, ProviderResolver
from ai_node.runtime.internal_scheduler import InternalScheduler
from ai_node.runtime.comfyui_template_catalog import load_comfyui_template_catalog
from ai_node.runtime.service_manager import (
    LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID,
    NullServiceManager,
    VISION_LLM_BUILTIN_DEFAULT_MODEL_ID,
)
from ai_node.runtime.capability_resolver import load_task_graph
from ai_node.runtime.execution_telemetry import ExecutionTelemetryPublisher
from ai_node.runtime.execution_queue import ExecutionQueueService
from ai_node.runtime.prompt_construction import render_prompt_template
from ai_node.runtime.task_execution_service import TaskExecutionService
from ai_node.runtime.capability_declaration_runner import (
    STATUS_HEARTBEAT_INTERVAL_SECONDS,
    STATUS_TELEMETRY_INTERVAL_SECONDS,
)
from ai_node.supervisor import SupervisorApiClient
from ai_node.time_utils import local_now, local_now_iso

MANUAL_IMAGE_REFERENCE_STRENGTH_VARIABLES = (
    "face_strength",
    "body_strength",
    "body_conditioning_strength",
    "body_latent_strength",
    "body_depth_strength",
    "pose_strength",
)

MANUAL_IMAGE_DEFAULT_TEMPLATE_ID = "template.avatar_body_depth_reference_transparent.realvisxl.v1"
AVATAR_HEAD_FACE_PREVIEW_TEMPLATE_ID = "template.avatar_head_face_preview.realvisxl.v1"
AVATAR_HEAD_FACE_PREVIEW_HISTORY_LIMIT = 10
AVATAR_HEAD_FACE_PROMPT_PART_ORDER = (
    "general",
    "hair",
    "eyes",
    "eyebrows",
    "nose",
    "cheeks",
    "mouth",
    "jaw_chin",
    "ears",
    "skin",
    "expression",
    "style_lighting",
)
AVATAR_BODY_DEPTH_PROFILE_CLIENT_ID = "hexe-node-avatar-body-depth"

MANUAL_IMAGE_PROGRESS_NODE_LABELS = {
    "CheckpointLoaderSimple": ("loading", "Load checkpoint"),
    "LoraLoader": ("loading", "Apply LoRA"),
    "EmptyLatentImage": ("prepare", "Prepare latent"),
    "CLIPTextEncode": ("prompt", "Encode prompt"),
    "LoadImage": ("reference", "Load reference image"),
    "LoadImageMask": ("reference", "Load inpaint mask"),
    "PulidModelLoader": ("identity", "Load PuLID model"),
    "PulidEvaClipLoader": ("identity", "Load EVA-CLIP"),
    "PulidInsightFaceLoader": ("identity", "Analyze face identity"),
    "ApplyPulidAdvanced": ("identity", "Apply face identity"),
    "ResizeAndPadImage": ("body", "Fit body reference"),
    "DepthAnythingV2Preprocessor": ("body", "Build body depth map"),
    "ControlNetLoader": ("body", "Load depth ControlNet"),
    "ControlNetApplyAdvanced": ("body", "Apply body depth guidance"),
    "KSampler": ("sampling", "Sampling"),
    "VAEEncodeForInpaint": ("prepare", "Prepare inpaint latent"),
    "VAEDecode": ("decode", "Decode image"),
    "LoadBackgroundRemovalModel": ("background", "Load background remover"),
    "RemoveBackground": ("background", "Remove background"),
    "InvertMask": ("background", "Prepare alpha mask"),
    "JoinImageWithAlpha": ("background", "Attach alpha channel"),
    "SaveImage": ("saving", "Save output"),
}


class CapabilityDeclarationPrerequisiteError(ValueError):
    def __init__(self, *, payload: dict) -> None:
        self.payload = payload
        super().__init__(str(payload.get("message") or "capability declaration prerequisites are not satisfied"))


class LocalLlmBusyError(RuntimeError):
    pass


class DirectExecutionBusyError(RuntimeError):
    def __init__(self, *, payload: dict, retry_after_seconds: int, status_code: int = 503) -> None:
        self.payload = payload
        self.retry_after_seconds = max(int(retry_after_seconds), 1)
        self.status_code = int(status_code)
        super().__init__(str(payload.get("reason") or "direct_execution_busy"))


@dataclass(frozen=True)
class DirectExecutionAdmissionConfig:
    enabled: bool = True
    max_in_flight: int = 2
    dynamic_in_flight_enabled: bool = False
    min_effective_in_flight: int = 1
    min_memory_available_mb: int = 512
    warm_memory_available_mb: int = 8192
    hot_memory_available_mb: int = 2048
    max_swap_used_ratio: float = 0.95
    warm_swap_used_ratio: float = 0.5
    hot_swap_used_ratio: float = 0.8
    max_load_per_cpu: float = 2.0
    warm_load_per_cpu: float = 0.8
    hot_load_per_cpu: float = 1.5
    retry_after_seconds: int = 30

    @classmethod
    def from_env(cls) -> "DirectExecutionAdmissionConfig":
        return cls(
            enabled=_env_bool("HEXE_DIRECT_EXECUTION_ADMISSION_ENABLED", True),
            max_in_flight=max(_env_int("HEXE_DIRECT_EXECUTION_MAX_IN_FLIGHT", 2), 1),
            dynamic_in_flight_enabled=_env_bool("HEXE_DIRECT_EXECUTION_DYNAMIC_IN_FLIGHT_ENABLED", False),
            min_effective_in_flight=max(_env_int("HEXE_DIRECT_EXECUTION_MIN_EFFECTIVE_IN_FLIGHT", 1), 1),
            min_memory_available_mb=max(_env_int("HEXE_DIRECT_EXECUTION_MIN_MEMORY_AVAILABLE_MB", 512), 0),
            warm_memory_available_mb=max(_env_int("HEXE_DIRECT_EXECUTION_WARM_MEMORY_AVAILABLE_MB", 8192), 0),
            hot_memory_available_mb=max(_env_int("HEXE_DIRECT_EXECUTION_HOT_MEMORY_AVAILABLE_MB", 2048), 0),
            max_swap_used_ratio=max(0.0, _env_float("HEXE_DIRECT_EXECUTION_MAX_SWAP_USED_RATIO", 0.95)),
            warm_swap_used_ratio=max(0.0, _env_float("HEXE_DIRECT_EXECUTION_WARM_SWAP_USED_RATIO", 0.5)),
            hot_swap_used_ratio=max(0.0, _env_float("HEXE_DIRECT_EXECUTION_HOT_SWAP_USED_RATIO", 0.8)),
            max_load_per_cpu=max(0.0, _env_float("HEXE_DIRECT_EXECUTION_MAX_LOAD_PER_CPU", 2.0)),
            warm_load_per_cpu=max(0.0, _env_float("HEXE_DIRECT_EXECUTION_WARM_LOAD_PER_CPU", 0.8)),
            hot_load_per_cpu=max(0.0, _env_float("HEXE_DIRECT_EXECUTION_HOT_LOAD_PER_CPU", 1.5)),
            retry_after_seconds=max(_env_int("HEXE_DIRECT_EXECUTION_RETRY_AFTER_SECONDS", 30), 1),
        )

    def payload(self) -> dict:
        return {
            "enabled": self.enabled,
            "max_in_flight": self.max_in_flight,
            "configured_max_in_flight": self.max_in_flight,
            "dynamic_in_flight_enabled": self.dynamic_in_flight_enabled,
            "min_effective_in_flight": min(self.min_effective_in_flight, self.max_in_flight),
            "min_memory_available_mb": self.min_memory_available_mb,
            "warm_memory_available_mb": self.warm_memory_available_mb,
            "hot_memory_available_mb": self.hot_memory_available_mb,
            "max_swap_used_ratio": self.max_swap_used_ratio,
            "warm_swap_used_ratio": self.warm_swap_used_ratio,
            "hot_swap_used_ratio": self.hot_swap_used_ratio,
            "max_load_per_cpu": self.max_load_per_cpu,
            "warm_load_per_cpu": self.warm_load_per_cpu,
            "hot_load_per_cpu": self.hot_load_per_cpu,
            "retry_after_seconds": self.retry_after_seconds,
        }


@dataclass(frozen=True)
class DirectExecutionAdmissionDecision:
    accepted: bool
    reason: str | None
    retry_after_seconds: int
    resources: dict
    in_flight: int
    route: str
    effective_max_in_flight: int
    capacity_tier: str


class DirectExecutionAdmissionGuard:
    def __init__(self, *, config: DirectExecutionAdmissionConfig | None = None, resource_sampler=None, logger=None) -> None:
        self._config = config or DirectExecutionAdmissionConfig.from_env()
        self._resource_sampler = resource_sampler or self._sample_resources
        self._logger = logger
        self._lock = Lock()
        self._in_flight = 0
        self._accepted_count = 0
        self._rejected_count = 0
        self._route_counts: dict[str, dict[str, int]] = {}
        self._last_decision: DirectExecutionAdmissionDecision | None = None
        self._last_rejection: dict | None = None

    @property
    def config(self) -> DirectExecutionAdmissionConfig:
        return self._config

    def try_acquire(self, *, route: str = "direct") -> DirectExecutionAdmissionDecision:
        route_key = self._normalize_route(route)
        resources = self._resource_sampler()
        reason = self._rejection_reason(resources=resources)
        effective_max, capacity_tier = self._effective_capacity(resources=resources)
        with self._lock:
            route_counts = self._route_counts.setdefault(route_key, {"in_flight": 0, "accepted_count": 0, "rejected_count": 0})
            if self._config.enabled and reason is None and self._in_flight >= effective_max:
                reason = "max_in_flight_exceeded"
            if self._config.enabled and reason is not None:
                self._rejected_count += 1
                route_counts["rejected_count"] += 1
                decision = DirectExecutionAdmissionDecision(
                    accepted=False,
                    reason=reason,
                    retry_after_seconds=self._config.retry_after_seconds,
                    resources=resources,
                    in_flight=self._in_flight,
                    route=route_key,
                    effective_max_in_flight=effective_max,
                    capacity_tier=capacity_tier,
                )
                self._last_decision = decision
                self._last_rejection = self._decision_payload(decision)
                if hasattr(self._logger, "warning"):
                    self._logger.warning(
                        "[direct-execution-admission-rejected] %s",
                        {
                            "route": route_key,
                            "reason": reason,
                            "in_flight": self._in_flight,
                            "effective_max_in_flight": effective_max,
                            "capacity_tier": capacity_tier,
                            "retry_after_seconds": self._config.retry_after_seconds,
                            "resources": resources,
                        },
                    )
                return decision

            self._in_flight += 1
            self._accepted_count += 1
            route_counts["in_flight"] += 1
            route_counts["accepted_count"] += 1
            decision = DirectExecutionAdmissionDecision(
                accepted=True,
                reason=None,
                retry_after_seconds=0,
                resources=resources,
                in_flight=self._in_flight,
                route=route_key,
                effective_max_in_flight=effective_max,
                capacity_tier=capacity_tier,
            )
            self._last_decision = decision
            return decision

    def release(self, *, route: str = "direct") -> None:
        route_key = self._normalize_route(route)
        with self._lock:
            self._in_flight = max(self._in_flight - 1, 0)
            route_counts = self._route_counts.setdefault(route_key, {"in_flight": 0, "accepted_count": 0, "rejected_count": 0})
            route_counts["in_flight"] = max(route_counts.get("in_flight", 0) - 1, 0)

    def snapshot(self) -> dict:
        resources = self._resource_sampler()
        reason = self._rejection_reason(resources=resources)
        effective_max, capacity_tier = self._effective_capacity(resources=resources)
        with self._lock:
            would_accept = (not self._config.enabled) or (reason is None and self._in_flight < effective_max)
            return {
                "configured": True,
                "enabled": self._config.enabled,
                "would_accept_now": would_accept,
                "current_rejection_reason": None if would_accept else (reason or "max_in_flight_exceeded"),
                "in_flight": self._in_flight,
                "accepted_count": self._accepted_count,
                "rejected_count": self._rejected_count,
                "last_rejection": dict(self._last_rejection) if self._last_rejection else None,
                "route_counts": {key: dict(value) for key, value in sorted(self._route_counts.items())},
                "thresholds": {
                    **self._config.payload(),
                    "effective_max_in_flight": effective_max,
                    "capacity_tier": capacity_tier,
                },
                "resources": resources,
            }

    def busy_payload(self, *, decision: DirectExecutionAdmissionDecision) -> dict:
        return {
            "accepted": False,
            "status": "busy",
            "reason": decision.reason or "node_at_capacity",
            "retry_after_seconds": decision.retry_after_seconds,
            "in_flight": decision.in_flight,
            "route": decision.route,
            "effective_max_in_flight": decision.effective_max_in_flight,
            "capacity_tier": decision.capacity_tier,
            "resources": decision.resources,
        }

    def _decision_payload(self, decision: DirectExecutionAdmissionDecision) -> dict:
        return {
            "accepted": decision.accepted,
            "route": decision.route,
            "reason": decision.reason,
            "retry_after_seconds": decision.retry_after_seconds,
            "in_flight": decision.in_flight,
            "effective_max_in_flight": decision.effective_max_in_flight,
            "capacity_tier": decision.capacity_tier,
            "resources": decision.resources,
            "timestamp": local_now_iso(),
        }

    @staticmethod
    def _normalize_route(route: str) -> str:
        normalized = str(route or "").strip().lower().replace("/", "_").replace("-", "_")
        return normalized or "execution"

    def _effective_capacity(self, *, resources: dict) -> tuple[int, str]:
        max_in_flight = max(int(self._config.max_in_flight), 1)
        floor = min(max(int(self._config.min_effective_in_flight), 1), max_in_flight)
        if not self._config.dynamic_in_flight_enabled:
            return max_in_flight, "static"

        tier = "healthy"
        memory_available_mb = resources.get("memory_available_mb")
        if memory_available_mb is not None:
            if memory_available_mb <= self._config.hot_memory_available_mb:
                tier = "hot"
            elif memory_available_mb <= self._config.warm_memory_available_mb and tier == "healthy":
                tier = "warm"
        swap_used_ratio = resources.get("swap_used_ratio")
        if swap_used_ratio is not None:
            if swap_used_ratio >= self._config.hot_swap_used_ratio:
                tier = "hot"
            elif swap_used_ratio >= self._config.warm_swap_used_ratio and tier == "healthy":
                tier = "warm"
        load_per_cpu = resources.get("load_per_cpu")
        if load_per_cpu is not None:
            if load_per_cpu >= self._config.hot_load_per_cpu:
                tier = "hot"
            elif load_per_cpu >= self._config.warm_load_per_cpu and tier == "healthy":
                tier = "warm"

        if tier == "hot":
            return floor, tier
        if tier == "warm":
            return max(floor, (max_in_flight + 1) // 2), tier
        return max_in_flight, tier

    def _rejection_reason(self, *, resources: dict) -> str | None:
        if not self._config.enabled:
            return None
        memory_available_mb = resources.get("memory_available_mb")
        if memory_available_mb is not None and memory_available_mb < self._config.min_memory_available_mb:
            return "memory_available_below_floor"
        swap_used_ratio = resources.get("swap_used_ratio")
        if swap_used_ratio is not None and swap_used_ratio >= self._config.max_swap_used_ratio:
            return "swap_pressure_high"
        load_per_cpu = resources.get("load_per_cpu")
        if load_per_cpu is not None and load_per_cpu >= self._config.max_load_per_cpu:
            return "load_average_high"
        return None

    @staticmethod
    def _sample_resources() -> dict:
        memory = _read_memory_snapshot()
        load = _read_load_snapshot()
        return {**memory, **load}


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_memory_snapshot() -> dict:
    values: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                key = parts[0].rstrip(":")
                if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                    try:
                        values[key] = int(parts[1])
                    except ValueError:
                        continue
    except OSError:
        return {}

    total_memory_kb = values.get("MemTotal")
    available_memory_kb = values.get("MemAvailable")
    total_swap_kb = values.get("SwapTotal")
    free_swap_kb = values.get("SwapFree")
    payload: dict[str, int | float | None] = {}
    if total_memory_kb is not None:
        payload["memory_total_mb"] = round(total_memory_kb / 1024)
    if available_memory_kb is not None:
        payload["memory_available_mb"] = round(available_memory_kb / 1024)
    if total_swap_kb is not None:
        payload["swap_total_mb"] = round(total_swap_kb / 1024)
    if free_swap_kb is not None:
        payload["swap_free_mb"] = round(free_swap_kb / 1024)
    if total_swap_kb and free_swap_kb is not None and total_swap_kb > 0:
        payload["swap_used_ratio"] = round(max(total_swap_kb - free_swap_kb, 0) / total_swap_kb, 4)
    elif total_swap_kb == 0:
        payload["swap_used_ratio"] = 0.0
    return payload


def _read_load_snapshot() -> dict:
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except OSError:
        return {}
    cpu_count = os.cpu_count() or 1
    return {
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
        "cpu_count": cpu_count,
        "load_per_cpu": round(load_1m / cpu_count, 3),
    }


def _mask_grant_name(value: object) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) <= 10:
        return normalized[:2] + ("*" * max(len(normalized) - 4, 0)) + normalized[-2:]
    return normalized[:6] + ("*" * max(len(normalized) - 10, 1)) + normalized[-4:]


def _short_grant_name(value: object, *, scope_kind: object = None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    parts = [part for part in normalized.split(":") if part]
    scope = str(scope_kind or (parts[-1] if parts else "")).strip().lower() or "grant"
    candidate = parts[-2] if len(parts) >= 2 else normalized
    candidate_alnum = "".join(ch for ch in str(candidate) if ch.isalnum())
    suffix = candidate_alnum[-4:] if len(candidate_alnum) >= 4 else candidate_alnum
    if suffix:
        return f"{scope} {suffix}".strip()
    return scope


class NodeRuntimeMetrics:
    def __init__(self, *, window_s: float = 60.0, max_samples: int = 4000) -> None:
        self._window_s = float(window_s)
        self._max_samples = max(100, int(max_samples))
        self._samples: deque[tuple[float, float, bool]] = deque()
        self._lock = Lock()
        self._last_cpu_sample: tuple[float, float] | None = None

    def record_request(self, *, duration_ms: float, status_code: int) -> None:
        now = time.monotonic()
        is_error = int(status_code) >= 400
        with self._lock:
            self._samples.append((now, float(duration_ms), is_error))
            self._prune_locked(now)
            if len(self._samples) > self._max_samples:
                while len(self._samples) > self._max_samples:
                    self._samples.popleft()

    def snapshot(self) -> dict[str, float]:
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            durations = [item[1] for item in self._samples]
            count = len(durations)
            errors = sum(1 for item in self._samples if item[2])
            rps = (count / self._window_s) if self._window_s > 0 else 0.0
            p95 = self._p95_ms(durations)
            error_rate = (errors / count) if count else 0.0
            cpu_percent = self._process_cpu_percent_locked()
        mem_percent = self._process_mem_percent()
        payload: dict[str, float] = {
            "rps": round(rps, 2),
            "error_rate": round(error_rate, 3),
        }
        if p95 is not None:
            payload["latency_ms_p95"] = round(p95, 2)
        if cpu_percent is not None:
            payload["cpu_percent"] = round(cpu_percent, 2)
        if mem_percent is not None:
            payload["mem_percent"] = round(mem_percent, 2)
        return payload

    def _prune_locked(self, now: float) -> None:
        while self._samples and (now - self._samples[0][0]) > self._window_s:
            self._samples.popleft()

    def _p95_ms(self, durations: list[float]) -> float | None:
        if not durations:
            return None
        sorted_vals = sorted(durations)
        idx = max(0, int(round(0.95 * len(sorted_vals) + 0.5)) - 1)
        idx = min(idx, len(sorted_vals) - 1)
        return float(sorted_vals[idx])

    def _process_cpu_percent_locked(self) -> float | None:
        sample = self._read_cpu_times()
        if sample is None:
            return None
        total, idle = sample
        if self._last_cpu_sample is None:
            self._last_cpu_sample = (total, idle)
            return None
        last_total, last_idle = self._last_cpu_sample
        self._last_cpu_sample = (total, idle)
        delta_total = total - last_total
        if delta_total <= 0:
            return None
        process_delta = self._read_process_cpu_delta(delta_total, last_total=last_total, total=total)
        if process_delta is None:
            return None
        usage = process_delta / delta_total
        return max(0.0, min(100.0, usage * 100.0))

    @staticmethod
    def _read_cpu_times() -> tuple[float, float] | None:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as handle:
                first = handle.readline()
        except OSError:
            return None
        if not first.startswith("cpu "):
            return None
        parts = first.strip().split()
        if len(parts) < 5:
            return None
        try:
            values = [float(item) for item in parts[1:]]
        except ValueError:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0.0)
        return total, idle

    def _read_process_cpu_delta(
        self, delta_total: float, *, last_total: float, total: float
    ) -> float | None:
        if delta_total <= 0:
            return None
        current = self._read_process_cpu_time()
        if current is None:
            return None
        if not hasattr(self, "_last_process_cpu"):
            self._last_process_cpu = current
            return None
        last_proc = getattr(self, "_last_process_cpu")
        self._last_process_cpu = current
        delta_proc = current - last_proc
        if delta_proc < 0:
            return None
        return delta_proc

    @staticmethod
    def _read_process_cpu_time() -> float | None:
        try:
            with open("/proc/self/stat", "r", encoding="utf-8") as handle:
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
    def _process_mem_percent() -> float | None:
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                raw = handle.readlines()
        except OSError:
            return None
        total = None
        available = None
        for line in raw:
            if line.startswith("MemTotal:"):
                total = float(line.split()[1]) * 1024.0
            elif line.startswith("MemAvailable:"):
                available = float(line.split()[1]) * 1024.0
            if total is not None and available is not None:
                break
        if total is None or total <= 0:
            return None
        rss = NodeRuntimeMetrics._read_process_rss_bytes()
        if rss is None:
            return None
        return max(0.0, min(100.0, (rss / total) * 100.0))

    @staticmethod
    def _read_process_rss_bytes() -> float | None:
        try:
            with open("/proc/self/statm", "r", encoding="utf-8") as handle:
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


class NodeControlState:
    def __init__(
        self,
        *,
        lifecycle: NodeLifecycle,
        config_path: str,
        logger,
        bootstrap_runner=None,
        onboarding_runtime=None,
        capability_runner=None,
        node_identity_store=None,
        provider_selection_store=None,
        provider_credentials_store=None,
        task_capability_selection_store=None,
        trust_state_store=None,
        governance_state_store=None,
        prompt_service_state_store=None,
        image_generation_template_state_store=None,
        budget_state_store=None,
        client_usage_store=None,
        trust_status_client=None,
        budget_declaration_client=None,
        execution_gateway=None,
        provider_runtime_manager=None,
        budget_manager=None,
        notification_service=None,
        service_manager=None,
        task_execution_service=None,
        internal_scheduler=None,
        supervisor_client=None,
        node_hostname: str | None = None,
        node_api_base_url: str | None = None,
        node_ui_endpoint: str | None = None,
        node_software_version: str | None = None,
        protocol_version: str | None = None,
        comfyui_template_catalog_dir: str | None = None,
        provider_refresh_interval_seconds: int = 900,
        mqtt_recovery_store=None,
        operational_mqtt_health_check_interval_seconds: int = 10,
        operational_mqtt_health_normal_interval_seconds: int = 300,
        operational_mqtt_health_fast_window_seconds: int = 300,
        operational_mqtt_restart_delay_seconds: int = 10,
        operational_mqtt_restart_max_attempts: int = 3,
        startup_mode: str = "bootstrap_onboarding",
        trusted_runtime_context: dict | None = None,
        direct_execution_admission_guard: DirectExecutionAdmissionGuard | None = None,
        direct_execution_admission_config: DirectExecutionAdmissionConfig | None = None,
        execution_queue: ExecutionQueueService | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._config_path = Path(config_path)
        self._logger = logger
        self._bootstrap_runner = bootstrap_runner
        self._onboarding_runtime = onboarding_runtime
        self._capability_runner = capability_runner
        self._node_identity_store = node_identity_store
        self._provider_selection_store = provider_selection_store
        self._provider_credentials_store = provider_credentials_store
        self._task_capability_selection_store = task_capability_selection_store
        self._trust_state_store = trust_state_store
        self._governance_state_store = governance_state_store
        self._prompt_service_state_store = prompt_service_state_store
        self._prompt_registry = None
        self._image_generation_template_state_store = image_generation_template_state_store
        self._budget_state_store = budget_state_store
        self._client_usage_store = client_usage_store
        self._trust_status_client = trust_status_client or TrustStatusClient(logger=logger)
        self._budget_declaration_client = budget_declaration_client or BudgetDeclarationClient(logger=logger)
        self._execution_gateway = execution_gateway or ExecutionGateway()
        self._provider_runtime_manager = provider_runtime_manager
        self._budget_manager = budget_manager
        self._notification_service = notification_service
        self._service_manager = service_manager or NullServiceManager()
        self._task_execution_service = task_execution_service
        self._internal_scheduler = internal_scheduler or InternalScheduler(logger=logger)
        self._supervisor_client = supervisor_client or SupervisorApiClient()
        self._node_hostname = node_hostname
        self._node_api_base_url = node_api_base_url
        self._node_ui_endpoint = node_ui_endpoint
        self._node_software_version = node_software_version
        self._protocol_version = protocol_version
        self._comfyui_template_catalog_dir = str(
            comfyui_template_catalog_dir
            or os.environ.get("HEXE_COMFYUI_TEMPLATE_CATALOG_DIR")
            or "config/comfyui/templates"
        ).strip()
        self._provider_refresh_interval_seconds = max(int(provider_refresh_interval_seconds), 60)
        self._mqtt_recovery_store = mqtt_recovery_store
        self._operational_mqtt_health_check_interval_seconds = max(int(operational_mqtt_health_check_interval_seconds), 5)
        self._operational_mqtt_health_normal_interval_seconds = max(
            int(operational_mqtt_health_normal_interval_seconds), 60
        )
        self._operational_mqtt_health_fast_window_seconds = max(
            int(operational_mqtt_health_fast_window_seconds), 0
        )
        self._operational_mqtt_restart_delay_seconds = max(int(operational_mqtt_restart_delay_seconds), 1)
        self._operational_mqtt_restart_max_attempts = max(int(operational_mqtt_restart_max_attempts), 1)
        self._startup_mode = startup_mode
        self._trusted_runtime_context = trusted_runtime_context or {}
        self._runtime_metrics = NodeRuntimeMetrics()
        self._direct_execution_admission_guard = direct_execution_admission_guard or DirectExecutionAdmissionGuard(
            config=direct_execution_admission_config,
            logger=logger,
        )
        local_queue_concurrency = max(
            _env_int("HEXE_EXECUTION_QUEUE_LOCAL_CONCURRENCY", _env_int("LLAMACPP_PARALLEL", 1) + 1),
            1,
        )
        self._execution_queue = execution_queue or ExecutionQueueService(
            logger=logger,
            local_concurrency=local_queue_concurrency,
            cloud_concurrency=max(_env_int("HEXE_EXECUTION_QUEUE_CLOUD_CONCURRENCY", 4), 1),
            check_after_seconds=max(_env_int("HEXE_EXECUTION_QUEUE_CHECK_AFTER_SECONDS", 5), 1),
            job_ttl_seconds=max(_env_int("HEXE_EXECUTION_QUEUE_JOB_TTL_SECONDS", 3600), 60),
            extra_queue_concurrency={
                "cpu_comfyui": max(_env_int("HEXE_COMFYUI_CPU_QUEUE_CONCURRENCY", 1), 1),
            },
            state_path=str(
                Path(
                    os.environ.get("HEXE_EXECUTION_QUEUE_STATE_PATH")
                    or self._config_path.parent / "execution_queue_jobs.json"
                )
            ),
            max_pending_per_client=max(_env_int("HEXE_EXECUTION_QUEUE_MAX_PENDING_PER_CLIENT", 20), 0),
        )
        self._local_preferred_spillover_enabled = _env_bool("HEXE_LOCAL_PREFERRED_SPILLOVER_ENABLED", True)
        self._local_preferred_spillover_critical_pending = max(
            _env_int("HEXE_LOCAL_PREFERRED_SPILLOVER_CRITICAL_PENDING", 2),
            0,
        )
        self._local_preferred_spillover_high_pending = max(
            _env_int("HEXE_LOCAL_PREFERRED_SPILLOVER_HIGH_PENDING", 5),
            0,
        )
        self._operational_mqtt_fast_until = local_now() + timedelta(
            seconds=self._operational_mqtt_health_fast_window_seconds
        )
        self._phase2_diag = Phase2DiagnosticsLogger(logger)
        self._bootstrap_config = None
        self._provider_selection_config = None
        self._provider_credentials_summary = None
        self._task_capability_selection_config = None
        self._prompt_service_state = None
        self._image_generation_template_state = None
        self._node_id = None
        self._identity_state = "unknown"
        self._supervisor_registered = False
        self._supervisor_last_error = None
        self._supervisor_last_seen = None
        self._local_llm_switch_lock = asyncio.Lock()
        self._local_llm_default_revert_check_interval_seconds = max(
            _env_int("HEXE_LOCAL_LLM_DEFAULT_REVERT_CHECK_INTERVAL_SECONDS", 60),
            1,
        )
        self._local_llm_always_on_check_interval_seconds = max(
            _env_int("HEXE_LOCAL_LLM_ALWAYS_ON_CHECK_INTERVAL_SECONDS", 60),
            1,
        )
        self._comfyui_gpu_presets_config_path = str(
            os.environ.get("HEXE_COMFYUI_GPU_PRESETS_CONFIG") or "config/comfyui-gpu-presets.json"
        ).strip()
        self._vision_runtime_residency_check_interval_seconds = max(
            _env_int("HEXE_VISION_LLM_RESIDENCY_CHECK_INTERVAL_SECONDS", 60),
            1,
        )
        self._comfyui_webui_idle_check_interval_seconds = max(
            _env_int("HEXE_COMFYUI_WEBUI_IDLE_CHECK_INTERVAL_SECONDS", 15),
            1,
        )
        self._manual_image_generation_job_path = Path(
            os.environ.get("HEXE_MANUAL_IMAGE_GENERATION_JOB_PATH")
            or self._config_path.parent / "manual_image_generation_job.json"
        )
        self._load_identity()
        self._rehydrate_trusted_state()
        self._load_provider_selection_config()
        self._load_provider_credentials_summary()
        self._load_task_capability_selection_config()
        self._load_prompt_service_state()
        self._load_image_generation_template_state()
        self._load_existing_config()
        self._register_background_scheduler_tasks()

    @staticmethod
    def _is_non_empty_string(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def _is_provider_selection_valid(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return False
        supported = providers.get("supported")
        if not isinstance(supported, dict):
            return False
        supported_any = bool(
            (supported.get("cloud") or [])
            or (supported.get("local") or [])
            or (supported.get("future") or [])
        )
        return supported_any

    def _is_task_capability_selection_valid(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        selected = payload.get("selected_task_families")
        if not isinstance(selected, list) or not selected:
            return False
        canonical = set(DECLARABLE_TASK_FAMILIES)
        return all(isinstance(item, str) and item.strip() in canonical for item in selected)

    def _build_capability_setup_contract(self) -> dict:
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        trusted_context = self._trusted_runtime_context if isinstance(self._trusted_runtime_context, dict) else {}
        provider_config = self._provider_selection_config if isinstance(self._provider_selection_config, dict) else None
        task_capability_config = (
            self._task_capability_selection_config if isinstance(self._task_capability_selection_config, dict) else None
        )
        enabled_providers = []
        provider_budget_limits = {}
        supported_providers = {"cloud": [], "local": [], "future": []}
        selected_task_families = []
        budget_status = self.budget_state_payload()
        if isinstance(provider_config, dict):
            providers = provider_config.get("providers") if isinstance(provider_config.get("providers"), dict) else {}
            enabled_providers = list(providers.get("enabled") or [])
            provider_budget_limits = dict(providers.get("budget_limits") or {})
            supported = providers.get("supported") if isinstance(providers.get("supported"), dict) else {}
            supported_providers = {
                "cloud": list(supported.get("cloud") or []),
                "local": list(supported.get("local") or []),
                "future": list(supported.get("future") or []),
            }
        if isinstance(task_capability_config, dict):
            selected_task_families = list(task_capability_config.get("selected_task_families") or [])

        readiness_flags = {
            "trust_state_valid": isinstance(trust_state, dict),
            "node_identity_valid": self._identity_state == "valid" and self._is_non_empty_string(self._node_id),
            "provider_selection_valid": self._is_provider_selection_valid(provider_config),
            "task_capability_selection_valid": self._is_task_capability_selection_valid(task_capability_config),
            "core_runtime_context_valid": (
                self._is_non_empty_string(trusted_context.get("paired_core_id"))
                and self._is_non_empty_string(trusted_context.get("core_api_endpoint"))
                and self._is_non_empty_string(trusted_context.get("operational_mqtt_host"))
                and trusted_context.get("operational_mqtt_port") is not None
            ),
        }
        openai_ready, openai_blockers, openai_flags = self._openai_declaration_readiness(provider_config=provider_config)
        readiness_flags.update(openai_flags)
        blocking_reasons: list[str] = []
        if not readiness_flags["trust_state_valid"]:
            blocking_reasons.append("missing_or_invalid_trust_state")
        if not readiness_flags["node_identity_valid"]:
            blocking_reasons.append("missing_or_invalid_node_identity")
        if not readiness_flags["provider_selection_valid"]:
            blocking_reasons.append("missing_or_invalid_provider_selection")
        if not readiness_flags["task_capability_selection_valid"]:
            blocking_reasons.append("missing_or_invalid_task_capability_selection")
        if not readiness_flags["core_runtime_context_valid"]:
            blocking_reasons.append("missing_or_invalid_trusted_runtime_context")
        blocking_reasons.extend(openai_blockers)

        lifecycle_state = self._lifecycle.get_state()
        declaration_allowed = (
            lifecycle_state in {
                NodeLifecycleState.CAPABILITY_SETUP_PENDING,
                NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
            }
            and not blocking_reasons
        )
        return {
            "active": lifecycle_state == NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            "readiness_flags": readiness_flags,
            "provider_selection": {
                "configured": provider_config is not None,
                "enabled_count": len(enabled_providers),
                "enabled": enabled_providers,
                "budget_limits": provider_budget_limits,
                "supported": supported_providers,
            },
            "task_capability_selection": {
                "configured": task_capability_config is not None,
                "selected_count": len(selected_task_families),
                "selected": selected_task_families,
                "available": list(DECLARABLE_TASK_FAMILIES),
            },
            "budget_policy": budget_status,
            "blocking_reasons": blocking_reasons,
            "declaration_allowed": declaration_allowed,
            "disallowed_transitions": [
                NodeLifecycleState.UNCONFIGURED.value,
                NodeLifecycleState.BOOTSTRAP_CONNECTING.value,
                NodeLifecycleState.BOOTSTRAP_CONNECTED.value,
                NodeLifecycleState.CORE_DISCOVERED.value,
                NodeLifecycleState.REGISTRATION_PENDING.value,
                NodeLifecycleState.PENDING_APPROVAL.value,
                NodeLifecycleState.TRUSTED.value,
            ],
        }

    def _openai_declaration_readiness(self, *, provider_config: dict | None) -> tuple[bool, list[str], dict]:
        providers = provider_config.get("providers") if isinstance(provider_config, dict) else None
        enabled_providers = providers.get("enabled") if isinstance(providers, dict) else []
        enabled_provider_set = {str(item or "").strip().lower() for item in enabled_providers if str(item or "").strip()}
        if "openai" not in enabled_provider_set:
            return True, [], {
                "openai_enabled_models_ready": True,
                "openai_classification_ready": True,
                "openai_pricing_ready": True,
            }

        blockers: list[str] = []

        enabled_payload = self.openai_enabled_models_payload()
        enabled_models_raw = enabled_payload.get("models") if isinstance(enabled_payload, dict) else []
        enabled_model_ids = sorted(
            {
                str(item.get("model_id") or "").strip().lower()
                for item in (enabled_models_raw if isinstance(enabled_models_raw, list) else [])
                if isinstance(item, dict) and bool(item.get("enabled")) and str(item.get("model_id") or "").strip()
            }
        )
        if not enabled_model_ids:
            blockers.append("openai_enabled_models_required_before_declare")

        capability_payload = self.openai_provider_model_capabilities_payload()
        classified_entries = capability_payload.get("entries") if isinstance(capability_payload, dict) else []
        classified_ids = {
            str(item.get("model_id") or "").strip().lower()
            for item in (classified_entries if isinstance(classified_entries, list) else [])
            if isinstance(item, dict) and str(item.get("model_id") or "").strip()
        }
        missing_classification = sorted(set(enabled_model_ids) - classified_ids)

        pricing_diag = self.openai_pricing_diagnostics_payload()
        pricing_state = str(pricing_diag.get("refresh_state") or "").strip().lower() if isinstance(pricing_diag, dict) else ""
        pricing_state_ready = pricing_state in {"ok", "manual", "failed_preserved"}
        usable_model_ids: list[str] = []
        blocked_models = []
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "openai_usable_models_payload"):
            usable_payload = self._provider_runtime_manager.openai_usable_models_payload()
            usable_model_ids = list(usable_payload.get("usable_model_ids") or [])
            blocked_models = list(usable_payload.get("blocked_models") or [])
        usable_model_set = {str(item or "").strip().lower() for item in usable_model_ids if str(item or "").strip()}
        missing_pricing = sorted(
            item.get("model_id")
            for item in blocked_models
            if isinstance(item, dict)
            and "not_available" in list(item.get("blockers") or [])
            and str(item.get("model_id") or "").strip()
        )
        if enabled_model_ids and not usable_model_set:
            blockers.append("openai_usable_models_required_before_declare")

        ready = not blockers
        return ready, blockers, {
            "openai_enabled_models_ready": bool(enabled_model_ids),
            "openai_classification_ready": not missing_classification and bool(enabled_model_ids),
            "openai_pricing_ready": pricing_state_ready and not missing_pricing and bool(enabled_model_ids),
            "openai_usable_models_ready": bool(usable_model_set),
        }

    def _load_identity(self) -> None:
        if self._node_identity_store is None or not hasattr(self._node_identity_store, "load"):
            self._identity_state = "unknown"
            self._node_id = None
            return
        payload = self._node_identity_store.load()
        if payload is None:
            self._identity_state = "missing"
            self._node_id = None
            return
        self._identity_state = "valid"
        self._node_id = payload.get("node_id")

    def _rehydrate_trusted_state(self) -> None:
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        if not isinstance(trust_state, dict):
            return

        trust_node_id = str(trust_state.get("node_id") or "").strip()
        if (
            not self._is_non_empty_string(self._node_id)
            and trust_node_id
            and self._node_identity_store is not None
            and hasattr(self._node_identity_store, "load_or_create")
        ):
            try:
                payload = self._node_identity_store.load_or_create(migration_node_id=trust_node_id)
            except TypeError:
                payload = self._node_identity_store.load_or_create()
            if isinstance(payload, dict) and self._is_non_empty_string(payload.get("node_id")):
                self._node_id = str(payload.get("node_id")).strip()
                self._identity_state = "valid"

        if not self._is_non_empty_string(self._node_id) and trust_node_id:
            self._node_id = trust_node_id
            self._identity_state = "valid"

        if not isinstance(self._trusted_runtime_context, dict):
            self._trusted_runtime_context = {}
        if not self._trusted_runtime_context and trust_node_id:
            self._trusted_runtime_context = {
                "node_id": trust_node_id,
                "paired_core_id": str(trust_state.get("paired_core_id") or "").strip(),
                "core_api_endpoint": str(trust_state.get("core_api_endpoint") or "").strip(),
                "operational_mqtt_host": str(trust_state.get("operational_mqtt_host") or "").strip(),
                "operational_mqtt_port": trust_state.get("operational_mqtt_port"),
                "pairing_timestamp": str(trust_state.get("registration_timestamp") or "").strip(),
            }
        if (
            trust_node_id
            and self._startup_mode == "bootstrap_onboarding"
            and self._is_non_empty_string(self._trusted_runtime_context.get("paired_core_id"))
        ):
            self._startup_mode = "trusted_resume"

    def _load_existing_config(self) -> None:
        if not self._config_path.exists():
            return
        if self._lifecycle.get_state() != NodeLifecycleState.UNCONFIGURED:
            if hasattr(self._logger, "info"):
                self._logger.info(
                    "[node-control] skipping persisted bootstrap config load due to startup state=%s",
                    self._lifecycle.get_state().value,
                )
            return
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
            self._bootstrap_config = create_bootstrap_config(payload)
            self._lifecycle.transition_to(
                NodeLifecycleState.BOOTSTRAP_CONNECTING,
                {"source": "persisted_bootstrap_config"},
            )
            self._start_bootstrap_runner_if_available()
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[node-control] invalid persisted bootstrap config ignored: %s", self._config_path
                )

    def _load_provider_selection_config(self) -> None:
        if self._provider_selection_store is None or not hasattr(self._provider_selection_store, "load_or_create"):
            self._provider_selection_config = None
            return
        self._provider_selection_config = self._provider_selection_store.load_or_create(openai_enabled=False)

    def _load_task_capability_selection_config(self) -> None:
        if self._task_capability_selection_store is None or not hasattr(
            self._task_capability_selection_store, "load_or_create"
        ):
            self._task_capability_selection_config = None
            return
        self._task_capability_selection_config = self._task_capability_selection_store.load_or_create()

    def _load_provider_credentials_summary(self) -> None:
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "load_or_create"):
            self._provider_credentials_summary = None
            return
        self._provider_credentials_summary = summarize_provider_credentials(self._provider_credentials_store.load_or_create())

    def _load_prompt_service_state(self) -> None:
        if self._prompt_service_state_store is None or not hasattr(self._prompt_service_state_store, "load_or_create"):
            self._prompt_service_state = None
            self._prompt_registry = None
            return
        self._prompt_registry = PromptRegistry(store=self._prompt_service_state_store, logger=self._logger)
        self._prompt_service_state = self._prompt_registry.snapshot()

    def _load_image_generation_template_state(self) -> None:
        if self._image_generation_template_state_store is None or not hasattr(
            self._image_generation_template_state_store, "load_or_create"
        ):
            self._image_generation_template_state = None
            return
        self._image_generation_template_state = self._image_generation_template_state_store.load_or_create()

    @staticmethod
    def _now_iso() -> str:
        return local_now_iso()

    def status_payload(self) -> dict:
        self._rehydrate_trusted_state()
        self._sync_core_support_status()
        state = self._lifecycle.get_state()
        runtime_context = {}
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "get_status_context"):
            runtime_context = self._onboarding_runtime.get_status_context()
        capability_context = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        capability_setup_contract = self._build_capability_setup_contract()
        if state == NodeLifecycleState.CAPABILITY_SETUP_PENDING and hasattr(self._logger, "info"):
            self._logger.info(
                "[capability-setup-readiness] %s",
                {
                    "readiness_flags": capability_setup_contract.get("readiness_flags"),
                    "blocking_reasons": capability_setup_contract.get("blocking_reasons"),
                    "declaration_allowed": capability_setup_contract.get("declaration_allowed"),
                },
            )
        return {
            "status": state.value,
            "bootstrap_configured": self._bootstrap_config is not None,
            "pending_approval_url": runtime_context.get("pending_approval_url"),
            "pending_session_id": runtime_context.get("pending_session_id"),
            "pending_node_nonce": runtime_context.get("pending_node_nonce"),
            "node_id": self._node_id,
            "identity_state": self._identity_state,
            "startup_mode": self._startup_mode,
            "trusted_runtime_context": self._trusted_runtime_context,
            "api_metrics": self._resource_usage_payload(),
            "direct_execution_admission": self.direct_execution_admission_payload(),
            "provider_selection_configured": self._provider_selection_config is not None,
            "provider_credentials": self.provider_credentials_payload(provider_id="openai"),
            "task_capability_selection_configured": self._task_capability_selection_config is not None,
            "capability_setup": capability_setup_contract,
            "capability_declaration": capability_context,
            "operational_mqtt_recovery": self.operational_mqtt_recovery_payload(),
            "internal_scheduler": self.internal_scheduler_payload(),
            "prompt_service_state": self.prompt_service_state_payload(),
            "services": self.service_status_payload().get("services"),
        }

    def internal_scheduler_payload(self) -> dict:
        if self._internal_scheduler is None or not hasattr(self._internal_scheduler, "snapshot"):
            return {"configured": False, "scheduler_status": "unavailable", "tasks": {}}
        snapshot = self._internal_scheduler.snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {})}

    def operational_mqtt_recovery_payload(self) -> dict:
        if self._mqtt_recovery_store is None or not hasattr(self._mqtt_recovery_store, "snapshot"):
            return {
                "configured": False,
                "active": False,
                "attempt_count": 0,
                "max_attempts": self._operational_mqtt_restart_max_attempts,
                "last_error": None,
                "last_checked_at": None,
                "last_restart_requested_at": None,
                "next_restart_not_before": None,
                "exhausted": False,
            }
        snapshot = self._mqtt_recovery_store.snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {})}

    def _sync_core_support_status(self) -> None:
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        if not isinstance(trust_state, dict):
            return
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        trust_token = str(trust_state.get("node_trust_token") or "").strip()
        core_api_endpoint = str(trust_state.get("core_api_endpoint") or "").strip()
        if not node_id or not trust_token or not core_api_endpoint:
            return
        state = self._lifecycle.get_state()
        if state in {
            NodeLifecycleState.UNCONFIGURED,
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            NodeLifecycleState.BOOTSTRAP_CONNECTED,
            NodeLifecycleState.CORE_DISCOVERED,
            NodeLifecycleState.REGISTRATION_PENDING,
            NodeLifecycleState.PENDING_APPROVAL,
        }:
            return
        if self._trust_status_client is None or not hasattr(self._trust_status_client, "fetch"):
            return
        try:
            support_result = self._trust_status_client.fetch(
                core_api_endpoint=core_api_endpoint,
                trust_token=trust_token,
                node_id=node_id,
            )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[trust-status-check-failed] %s", {"node_id": node_id, "error": str(exc)})
            return
        if support_result.status == "removed":
            self._reset_for_core_removal(payload=support_result.payload)

    @staticmethod
    def _delete_store_file(store) -> None:
        path = getattr(store, "_path", None)
        if isinstance(path, Path) and path.exists():
            path.unlink()

    @classmethod
    def _clear_persisted_store(cls, store) -> None:
        if store is None:
            return
        if hasattr(store, "clear") and callable(getattr(store, "clear")):
            store.clear()
            return
        cls._delete_store_file(store)

    def _reset_for_core_removal(self, *, payload: dict) -> None:
        if hasattr(self._logger, "warning"):
            self._logger.warning(
                "[core-node-removed] %s",
                {
                    "node_id": payload.get("node_id") or self._node_id,
                    "support_state": payload.get("support_state"),
                    "message": payload.get("message"),
                },
            )
        if self._bootstrap_runner is not None and hasattr(self._bootstrap_runner, "stop"):
            self._bootstrap_runner.stop()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "cancel"):
            self._onboarding_runtime.cancel()
        self._bootstrap_config = None
        if self._config_path.exists():
            self._config_path.unlink()
        self._delete_store_file(self._trust_state_store)
        self._delete_store_file(self._node_identity_store)
        self._delete_store_file(self._governance_state_store)
        self._delete_store_file(self._prompt_service_state_store)
        self._delete_store_file(self._image_generation_template_state_store)
        if self._capability_runner is not None and hasattr(self._capability_runner, "clear_local_state_for_reonboarding"):
            self._capability_runner.clear_local_state_for_reonboarding()
        self._trusted_runtime_context = {}
        self._node_id = None
        self._identity_state = "unknown"
        self._startup_mode = "bootstrap_onboarding"
        self._lifecycle.reset_to_unconfigured({"source": "core_node_removed"})

    def provider_selection_payload(self) -> dict:
        if self._provider_selection_config is None:
            return {"configured": False, "config": None}
        return {"configured": True, "config": self._provider_selection_config}

    def service_status_payload(self) -> dict:
        if self._service_manager is None or not hasattr(self._service_manager, "get_status"):
            return {
                "configured": False,
                "services": {"backend": "unknown", "frontend": "unknown", "local_llm": "unknown", "node": "unknown"},
            }
        return {
            "configured": True,
            "services": self._service_manager.get_status(),
        }

    def provider_credentials_payload(self, *, provider_id: str) -> dict:
        summary = (
            self._provider_credentials_summary
            if isinstance(self._provider_credentials_summary, dict)
            else summarize_provider_credentials(None)
        )
        provider_name = str(provider_id or "").strip().lower()
        providers = summary.get("providers") if isinstance(summary.get("providers"), dict) else {}
        credentials = providers.get(provider_name) if isinstance(providers, dict) else None
        return {
            "provider": provider_name,
            "configured": bool(credentials and credentials.get("configured")),
            "credentials": credentials
            if isinstance(credentials, dict)
            else {
                "configured": False,
                "has_api_token": False,
                "has_service_token": False,
                "api_token_hint": None,
                "service_token_hint": None,
                "project_name": None,
                "default_model_id": None,
                "selected_model_ids": [],
                "updated_at": None,
            },
        }

    def task_capability_selection_payload(self) -> dict:
        if self._task_capability_selection_config is None:
            return {"configured": False, "config": None}
        return {"configured": True, "config": self._task_capability_selection_config}

    def prompt_service_state_payload(self) -> dict:
        if self._prompt_registry is not None:
            self._prompt_service_state = self._prompt_registry.snapshot()
        if not isinstance(self._prompt_service_state, dict):
            return {"configured": False, "state": None}
        prompts = self._prompt_service_state.get("prompt_services")
        prompt_list = prompts if isinstance(prompts, list) else []
        return {
            "configured": True,
            "state": self._prompt_service_state,
            "summary": {
                "prompt_count": len(prompt_list),
                "review_due_count": len(
                    [
                        item
                        for item in prompt_list
                        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "review_due"
                    ]
                ),
                "active_count": len(
                    [
                        item
                        for item in prompt_list
                        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "active"
                    ]
                ),
            },
        }

    def image_generation_template_state_payload(self) -> dict:
        if self._image_generation_template_state_store is None:
            return {"configured": False, "state": None}
        if not isinstance(self._image_generation_template_state, dict):
            self._load_image_generation_template_state()
        state = self._image_generation_template_state if isinstance(self._image_generation_template_state, dict) else create_image_generation_template_state()
        templates = state.get("templates") if isinstance(state.get("templates"), list) else []
        return {
            "configured": True,
            "state": state,
            "summary": {
                "template_count": len(templates),
                "active_count": len(
                    [
                        item
                        for item in templates
                        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "active"
                    ]
                ),
                "review_due_count": len(
                    [
                        item
                        for item in templates
                        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "review_due"
                    ]
                ),
            },
        }

    def _save_image_generation_template_state(self, state: dict) -> dict:
        if self._image_generation_template_state_store is None or not hasattr(
            self._image_generation_template_state_store, "save"
        ):
            raise ValueError("image generation template state store is not configured")
        normalized = normalize_image_generation_template_state(state)
        normalized["updated_at"] = self._now_iso()
        self._image_generation_template_state = self._image_generation_template_state_store.save(normalized)
        return self._image_generation_template_state

    def _image_generation_template_index(self, *, template_id: str) -> int:
        template = str(template_id or "").strip()
        if not template:
            raise ValueError("template_id_required")
        state = self.image_generation_template_state_payload().get("state")
        templates = state.get("templates") if isinstance(state, dict) else []
        for index, entry in enumerate(templates if isinstance(templates, list) else []):
            if isinstance(entry, dict) and str(entry.get("template_id") or "").strip() == template:
                return index
        raise ValueError("image_generation_template_not_found")

    def get_image_generation_template(self, *, template_id: str) -> dict:
        index = self._image_generation_template_index(template_id=template_id)
        templates = self._image_generation_template_state.get("templates") if isinstance(self._image_generation_template_state, dict) else []
        return {"configured": True, "template": templates[index]}

    def comfyui_template_catalog_payload(self) -> dict:
        try:
            catalog = load_comfyui_template_catalog(catalog_dir=self._comfyui_template_catalog_dir)
        except ValueError as exc:
            return {
                "configured": True,
                "catalog_dir": self._comfyui_template_catalog_dir,
                "templates": [],
                "summary": {"template_count": 0, "valid": False},
                "errors": [str(exc)],
            }
        templates = list(catalog.get("templates") or [])
        return {
            **catalog,
            "summary": {
                "template_count": len(templates),
                "valid": not bool(catalog.get("errors")),
                "runtimes": sorted(
                    {
                        str(item.get("runtime_id") or "").strip()
                        for item in templates
                        if isinstance(item, dict) and str(item.get("runtime_id") or "").strip()
                    }
                ),
            },
        }

    def get_comfyui_template_catalog_entry(self, *, template_id: str) -> dict:
        normalized_id = str(template_id or "").strip()
        if not normalized_id:
            raise ValueError("template_id_required")
        catalog = self.comfyui_template_catalog_payload()
        for entry in list(catalog.get("templates") or []):
            if isinstance(entry, dict) and str(entry.get("template_id") or "").strip() == normalized_id:
                return {"configured": catalog.get("configured"), "template": entry}
        raise ValueError("comfyui_template_not_found")

    def manual_image_generation_status(self) -> dict:
        services = self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        manual_paths = webui.get("manual_paths") if isinstance(webui, dict) else {}
        runtime = str(webui.get("runtime") or "gpu").strip().lower() if isinstance(webui, dict) else "gpu"
        runtime_key = "comfyui_cpu" if runtime == "cpu" else "comfyui_gpu"
        runtime_service = services.get(runtime_key) if isinstance(services, dict) else {}
        generation_status = {}
        if self._service_manager is not None and hasattr(self._service_manager, "comfyui_webui_generation_status"):
            try:
                generation_status = self._service_manager.comfyui_webui_generation_status()
            except Exception as exc:
                generation_status = {"available": False, "error": str(exc)}
        if not isinstance(generation_status, dict):
            generation_status = {}
        outputs = self._manual_image_outputs(limit=24)
        latest_job = self._manual_image_latest_job(
            generation_status=generation_status,
            outputs=outputs,
            runtime_service=runtime_service if isinstance(runtime_service, dict) else {},
        )
        if isinstance(latest_job.get("progress_detail"), dict):
            generation_status = {**generation_status, "progress_detail": latest_job["progress_detail"]}
        cleanup = latest_job.get("rgb_fallback_cleanup") if isinstance(latest_job.get("rgb_fallback_cleanup"), dict) else {}
        if cleanup.get("deleted"):
            outputs = self._manual_image_outputs(limit=24)
        references = self._manual_image_references(limit=48)
        catalog = self.comfyui_template_catalog_payload()
        templates = [
            item
            for item in list(catalog.get("templates") or [])
            if isinstance(item, dict)
            and str(item.get("runtime_id") or "") == "comfyui_gpu"
            and str(item.get("output_scope") or "") in {"normal", "manual", "normal_and_manual"}
        ]
        return {
            "configured": True,
            "service": webui,
            "runtime_service": runtime_service if isinstance(runtime_service, dict) else {},
            "generation_status": generation_status,
            "latest_job": latest_job,
            "manual_paths": manual_paths if isinstance(manual_paths, dict) else {},
            "templates": templates,
            "references": references,
            "outputs": outputs,
        }

    async def submit_manual_image_generation(self, *, payload: "ManualImageGenerationRequest") -> dict:
        service = await self.start_service(target="comfyui_webui")
        services = service.get("services") if isinstance(service.get("services"), dict) else self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        runtime_service = services.get("comfyui_gpu") if isinstance(services, dict) else {}
        runtime_service = runtime_service if isinstance(runtime_service, dict) else {}
        manual_paths = webui.get("manual_paths") if isinstance(webui, dict) else {}
        socket_path = str(webui.get("socket_path") or "") if isinstance(webui, dict) else ""
        if not socket_path:
            raise ValueError("manual_comfyui_socket_unavailable")

        mode = str(payload.mode or "txt2img").strip().lower()
        if mode not in {"txt2img", "img2img"}:
            raise ValueError("invalid_manual_image_generation_mode")
        input_image = str(payload.input_image or "").strip()
        if payload.reference_image_data_base64:
            input_image = self._save_manual_reference_image(
                manual_paths=manual_paths if isinstance(manual_paths, dict) else {},
                filename=payload.reference_image_filename,
                data_base64=payload.reference_image_data_base64,
            )
        template_id = str(payload.template_id or "").strip()
        if not template_id:
            template_id = MANUAL_IMAGE_DEFAULT_TEMPLATE_ID
        template = self.get_comfyui_template_catalog_entry(template_id=template_id)["template"]
        if str(template.get("runtime_id") or "") != "comfyui_gpu":
            raise ValueError("manual_image_template_runtime_unsupported")
        batch_count = self._manual_image_batch_count(payload.batch_count)
        outputs_before = self._manual_image_outputs(limit=24)
        submitted_at = datetime.now(timezone.utc).isoformat()
        preflight_memory_cleanup = self._free_manual_image_runtime_models(socket_path=socket_path)
        if self._service_manager is not None and hasattr(self._service_manager, "ensure_comfyui_progress_listener"):
            try:
                self._service_manager.ensure_comfyui_progress_listener(client_id="hexe-node-manual-image-ui")
            except Exception as exc:
                self._logger.debug("manual image progress listener unavailable: %s", exc)
        submissions: list[dict] = []
        for index in range(batch_count):
            item_payload = self._manual_image_batch_item_payload(template=template, payload=payload, batch_index=index)
            workflow, resolved_values = self._manual_image_workflow_and_values_from_template(
                template=template,
                payload=item_payload,
                input_image=input_image,
            )
            response = self._uds_json_request(
                socket_path=socket_path,
                method="POST",
                path="/prompt",
                body={"client_id": "hexe-node-manual-image-ui", "prompt": workflow},
            )
            submissions.append(
                {
                    "index": index + 1,
                    "prompt_id": response.get("prompt_id"),
                    "number": response.get("number"),
                    "seed": resolved_values.get("seed"),
                    "reference_strengths": {
                        name: resolved_values.get(name)
                        for name in MANUAL_IMAGE_REFERENCE_STRENGTH_VARIABLES
                        if name in resolved_values
                    },
                    "node_errors": response.get("node_errors") or {},
                }
            )
        prompt_ids = [str(item.get("prompt_id") or "").strip() for item in submissions if str(item.get("prompt_id") or "").strip()]
        prompt_id = prompt_ids[0] if prompt_ids else None
        first_submission = submissions[0] if submissions else {}
        self._write_manual_image_latest_job(
            {
                "status": "submitted",
                "mode": mode,
                "template_id": template_id,
                "prompt_id": prompt_id,
                "prompt_ids": prompt_ids,
                "number": first_submission.get("number"),
                "submissions": submissions,
                "batch_count": batch_count,
                "submitted_count": len(submissions),
                "submitted_at": submitted_at,
                "output_count_before": len(outputs_before),
                "completed_output_count": 0,
                "runtime_pid": runtime_service.get("pid"),
                "runtime_started_at": runtime_service.get("started_at"),
                "runtime_restart_count": runtime_service.get("restart_count"),
                "preflight_memory_cleanup": preflight_memory_cleanup,
                "lora_metadata": {
                    "enabled": bool(payload.create_lora_metadata),
                    "caption": str(payload.prompt or "").strip(),
                    "negative_prompt": str(payload.negative_prompt or "").strip(),
                    "template_id": template_id,
                    "mode": mode,
                    "width": payload.width,
                    "height": payload.height,
                    "seed": first_submission.get("seed"),
                    "batch_count": batch_count,
                    "batch_items": submissions,
                    "steps": payload.steps,
                    "cfg": payload.cfg,
                    "denoise": payload.denoise,
                },
            }
        )
        return {
            "status": "submitted",
            "mode": mode,
            "template_id": template_id,
            "prompt_id": prompt_id,
            "prompt_ids": prompt_ids,
            "number": first_submission.get("number"),
            "batch_count": batch_count,
            "submitted_count": len(submissions),
            "submissions": submissions,
            "node_errors": (submissions[0].get("node_errors") or {})
            if batch_count == 1 and submissions
            else [item.get("node_errors") or {} for item in submissions],
            "input_image": input_image or None,
            "manual_paths": manual_paths,
            "outputs": self._manual_image_outputs(limit=24),
        }

    def manual_image_prompt_helper(self, *, payload: "ManualImagePromptHelperRequest") -> dict:
        services = self.service_status_payload().get("services", {})
        local_llm = services.get("local_llm") if isinstance(services, dict) else {}
        socket_path = str(local_llm.get("socket_path") or "") if isinstance(local_llm, dict) else ""
        model_id = str(local_llm.get("model_id") or local_llm.get("default_model_id") or "local").strip() if isinstance(local_llm, dict) else "local"
        if not socket_path:
            raise ValueError("local_llm_socket_unavailable")
        if isinstance(local_llm, dict) and str(local_llm.get("state") or "").strip().lower() not in {"running", "healthy"}:
            raise ValueError("local_llm_unavailable")
        mode = str(payload.mode or "txt2img").strip().lower()
        if mode not in {"txt2img", "img2img"}:
            mode = "img2img" if payload.reference_image_provided else "txt2img"
        request_body = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "/no_think You help draft concise SDXL/ComfyUI image prompts. "
                        "Return only JSON with keys prompt and negative_prompt. "
                        "Keep the user's intent, add visual detail, subject, setting, lighting, composition, and quality terms. "
                        "Do not include explanations or markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "/no_think "
                        + json.dumps(
                            {
                                "mode": mode,
                                "template_id": payload.template_id,
                                "current_prompt": str(payload.prompt or "").strip(),
                                "current_negative_prompt": str(payload.negative_prompt or "").strip(),
                                "width": payload.width,
                                "height": payload.height,
                                "reference_image_provided": bool(payload.reference_image_provided),
                            },
                            sort_keys=True,
                        )
                    ),
                },
            ],
            "temperature": 0.7,
            "max_tokens": 350,
            "stream": False,
        }
        response = self._uds_json_request(
            socket_path=socket_path,
            method="POST",
            path="/v1/chat/completions",
            body=request_body,
            host="local-llm",
            error_label="local_llm_prompt_helper_failed",
        )
        content = ""
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(message.get("content") or message.get("reasoning_content") or choices[0].get("text") or "").strip()
        parsed = self._parse_manual_image_prompt_helper_content(content)
        prompt = str(parsed.get("prompt") or content or payload.prompt or "").strip()
        negative_prompt = str(parsed.get("negative_prompt") or payload.negative_prompt or "").strip()
        return {
            "status": "ok",
            "provider": "local_llm",
            "model_id": model_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
        }

    def manual_image_pose_helper(self, *, payload: "ManualImagePoseHelperRequest") -> dict:
        pose_text = str(payload.pose_text or "").strip()
        if not pose_text:
            raise ValueError("manual_pose_text_required")
        template_id = str(payload.template_id or MANUAL_IMAGE_DEFAULT_TEMPLATE_ID).strip()
        template_defaults: dict = {}
        try:
            template = self.get_comfyui_template_catalog_entry(template_id=template_id)["template"]
            template_defaults = dict(template.get("defaults") or {})
        except Exception:
            template = {}
        width = self._coerce_manual_pose_dimension(payload.width, default=template_defaults.get("width"), fallback=768)
        height = self._coerce_manual_pose_dimension(payload.height, default=template_defaults.get("height"), fallback=1152)
        llm_plan, provider, model_id = self._manual_pose_plan_from_local_llm(payload=payload, template=template)
        plan = self._normalize_manual_pose_plan(pose_text=pose_text, parsed=llm_plan)
        pose_prompt = str(llm_plan.get("pose_prompt") or "").strip() if isinstance(llm_plan, dict) else ""
        if not pose_prompt:
            pose_prompt = self._manual_pose_prompt_from_plan(plan=plan)
        reference = None
        if payload.generate_reference is not False:
            services = self.service_status_payload().get("services", {})
            webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
            manual_paths = webui.get("manual_paths") if isinstance(webui, dict) else {}
            reference = self._write_manual_pose_reference(
                manual_paths=manual_paths if isinstance(manual_paths, dict) else {},
                avatar_name=payload.avatar_name,
                pose_text=pose_text,
                pose_prompt=pose_prompt,
                plan=plan,
                width=width,
                height=height,
            )
        return {
            "status": "ok",
            "provider": provider,
            "model_id": model_id,
            "template_id": template_id,
            "width": width,
            "height": height,
            "pose_text": pose_text,
            "pose_plan": plan,
            "pose_prompt": pose_prompt,
            "reference": reference,
            "body_reference_image": reference.get("input_image") if isinstance(reference, dict) else None,
            "references": self._manual_image_references(limit=48),
        }

    def upload_manual_image_reference(self, *, payload: "ManualImageReferenceUploadRequest") -> dict:
        services = self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        manual_paths = webui.get("manual_paths") if isinstance(webui, dict) else {}
        category = self._manual_reference_category(payload.category)
        role = self._safe_filename_component(payload.role or "reference")
        display_name = str(payload.name or Path(str(payload.filename or "")).stem or category).strip()
        safe_name = self._safe_filename_component(display_name)
        raw_name = Path(str(payload.filename or f"{safe_name}.png")).name
        suffix = Path(raw_name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        references_root = self._manual_image_reference_root(manual_paths=manual_paths if isinstance(manual_paths, dict) else {})
        target_dir = references_root / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_name = f"{safe_name}_{role}_{int(time.time())}{suffix}"
        target_path = target_dir / target_name
        encoded = str(payload.data_base64 or "")
        if "," in encoded and encoded.split(",", 1)[0].lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid_reference_image_data") from exc
        if not data:
            raise ValueError("reference_image_empty")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("reference_image_too_large")
        target_path.write_bytes(data)
        metadata = {
            "category": category,
            "role": role,
            "name": display_name or safe_name,
            "filename": target_name,
            "input_image": f"references/{category}/{target_name}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        target_path.with_suffix(target_path.suffix + ".json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return {
            "status": "uploaded",
            "reference": self._manual_image_reference_payload(path=target_path, metadata=metadata),
            "references": self._manual_image_references(limit=48),
        }

    def manual_image_reference_response(self, *, relative_path: str) -> FileResponse:
        root = self._manual_image_reference_root()
        safe_relative = self._safe_relative_path(relative_path)
        path = (root / safe_relative).resolve()
        if root not in path.parents and path != root:
            raise ValueError("manual_reference_path_invalid")
        if not path.exists() or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("manual_reference_not_found")
        return FileResponse(path)

    def delete_manual_image_reference(self, *, relative_path: str) -> dict:
        root = self._manual_image_reference_root()
        safe_relative = self._safe_relative_path(relative_path)
        path = (root / safe_relative).resolve()
        if root not in path.parents and path != root:
            raise ValueError("manual_reference_path_invalid")
        if not path.exists() or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("manual_reference_not_found")
        path.unlink()
        sidecar = path.with_suffix(path.suffix + ".json")
        if sidecar.exists() and sidecar.is_file():
            sidecar.unlink()
        return {
            "deleted": True,
            "relative_path": safe_relative.as_posix(),
            "references": self._manual_image_references(limit=48),
        }

    def manual_image_vision_describe(self, *, payload: "ManualImageVisionDescribeRequest") -> dict:
        image_bytes, mime_type, image_name = self._manual_vision_image_payload(payload=payload)
        prompt = self._manual_vision_describe_prompt(mode=payload.mode, custom_prompt=payload.custom_prompt)
        description, model_id = self._vision_describe_image_bytes(
            image_bytes=image_bytes,
            mime_type=mime_type,
            image_name=image_name,
            prompt=prompt,
            max_tokens=450,
        )
        return {
            "status": "ok",
            "provider": "vision_llm",
            "model_id": model_id,
            "mode": str(payload.mode or "avatar"),
            "image_name": image_name,
            "description": description,
        }

    def _vision_describe_image_bytes(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        image_name: str,
        prompt: str,
        max_tokens: int = 450,
        timeout_s: float = 10,
    ) -> tuple[str, str]:
        services = self.service_status_payload().get("services", {})
        vision_llm = services.get("vision_llm") if isinstance(services, dict) else {}
        socket_path = str(vision_llm.get("socket_path") or "") if isinstance(vision_llm, dict) else ""
        model_id = str(vision_llm.get("default_model_id") or VISION_LLM_BUILTIN_DEFAULT_MODEL_ID).strip()
        state = str(vision_llm.get("state") or "").strip().lower() if isinstance(vision_llm, dict) else ""
        if not socket_path or state not in {"running", "healthy"}:
            residency = vision_llm.get("residency") if isinstance(vision_llm, dict) else {}
            reason = str(residency.get("reason") or state or "vision_runtime_unavailable") if isinstance(residency, dict) else "vision_runtime_unavailable"
            raise ValueError(f"vision_runtime_unavailable:{reason}")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = self._uds_json_request(
            socket_path=socket_path,
            method="POST",
            path="/v1/chat/completions",
            body={
                "model": model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                        ],
                    }
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "stream": False,
            },
            host="vision-llm",
            error_label="vision_describe_failed",
            timeout_s=timeout_s,
        )
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(message.get("content") or message.get("reasoning_content") or choices[0].get("text") or "").strip()
        return content, model_id

    def avatar_generation_status(self) -> dict:
        selected_profile_id = self._selected_avatar_profile_id()
        profiles = self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id)
        selected_profile = next((profile for profile in profiles if profile.get("profile_id") == selected_profile_id), None)
        return {
            "configured": True,
            "profile_root": self._avatar_profile_root().as_posix(),
            "selected_profile_id": selected_profile_id,
            "selected_profile": selected_profile,
            "profiles": profiles,
        }

    async def generate_avatar_body_depth_profile(self, *, profile_id: str, payload: "AvatarBodyDepthProfileGenerateRequest") -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        profile_id = self._safe_filename_component(metadata.get("profile_id") or profile_dir.name)
        sources = self._avatar_body_depth_profile_sources(
            profile_dir=profile_dir,
            metadata=metadata,
            source_filenames=payload.source_filenames,
        )
        if not sources:
            raise ValueError("avatar_body_depth_sources_not_found")

        service = await self.start_service(target="comfyui_webui")
        services = service.get("services") if isinstance(service.get("services"), dict) else self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        runtime_service = services.get("comfyui_gpu") if isinstance(services, dict) else {}
        runtime_service = runtime_service if isinstance(runtime_service, dict) else {}
        socket_path = str(webui.get("socket_path") or "") if isinstance(webui, dict) else ""
        if not socket_path:
            raise ValueError("manual_comfyui_socket_unavailable")

        width = self._coerce_manual_pose_dimension(payload.width, default=768, fallback=768)
        height = self._coerce_manual_pose_dimension(payload.height, default=1152, fallback=1152)
        depth_resolution = self._coerce_manual_pose_dimension(payload.depth_resolution, default=1024, fallback=1024)
        depth_model = str(payload.depth_model or "depth_anything_v2_vits.pth").strip() or "depth_anything_v2_vits.pth"
        bg_removal_model = str(payload.bg_removal_model or "birefnet.safetensors").strip() or "birefnet.safetensors"
        replace_source_images = payload.replace_source_images is not False
        submitted_at = datetime.now(timezone.utc).isoformat()
        job_token = str(int(time.time()))
        preflight_memory_cleanup = self._free_manual_image_runtime_models(socket_path=socket_path)
        if self._service_manager is not None and hasattr(self._service_manager, "ensure_comfyui_progress_listener"):
            try:
                self._service_manager.ensure_comfyui_progress_listener(client_id=AVATAR_BODY_DEPTH_PROFILE_CLIENT_ID)
            except Exception as exc:
                self._logger.debug("avatar body depth progress listener unavailable: %s", exc)

        submissions: list[dict] = []
        job_items: list[dict] = []
        for index, source in enumerate(sources, start=1):
            source_stem = self._safe_filename_component(Path(str(source.get("filename") or f"body_{index}")).stem)
            item_token = f"{job_token}_{index:02d}"
            target_body_filename = f"avatar_body_{source_stem}_{item_token}.png"
            target_depth_filename = f"avatar_body_depth_{source_stem}_{item_token}.png"
            output_base = f"hexe/avatar_profile_body_depth/{profile_id}"
            nobg_output_prefix = f"{output_base}/{Path(target_body_filename).stem}"
            depth_output_prefix = f"{output_base}/{Path(target_depth_filename).stem}"
            workflow = self._avatar_body_depth_profile_workflow(
                source_input_image=str(source.get("input_image") or ""),
                width=width,
                height=height,
                depth_resolution=depth_resolution,
                depth_model=depth_model,
                bg_removal_model=bg_removal_model,
                nobg_output_prefix=nobg_output_prefix,
                depth_output_prefix=depth_output_prefix,
            )
            response = self._uds_json_request(
                socket_path=socket_path,
                method="POST",
                path="/prompt",
                body={"client_id": AVATAR_BODY_DEPTH_PROFILE_CLIENT_ID, "prompt": workflow},
            )
            submissions.append(
                {
                    "index": index,
                    "prompt_id": response.get("prompt_id"),
                    "number": response.get("number"),
                    "node_errors": response.get("node_errors") or {},
                }
            )
            job_items.append(
                {
                    "index": index,
                    "source_role": source.get("role"),
                    "source_name": source.get("name"),
                    "source_filename": source.get("filename"),
                    "source_input_image": source.get("input_image"),
                    "target_body_filename": target_body_filename,
                    "target_depth_filename": target_depth_filename,
                    "nobg_output_prefix": nobg_output_prefix,
                    "depth_output_prefix": depth_output_prefix,
                    "imported": False,
                }
            )

        prompt_ids = [str(item.get("prompt_id") or "").strip() for item in submissions if str(item.get("prompt_id") or "").strip()]
        job = {
            "schema_version": "1.0",
            "status": "submitted",
            "profile_id": profile_id,
            "prompt_id": prompt_ids[0] if prompt_ids else None,
            "prompt_ids": prompt_ids,
            "submissions": submissions,
            "submitted_at": submitted_at,
            "source_count": len(job_items),
            "replace_source_images": replace_source_images,
            "settings": {
                "width": width,
                "height": height,
                "depth_resolution": depth_resolution,
                "depth_model": depth_model,
                "bg_removal_model": bg_removal_model,
            },
            "runtime_pid": runtime_service.get("pid"),
            "runtime_started_at": runtime_service.get("started_at"),
            "runtime_restart_count": runtime_service.get("restart_count"),
            "preflight_memory_cleanup": preflight_memory_cleanup,
            "items": job_items,
        }
        self._write_avatar_body_depth_profile_job(profile_dir=profile_dir, payload=job)
        now = datetime.now(timezone.utc).isoformat()
        updated_metadata = {
            **metadata,
            "body_depth_profile": {
                "status": "submitted",
                "job_id": job_token,
                "source_count": len(job_items),
                "generated_count": 0,
                "width": width,
                "height": height,
                "depth_resolution": depth_resolution,
                "updated_at": now,
            },
            "updated_at": now,
        }
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "submitted",
            "profile_id": profile_id,
            "prompt_id": prompt_ids[0] if prompt_ids else None,
            "prompt_ids": prompt_ids,
            "submitted_count": len(submissions),
            "submissions": submissions,
            "job": self._read_avatar_body_depth_profile_job(profile_dir=profile_dir),
            "profile": profile,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def save_avatar_profile(self, *, payload: "AvatarProfileSaveRequest") -> dict:
        display_name = str(payload.name or "").strip()
        if not display_name:
            raise ValueError("avatar_profile_name_required")
        profile_id = self._safe_filename_component(display_name)
        profile_dir = self._avatar_profile_root() / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        existing = {}
        profile_path = profile_dir / "profile.json"
        if profile_path.exists():
            try:
                existing = json.loads(profile_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing = existing if isinstance(existing, dict) else {}
        existing_face = Path(str(existing.get("face_image") or "")).name
        existing_body = Path(str(existing.get("body_image") or "")).name
        face_filename = existing_face if existing_face and (profile_dir / existing_face).is_file() else None
        body_filename = existing_body if existing_body and (profile_dir / existing_body).is_file() else None
        if payload.face_image_data_base64:
            face_filename = self._write_avatar_profile_image(
                profile_dir=profile_dir,
                profile_id=profile_id,
                role="face",
                filename=payload.face_image_filename,
                data_base64=payload.face_image_data_base64,
            )
        if payload.body_image_data_base64:
            body_filename = self._write_avatar_profile_image(
                profile_dir=profile_dir,
                profile_id=profile_id,
                role="body",
                filename=payload.body_image_filename,
                data_base64=payload.body_image_data_base64,
            )
        prompt_workspaces = existing.get("prompt_workspaces") if isinstance(existing.get("prompt_workspaces"), dict) else {}
        metadata = {
            "schema_version": "1.0",
            "profile_id": profile_id,
            "name": display_name,
            "description": str(payload.description or "").strip(),
            "gender": str(payload.gender or "").strip(),
            "skin_color": str(payload.skin_color or "").strip(),
            "hair_color": str(payload.hair_color or "").strip(),
            "character_type": str(payload.character_type or "").strip(),
            "visual_style": str(payload.visual_style or "").strip(),
            "initial_data": str(payload.initial_data or "").strip(),
            "nsfw": bool(payload.nsfw) if payload.nsfw is not None else bool(existing.get("nsfw", False)),
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        general_prompt = str(existing.get("general_prompt") or "").strip() or self._avatar_profile_general_initial_prompt(profile=metadata)
        metadata["general_prompt"] = general_prompt
        if "head_face" not in prompt_workspaces:
            head_prompt_parts = self._avatar_profile_default_head_prompt_parts(profile={**metadata, "general_prompt": general_prompt})
            prompt_workspaces = {
                **prompt_workspaces,
                "head_face": {
                    "section": "head_face",
                    "prompt_parts": head_prompt_parts,
                    "prompt": self._avatar_profile_head_prompt_from_parts(prompt_parts=head_prompt_parts, profile=metadata),
                    "negative_prompt": "",
                    "conversation": [],
                    "preview_history": [],
                    "created_at": now,
                    "updated_at": now,
                    "source": "profile_creation_baseline",
                },
            }
        metadata["prompt_workspaces"] = prompt_workspaces
        if face_filename:
            metadata["face_image"] = face_filename
            metadata["face_input_image"] = f"avatar_profiles/{profile_id}/{face_filename}"
        if body_filename:
            metadata["body_image"] = body_filename
            metadata["body_input_image"] = f"avatar_profiles/{profile_id}/{body_filename}"
        profile_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        profile = self._avatar_profile_payload(profile_dir=profile_dir)
        return {
            "status": "saved",
            "profile": profile,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=self._selected_avatar_profile_id()),
        }

    def refine_avatar_profile_head_prompt(self, *, profile_id: str, payload: "AvatarProfileHeadPromptRefineRequest") -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        user_message = str(payload.user_message or "").strip()
        if not user_message:
            raise ValueError("avatar_head_prompt_user_message_required")
        workspace = self._avatar_profile_prompt_workspace(metadata=metadata, section="head_face")
        prompt_parts = self._avatar_profile_normalized_head_prompt_parts(
            profile=metadata,
            prompt_parts=payload.prompt_parts if isinstance(payload.prompt_parts, dict) else workspace.get("prompt_parts"),
            fallback_prompt=str(payload.current_prompt or workspace.get("prompt") or "").strip(),
        )
        current_prompt = str(payload.current_prompt or "").strip() or self._avatar_profile_head_prompt_from_parts(
            prompt_parts=prompt_parts,
            profile=metadata,
        )
        if not current_prompt:
            current_prompt = self._avatar_profile_default_head_prompt(profile=metadata)
        current_negative = str(payload.negative_prompt or workspace.get("negative_prompt") or "").strip()
        prompt, negative_prompt, model_id = self._avatar_profile_head_prompt_from_local_llm(
            profile=metadata,
            current_prompt=current_prompt,
            current_negative_prompt=current_negative,
            user_message=user_message,
        )
        now = datetime.now(timezone.utc).isoformat()
        conversation = list(workspace.get("conversation") or [])
        conversation.append({"role": "user", "content": user_message, "created_at": now})
        conversation.append({"role": "assistant", "content": prompt, "negative_prompt": negative_prompt, "model_id": model_id, "created_at": now})
        updated_workspace = {
            **workspace,
            "section": "head_face",
            "prompt": prompt,
            "prompt_parts": prompt_parts,
            "negative_prompt": negative_prompt,
            "updated_at": now,
            "local_llm_model_id": model_id,
            "conversation": conversation[-50:],
            "preview_history": list(workspace.get("preview_history") or [])[-AVATAR_HEAD_FACE_PREVIEW_HISTORY_LIMIT:],
        }
        updated_metadata = self._avatar_profile_metadata_with_workspace(
            metadata=metadata,
            section="head_face",
            workspace=updated_workspace,
        )
        updated_metadata["updated_at"] = now
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        saved_profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "head_prompt_refined",
            "profile": saved_profile,
            "workspace": saved_profile.get("prompt_workspaces", {}).get("head_face", {}),
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    async def create_avatar_profile_head_preview(self, *, profile_id: str, payload: "AvatarProfileHeadPreviewRequest") -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        workspace = self._avatar_profile_prompt_workspace(metadata=metadata, section="head_face")
        prompt_parts = self._avatar_profile_normalized_head_prompt_parts(
            profile=metadata,
            prompt_parts=payload.prompt_parts if isinstance(payload.prompt_parts, dict) else workspace.get("prompt_parts"),
            fallback_prompt=str(payload.prompt or workspace.get("prompt") or "").strip(),
        )
        prompt = str(payload.prompt or "").strip() or self._avatar_profile_head_prompt_from_parts(
            prompt_parts=prompt_parts,
            profile=metadata,
        )
        if not prompt:
            prompt = self._avatar_profile_default_head_prompt(profile=metadata)
        negative_prompt = str(payload.negative_prompt or workspace.get("negative_prompt") or "").strip()
        template = self.get_comfyui_template_catalog_entry(template_id=AVATAR_HEAD_FACE_PREVIEW_TEMPLATE_ID)["template"]
        defaults = template.get("defaults") if isinstance(template.get("defaults"), dict) else {}
        if not negative_prompt:
            negative_prompt = str(defaults.get("negative_prompt") or "").strip()
        width = int(defaults.get("width") or 512)
        height = int(defaults.get("height") or 512)
        steps = int(defaults.get("steps") or 4)
        cfg = float(defaults.get("cfg") or 1.2)
        denoise = float(defaults.get("denoise") or 1.0)
        avatar_name = self._safe_filename_component(metadata.get("name") or profile_dir.name or "avatar")
        generation = await self.submit_manual_image_generation(
            payload=ManualImageGenerationRequest(
                template_id=AVATAR_HEAD_FACE_PREVIEW_TEMPLATE_ID,
                mode="txt2img",
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg=cfg,
                denoise=denoise,
                batch_count=1,
                randomize_seed=True,
                template_variables={"avatar_name": avatar_name},
            )
        )
        now = datetime.now(timezone.utc).isoformat()
        submissions = generation.get("submissions") if isinstance(generation.get("submissions"), list) else []
        first_submission = submissions[0] if submissions and isinstance(submissions[0], dict) else {}
        preview = {
            "preview_id": f"head_face_{int(time.time())}",
            "section": "head_face",
            "status": str(generation.get("status") or "submitted"),
            "template_id": AVATAR_HEAD_FACE_PREVIEW_TEMPLATE_ID,
            "prompt_id": generation.get("prompt_id"),
            "prompt_ids": generation.get("prompt_ids") or [],
            "seed": first_submission.get("seed"),
            "width": width,
            "height": height,
            "steps": steps,
            "cfg": cfg,
            "denoise": denoise,
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "created_at": now,
        }
        preview_history = list(workspace.get("preview_history") or [])
        preview_history.append(preview)
        updated_workspace = {
            **workspace,
            "section": "head_face",
            "prompt": prompt,
            "prompt_parts": prompt_parts,
            "negative_prompt": negative_prompt,
            "updated_at": now,
            "preview_history": preview_history[-AVATAR_HEAD_FACE_PREVIEW_HISTORY_LIMIT:],
        }
        updated_metadata = self._avatar_profile_metadata_with_workspace(
            metadata=metadata,
            section="head_face",
            workspace=updated_workspace,
        )
        updated_metadata["updated_at"] = now
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        saved_profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "preview_submitted",
            "preview": preview,
            "generation": generation,
            "profile": saved_profile,
            "workspace": saved_profile.get("prompt_workspaces", {}).get("head_face", {}),
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def select_avatar_profile(self, *, profile_id: str) -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        if not (profile_dir / "profile.json").exists():
            raise ValueError("avatar_profile_not_found")
        selected_profile_id = profile_dir.name
        self._write_selected_avatar_profile_id(profile_id=selected_profile_id)
        profiles = self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id)
        selected_profile = next((profile for profile in profiles if profile.get("profile_id") == selected_profile_id), None)
        return {
            "status": "selected",
            "selected_profile_id": selected_profile_id,
            "selected_profile": selected_profile,
            "profiles": profiles,
        }

    def delete_avatar_profile(self, *, profile_id: str) -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        if not profile_dir.exists() or not profile_dir.is_dir():
            raise ValueError("avatar_profile_not_found")
        shutil.rmtree(profile_dir)
        selected_profile_id = self._selected_avatar_profile_id()
        if selected_profile_id == profile_dir.name:
            self._write_selected_avatar_profile_id(profile_id="")
            selected_profile_id = None
        return {
            "deleted": True,
            "profile_id": profile_dir.name,
            "selected_profile_id": selected_profile_id,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def upload_avatar_profile_reference(self, *, profile_id: str, payload: "AvatarProfileReferenceUploadRequest") -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        profile_id = self._safe_filename_component(metadata.get("profile_id") or profile_dir.name)
        role = self._avatar_profile_reference_role(payload.role)
        display_name = str(payload.name or Path(str(payload.filename or "")).stem or role).strip()
        safe_name = self._safe_filename_component(display_name)
        raw_name = Path(str(payload.filename or f"{safe_name}.png")).name
        suffix = Path(raw_name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        reference_dir = (profile_dir / "refs" / role).resolve()
        if self._avatar_profile_root() not in reference_dir.parents:
            raise ValueError("avatar_profile_reference_path_invalid")
        reference_dir.mkdir(parents=True, exist_ok=True)
        target_name = f"{safe_name}_{role}_{int(time.time())}{suffix}"
        target_path = (reference_dir / target_name).resolve()
        data = self._decode_avatar_profile_reference_image(payload.data_base64, role=role)
        target_path.write_bytes(data)
        now = datetime.now(timezone.utc).isoformat()
        reference = {
            "profile_id": profile_id,
            "role": role,
            "name": display_name or safe_name,
            "filename": target_name,
            "input_image": f"avatar_profiles/{profile_id}/refs/{role}/{target_name}",
            "url": f"/api/avatar-generation/profiles/{profile_id}/references/{role}/{target_name}",
            "created_at": now,
        }
        target_path.with_suffix(target_path.suffix + ".json").write_text(
            json.dumps(reference, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        existing = metadata.get("reference_counts") if isinstance(metadata.get("reference_counts"), dict) else {}
        updated_metadata = {
            **metadata,
            "reference_counts": {
                **existing,
                role: len(self._avatar_profile_references(profile_dir=profile_dir).get(role, [])),
            },
            "updated_at": now,
        }
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        saved_profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "uploaded",
            "reference": self._avatar_profile_reference_payload(path=target_path),
            "profile": saved_profile,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def delete_avatar_profile_reference(self, *, profile_id: str, role: str, asset_name: str) -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        role = self._avatar_profile_reference_role(role)
        safe_asset_name = Path(str(asset_name or "")).name
        path = (profile_dir / "refs" / role / safe_asset_name).resolve()
        if profile_dir not in path.parents or not path.exists() or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("avatar_profile_reference_not_found")
        path.unlink()
        sidecar = path.with_suffix(path.suffix + ".json")
        if sidecar.exists() and sidecar.is_file():
            sidecar.unlink()
        now = datetime.now(timezone.utc).isoformat()
        existing = metadata.get("reference_counts") if isinstance(metadata.get("reference_counts"), dict) else {}
        updated_metadata = {
            **metadata,
            "reference_counts": {
                **existing,
                role: len(self._avatar_profile_references(profile_dir=profile_dir).get(role, [])),
            },
            "updated_at": now,
        }
        if role == "face" and Path(str(metadata.get("primary_face_reference_filename") or "")).name == safe_asset_name:
            updated_metadata.pop("primary_face_reference_filename", None)
            updated_metadata.pop("primary_face_reference", None)
            updated_metadata.pop("primary_face_input_image", None)
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        return {
            "deleted": True,
            "role": role,
            "filename": safe_asset_name,
            "profile": self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id),
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def set_avatar_profile_primary_face(self, *, profile_id: str, payload: "AvatarPrimaryFaceRequest") -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        filename = Path(str(payload.filename or "")).name
        if not filename:
            raise ValueError("avatar_primary_face_filename_required")
        path = (profile_dir / "refs" / "face" / filename).resolve()
        if profile_dir not in path.parents or not path.exists() or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("avatar_face_reference_not_found")
        reference = self._avatar_profile_reference_payload(path=path)
        now = datetime.now(timezone.utc).isoformat()
        primary = {
            "filename": reference["filename"],
            "name": reference.get("name"),
            "input_image": reference.get("input_image"),
            "url": reference.get("url"),
            "updated_at": now,
        }
        updated_metadata = {
            **metadata,
            "primary_face_reference_filename": reference["filename"],
            "primary_face_reference": primary,
            "primary_face_input_image": reference.get("input_image"),
            "updated_at": now,
        }
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        saved_profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "primary_face_selected",
            "primary_face_reference": saved_profile.get("primary_face_reference"),
            "profile": saved_profile,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def extract_avatar_face_profile(self, *, profile_id: str, payload: "AvatarFaceProfileExtractRequest") -> dict:
        self._assert_avatar_vision_not_blocked_by_comfyui()
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        profile = self._avatar_profile_payload(profile_dir=profile_dir)
        sources = self._avatar_face_profile_sources(profile_dir=profile_dir, metadata=metadata, source_filenames=payload.source_filenames)
        if not sources:
            raise ValueError("avatar_face_references_not_found")
        descriptions: list[dict] = []
        vision_model_id = None
        prompt = self._avatar_face_reference_vision_prompt()
        for source in sources[:15]:
            path = source["path"]
            description, model_id = self._vision_describe_image_bytes(
                image_bytes=path.read_bytes(),
                mime_type=self._image_mime_type(path.suffix),
                image_name=path.name,
                prompt=prompt,
                max_tokens=1100,
                timeout_s=45,
            )
            vision_model_id = vision_model_id or model_id
            descriptions.append(
                {
                    "filename": source.get("filename"),
                    "name": source.get("name"),
                    "input_image": source.get("input_image"),
                    "description": description,
                }
            )
        structured, llm_model_id = self._avatar_face_profile_json_from_local_llm(
            profile=profile,
            descriptions=descriptions,
            primary_face_input_image=str(profile.get("primary_face_input_image") or profile.get("face_input_image") or ""),
            primary_face_filename=str(profile.get("primary_face_reference_filename") or profile.get("face_image") or ""),
        )
        now = datetime.now(timezone.utc).isoformat()
        face_profile = {
            "schema_version": "1.0",
            "status": "extracted",
            "created_at": now,
            "vision_model_id": vision_model_id,
            "local_llm_model_id": llm_model_id,
            "reference_count": len(descriptions),
            "primary_face_input_image": str(profile.get("primary_face_input_image") or profile.get("face_input_image") or ""),
            "primary_face_reference_filename": str(profile.get("primary_face_reference_filename") or ""),
            "references": descriptions,
            "combined_description": "\n\n".join(
                f"{item.get('filename')}: {item.get('description')}" for item in descriptions if item.get("description")
            ),
            "structured": structured,
        }
        updated_metadata = self._merge_avatar_face_profile_into_metadata(
            metadata=metadata,
            face_profile=face_profile,
            now=now,
        )
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        saved_profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "face_profile_extracted",
            "profile": saved_profile,
            "face_profile": face_profile,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def extract_avatar_profile_data(self, *, profile_id: str) -> dict:
        self._assert_avatar_vision_not_blocked_by_comfyui()
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        profile = self._avatar_profile_payload(profile_dir=profile_dir)
        if not profile:
            raise ValueError("avatar_profile_not_found")
        face_path = (profile_dir / str(profile.get("face_image") or "")).resolve()
        body_path = (profile_dir / str(profile.get("body_image") or "")).resolve()
        root = self._avatar_profile_root()
        if root not in face_path.parents or root not in body_path.parents or not face_path.exists() or not body_path.exists():
            raise ValueError("avatar_profile_assets_missing")
        face_description, vision_model_id = self._vision_describe_image_bytes(
            image_bytes=face_path.read_bytes(),
            mime_type=self._image_mime_type(face_path.suffix),
            image_name=face_path.name,
            prompt=(
                "Analyze this adult avatar face reference for reusable image-generation identity data. "
                "Return dense, non-repetitive, concrete visual observations for preserving the same face across future generations. "
                "Use compact bullet-style detail. Avoid generic praise, beauty/charm language, and application-suitability commentary. "
                "Describe face shape and proportions; forehead, temples, cheeks, cheekbones, jaw, chin; skin tone and skin texture; "
                "eye color, size, shape, spacing, eyelids, and gaze; eyebrow thickness, arch, and placement; nose bridge, tip, and nostrils; "
                "lip fullness, mouth shape, and smile line; ears and neck if visible; hairline, hair color, part, length, texture, volume, and styling; "
                "expression, makeup, distinctive marks, scars, moles, piercings, accessories, and identity-preservation notes. "
                "Separate stable identity traits from removable accessories or styling. Mark unclear or occluded traits as uncertain instead of guessing."
            ),
            max_tokens=1200,
            timeout_s=45,
        )
        body_description, _ = self._vision_describe_image_bytes(
            image_bytes=body_path.read_bytes(),
            mime_type=self._image_mime_type(body_path.suffix),
            image_name=body_path.name,
            prompt=(
                "Analyze this adult avatar full-body/body reference for reusable image-generation body identity data. "
                "Return a very detailed, non-repetitive, non-erotic, anatomy-preserving description that can help keep the same body shape in future generations. "
                "Use compact bullet-style detail. Avoid generic praise, health/damage/deformity claims, and repeated preservation statements. "
                "Do not estimate exact measurements; use relative visible descriptions only. Do not use 'average' as a default filler; use it only when the visible trait is clearly neutral compared with nearby body proportions. "
                "Prefer comparative silhouette language such as narrower, wider, longer, shorter, fuller, slimmer, straighter, rounded, tapered, compact, elongated, or occluded/uncertain. "
                "Separate stable body shape from temporary pose, crop, clothing, and accessories. "
                "Describe shoulder-to-waist-to-hip ratio, torso-to-leg proportion, bust-waist-hip silhouette, height impression, shoulder width and slope, neck length, torso length, ribcage, abdomen, waist definition, hip width, pelvis shape, and overall silhouette. "
                "Describe bust/breasts by visible relative size, shape, position, symmetry, spacing, and silhouette; describe buttocks/glutes by visible width, roundness, projection, and placement. "
                "For clothed or covered regions, describe only visible silhouette and mark hidden details as occluded or uncertain. "
                "Describe arm thickness and length, elbows, wrists, hands, finger length/shape, hand size, legs, leg length relative to torso, thigh/calf fullness, knees, ankles, feet, and foot stance. "
                "Describe skin tone, skin texture, visible marks, body asymmetries, posture, pose angle, head/shoulder/hip orientation, hand and arm placement, leg and foot placement, clothing, accessories, and body-preservation notes. "
                "If a trait is hidden by clothing, cropped out, or unclear, mark it as occluded or uncertain instead of inventing it or calling it average."
            ),
            max_tokens=1700,
            timeout_s=60,
        )
        body_description = self._clean_avatar_profile_body_description(body_description)
        structured, llm_model_id = self._avatar_profile_json_from_local_llm(
            profile=profile,
            face_description=face_description,
            body_description=body_description,
        )
        now = datetime.now(timezone.utc).isoformat()
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        extraction = {
            "schema_version": "1.0",
            "status": "extracted",
            "created_at": now,
            "vision_model_id": vision_model_id,
            "local_llm_model_id": llm_model_id,
            "face_description": face_description,
            "body_description": body_description,
            "structured": structured,
        }
        updated = {**metadata, "extraction": extraction, "updated_at": now}
        profile_path = profile_dir / "profile.json"
        profile_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        saved_profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "extracted",
            "profile": saved_profile,
            "extraction": extraction,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def update_avatar_profile_extraction(self, *, profile_id: str, payload: "AvatarProfileExtractionUpdateRequest") -> dict:
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            raise ValueError("avatar_profile_not_found")
        existing_extraction = metadata.get("extraction") if isinstance(metadata.get("extraction"), dict) else {}
        face_description = (
            str(payload.face_description).strip()
            if payload.face_description is not None
            else str(existing_extraction.get("face_description") or "").strip()
        )
        body_description = (
            str(payload.body_description).strip()
            if payload.body_description is not None
            else str(existing_extraction.get("body_description") or "").strip()
        )
        structured = self._normalize_avatar_profile_structured_data(
            parsed=payload.structured if isinstance(payload.structured, dict) else {},
            profile=metadata,
            face_description=face_description,
            body_description=body_description,
        )
        now = datetime.now(timezone.utc).isoformat()
        extraction = {
            **existing_extraction,
            "schema_version": existing_extraction.get("schema_version") or "1.0",
            "status": "edited",
            "created_at": existing_extraction.get("created_at") or now,
            "updated_at": now,
            "face_description": face_description,
            "body_description": body_description,
            "structured": structured,
        }
        updated = {**metadata, "extraction": extraction, "updated_at": now}
        profile_path = profile_dir / "profile.json"
        profile_path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        selected_profile_id = self._selected_avatar_profile_id()
        saved_profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
        return {
            "status": "updated",
            "profile": saved_profile,
            "extraction": extraction,
            "profiles": self._avatar_profiles(limit=48, selected_profile_id=selected_profile_id),
        }

    def _assert_avatar_vision_not_blocked_by_comfyui(self) -> None:
        services = self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        session = webui.get("session") if isinstance(webui, dict) and isinstance(webui.get("session"), dict) else {}
        webui_state = str(webui.get("state") or "").strip().lower() if isinstance(webui, dict) else ""
        manual_active = bool(webui.get("manual_session_active") or session.get("manual_session_active")) if isinstance(webui, dict) else False
        if webui_state in {"running", "starting"} or manual_active:
            raise ValueError("vision_blocked_by_manual_comfyui_webui")
        comfyui_gpu = services.get("comfyui_gpu") if isinstance(services, dict) else {}
        comfyui_gpu_state = str(comfyui_gpu.get("state") or "").strip().lower() if isinstance(comfyui_gpu, dict) else ""
        if comfyui_gpu_state in {"running", "starting"}:
            raise ValueError("vision_blocked_by_comfyui_gpu")

    def _avatar_face_profile_sources(self, *, profile_dir: Path, metadata: dict, source_filenames: list[str] | None) -> list[dict]:
        selected = {
            Path(str(item or "")).name
            for item in list(source_filenames or [])
            if str(item or "").strip()
        }
        references = self._avatar_profile_references(profile_dir=profile_dir).get("face", [])
        sources: list[dict] = []
        for reference in references:
            filename = Path(str(reference.get("filename") or "")).name
            if not filename or (selected and filename not in selected):
                continue
            path = (profile_dir / "refs" / "face" / filename).resolve()
            if profile_dir not in path.parents or not path.exists() or not path.is_file():
                continue
            sources.append({**reference, "path": path})
        if sources or selected:
            return sources
        face_image = Path(str(metadata.get("face_image") or "")).name
        if not face_image:
            return []
        face_path = (profile_dir / face_image).resolve()
        if profile_dir not in face_path.parents or not face_path.exists() or not face_path.is_file():
            return []
        profile_id = self._safe_filename_component(metadata.get("profile_id") or profile_dir.name)
        return [
            {
                "profile_id": profile_id,
                "role": "face",
                "name": "Profile Face",
                "filename": face_image,
                "input_image": f"avatar_profiles/{profile_id}/{face_image}",
                "path": face_path,
            }
        ]

    @staticmethod
    def _avatar_face_reference_vision_prompt() -> str:
        return (
            "Analyze this adult avatar face reference for reusable identity control. "
            "Return dense, concrete, non-repetitive observations. Describe only visible traits and mark unclear traits uncertain. "
            "Cover face shape and proportions; forehead, temples, cheeks, cheekbones, jaw, chin; skin tone and texture; "
            "eye color, size, shape, spacing, eyelids, gaze; eyebrow thickness, arch, placement; nose bridge, tip, nostrils; "
            "lip fullness, mouth shape, smile line; ears and neck if visible; hairline, hair color, part, length, texture, volume, styling; "
            "expression, makeup, distinctive marks, scars, moles, piercings, accessories, crop/framing, lighting/quality, and identity-preservation notes. "
            "Separate stable identity traits from removable styling or accessories."
        )

    def _avatar_face_profile_json_from_local_llm(
        self,
        *,
        profile: dict,
        descriptions: list[dict],
        primary_face_input_image: str,
        primary_face_filename: str,
    ) -> tuple[dict, str]:
        compact_descriptions = self._avatar_face_profile_compact_observations(descriptions)
        combined_description = "\n\n".join(
            f"{item.get('filename')}: {item.get('description')}" for item in compact_descriptions if item.get("description")
        )
        services = self.service_status_payload().get("services", {})
        local_llm = services.get("local_llm") if isinstance(services, dict) else {}
        socket_path = str(local_llm.get("socket_path") or "") if isinstance(local_llm, dict) else ""
        model_id = str(local_llm.get("model_id") or local_llm.get("default_model_id") or "local").strip() if isinstance(local_llm, dict) else "local"
        state = str(local_llm.get("state") or "").strip().lower() if isinstance(local_llm, dict) else ""
        request_payload = {
            "profile_name": profile.get("name") or profile.get("profile_id"),
            "primary_face_filename": primary_face_filename,
            "primary_face_input_image": primary_face_input_image,
            "face_reference_observations": compact_descriptions,
        }
        if not socket_path or state not in {"running", "healthy"}:
            return self._fallback_avatar_face_profile_structured(
                profile=profile,
                descriptions=descriptions,
                combined_description=combined_description,
                primary_face_input_image=primary_face_input_image,
                primary_face_filename=primary_face_filename,
                model_id=model_id,
                error=f"local_llm_unavailable:{state or 'not_running'}",
            ), "local_rules"
        request_body = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "/no_think Combine multiple avatar face-reference observations into strict reusable JSON for SDXL/ComfyUI identity prompts. "
                        "Return only JSON, no markdown. Required keys: schema_version, profile_name, primary_face_filename, primary_face_input_image, "
                        "stable_identity, identity_prompt, face_prompt, hair_prompt, expression_prompt, removable_styling, accessories, reference_quality_notes, negative_prompt_terms. "
                        "stable_identity must include face_shape, skin, eyes, brows, nose, lips, cheekbones, jaw_chin, hairline_hair, visible_age_range, distinctive_marks, and identity_preservation. "
                        "identity_prompt and face_prompt must be prompt-ready strings that preserve traits seen consistently across references. "
                        "Do not invent traits not supported by the references. Mark disagreements or occlusions as uncertain in reference_quality_notes. "
                        "negative_prompt_terms must avoid bad identity outcomes, never anatomy-erasing terms like no face, no eyes, no skin, no hair."
                    ),
                },
                {"role": "user", "content": "/no_think " + json.dumps(request_payload, sort_keys=True)},
            ],
            "temperature": 0.1,
            "max_tokens": 1000,
            "stream": False,
        }
        try:
            response = self._uds_json_request(
                socket_path=socket_path,
                method="POST",
                path="/v1/chat/completions",
                body=request_body,
                host="local-llm",
                error_label="local_llm_avatar_face_profile_extract_failed",
                timeout_s=75,
            )
        except Exception as exc:
            return self._fallback_avatar_face_profile_structured(
                profile=profile,
                descriptions=descriptions,
                combined_description=combined_description,
                primary_face_input_image=primary_face_input_image,
                primary_face_filename=primary_face_filename,
                model_id=model_id,
                error=str(exc),
            ), "local_rules"
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(message.get("content") or message.get("reasoning_content") or choices[0].get("text") or "").strip()
        parsed = self._parse_manual_image_prompt_helper_content(content)
        if not parsed:
            parsed = {}
        return self._normalize_avatar_face_profile_structured(
            parsed=parsed,
            profile=profile,
            descriptions=descriptions,
            combined_description=combined_description,
            primary_face_input_image=primary_face_input_image,
            primary_face_filename=primary_face_filename,
        ), model_id

    @classmethod
    def _fallback_avatar_face_profile_structured(
        cls,
        *,
        profile: dict,
        descriptions: list[dict],
        combined_description: str,
        primary_face_input_image: str,
        primary_face_filename: str,
        model_id: str,
        error: str,
    ) -> dict:
        return cls._normalize_avatar_face_profile_structured(
            parsed={
                "profile_name": profile.get("name") or profile.get("profile_id"),
                "primary_face_filename": primary_face_filename,
                "primary_face_input_image": primary_face_input_image,
                "stable_identity": {"description": combined_description},
                "identity_prompt": combined_description,
                "face_prompt": combined_description,
                "hair_prompt": "",
                "expression_prompt": "",
                "reference_quality_notes": {
                    "structured_source": "vision_descriptions_local_rules",
                    "local_llm_model_id": model_id,
                    "local_llm_error": error,
                },
                **cls._avatar_face_profile_prompt_fields_from_descriptions(
                    profile=profile,
                    descriptions=descriptions,
                ),
            },
            profile=profile,
            descriptions=descriptions,
            combined_description=combined_description,
            primary_face_input_image=primary_face_input_image,
            primary_face_filename=primary_face_filename,
        )

    @classmethod
    def _normalize_avatar_face_profile_structured(
        cls,
        *,
        parsed: dict,
        profile: dict,
        descriptions: list[dict],
        combined_description: str,
        primary_face_input_image: str,
        primary_face_filename: str,
    ) -> dict:
        source = parsed if isinstance(parsed, dict) else {}
        stable_identity = cls._avatar_profile_dict_value(source.get("stable_identity"))
        if not stable_identity:
            stable_identity = {"description": combined_description}
        identity_prompt = cls._avatar_profile_prompt_sized_text(
            str(source.get("identity_prompt") or "").strip() or cls._avatar_profile_compact_text(stable_identity) or combined_description,
            max_chars=900,
        )
        face_prompt = cls._avatar_profile_prompt_sized_text(
            str(source.get("face_prompt") or "").strip() or identity_prompt,
            max_chars=700,
        )
        negative_terms = cls._avatar_profile_negative_terms(source.get("negative_prompt_terms") or ["different person", "changed face", "blurred face", "distorted face", "inconsistent identity"])
        return {
            "schema_version": str(source.get("schema_version") or "1.0"),
            "profile_name": str(source.get("profile_name") or profile.get("name") or profile.get("profile_id") or "avatar").strip(),
            "primary_face_filename": str(source.get("primary_face_filename") or primary_face_filename).strip(),
            "primary_face_input_image": str(source.get("primary_face_input_image") or primary_face_input_image).strip(),
            "reference_count": len(descriptions),
            "stable_identity": stable_identity,
            "identity_prompt": identity_prompt,
            "face_prompt": face_prompt,
            "hair_prompt": cls._avatar_profile_prompt_sized_text(str(source.get("hair_prompt") or "").strip(), max_chars=350),
            "expression_prompt": cls._avatar_profile_prompt_sized_text(str(source.get("expression_prompt") or "").strip(), max_chars=250),
            "removable_styling": cls._avatar_profile_dict_value(source.get("removable_styling")),
            "accessories": cls._avatar_profile_dict_value(source.get("accessories")),
            "reference_quality_notes": cls._avatar_profile_dict_value(source.get("reference_quality_notes")),
            "negative_prompt_terms": negative_terms,
            "negative_identity_prompt": ", ".join(negative_terms),
        }

    @classmethod
    def _avatar_face_profile_compact_observations(cls, descriptions: list[dict], *, max_per_reference: int = 1100) -> list[dict]:
        compact = []
        for item in descriptions:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "")
            trait_text = cls._avatar_profile_trait_text(
                description,
                keywords=(
                    "face",
                    "forehead",
                    "temple",
                    "cheek",
                    "jaw",
                    "chin",
                    "skin",
                    "eye",
                    "eyelid",
                    "brow",
                    "nose",
                    "lip",
                    "mouth",
                    "hair",
                    "expression",
                    "makeup",
                    "mark",
                    "mole",
                    "scar",
                    "piercing",
                    "accessor",
                    "identity",
                ),
                max_items=18,
            )
            compact.append(
                {
                    "filename": item.get("filename"),
                    "name": item.get("name"),
                    "input_image": item.get("input_image"),
                    "description": cls._avatar_profile_prompt_sized_text(trait_text or description, max_chars=max_per_reference),
                }
            )
        return compact

    @classmethod
    def _avatar_face_profile_prompt_fields_from_descriptions(cls, *, profile: dict, descriptions: list[dict]) -> dict:
        combined = "\n".join(str(item.get("description") or "") for item in descriptions if isinstance(item, dict))
        field_specs = {
            "face_shape": ("face shape", "oval", "round", "forehead", "temple", "proportion", "symmetr"),
            "skin": ("skin tone", "skin texture", "fair", "light", "medium", "smooth", "freckle"),
            "eyes": ("eye", "eyelid", "gaze", "almond", "green"),
            "brows": ("eyebrow", "brow", "arch"),
            "nose": ("nose", "nostril", "bridge"),
            "lips": ("lip", "mouth", "smile line"),
            "cheekbones": ("cheek", "cheekbone"),
            "jaw_chin": ("jaw", "chin"),
            "hairline_hair": ("hairline", "hair color", "hair", "part", "wavy", "volume"),
            "expression": ("expression", "makeup"),
            "distinctive_marks": ("distinctive", "mark", "mole", "scar", "piercing", "accessor"),
        }
        stable_identity = {}
        for field, keywords in field_specs.items():
            text = cls._avatar_profile_trait_text(combined, keywords=keywords, max_items=4)
            if text:
                stable_identity[field] = cls._avatar_profile_prompt_sized_text(text, max_chars=220)
        if not stable_identity:
            stable_identity["description"] = cls._avatar_profile_prompt_sized_text(combined, max_chars=700)
        face_parts = [
            stable_identity.get("face_shape"),
            stable_identity.get("skin"),
            stable_identity.get("eyes"),
            stable_identity.get("brows"),
            stable_identity.get("nose"),
            stable_identity.get("lips"),
            stable_identity.get("cheekbones"),
            stable_identity.get("jaw_chin"),
        ]
        identity_prompt = cls._avatar_profile_join_prompt_parts(
            ["same avatar identity", *face_parts, stable_identity.get("hairline_hair"), stable_identity.get("expression")],
            max_chars=850,
        )
        face_prompt = cls._avatar_profile_join_prompt_parts(face_parts, max_chars=650) or identity_prompt
        hair_prompt = cls._avatar_profile_prompt_sized_text(stable_identity.get("hairline_hair") or "", max_chars=300)
        expression_prompt = cls._avatar_profile_prompt_sized_text(stable_identity.get("expression") or "", max_chars=220)
        return {
            "stable_identity": stable_identity,
            "identity_prompt": identity_prompt,
            "face_prompt": face_prompt,
            "hair_prompt": hair_prompt,
            "expression_prompt": expression_prompt,
            "negative_prompt_terms": ["different person", "changed face", "blurred face", "distorted face", "inconsistent identity"],
        }

    @classmethod
    def _merge_avatar_face_profile_into_metadata(cls, *, metadata: dict, face_profile: dict, now: str) -> dict:
        structured_face = face_profile.get("structured") if isinstance(face_profile.get("structured"), dict) else {}
        face_description = str(structured_face.get("face_prompt") or face_profile.get("combined_description") or "").strip()
        existing_extraction = metadata.get("extraction") if isinstance(metadata.get("extraction"), dict) else {}
        extraction = dict(existing_extraction)
        if face_description:
            extraction["face_description"] = face_description
        existing_structured = extraction.get("structured") if isinstance(extraction.get("structured"), dict) else {}
        if existing_structured:
            permanent_identity = cls._avatar_profile_dict_value(existing_structured.get("permanent_identity"))
            permanent_identity["face"] = structured_face.get("stable_identity") or face_description
            permanent_identity["identity_prompt"] = structured_face.get("identity_prompt") or permanent_identity.get("identity_prompt") or face_description
            prompt_sections = cls._avatar_profile_dict_value(existing_structured.get("prompt_sections"))
            prompt_sections["identity"] = structured_face.get("identity_prompt") or prompt_sections.get("identity") or ""
            prompt_sections["face"] = structured_face.get("face_prompt") or prompt_sections.get("face") or ""
            if structured_face.get("hair_prompt"):
                prompt_sections["hair"] = structured_face.get("hair_prompt")
            existing_structured = {
                **existing_structured,
                "permanent_identity": permanent_identity,
                "identity_prompt": prompt_sections.get("identity") or permanent_identity.get("identity_prompt") or "",
                "prompt_sections": prompt_sections,
            }
            extraction["structured"] = existing_structured
            extraction["updated_at"] = now
        elif face_description:
            extraction = {
                "schema_version": "1.0",
                "status": "face_extracted",
                "created_at": now,
                "updated_at": now,
                "face_description": face_description,
                "body_description": str(existing_extraction.get("body_description") or ""),
                "structured": {
                    "schema_version": "2.0",
                    "profile_name": metadata.get("name") or metadata.get("profile_id") or "avatar",
                    "identity_prompt": structured_face.get("identity_prompt") or face_description,
                    "permanent_identity": {
                        "face": structured_face.get("stable_identity") or face_description,
                        "identity_prompt": structured_face.get("identity_prompt") or face_description,
                    },
                    "prompt_sections": {
                        "identity": structured_face.get("identity_prompt") or face_description,
                        "face": structured_face.get("face_prompt") or face_description,
                        "hair": structured_face.get("hair_prompt") or "",
                        "body_shape": "",
                        "pose": "",
                        "clothing": "",
                        "accessories": cls._avatar_profile_compact_text(structured_face.get("accessories")),
                        "preservation": "",
                        "negative": structured_face.get("negative_identity_prompt") or "",
                    },
                    "negative_prompt_terms": structured_face.get("negative_prompt_terms") or [],
                },
            }
        return {**metadata, "face_profile": face_profile, "extraction": extraction, "updated_at": now}

    def _avatar_profile_json_from_local_llm(self, *, profile: dict, face_description: str, body_description: str) -> tuple[dict, str]:
        services = self.service_status_payload().get("services", {})
        local_llm = services.get("local_llm") if isinstance(services, dict) else {}
        socket_path = str(local_llm.get("socket_path") or "") if isinstance(local_llm, dict) else ""
        model_id = str(local_llm.get("model_id") or local_llm.get("default_model_id") or "local").strip() if isinstance(local_llm, dict) else "local"
        state = str(local_llm.get("state") or "").strip().lower() if isinstance(local_llm, dict) else ""
        if not socket_path or state not in {"running", "healthy"}:
            raise ValueError(f"local_llm_unavailable:{state or 'not_running'}")
        request_body = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "/no_think Convert avatar reference observations into strict reusable JSON for future SDXL/ComfyUI prompts. "
                        "Return only JSON, no markdown. Use schema_version '2.0'. "
                        "Required keys: schema_version, profile_name, permanent_identity, body_profile, removable_clothing, accessories, pose_reference, preservation_notes, prompt_sections, negative_prompt_terms. "
                        "permanent_identity must include stable face, skin, eyes, brows, nose, lips, cheekbones, jaw_chin, hair, visible_age_range, expression, and identity_prompt. "
                        "body_profile must be a JSON object with separate keys: proportions, silhouette, build, shoulders_neck, torso_waist_abdomen, bust_breasts, hips_pelvis, buttocks_glutes, arms_hands_fingers, legs_feet, skin_texture_marks, and body_prompt. "
                        "Do not return body_profile as a single markdown body_prompt only. "
                        "body_prompt must be a dense, non-repetitive, prompt-ready paragraph, not markdown, preserving shoulder-to-waist-to-hip ratio, torso-to-leg proportions, bust-waist-hip silhouette, limb thickness, hands, legs, bust/breasts, hips, and buttocks/glutes while marking occluded traits as uncertain. "
                        "Avoid using average as filler. If the vision notes say average without useful detail, convert it into visible comparative shape language or mark the trait uncertain/occluded. "
                        "Avoid exact measurements, health/damage/deformity claims, and repeated preservation phrases unless directly visible and useful. "
                        "removable_clothing must describe only currently worn clothing and must not be mixed into identity unless it is truly permanent. "
                        "accessories must separate permanent_accessories from removable_accessories and mark uncertain items as uncertain. "
                        "pose_reference must describe current pose separately from body shape, including head_turn, body_angle, shoulders, arms_hands, legs_feet, and crop/framing when visible. "
                        "prompt_sections must be an object with identity, face, hair, body_shape, pose, clothing, accessories, preservation, and negative keys. "
                        "prompt_sections.body_shape must preserve the detailed body_profile rather than reducing it to a short summary. "
                        "negative_prompt_terms must be an array of bad outcomes to avoid. Never include terms that erase normal anatomy or identity such as no face, no eyes, no skin, no nose, no lips, no hair, or no expression. "
                        "Keep values specific, compact, and avoid inventing accessories not supported by the observations."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "/no_think "
                        + json.dumps(
                            {
                                "profile_name": profile.get("name"),
                                "manual_description": profile.get("description"),
                                "face_vision_description": face_description,
                                "body_vision_description": body_description,
                            },
                            sort_keys=True,
                        )
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 1200,
            "stream": False,
        }
        try:
            response = self._uds_json_request(
                socket_path=socket_path,
                method="POST",
                path="/v1/chat/completions",
                body=request_body,
                host="local-llm",
                error_label="local_llm_avatar_profile_extract_failed",
                timeout_s=90,
            )
        except Exception as exc:
            if self._logger:
                self._logger.warning(
                    "avatar profile local LLM extraction failed; using vision-only fallback",
                    extra={"error": str(exc), "model_id": model_id},
                )
            parsed = self._fallback_avatar_profile_parsed(
                profile=profile,
                face_description=face_description,
                body_description=body_description,
                model_id=model_id,
                error=str(exc),
            )
            return self._normalize_avatar_profile_structured_data(
                parsed=parsed,
                profile=profile,
                face_description=face_description,
                body_description=body_description,
            ), "local_rules"
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(message.get("content") or message.get("reasoning_content") or choices[0].get("text") or "").strip()
        parsed = self._parse_manual_image_prompt_helper_content(content)
        if not parsed:
            parsed = {
                "profile_name": profile.get("name"),
                "permanent_identity": {"identity_prompt": str(profile.get("description") or "").strip(), "face": face_description},
                "body_profile": {"body_prompt": body_description},
                "raw_response": content,
            }
        return self._normalize_avatar_profile_structured_data(
            parsed=parsed,
            profile=profile,
            face_description=face_description,
            body_description=body_description,
        ), model_id

    @classmethod
    def _fallback_avatar_profile_parsed(
        cls,
        *,
        profile: dict,
        face_description: str,
        body_description: str,
        model_id: str,
        error: str,
    ) -> dict:
        profile_name = str(profile.get("name") or profile.get("profile_id") or "avatar").strip()
        manual_description = str(profile.get("description") or "").strip()
        identity_prompt = manual_description or face_description
        return {
            "schema_version": "2.0",
            "profile_name": profile_name,
            "permanent_identity": {
                "face": face_description,
                "identity_prompt": identity_prompt,
            },
            "body_profile": {
                "description": body_description,
                "body_prompt": body_description,
            },
            "removable_clothing": {
                "description": "Not separated by local LLM; review the body description before using clothing as a reusable identity trait."
            },
            "accessories": {
                "description": "Not separated by local LLM; review the face and body descriptions for permanent versus removable accessories."
            },
            "pose_reference": {
                "description": "Not separated by local LLM; review the body description for pose details."
            },
            "preservation_notes": {
                "notes": "Generated from local vision descriptions because local LLM profile structuring was unavailable."
            },
            "source_quality_notes": {
                "structured_source": "vision_descriptions_local_rules",
                "local_llm_model_id": model_id,
                "local_llm_error": error,
            },
        }

    @classmethod
    def _normalize_avatar_profile_structured_data(
        cls,
        *,
        parsed: dict,
        profile: dict,
        face_description: str,
        body_description: str,
    ) -> dict:
        body_description = cls._clean_avatar_profile_body_description(body_description)
        source = parsed if isinstance(parsed, dict) else {}
        profile_name = str(source.get("profile_name") or profile.get("name") or profile.get("profile_id") or "avatar").strip()
        permanent_identity = cls._avatar_profile_dict_value(source.get("permanent_identity"))
        legacy_face = cls._avatar_profile_dict_value(source.get("face"))
        legacy_hair = source.get("hair")
        if legacy_face and not permanent_identity.get("face"):
            permanent_identity["face"] = legacy_face
        if legacy_hair and not permanent_identity.get("hair"):
            permanent_identity["hair"] = legacy_hair
        if not permanent_identity.get("face"):
            permanent_identity["face"] = face_description
        if not permanent_identity.get("identity_prompt"):
            permanent_identity["identity_prompt"] = (
                str(source.get("identity_prompt") or "").strip()
                or cls._avatar_profile_compact_text(permanent_identity)
                or str(profile.get("description") or "").strip()
            )

        body_profile = cls._avatar_profile_dict_value(source.get("body_profile") or source.get("body"))
        if not body_profile.get("body_prompt"):
            body_profile["body_prompt"] = cls._avatar_profile_compact_text(body_profile) or body_description
        body_profile["body_prompt"] = cls._clean_avatar_profile_body_description(body_profile.get("body_prompt"))
        cls._populate_avatar_profile_body_sections(body_profile=body_profile, body_description=body_description)
        cls._clean_avatar_profile_body_profile_fields(body_profile)

        removable_clothing = cls._avatar_profile_dict_value(source.get("removable_clothing") or source.get("clothing_reference"))
        accessories = cls._avatar_profile_dict_value(source.get("accessories"))
        pose_reference = cls._avatar_profile_dict_value(source.get("pose_reference"))
        preservation_notes = cls._avatar_profile_dict_value(source.get("preservation_notes"))
        if not preservation_notes:
            notes = source.get("preservation_notes")
            preservation_notes = {"notes": str(notes or "").strip()} if notes else {}

        prompt_sections = cls._avatar_profile_dict_value(source.get("prompt_sections"))
        prompt_sections = {
            "identity": str(prompt_sections.get("identity") or permanent_identity.get("identity_prompt") or "").strip(),
            "face": str(prompt_sections.get("face") or cls._avatar_profile_compact_text(permanent_identity.get("face"))).strip(),
            "hair": str(prompt_sections.get("hair") or cls._avatar_profile_compact_text(permanent_identity.get("hair"))).strip(),
            "body_shape": cls._clean_avatar_profile_body_description(str(prompt_sections.get("body_shape") or body_profile.get("body_prompt") or "").strip()),
            "pose": str(prompt_sections.get("pose") or cls._avatar_profile_compact_text(pose_reference)).strip(),
            "clothing": str(prompt_sections.get("clothing") or cls._avatar_profile_compact_text(removable_clothing)).strip(),
            "accessories": str(prompt_sections.get("accessories") or cls._avatar_profile_compact_text(accessories)).strip(),
            "preservation": str(prompt_sections.get("preservation") or cls._avatar_profile_compact_text(preservation_notes)).strip(),
            "negative": "",
        }
        negative_terms = cls._avatar_profile_negative_terms(
            source.get("negative_prompt_terms") or source.get("negative_identity_prompt") or prompt_sections.get("negative")
        )
        prompt_sections["negative"] = ", ".join(negative_terms)
        identity_prompt = prompt_sections["identity"] or str(permanent_identity.get("identity_prompt") or "").strip()

        return {
            "schema_version": "2.0",
            "profile_name": profile_name,
            "identity_prompt": identity_prompt,
            "permanent_identity": permanent_identity,
            "body_profile": body_profile,
            "removable_clothing": removable_clothing,
            "accessories": accessories,
            "pose_reference": pose_reference,
            "preservation_notes": preservation_notes,
            "prompt_sections": prompt_sections,
            "negative_prompt_terms": negative_terms,
            "negative_identity_prompt": ", ".join(negative_terms),
            "source_quality_notes": cls._avatar_profile_dict_value(source.get("source_quality_notes")),
        }

    @classmethod
    def _avatar_profile_dict_value(cls, value) -> dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            return {"description": value.strip()}
        return {}

    @classmethod
    def _populate_avatar_profile_body_sections(cls, *, body_profile: dict, body_description: str) -> None:
        source_text = cls._avatar_profile_compact_text(body_profile.get("body_prompt")) or body_description
        sections = cls._avatar_profile_markdown_sections(source_text)
        if not sections:
            return
        field_keywords = {
            "proportions": ("height", "proportion"),
            "silhouette": ("silhouette",),
            "build": ("build",),
            "shoulders_neck": ("shoulder", "neck", "clavicle"),
            "torso_waist_abdomen": ("torso", "ribcage", "abdomen", "waist"),
            "bust_breasts": ("bust", "breast"),
            "hips_pelvis": ("hip", "pelvis"),
            "buttocks_glutes": ("buttock", "glute"),
            "arms_hands_fingers": ("arm", "elbow", "wrist", "hand", "finger"),
            "legs_feet": ("leg", "thigh", "knee", "calf", "ankle", "foot", "feet"),
            "skin_texture_marks": ("skin", "mark", "scar", "mole", "asymmetr"),
        }
        for field, keywords in field_keywords.items():
            if cls._avatar_profile_compact_text(body_profile.get(field)):
                continue
            text = cls._avatar_profile_sections_for_keywords(sections=sections, keywords=keywords)
            if text:
                body_profile[field] = text

    @classmethod
    def _clean_avatar_profile_body_profile_fields(cls, body_profile: dict) -> None:
        for field in (
            "proportions",
            "silhouette",
            "build",
            "shoulders_neck",
            "torso_waist_abdomen",
            "bust_breasts",
            "hips_pelvis",
            "buttocks_glutes",
            "arms_hands_fingers",
            "legs_feet",
            "skin_texture_marks",
        ):
            if field in body_profile:
                body_profile[field] = cls._clean_avatar_profile_inline_body_text(body_profile.get(field))

    @classmethod
    def _avatar_profile_markdown_sections(cls, text: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_lines: list[str] = []
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                if current_lines and current_lines[-1]:
                    current_lines.append("")
                continue
            bullet_label = cls._avatar_profile_bullet_label(line)
            if bullet_label:
                heading, body = bullet_label
                if current_heading and current_lines:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                if body:
                    sections.append((heading, body))
                    current_heading = ""
                    current_lines = []
                else:
                    current_heading = heading
                    current_lines = []
                continue
            heading = ""
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
            elif line.endswith(":") and len(line) <= 80:
                heading = line[:-1].strip()
            if heading:
                if current_heading and current_lines:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                current_heading = heading
                current_lines = []
                continue
            if current_heading:
                current_lines.append(line.lstrip("-* ").strip())
        if current_heading and current_lines:
            sections.append((current_heading, "\n".join(current_lines).strip()))
        return sections

    @classmethod
    def _avatar_profile_bullet_label(cls, line: str) -> tuple[str, str] | None:
        candidate = str(line or "").strip()
        if candidate.startswith(("- ", "* ")):
            candidate = candidate[2:].strip()
        malformed_bold = re.match(r"^\*{2,}(.+?)\*{2}:\s*(.*)$", candidate)
        if malformed_bold:
            heading, body = malformed_bold.groups()
            return heading.strip().strip("*"), body.strip()
        if candidate.startswith("**") and "**:" in candidate:
            heading, body = candidate[2:].split("**:", 1)
            return heading.strip(), body.strip()
        if ":" not in candidate:
            return None
        heading, body = candidate.split(":", 1)
        heading = heading.strip()
        if not heading or len(heading) > 80:
            return None
        return heading, body.strip()

    @classmethod
    def _avatar_profile_sections_for_keywords(cls, *, sections: list[tuple[str, str]], keywords: tuple[str, ...]) -> str:
        parts = []
        seen = set()
        for heading, body in sections:
            lowered = heading.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            text = body.strip()
            normalized = " ".join(text.lower().split())
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            parts.append(text)
        return " ".join(parts)

    @classmethod
    def _avatar_profile_trait_text(cls, text: str, *, keywords: tuple[str, ...], max_items: int = 8) -> str:
        candidates: list[str] = []
        sections = cls._avatar_profile_markdown_sections(text)
        for heading, body in sections:
            candidate = f"{heading}: {body}".strip()
            candidates.append(candidate)
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if line:
                candidates.append(line)
        parts = []
        seen = set()
        for candidate in candidates:
            cleaned = cls._avatar_profile_clean_prompt_fragment(candidate)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            if cls._avatar_profile_low_value_observation(lowered):
                continue
            normalized = " ".join(lowered.split())
            if normalized in seen:
                continue
            seen.add(normalized)
            parts.append(cleaned)
            if len(parts) >= max_items:
                break
        return cls._avatar_profile_join_prompt_parts(parts, max_chars=900)

    @staticmethod
    def _avatar_profile_low_value_observation(lowered: str) -> bool:
        if not lowered:
            return True
        low_value_fragments = (
            "high-quality",
            "image quality",
            "suitable for",
            "intended for",
            "no visible signs of digital",
            "no visible artifacts",
            "no visible crop marks",
            "no visible lighting marks",
            "no visible health",
            "health damage",
            "health deform",
            "health asymmetr",
        )
        return any(fragment in lowered for fragment in low_value_fragments)

    @classmethod
    def _avatar_profile_clean_prompt_fragment(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = re.sub(r"^[\w .()_-]+\.(?:png|jpe?g|webp):\s*", "", text, flags=re.IGNORECASE)
        text = cls._avatar_profile_strip_non_english_fragments(text)
        text = text.lstrip("-*# ").strip()
        text = text.replace("**", "").replace("__", "")
        text = re.sub(r"\s+", " ", text)
        text = text.strip(" -;,.")
        return text

    @classmethod
    def _avatar_profile_prompt_sized_text(cls, value: str, *, max_chars: int) -> str:
        text = cls._avatar_profile_clean_prompt_fragment(value)
        if len(text) <= max_chars:
            return text
        shortened = text[:max_chars].rsplit(",", 1)[0].rsplit(".", 1)[0].strip()
        if len(shortened) < max_chars * 0.5:
            shortened = text[:max_chars].strip()
        return shortened.strip(" -;,.")

    @classmethod
    def _avatar_profile_join_prompt_parts(cls, parts, *, max_chars: int = 900) -> str:
        joined = []
        seen = set()
        for part in parts:
            text = cls._avatar_profile_clean_prompt_fragment(part)
            if not text:
                continue
            normalized = " ".join(text.lower().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            candidate = ", ".join([*joined, text]) if joined else text
            if len(candidate) > max_chars:
                break
            joined.append(text)
        return ", ".join(joined)

    @classmethod
    def _clean_avatar_profile_body_description(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        cleaned_lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                if cleaned_lines and cleaned_lines[-1]:
                    cleaned_lines.append("")
                continue
            bullet = cls._avatar_profile_bullet_label(line)
            if bullet:
                heading, body = bullet
                body = cls._avatar_profile_clean_body_clause_text(body, heading=heading)
                if not body:
                    continue
                prefix = "- " if line.lstrip().startswith(("-", "*")) else ""
                cleaned_lines.append(f"{prefix}{heading}: {body}")
                continue
            cleaned_lines.append(cls._avatar_profile_clean_body_clause_text(line, heading=""))
        while cleaned_lines and not cleaned_lines[-1]:
            cleaned_lines.pop()
        return "\n".join(line for line in cleaned_lines if line is not None).strip()

    @classmethod
    def _clean_avatar_profile_inline_body_text(cls, value) -> str:
        text = cls._avatar_profile_compact_text(value)
        if not text:
            return ""
        parts = []
        seen = set()
        for raw_part in re.split(r"(?<=[.!?])\s+|;\s+", text):
            cleaned = cls._avatar_profile_clean_body_clause_text(raw_part, heading="")
            if not cleaned:
                continue
            normalized = " ".join(cleaned.lower().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            parts.append(cleaned)
        return " ".join(parts).strip()

    @classmethod
    def _avatar_profile_clean_body_clause_text(cls, text: str, *, heading: str) -> str:
        source = str(text or "").strip()
        if not source:
            return ""
        source = cls._avatar_profile_strip_non_english_fragments(source)
        source = cls._avatar_profile_collapse_awkward_body_phrases(source)
        source = cls._avatar_profile_reduce_average_filler(source)
        heading_lower = str(heading or "").lower()
        clauses = [
            cls._avatar_profile_clean_prompt_fragment(item)
            for item in re.split(r"[,;]\s+|(?<=[.!?])\s+", source)
        ]
        cleaned = []
        seen = set()
        noisy_count = 0
        for clause in clauses:
            lowered = clause.lower()
            if not clause:
                continue
            if any(fragment in lowered for fragment in ("health", "damage", "deformit")):
                noisy_count += 1
                continue
            clause = cls._avatar_profile_reduce_average_filler(clause)
            clause = cls._avatar_profile_collapse_awkward_body_phrases(clause)
            lowered = clause.lower()
            normalized = " ".join(lowered.split())
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(clause)
        if "body-preservation" in heading_lower and (noisy_count or len(cleaned) > 8):
            return "Preserve visible silhouette, body proportions, posture, and pose; treat hidden or covered traits as uncertain."
        if len(cleaned) > 12:
            cleaned = cleaned[:12]
        result = ", ".join(cleaned).strip()
        if len(cleaned) == 1 and source.rstrip().endswith((".", "!", "?")) and not result.endswith((".", "!", "?")):
            result += "."
        return result or source

    @staticmethod
    def _avatar_profile_strip_non_english_fragments(text: str) -> str:
        cleaned = re.sub(r"[\u0080-\uffff]+", "", str(text or ""))
        cleaned = re.sub(r"\band\s+shape\b", "shape", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\band\s+butt\b", "butt", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _avatar_profile_collapse_awkward_body_phrases(text: str) -> str:
        cleaned = str(text or "").strip()
        replacements = {
            r"\bstraight and straightened\b": "straight",
            r"\bstraightened and straight\b": "straight",
            r"\brounded and rounded\b": "rounded",
            r"\bfuller and fuller\b": "fuller",
            r"\bmore rounded and butt\b": "more rounded butt",
            r"\bround and shape\b": "round shape",
            r"\brounded and shape\b": "rounded shape",
        }
        for pattern, replacement in replacements.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _avatar_profile_reduce_average_filler(clause: str) -> str:
        text = str(clause or "").strip()
        if not text:
            return ""
        text = re.sub(
            r"\b(slightly|moderately|visibly)\s+([a-z-]+(?:er|ter))\s+than\s+average\b",
            r"\1 \2",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(slightly|moderately|visibly)\s+(fuller|slimmer|rounder|thicker|thinner|longer|shorter|wider|narrower)\s+than\s+average\b",
            r"\1 \2",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\baverage\s+(waist|height impression|skin tone)\b", r"neutral \1", text, flags=re.IGNORECASE)
        text = re.sub(r"\bis average\b", "appears neutral", text, flags=re.IGNORECASE)
        lowered = text.lower()
        if not lowered.startswith("average "):
            return text
        remainder = text[len("average ") :].strip()
        if "," in remainder:
            return remainder
        if any(
            cue in lowered
            for cue in (
                "slight",
                "rounded",
                "straight",
                "symmetrical",
                "narrow",
                "wide",
                "wider",
                "bent",
                "apart",
                "protruding",
                "central",
                "smooth",
                "standing",
            )
        ):
            return remainder
        return text

    @classmethod
    def _avatar_profile_compact_text(cls, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return ", ".join(cls._avatar_profile_compact_text(item) for item in value if cls._avatar_profile_compact_text(item))
        if isinstance(value, dict):
            parts = []
            for key, item in value.items():
                text = cls._avatar_profile_compact_text(item)
                if text:
                    parts.append(f"{key}: {text}")
            return "; ".join(parts)
        return str(value).strip()

    @classmethod
    def _avatar_profile_negative_terms(cls, value) -> list[str]:
        if isinstance(value, str):
            candidates = [item.strip() for item in value.replace("\n", ",").split(",")]
        elif isinstance(value, list):
            candidates = [str(item or "").strip() for item in value]
        else:
            candidates = []
        if not candidates:
            candidates = [
                "different person",
                "changed face",
                "changed body proportions",
                "different body shape",
                "blurred face",
                "distorted face",
                "distorted hands",
                "extra limbs",
                "cropped body",
                "out of frame",
                "watermark",
                "text",
            ]
        unsafe_fragments = (
            "no face",
            "no facial",
            "no skin",
            "no eyes",
            "no nose",
            "no lips",
            "no hair",
            "no eyebrows",
            "no expression",
            "faceless",
            "missing face",
            "missing eyes",
            "missing nose",
            "missing lips",
            "missing hair",
        )
        cleaned = []
        seen = set()
        for candidate in candidates:
            normalized = " ".join(candidate.split())
            lowered = normalized.lower()
            if not normalized or any(fragment in lowered for fragment in unsafe_fragments):
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            cleaned.append(normalized)
        return cleaned or ["different person", "changed face", "changed body proportions", "blurred face", "distorted hands"]

    def avatar_profile_asset_response(self, *, profile_id: str, asset_name: str) -> FileResponse:
        root = self._avatar_profile_root()
        safe_profile_id = self._safe_filename_component(profile_id)
        safe_asset_name = Path(str(asset_name or "")).name
        if safe_asset_name not in {"face.png", "face.jpg", "face.jpeg", "face.webp", "body.png", "body.jpg", "body.jpeg", "body.webp"}:
            raise ValueError("avatar_profile_asset_not_found")
        path = (root / safe_profile_id / safe_asset_name).resolve()
        if root not in path.parents or not path.exists() or not path.is_file():
            raise ValueError("avatar_profile_asset_not_found")
        return FileResponse(path)

    def avatar_profile_reference_response(self, *, profile_id: str, role: str, asset_name: str) -> FileResponse:
        root = self._avatar_profile_root()
        safe_profile_id = self._safe_filename_component(profile_id)
        safe_role = self._avatar_profile_reference_role(role)
        if safe_role == "head_face":
            safe_asset_path = self._safe_relative_path(str(asset_name or ""))
        else:
            safe_asset_path = Path(Path(str(asset_name or "")).name)
        path = (root / safe_profile_id / "refs" / safe_role / safe_asset_path).resolve()
        if root not in path.parents or not path.exists() or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
            raise ValueError("avatar_profile_reference_not_found")
        return FileResponse(path)

    def _avatar_profile_root(self) -> Path:
        return (self._manual_image_input_dir() / "avatar_profiles").resolve()

    def _avatar_profile_dir(self, *, profile_id: str) -> Path:
        return (self._avatar_profile_root() / self._safe_filename_component(profile_id)).resolve()

    def _avatar_profiles(self, *, limit: int, selected_profile_id: str | None = None) -> list[dict]:
        root = self._avatar_profile_root()
        if not root.exists():
            return []
        profiles = []
        for profile_dir in root.iterdir():
            if not profile_dir.is_dir():
                continue
            profile = self._avatar_profile_payload(profile_dir=profile_dir, selected_profile_id=selected_profile_id)
            if profile:
                profiles.append(profile)
        profiles.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return profiles[: max(int(limit), 1)]

    def _avatar_profile_payload(self, *, profile_dir: Path, selected_profile_id: str | None = None) -> dict:
        metadata = self._avatar_profile_metadata(profile_dir=profile_dir)
        if not metadata:
            return {}
        metadata = self._refresh_avatar_body_depth_profile_job(profile_dir=profile_dir, metadata=metadata)
        metadata = self._refresh_avatar_head_face_preview_outputs(profile_dir=profile_dir, metadata=metadata)
        profile_id = self._safe_filename_component(metadata.get("profile_id") or profile_dir.name)
        face_image = Path(str(metadata.get("face_image") or "")).name
        body_image = Path(str(metadata.get("body_image") or "")).name
        face_exists = bool(face_image) and (profile_dir / face_image).is_file()
        body_exists = bool(body_image) and (profile_dir / body_image).is_file()
        references = self._avatar_profile_references(profile_dir=profile_dir)
        primary_face_filename = Path(str(metadata.get("primary_face_reference_filename") or "")).name
        primary_face_reference = None
        if primary_face_filename:
            for reference in references.get("face", []):
                if Path(str(reference.get("filename") or "")).name == primary_face_filename:
                    reference["primary"] = True
                    primary_face_reference = reference
                    break
        primary_face_input_image = (
            str(primary_face_reference.get("input_image") or "").strip()
            if isinstance(primary_face_reference, dict)
            else str(metadata.get("primary_face_input_image") or "").strip()
        )
        if not primary_face_input_image and face_exists:
            primary_face_input_image = f"avatar_profiles/{profile_id}/{face_image}"
        return {
            **metadata,
            "profile_id": profile_id,
            "selected": bool(selected_profile_id and selected_profile_id == profile_id),
            "face_image": face_image if face_exists else None,
            "body_image": body_image if body_exists else None,
            "face_input_image": f"avatar_profiles/{profile_id}/{face_image}" if face_exists else "",
            "body_input_image": f"avatar_profiles/{profile_id}/{body_image}" if body_exists else "",
            "face_url": f"/api/avatar-generation/profiles/{profile_id}/assets/{face_image}" if face_exists else "",
            "body_url": f"/api/avatar-generation/profiles/{profile_id}/assets/{body_image}" if body_exists else "",
            "primary_face_reference": primary_face_reference,
            "primary_face_reference_filename": primary_face_filename or None,
            "primary_face_input_image": primary_face_input_image,
            "pulid_face_reference_image": primary_face_input_image,
            "references": references,
            "body_depth_job": self._read_avatar_body_depth_profile_job(profile_dir=profile_dir),
        }

    def _avatar_profile_metadata(self, *, profile_dir: Path) -> dict:
        profile_path = profile_dir / "profile.json"
        try:
            metadata = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return metadata if isinstance(metadata, dict) else {}

    @classmethod
    def _avatar_profile_prompt_workspace(cls, *, metadata: dict, section: str) -> dict:
        workspaces = metadata.get("prompt_workspaces") if isinstance(metadata.get("prompt_workspaces"), dict) else {}
        workspace = workspaces.get(section) if isinstance(workspaces.get(section), dict) else {}
        return dict(workspace)

    @classmethod
    def _avatar_profile_metadata_with_workspace(cls, *, metadata: dict, section: str, workspace: dict) -> dict:
        workspaces = metadata.get("prompt_workspaces") if isinstance(metadata.get("prompt_workspaces"), dict) else {}
        return {
            **metadata,
            "prompt_workspaces": {
                **workspaces,
                section: workspace,
            },
        }

    @classmethod
    def _avatar_profile_general_initial_prompt(cls, *, profile: dict) -> str:
        style = str(profile.get("visual_style") or "").replace("-", " ").strip()
        character_type = str(profile.get("character_type") or "").replace("-", " ").strip()
        parts = [
            str(profile.get("name") or profile.get("profile_id") or "avatar").strip(),
            style,
            character_type,
            str(profile.get("gender") or "").strip(),
            f"{profile.get('skin_color')} skin" if str(profile.get("skin_color") or "").strip() else "",
            f"{profile.get('hair_color')} hair" if str(profile.get("hair_color") or "").strip() else "",
            "adult character avatar" if profile.get("nsfw") else "character avatar",
            "consistent identity",
            "clean full character design",
            "high quality ComfyUI SDXL prompt baseline",
        ]
        return ", ".join(item for item in parts if item)

    @classmethod
    def _avatar_profile_default_head_prompt_parts(cls, *, profile: dict) -> dict:
        general_prompt = str(profile.get("general_prompt") or "").strip()
        hair_color = str(profile.get("hair_color") or "").strip()
        skin_color = str(profile.get("skin_color") or "").strip()
        return {
            "general": general_prompt or cls._avatar_profile_general_initial_prompt(profile=profile),
            "hair": f"detailed {hair_color} hair" if hair_color else "detailed hair",
            "eyes": "expressive detailed eyes",
            "eyebrows": "natural eyebrows",
            "nose": "defined nose",
            "cheeks": "natural cheeks",
            "mouth": "natural lips",
            "jaw_chin": "clear jaw and chin shape",
            "ears": "natural ears",
            "skin": f"{skin_color} skin, natural skin texture" if skin_color else "natural skin texture",
            "expression": "natural expression",
            "style_lighting": "head and shoulders portrait, clear face, centered composition, clean studio lighting",
        }

    @classmethod
    def _avatar_profile_normalized_head_prompt_parts(cls, *, profile: dict, prompt_parts: object, fallback_prompt: str = "") -> dict:
        defaults = cls._avatar_profile_default_head_prompt_parts(profile=profile)
        source = prompt_parts if isinstance(prompt_parts, dict) else {}
        has_source_parts = any(str(source.get(key) or "").strip() for key in AVATAR_HEAD_FACE_PROMPT_PART_ORDER)
        normalized = {
            key: str(source.get(key) if has_source_parts and source.get(key) is not None else defaults.get(key) or "").strip()
            for key in AVATAR_HEAD_FACE_PROMPT_PART_ORDER
        }
        fallback = str(fallback_prompt or "").strip()
        if fallback and not has_source_parts:
            normalized["general"] = fallback
        return normalized

    @classmethod
    def _avatar_profile_head_prompt_from_parts(cls, *, prompt_parts: object, profile: dict) -> str:
        normalized = cls._avatar_profile_normalized_head_prompt_parts(
            profile=profile,
            prompt_parts=prompt_parts,
        )
        return ", ".join(normalized[key] for key in AVATAR_HEAD_FACE_PROMPT_PART_ORDER if normalized.get(key))

    @classmethod
    def _avatar_profile_default_head_prompt(cls, *, profile: dict) -> str:
        return cls._avatar_profile_head_prompt_from_parts(
            prompt_parts=cls._avatar_profile_default_head_prompt_parts(profile=profile),
            profile=profile,
        )

    def _avatar_profile_head_prompt_from_local_llm(
        self,
        *,
        profile: dict,
        current_prompt: str,
        current_negative_prompt: str,
        user_message: str,
    ) -> tuple[str, str, str]:
        services = self.service_status_payload().get("services", {})
        local_llm = services.get("local_llm") if isinstance(services, dict) else {}
        socket_path = str(local_llm.get("socket_path") or "") if isinstance(local_llm, dict) else ""
        model_id = str(local_llm.get("model_id") or local_llm.get("default_model_id") or "local").strip() if isinstance(local_llm, dict) else "local"
        if not socket_path:
            raise ValueError("local_llm_socket_unavailable")
        if isinstance(local_llm, dict) and str(local_llm.get("state") or "").strip().lower() not in {"running", "healthy"}:
            raise ValueError("local_llm_unavailable")
        request_payload = {
            "profile": {
                "name": profile.get("name") or profile.get("profile_id"),
                "gender": profile.get("gender"),
                "skin_color": profile.get("skin_color"),
                "hair_color": profile.get("hair_color"),
                "character_type": profile.get("character_type"),
                "visual_style": profile.get("visual_style"),
                "nsfw": bool(profile.get("nsfw")),
            },
            "section": "head_face",
            "current_prompt": current_prompt,
            "current_negative_prompt": current_negative_prompt,
            "user_request": user_message,
        }
        response = self._uds_json_request(
            socket_path=socket_path,
            method="POST",
            path="/v1/chat/completions",
            body={
                "model": model_id,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "/no_think You refine SDXL/ComfyUI prompts for an avatar head and face design workspace. "
                            "Return only JSON with keys prompt and negative_prompt. "
                            "Preserve stable profile facts unless the user explicitly changes them. "
                            "Focus on head, face, hair, expression, skin, eyes, makeup/accessories, portrait framing, lighting, and style. "
                            "Do not write explanations or markdown."
                        ),
                    },
                    {"role": "user", "content": "/no_think " + json.dumps(request_payload, sort_keys=True)},
                ],
                "temperature": 0.4,
                "max_tokens": 550,
                "stream": False,
            },
            host="local-llm",
            error_label="local_llm_avatar_head_prompt_failed",
            timeout_s=60,
        )
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(message.get("content") or message.get("reasoning_content") or choices[0].get("text") or "").strip()
        parsed = self._parse_manual_image_prompt_helper_content(content)
        prompt = str(parsed.get("prompt") or content or current_prompt).strip()
        negative_prompt = str(parsed.get("negative_prompt") or current_negative_prompt).strip()
        return prompt, negative_prompt, model_id

    def _selected_avatar_profile_path(self) -> Path:
        return self._avatar_profile_root() / "selected_profile.json"

    def _selected_avatar_profile_id(self) -> str | None:
        try:
            payload = json.loads(self._selected_avatar_profile_path().read_text(encoding="utf-8"))
        except Exception:
            return None
        profile_id = str(payload.get("profile_id") or "").strip() if isinstance(payload, dict) else ""
        if not profile_id:
            return None
        profile_dir = self._avatar_profile_dir(profile_id=profile_id)
        return profile_dir.name if (profile_dir / "profile.json").exists() else None

    def _write_selected_avatar_profile_id(self, *, profile_id: str) -> None:
        path = self._selected_avatar_profile_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not profile_id:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        path.write_text(
            json.dumps({"profile_id": self._safe_filename_component(profile_id), "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _write_avatar_profile_image(
        self,
        *,
        profile_dir: Path,
        profile_id: str,
        role: str,
        filename: str | None,
        data_base64: str | None,
    ) -> str:
        encoded = str(data_base64 or "")
        if not encoded:
            raise ValueError(f"avatar_profile_{role}_image_required")
        raw_name = Path(str(filename or f"{role}.png")).name
        suffix = Path(raw_name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        target_name = f"{role}{suffix}"
        target_path = (profile_dir / target_name).resolve()
        root = self._avatar_profile_root()
        if root not in target_path.parents:
            raise ValueError("avatar_profile_path_invalid")
        if "," in encoded and encoded.split(",", 1)[0].lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"invalid_avatar_profile_{role}_image_data") from exc
        if not data:
            raise ValueError(f"avatar_profile_{role}_image_empty")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError(f"avatar_profile_{role}_image_too_large")
        for stale in profile_dir.glob(f"{role}.*"):
            if stale.name != target_name and stale.is_file():
                stale.unlink()
        target_path.write_bytes(data)
        sidecar = {
            "profile_id": profile_id,
            "role": role,
            "filename": target_name,
            "input_image": f"avatar_profiles/{profile_id}/{target_name}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        target_path.with_suffix(target_path.suffix + ".json").write_text(
            json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target_name

    @classmethod
    def _avatar_profile_reference_role(cls, value: str | None) -> str:
        role = cls._safe_filename_component(value or "reference")
        aliases = {
            "body": "body_depth",
            "bodydepth": "body_depth",
            "body_depths": "body_depth",
            "depth": "body_depth",
            "depth_map": "body_depth_map",
            "depth_maps": "body_depth_map",
            "body_depth_maps": "body_depth_map",
            "bodydepthmap": "body_depth_map",
            "faces": "face",
            "pose": "pose",
            "poses": "pose",
            "openpose": "pose",
            "head": "head_face",
            "headface": "head_face",
            "head_face_preview": "head_face",
            "headfacepreview": "head_face",
            "face_preview": "head_face",
            "facepreview": "head_face",
        }
        role = aliases.get(role, role)
        if role not in {"body_depth", "body_depth_map", "face", "pose", "head_face"}:
            raise ValueError("avatar_profile_reference_role_invalid")
        return role

    @staticmethod
    def _decode_avatar_profile_reference_image(data_base64: str, *, role: str) -> bytes:
        encoded = str(data_base64 or "")
        if not encoded:
            raise ValueError(f"avatar_profile_{role}_reference_required")
        if "," in encoded and encoded.split(",", 1)[0].lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"invalid_avatar_profile_{role}_reference_data") from exc
        if not data:
            raise ValueError(f"avatar_profile_{role}_reference_empty")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError(f"avatar_profile_{role}_reference_too_large")
        return data

    def _avatar_profile_references(self, *, profile_dir: Path) -> dict:
        references = {"body_depth": [], "body_depth_map": [], "face": [], "pose": [], "head_face": []}
        refs_root = profile_dir / "refs"
        if not refs_root.exists() or not refs_root.is_dir():
            return references
        for role in references:
            role_dir = refs_root / role
            if not role_dir.exists() or not role_dir.is_dir():
                continue
            items = []
            paths = role_dir.rglob("*") if role == "head_face" else role_dir.iterdir()
            for path in paths:
                if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
                    continue
                items.append(self._avatar_profile_reference_payload(path=path))
            items.sort(key=lambda item: str(item.get("created_at") or item.get("filename") or ""), reverse=True)
            references[role] = items
        return references

    def _avatar_profile_reference_payload(self, *, path: Path) -> dict:
        sidecar = path.with_suffix(path.suffix + ".json")
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
        inferred_role = path.parent.parent.name if path.parent.name == "preview" else path.parent.name
        role = self._avatar_profile_reference_role(metadata.get("role") or inferred_role)
        fallback_profile_id = path.parent.parent.parent.parent.name if path.parent.name == "preview" else path.parent.parent.parent.name
        profile_id = self._safe_filename_component(metadata.get("profile_id") or fallback_profile_id)
        filename = Path(str(metadata.get("filename") or path.name)).name
        relative_name = str(metadata.get("relative_name") or filename)
        return {
            **(metadata if isinstance(metadata, dict) else {}),
            "profile_id": profile_id,
            "role": role,
            "filename": filename,
            "name": str((metadata if isinstance(metadata, dict) else {}).get("name") or Path(filename).stem),
            "input_image": str((metadata if isinstance(metadata, dict) else {}).get("input_image") or f"avatar_profiles/{profile_id}/refs/{role}/{relative_name}"),
            "url": str((metadata if isinstance(metadata, dict) else {}).get("url") or f"/api/avatar-generation/profiles/{profile_id}/references/{role}/{relative_name}"),
        }

    def _avatar_body_depth_profile_sources(self, *, profile_dir: Path, metadata: dict, source_filenames: list[str] | None) -> list[dict]:
        selected = {
            Path(str(item or "")).name
            for item in list(source_filenames or [])
            if str(item or "").strip()
        }
        references = self._avatar_profile_references(profile_dir=profile_dir).get("body_depth", [])
        sources: list[dict] = []
        for reference in references:
            filename = Path(str(reference.get("filename") or "")).name
            if not filename or (selected and filename not in selected):
                continue
            if not selected and bool(reference.get("background_removed")):
                continue
            path = (profile_dir / "refs" / "body_depth" / filename).resolve()
            if profile_dir not in path.parents or not path.exists() or not path.is_file():
                continue
            sources.append({**reference, "path": path, "role": "body_depth"})
        if sources or selected:
            return sources

        body_image = Path(str(metadata.get("body_image") or "")).name
        if not body_image:
            return []
        body_path = (profile_dir / body_image).resolve()
        if profile_dir not in body_path.parents or not body_path.exists() or not body_path.is_file():
            return []
        profile_id = self._safe_filename_component(metadata.get("profile_id") or profile_dir.name)
        return [
            {
                "profile_id": profile_id,
                "role": "body",
                "name": "Profile Body",
                "filename": body_image,
                "input_image": f"avatar_profiles/{profile_id}/{body_image}",
                "path": body_path,
            }
        ]

    @staticmethod
    def _avatar_body_depth_profile_workflow(
        *,
        source_input_image: str,
        width: int,
        height: int,
        depth_resolution: int,
        depth_model: str,
        bg_removal_model: str,
        nobg_output_prefix: str,
        depth_output_prefix: str,
    ) -> dict:
        return {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": source_input_image},
            },
            "2": {
                "class_type": "ResizeAndPadImage",
                "inputs": {
                    "image": ["1", 0],
                    "target_width": int(width),
                    "target_height": int(height),
                    "padding_color": "black",
                    "interpolation": "lanczos",
                },
            },
            "3": {
                "class_type": "LoadBackgroundRemovalModel",
                "inputs": {"bg_removal_name": bg_removal_model},
            },
            "4": {
                "class_type": "RemoveBackground",
                "inputs": {
                    "image": ["2", 0],
                    "bg_removal_model": ["3", 0],
                },
            },
            "5": {
                "class_type": "InvertMask",
                "inputs": {"mask": ["4", 0]},
            },
            "6": {
                "class_type": "JoinImageWithAlpha",
                "inputs": {
                    "image": ["2", 0],
                    "alpha": ["5", 0],
                },
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["6", 0],
                    "filename_prefix": nobg_output_prefix,
                },
            },
            "8": {
                "class_type": "DepthAnythingV2Preprocessor",
                "inputs": {
                    "image": ["6", 0],
                    "ckpt_name": depth_model,
                    "resolution": int(depth_resolution),
                },
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["8", 0],
                    "filename_prefix": depth_output_prefix,
                },
            },
        }

    def _read_avatar_body_depth_profile_job(self, *, profile_dir: Path) -> dict:
        try:
            payload = json.loads((profile_dir / "body_depth_job.json").read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_avatar_body_depth_profile_job(self, *, profile_dir: Path, payload: dict) -> None:
        (profile_dir / "body_depth_job.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _avatar_head_face_preview_sidecar(
        self,
        *,
        profile_id: str,
        preview: dict,
        filename: str,
        relative_name: str,
        now: str,
        source: str,
        source_output: str | None = None,
        placeholder: bool = False,
        background_removed: bool = False,
        rgb_fallback: bool = False,
    ) -> dict:
        seed = preview.get("seed")
        return {
            "profile_id": profile_id,
            "role": "head_face",
            "name": f"Head Face Preview {seed or 'pending'}",
            "filename": filename,
            "relative_name": relative_name,
            "input_image": f"avatar_profiles/{profile_id}/refs/head_face/{relative_name}",
            "url": f"/api/avatar-generation/profiles/{profile_id}/references/head_face/{relative_name}",
            "source": source,
            "source_output": source_output,
            "placeholder": bool(placeholder),
            "background_removed": bool(background_removed),
            "rgb_fallback": bool(rgb_fallback),
            "preview_id": preview.get("preview_id"),
            "prompt_id": preview.get("prompt_id"),
            "seed": seed,
            "prompt": preview.get("prompt"),
            "negative_prompt": preview.get("negative_prompt"),
            "created_at": preview.get("created_at") or now,
            "imported_at": now,
        }

    def _write_avatar_head_face_preview_placeholder(self, *, path: Path, preview: dict, profile_name: str) -> None:
        prompt_id = html.escape(str(preview.get("prompt_id") or "pending"))
        seed = html.escape(str(preview.get("seed") or "pending"))
        profile = html.escape(str(profile_name or "Avatar"))
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="#111827"/>
  <rect x="28" y="28" width="456" height="456" rx="18" fill="#1f2937" stroke="#64748b" stroke-width="2"/>
  <circle cx="256" cy="202" r="74" fill="#334155" stroke="#94a3b8" stroke-width="4"/>
  <path d="M126 408c22-72 75-112 130-112s108 40 130 112" fill="#334155" stroke="#94a3b8" stroke-width="4"/>
  <text x="256" y="82" fill="#e5e7eb" font-family="Arial, sans-serif" font-size="28" text-anchor="middle">Preview pending</text>
  <text x="256" y="448" fill="#cbd5e1" font-family="Arial, sans-serif" font-size="18" text-anchor="middle">{profile}</text>
  <text x="256" y="474" fill="#94a3b8" font-family="Arial, sans-serif" font-size="14" text-anchor="middle">seed {seed} | {prompt_id}</text>
</svg>
"""
        path.write_text(svg, encoding="utf-8")

    def _refresh_avatar_head_face_preview_outputs(self, *, profile_dir: Path, metadata: dict) -> dict:
        workspace = self._avatar_profile_prompt_workspace(metadata=metadata, section="head_face")
        preview_history = list(workspace.get("preview_history") or [])
        if not preview_history:
            return metadata
        profile_id = self._safe_filename_component(metadata.get("profile_id") or profile_dir.name)
        avatar_name = self._safe_filename_component(metadata.get("name") or profile_dir.name or "avatar")
        output_dir = self._manual_image_output_dir()
        preview_dir = profile_dir / "refs" / "head_face" / "preview"
        updated_history = []
        changed = False
        now = datetime.now(timezone.utc).isoformat()
        for preview in preview_history:
            if not isinstance(preview, dict):
                updated_history.append(preview)
                continue
            existing_input = str(preview.get("input_image") or "").strip()
            existing_filename = Path(str(preview.get("filename") or "")).name
            existing_is_placeholder = bool(preview.get("placeholder"))
            if existing_input and existing_filename and (preview_dir / existing_filename).is_file() and not existing_is_placeholder:
                if str(preview.get("status") or "").strip() != "completed":
                    updated_history.append({**preview, "status": "completed"})
                    changed = True
                else:
                    updated_history.append(preview)
                continue
            seed = str(preview.get("seed") or "").strip()
            preview_id = self._safe_filename_component(preview.get("preview_id") or f"head_face_{seed}")
            preview_dir.mkdir(parents=True, exist_ok=True)
            output_path = None
            if seed:
                prefix = f"hexe/avatar_head_face_preview/{avatar_name}_seed{seed}"
                output_path = self._avatar_head_face_preview_output_for_prefix(output_dir=output_dir, prefix=prefix)
            if not output_path:
                if existing_is_placeholder and existing_filename and (preview_dir / existing_filename).is_file():
                    updated_history.append(preview)
                    continue
                filename = existing_filename if existing_is_placeholder and existing_filename else f"{preview_id}_seed{seed or 'pending'}_placeholder.svg"
                target_path = (preview_dir / filename).resolve()
                if profile_dir not in target_path.parents:
                    raise ValueError("avatar_head_face_preview_path_invalid")
                if not target_path.exists():
                    self._write_avatar_head_face_preview_placeholder(path=target_path, preview=preview, profile_name=metadata.get("name") or profile_dir.name)
                relative_name = f"preview/{filename}"
                sidecar = self._avatar_head_face_preview_sidecar(
                    profile_id=profile_id,
                    preview=preview,
                    filename=filename,
                    relative_name=relative_name,
                    now=now,
                    source="avatar_head_face_preview_placeholder",
                    placeholder=True,
                )
                target_path.with_suffix(target_path.suffix + ".json").write_text(
                    json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                updated_history.append(
                    {
                        **preview,
                        "status": "pending",
                        "filename": filename,
                        "input_image": sidecar["input_image"],
                        "url": sidecar["url"],
                        "placeholder": True,
                        "imported_at": now,
                    }
                )
                changed = True
                continue
            if existing_is_placeholder and existing_filename:
                existing_path = (preview_dir / existing_filename).resolve()
                if profile_dir in existing_path.parents and existing_path.exists() and existing_path.is_file():
                    existing_path.unlink()
                existing_sidecar = existing_path.with_suffix(existing_path.suffix + ".json")
                if existing_sidecar.exists() and existing_sidecar.is_file():
                    existing_sidecar.unlink()
            filename = f"{preview_id}_seed{seed}.png"
            target_path = (preview_dir / filename).resolve()
            if profile_dir not in target_path.parents:
                raise ValueError("avatar_head_face_preview_path_invalid")
            shutil.copyfile(output_path, target_path)
            relative_name = f"preview/{filename}"
            source_output = output_path.relative_to(output_dir).as_posix() if output_dir in output_path.parents else str(output_path)
            rgb_fallback = self._avatar_head_face_preview_is_rgb_fallback_path(path=output_path)
            sidecar = self._avatar_head_face_preview_sidecar(
                profile_id=profile_id,
                preview=preview,
                filename=filename,
                relative_name=relative_name,
                now=now,
                source="avatar_head_face_preview_generation",
                source_output=source_output,
                placeholder=False,
                background_removed=not rgb_fallback,
                rgb_fallback=rgb_fallback,
            )
            target_path.with_suffix(target_path.suffix + ".json").write_text(
                json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            updated_history.append(
                {
                    **preview,
                    "status": "completed_with_fallback" if rgb_fallback else "completed",
                    "filename": filename,
                    "input_image": sidecar["input_image"],
                    "url": sidecar["url"],
                    "placeholder": False,
                    "background_removed": not rgb_fallback,
                    "rgb_fallback": rgb_fallback,
                    "imported_at": now,
                    "source_output": sidecar["source_output"],
                }
            )
            changed = True
        if not changed:
            return metadata
        updated_workspace = {
            **workspace,
            "section": "head_face",
            "preview_history": updated_history[-AVATAR_HEAD_FACE_PREVIEW_HISTORY_LIMIT:],
            "updated_at": now,
        }
        updated_metadata = self._avatar_profile_metadata_with_workspace(
            metadata=metadata,
            section="head_face",
            workspace=updated_workspace,
        )
        references = self._avatar_profile_references(profile_dir=profile_dir)
        existing_counts = metadata.get("reference_counts") if isinstance(metadata.get("reference_counts"), dict) else {}
        updated_metadata["reference_counts"] = {
            **existing_counts,
            "head_face": len(references.get("head_face", [])),
        }
        updated_metadata["updated_at"] = now
        (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return updated_metadata

    @staticmethod
    def _avatar_head_face_preview_output_for_prefix(*, output_dir: Path, prefix) -> Path | None:
        relative = str(prefix or "").strip().strip("/")
        if not relative:
            return None
        prefix_path = (output_dir / relative).resolve()
        if output_dir not in prefix_path.parents:
            return None
        candidates = sorted(prefix_path.parent.glob(f"{prefix_path.name}*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
        rgb_fallback = None
        for candidate in candidates:
            if not candidate.is_file():
                continue
            if NodeControlState._avatar_head_face_preview_is_rgb_fallback_path(path=candidate):
                if rgb_fallback is None:
                    rgb_fallback = candidate.resolve()
                continue
            return candidate.resolve()
        return rgb_fallback

    @staticmethod
    def _avatar_head_face_preview_is_rgb_fallback_path(*, path: Path) -> bool:
        stem = path.stem
        return stem.endswith("_rgb") or "_rgb_" in stem

    def _refresh_avatar_body_depth_profile_job(self, *, profile_dir: Path, metadata: dict) -> dict:
        job = self._read_avatar_body_depth_profile_job(profile_dir=profile_dir)
        if not job or str(job.get("status") or "") in {"completed", "failed"}:
            return metadata
        prompt_ids = [
            str(item or "").strip()
            for item in list(job.get("prompt_ids") or [])
            if str(item or "").strip()
        ]
        services = self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        runtime_service = services.get("comfyui_gpu") if isinstance(services, dict) else {}
        generation_status = {}
        if self._service_manager is not None and hasattr(self._service_manager, "comfyui_webui_generation_status"):
            try:
                generation_status = self._service_manager.comfyui_webui_generation_status()
            except Exception:
                generation_status = {}
        session = generation_status.get("session") if isinstance(generation_status.get("session"), dict) else {}
        running_prompt_id = str(session.get("running_prompt_id") or "").strip()
        pending_prompt_ids = [str(item) for item in list(session.get("pending_prompt_ids") or [])]
        if running_prompt_id in prompt_ids:
            status = "running"
        elif any(item in pending_prompt_ids for item in prompt_ids):
            status = "queued"
        else:
            status = "submitted"

        imported_count = 0
        missing_outputs = []
        updated_items = []
        output_dir = self._manual_image_output_dir()
        for item in list(job.get("items") or []):
            if not isinstance(item, dict):
                continue
            if bool(item.get("imported")):
                imported_count += 1
                updated_items.append(item)
                continue
            nobg_output = self._avatar_body_depth_profile_output_for_prefix(output_dir=output_dir, prefix=item.get("nobg_output_prefix"))
            depth_output = self._avatar_body_depth_profile_output_for_prefix(output_dir=output_dir, prefix=item.get("depth_output_prefix"))
            if not nobg_output or not depth_output:
                missing_outputs.append(item.get("source_filename"))
                updated_items.append(item)
                continue
            self._import_avatar_body_depth_profile_outputs(
                profile_dir=profile_dir,
                metadata=metadata,
                item=item,
                nobg_output=nobg_output,
                depth_output=depth_output,
                replace_source_images=bool(job.get("replace_source_images", True)),
                settings=job.get("settings") if isinstance(job.get("settings"), dict) else {},
            )
            imported_count += 1
            updated_items.append(
                {
                    **item,
                    "imported": True,
                    "imported_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        submitted_epoch = self._manual_image_parse_epoch(job.get("submitted_at"))
        submitted_age_seconds = (time.time() - submitted_epoch) if submitted_epoch is not None else None
        job_inactive = status not in {"running", "queued"}
        source_count = len(updated_items)
        if imported_count >= source_count and source_count:
            status = "completed"
        elif job_inactive and missing_outputs and submitted_age_seconds is not None and submitted_age_seconds > 300:
            status = "failed"
        updated_job = {
            **job,
            "status": status,
            "items": updated_items,
            "imported_count": imported_count,
            "missing_outputs": [item for item in missing_outputs if item],
            "queue_active": bool(session.get("queue_active")),
            "running_count": int(session.get("running_count") or 0),
            "pending_count": int(session.get("pending_count") or 0),
            "runtime_pid": (runtime_service if isinstance(runtime_service, dict) else {}).get("pid"),
            "webui_state": (webui if isinstance(webui, dict) else {}).get("state"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if updated_job != job:
            self._write_avatar_body_depth_profile_job(profile_dir=profile_dir, payload=updated_job)
        references = self._avatar_profile_references(profile_dir=profile_dir)
        now = datetime.now(timezone.utc).isoformat()
        body_depth_profile = {
            **(metadata.get("body_depth_profile") if isinstance(metadata.get("body_depth_profile"), dict) else {}),
            "status": status,
            "source_count": source_count,
            "generated_count": imported_count,
            "body_reference_count": len(references.get("body_depth", [])),
            "depth_map_count": len(references.get("body_depth_map", [])),
            "updated_at": now,
        }
        existing_counts = metadata.get("reference_counts") if isinstance(metadata.get("reference_counts"), dict) else {}
        updated_metadata = {
            **metadata,
            "body_depth_profile": body_depth_profile,
            "reference_counts": {
                **existing_counts,
                "body_depth": len(references.get("body_depth", [])),
                "body_depth_map": len(references.get("body_depth_map", [])),
                "face": len(references.get("face", [])),
                "pose": len(references.get("pose", [])),
            },
            "updated_at": now,
        }
        if updated_metadata != metadata:
            (profile_dir / "profile.json").write_text(json.dumps(updated_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return updated_metadata

    @staticmethod
    def _avatar_body_depth_profile_output_for_prefix(*, output_dir: Path, prefix) -> Path | None:
        relative = str(prefix or "").strip().strip("/")
        if not relative:
            return None
        prefix_path = (output_dir / relative).resolve()
        if output_dir not in prefix_path.parents:
            return None
        candidates = sorted(prefix_path.parent.glob(f"{prefix_path.name}*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _import_avatar_body_depth_profile_outputs(
        self,
        *,
        profile_dir: Path,
        metadata: dict,
        item: dict,
        nobg_output: Path,
        depth_output: Path,
        replace_source_images: bool,
        settings: dict,
    ) -> None:
        profile_id = self._safe_filename_component(metadata.get("profile_id") or profile_dir.name)
        now = datetime.now(timezone.utc).isoformat()
        body_filename = Path(str(item.get("target_body_filename") or f"avatar_body_{int(time.time())}.png")).name
        depth_filename = Path(str(item.get("target_depth_filename") or f"avatar_body_depth_{int(time.time())}.png")).name
        body_dir = profile_dir / "refs" / "body_depth"
        depth_dir = profile_dir / "refs" / "body_depth_map"
        body_dir.mkdir(parents=True, exist_ok=True)
        depth_dir.mkdir(parents=True, exist_ok=True)
        body_path = (body_dir / body_filename).resolve()
        depth_path = (depth_dir / depth_filename).resolve()
        if profile_dir not in body_path.parents or profile_dir not in depth_path.parents:
            raise ValueError("avatar_body_depth_profile_path_invalid")
        shutil.copyfile(nobg_output, body_path)
        shutil.copyfile(depth_output, depth_path)
        source_filename = Path(str(item.get("source_filename") or "")).name
        source_name = str(item.get("source_name") or Path(source_filename).stem or "Body").strip()
        body_metadata = {
            "profile_id": profile_id,
            "role": "body_depth",
            "name": f"{source_name} No BG",
            "filename": body_filename,
            "input_image": f"avatar_profiles/{profile_id}/refs/body_depth/{body_filename}",
            "url": f"/api/avatar-generation/profiles/{profile_id}/references/body_depth/{body_filename}",
            "source": "avatar_body_depth_profile_generation",
            "source_reference_filename": source_filename,
            "source_input_image": item.get("source_input_image"),
            "background_removed": True,
            "depth_map_filename": depth_filename,
            "settings": settings,
            "created_at": now,
        }
        depth_metadata = {
            "profile_id": profile_id,
            "role": "body_depth_map",
            "name": f"{source_name} Depth Map",
            "filename": depth_filename,
            "input_image": f"avatar_profiles/{profile_id}/refs/body_depth_map/{depth_filename}",
            "url": f"/api/avatar-generation/profiles/{profile_id}/references/body_depth_map/{depth_filename}",
            "source": "avatar_body_depth_profile_generation",
            "source_reference_filename": source_filename,
            "source_body_filename": body_filename,
            "source_input_image": item.get("source_input_image"),
            "settings": settings,
            "created_at": now,
        }
        body_path.with_suffix(body_path.suffix + ".json").write_text(json.dumps(body_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        depth_path.with_suffix(depth_path.suffix + ".json").write_text(json.dumps(depth_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if replace_source_images and str(item.get("source_role") or "") == "body_depth" and source_filename and source_filename != body_filename:
            source_path = (profile_dir / "refs" / "body_depth" / source_filename).resolve()
            if profile_dir in source_path.parents and source_path.exists() and source_path.is_file():
                source_path.unlink()
            source_sidecar = source_path.with_suffix(source_path.suffix + ".json")
            if source_sidecar.exists() and source_sidecar.is_file():
                source_sidecar.unlink()

    def _manual_vision_image_payload(self, *, payload: "ManualImageVisionDescribeRequest") -> tuple[bytes, str, str]:
        if payload.reference_relative_path:
            root = self._manual_image_reference_root()
            safe_relative = self._safe_relative_path(payload.reference_relative_path)
            path = (root / safe_relative).resolve()
            if root not in path.parents and path != root:
                raise ValueError("manual_reference_path_invalid")
            if not path.exists() or not path.is_file():
                raise ValueError("manual_reference_not_found")
            return path.read_bytes(), self._image_mime_type(path.suffix), path.name
        encoded = str(payload.image_data_base64 or "")
        if "," in encoded and encoded.split(",", 1)[0].lower().startswith("data:"):
            header, encoded = encoded.split(",", 1)
            mime_type = header[5:].split(";", 1)[0] or self._image_mime_type(Path(str(payload.image_filename or "")).suffix)
        else:
            mime_type = self._image_mime_type(Path(str(payload.image_filename or "")).suffix)
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid_vision_image_data") from exc
        if not data:
            raise ValueError("vision_image_empty")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("vision_image_too_large")
        return data, mime_type, Path(str(payload.image_filename or "vision-reference.png")).name

    @staticmethod
    def _manual_vision_describe_prompt(*, mode: str, custom_prompt: str | None) -> str:
        custom = str(custom_prompt or "").strip()
        if custom:
            return custom
        normalized = str(mode or "").strip().lower()
        if normalized in {"scene", "place", "location"}:
            return "Describe this scene or place for an image-generation prompt. Include setting, objects, lighting, mood, camera angle, and useful style details. Be concise."
        if normalized in {"face", "body", "avatar"}:
            return "Describe this avatar for an image-generation prompt. Include face, hair, body/pose, clothing, visible style, scene context, and details useful for preserving identity. Be concise."
        return "Describe this image for an image-generation prompt. Include subject, scene, lighting, composition, style, and important visual details. Be concise."

    def _manual_pose_plan_from_local_llm(self, *, payload: "ManualImagePoseHelperRequest", template: dict) -> tuple[dict, str, str | None]:
        services = self.service_status_payload().get("services", {})
        local_llm = services.get("local_llm") if isinstance(services, dict) else {}
        socket_path = str(local_llm.get("socket_path") or "") if isinstance(local_llm, dict) else ""
        state = str(local_llm.get("state") or "").strip().lower() if isinstance(local_llm, dict) else ""
        model_id = str(local_llm.get("model_id") or local_llm.get("default_model_id") or "local").strip() if isinstance(local_llm, dict) else "local"
        if not socket_path or state not in {"running", "healthy"}:
            return {}, "local_rules", None
        request_body = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "/no_think You convert avatar pose descriptions into a compact JSON pose plan for SDXL body-depth reference generation. "
                        "Return only JSON with keys body_angle, camera_framing, head_turn, gaze, shoulders, hips, left_arm, right_arm, left_hand, right_hand, legs, weight_distribution, and pose_prompt. "
                        "Keep the pose adult, non-graphic, full-body, and physically plausible. Do not include markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "/no_think "
                        + json.dumps(
                            {
                                "template_id": payload.template_id or template.get("template_id") or MANUAL_IMAGE_DEFAULT_TEMPLATE_ID,
                                "template_description": template.get("description"),
                                "pose_text": str(payload.pose_text or "").strip(),
                                "current_pose_prompt": str(payload.current_pose_prompt or "").strip(),
                                "width": payload.width,
                                "height": payload.height,
                            },
                            sort_keys=True,
                        )
                    ),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 450,
            "stream": False,
        }
        try:
            response = self._uds_json_request(
                socket_path=socket_path,
                method="POST",
                path="/v1/chat/completions",
                body=request_body,
                host="local-llm",
                error_label="local_llm_pose_helper_failed",
            )
        except Exception as exc:
            if hasattr(self._logger, "debug"):
                self._logger.debug("manual pose helper local LLM unavailable: %s", exc)
            return {}, "local_rules", None
        choices = response.get("choices") if isinstance(response.get("choices"), list) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            content = str(message.get("content") or message.get("reasoning_content") or choices[0].get("text") or "").strip()
        parsed = self._parse_manual_image_prompt_helper_content(content)
        return parsed, "local_llm", model_id

    @classmethod
    def _normalize_manual_pose_plan(cls, *, pose_text: str, parsed: dict | None) -> dict:
        fallback = cls._fallback_manual_pose_plan(pose_text=pose_text)
        source = parsed.get("pose_plan") if isinstance(parsed, dict) and isinstance(parsed.get("pose_plan"), dict) else parsed
        source = source if isinstance(source, dict) else {}
        keys = (
            "body_angle",
            "camera_framing",
            "head_turn",
            "gaze",
            "shoulders",
            "hips",
            "left_arm",
            "right_arm",
            "left_hand",
            "right_hand",
            "legs",
            "weight_distribution",
        )
        plan = {}
        for key in keys:
            value = str(source.get(key) or fallback.get(key) or "").strip()
            plan[key] = value
        plan["source_text"] = pose_text
        return plan

    @staticmethod
    def _fallback_manual_pose_plan(*, pose_text: str) -> dict:
        text = str(pose_text or "").strip()
        lower = text.lower()
        facing_left = any(term in lower for term in ("left profile", "facing left", "turned left", "to the left"))
        facing_right = any(term in lower for term in ("right profile", "facing right", "turned right", "to the right"))
        back_view = any(term in lower for term in ("from behind", "back view", "back turned"))
        front_view = any(term in lower for term in ("front view", "facing camera", "front-facing", "straight on"))
        sitting = any(term in lower for term in ("sitting", "seated", "kneeling"))
        wide_stance = any(term in lower for term in ("wide stance", "feet apart", "power stance"))
        crossed_arms = "arms crossed" in lower or "crossed arms" in lower
        hands_on_hips = "hands on hips" in lower or "hand on hip" in lower
        hand_in_hair = "hand in hair" in lower or "touching hair" in lower
        raised_arm = any(term in lower for term in ("arm raised", "hand raised", "above her head", "overhead"))
        behind_back = "behind her back" in lower or "hands behind" in lower
        looking_down = "looking down" in lower or "gaze down" in lower
        looking_away = "looking away" in lower or "gaze away" in lower
        if back_view:
            body_angle = "back view with torso turned slightly for readable silhouette"
        elif front_view:
            body_angle = "front-facing full-body pose"
        elif facing_left:
            body_angle = "three-quarter body angle facing left"
        elif facing_right:
            body_angle = "three-quarter body angle facing right"
        else:
            body_angle = "three-quarter body angle, torso angled about 35 degrees"
        if crossed_arms:
            left_arm = "left arm crossing the torso"
            right_arm = "right arm crossing the torso"
            left_hand = "left hand near the opposite upper arm"
            right_hand = "right hand near the opposite upper arm"
        elif hands_on_hips:
            left_arm = "left elbow angled outward"
            right_arm = "right elbow angled outward"
            left_hand = "left hand resting on left hip"
            right_hand = "right hand resting on right hip"
        elif hand_in_hair:
            left_arm = "left arm lifted with elbow bent"
            right_arm = "right arm relaxed along the outer thigh"
            left_hand = "left hand touching the hair near the temple"
            right_hand = "right hand relaxed near the thigh"
        elif raised_arm:
            left_arm = "left arm raised overhead with a soft bend"
            right_arm = "right arm relaxed along the outer thigh"
            left_hand = "left hand above the head"
            right_hand = "right hand relaxed near the thigh"
        elif behind_back:
            left_arm = "left arm angled behind the back"
            right_arm = "right arm angled behind the back"
            left_hand = "left hand hidden behind the lower back"
            right_hand = "right hand hidden behind the lower back"
        else:
            left_arm = "left arm bent softly"
            right_arm = "right arm relaxed along the outer thigh"
            left_hand = "left hand resting near the hip"
            right_hand = "right hand relaxed near the thigh"
        if sitting:
            legs = "seated or kneeling lower-body pose with knees bent and feet visible where possible"
            weight = "weight supported by the seat or bent legs"
        elif wide_stance:
            legs = "standing wide stance with both feet planted and knees softly bent"
            weight = "balanced weight through both legs"
        else:
            legs = "standing full-body stance, left leg supporting weight, right knee softly bent forward"
            weight = "weight mostly on the left leg"
        return {
            "body_angle": body_angle,
            "camera_framing": "full body visible from head to feet with no crop",
            "head_turn": "head turned slightly toward the camera",
            "gaze": "eyes looking downward" if looking_down else ("eyes looking away from camera" if looking_away else "eyes looking toward the viewer"),
            "shoulders": "shoulders relaxed and readable",
            "hips": "hips angled naturally with a clear waist and hip line",
            "left_arm": left_arm,
            "right_arm": right_arm,
            "left_hand": left_hand,
            "right_hand": right_hand,
            "legs": legs,
            "weight_distribution": weight,
        }

    @staticmethod
    def _manual_pose_prompt_from_plan(*, plan: dict) -> str:
        ordered_keys = (
            "camera_framing",
            "body_angle",
            "weight_distribution",
            "legs",
            "shoulders",
            "hips",
            "left_arm",
            "left_hand",
            "right_arm",
            "right_hand",
            "head_turn",
            "gaze",
        )
        parts = [str(plan.get(key) or "").strip() for key in ordered_keys]
        parts.extend(["clear readable full-body pose", "strong body silhouette", "hands visible when not intentionally hidden"])
        return ", ".join(part for part in parts if part)

    @staticmethod
    def _coerce_manual_pose_dimension(value, *, default, fallback: int) -> int:
        try:
            parsed = int(value if value not in (None, "") else default)
        except (TypeError, ValueError):
            parsed = int(fallback)
        return min(max(parsed, 256), 1536)

    def _write_manual_pose_reference(
        self,
        *,
        manual_paths: dict,
        avatar_name: str | None,
        pose_text: str,
        pose_prompt: str,
        plan: dict,
        width: int,
        height: int,
    ) -> dict:
        references_root = self._manual_image_reference_root(manual_paths=manual_paths)
        target_dir = references_root / "avatar"
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_filename_component(avatar_name or "pose")
        target_name = f"{safe_name}_pose_{int(time.time())}.png"
        target_path = target_dir / target_name
        target_path.write_bytes(self._manual_pose_guide_png_bytes(width=width, height=height, plan=plan))
        metadata = {
            "category": "avatar",
            "role": "pose",
            "name": f"{safe_name} pose guide",
            "filename": target_name,
            "input_image": f"references/avatar/{target_name}",
            "source": "manual_pose_helper",
            "pose_text": pose_text,
            "pose_prompt": pose_prompt,
            "pose_plan": plan,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        target_path.with_suffix(target_path.suffix + ".json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self._manual_image_reference_payload(path=target_path, metadata=metadata)

    @classmethod
    def _manual_pose_guide_png_bytes(cls, *, width: int, height: int, plan: dict) -> bytes:
        w = min(max(int(width), 256), 1536)
        h = min(max(int(height), 256), 1536)
        pixels = bytearray()
        background = (248, 247, 244, 255)
        for _ in range(w * h):
            pixels.extend(background)

        def put_pixel(x: int, y: int, color: tuple[int, int, int, int]) -> None:
            if x < 0 or y < 0 or x >= w or y >= h:
                return
            offset = (y * w + x) * 4
            pixels[offset : offset + 4] = bytes(color)

        def draw_disc(cx: float, cy: float, radius: int, color: tuple[int, int, int, int]) -> None:
            left = int(cx) - radius
            right = int(cx) + radius
            top = int(cy) - radius
            bottom = int(cy) + radius
            radius_sq = radius * radius
            for yy in range(top, bottom + 1):
                for xx in range(left, right + 1):
                    if (xx - int(cx)) ** 2 + (yy - int(cy)) ** 2 <= radius_sq:
                        put_pixel(xx, yy, color)

        def draw_line(start: tuple[float, float], end: tuple[float, float], color: tuple[int, int, int, int], thickness: int = 7) -> None:
            x1, y1 = start
            x2, y2 = end
            steps = max(abs(int(x2 - x1)), abs(int(y2 - y1)), 1)
            for step in range(steps + 1):
                t = step / steps
                draw_disc(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, thickness, color)

        text = " ".join(str(value or "").lower() for value in plan.values())
        angle_text = str(plan.get("body_angle") or "").lower()
        direction = -1 if "left" in angle_text else 1
        if "front-facing" in angle_text or "front view" in angle_text:
            direction = 0
        torso_shift = int(w * 0.045) * direction
        head = (w * 0.5 - torso_shift * 0.35, h * 0.13)
        neck = (w * 0.5 - torso_shift * 0.2, h * 0.22)
        shoulder_center = (w * 0.5 - torso_shift, h * 0.27)
        hip_center = (w * 0.5 + torso_shift, h * 0.52)
        shoulder_half = w * (0.13 if direction else 0.16)
        hip_half = w * 0.1
        left_shoulder = (shoulder_center[0] - shoulder_half, shoulder_center[1])
        right_shoulder = (shoulder_center[0] + shoulder_half, shoulder_center[1])
        left_hip = (hip_center[0] - hip_half, hip_center[1])
        right_hip = (hip_center[0] + hip_half, hip_center[1])

        ink = (36, 39, 42, 255)
        accent = (92, 118, 180, 255)
        joint = (25, 25, 25, 255)
        guide = (202, 204, 210, 255)
        for y in (int(h * 0.08), int(h * 0.95)):
            draw_line((w * 0.18, y), (w * 0.82, y), guide, 2)
        draw_disc(*head, int(min(w, h) * 0.045), accent)
        draw_line(head, neck, ink, 5)
        draw_line(left_shoulder, right_shoulder, ink, 6)
        draw_line(left_shoulder, left_hip, ink, 7)
        draw_line(right_shoulder, right_hip, ink, 7)
        draw_line(left_hip, right_hip, ink, 6)

        if "crossing the torso" in text or "crossed" in text:
            left_elbow = (w * 0.44, h * 0.39)
            left_wrist = (w * 0.58, h * 0.36)
            right_elbow = (w * 0.56, h * 0.39)
            right_wrist = (w * 0.42, h * 0.36)
        elif "overhead" in text or "above the head" in text or "raised" in text:
            left_elbow = (left_shoulder[0] - w * 0.04, h * 0.17)
            left_wrist = (w * 0.45, h * 0.06)
            right_elbow = (right_shoulder[0] + w * 0.04, h * 0.43)
            right_wrist = (right_hip[0] + w * 0.08, h * 0.63)
        elif "hair" in text or "temple" in text:
            left_elbow = (left_shoulder[0] - w * 0.05, h * 0.21)
            left_wrist = (head[0] - w * 0.04, head[1] - h * 0.01)
            right_elbow = (right_shoulder[0] + w * 0.04, h * 0.43)
            right_wrist = (right_hip[0] + w * 0.08, h * 0.63)
        elif "behind" in text:
            left_elbow = (left_shoulder[0] - w * 0.03, h * 0.4)
            left_wrist = (hip_center[0] - w * 0.03, h * 0.55)
            right_elbow = (right_shoulder[0] + w * 0.03, h * 0.4)
            right_wrist = (hip_center[0] + w * 0.03, h * 0.55)
        elif "hip" in text:
            left_elbow = (left_shoulder[0] - w * 0.09, h * 0.39)
            left_wrist = left_hip
            right_elbow = (right_shoulder[0] + w * 0.09, h * 0.39)
            right_wrist = right_hip
        else:
            left_elbow = (left_shoulder[0] - w * 0.04, h * 0.42)
            left_wrist = (left_hip[0] - w * 0.04, h * 0.58)
            right_elbow = (right_shoulder[0] + w * 0.04, h * 0.46)
            right_wrist = (right_hip[0] + w * 0.07, h * 0.64)
        for start, elbow, wrist in ((left_shoulder, left_elbow, left_wrist), (right_shoulder, right_elbow, right_wrist)):
            draw_line(start, elbow, ink, 5)
            draw_line(elbow, wrist, ink, 5)

        if "seated" in text or "sitting" in text or "kneeling" in text:
            left_knee = (left_hip[0] - w * 0.11, h * 0.66)
            right_knee = (right_hip[0] + w * 0.12, h * 0.66)
            left_ankle = (left_knee[0] - w * 0.03, h * 0.83)
            right_ankle = (right_knee[0] + w * 0.03, h * 0.83)
        elif "wide stance" in text or "feet apart" in text:
            left_knee = (left_hip[0] - w * 0.09, h * 0.72)
            right_knee = (right_hip[0] + w * 0.09, h * 0.72)
            left_ankle = (left_knee[0] - w * 0.08, h * 0.93)
            right_ankle = (right_knee[0] + w * 0.08, h * 0.93)
        else:
            left_knee = (left_hip[0] - w * 0.03, h * 0.72)
            right_knee = (right_hip[0] + w * 0.08, h * 0.71)
            left_ankle = (left_knee[0] - w * 0.02, h * 0.93)
            right_ankle = (right_knee[0] + w * 0.05, h * 0.91)
        for hip, knee, ankle in ((left_hip, left_knee, left_ankle), (right_hip, right_knee, right_ankle)):
            draw_line(hip, knee, ink, 6)
            draw_line(knee, ankle, ink, 6)
        for point in (
            head,
            neck,
            left_shoulder,
            right_shoulder,
            left_elbow,
            right_elbow,
            left_wrist,
            right_wrist,
            left_hip,
            right_hip,
            left_knee,
            right_knee,
            left_ankle,
            right_ankle,
        ):
            draw_disc(*point, 8, joint)
        return cls._rgba_png_bytes(width=w, height=h, pixels=bytes(pixels))

    @staticmethod
    def _rgba_png_bytes(*, width: int, height: int, pixels: bytes) -> bytes:
        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        rows = []
        stride = width * 4
        for y in range(height):
            rows.append(b"\x00" + pixels[y * stride : (y + 1) * stride])
        compressed = zlib.compress(b"".join(rows), level=6)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", compressed)
            + chunk(b"IEND", b"")
        )

    @staticmethod
    def _image_mime_type(suffix: str) -> str:
        normalized = str(suffix or "").lower()
        if normalized in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if normalized == ".webp":
            return "image/webp"
        return "image/png"

    @staticmethod
    def _parse_manual_image_prompt_helper_content(content: str) -> dict:
        text = str(content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    parsed = {}
            else:
                parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _manual_image_latest_job(self, *, generation_status: dict, outputs: list[dict], runtime_service: dict | None = None) -> dict:
        runtime_service = runtime_service if isinstance(runtime_service, dict) else {}
        job = self._read_manual_image_latest_job()
        prompt_id = str(job.get("prompt_id") or "").strip()
        prompt_ids = [
            str(item or "").strip()
            for item in list(job.get("prompt_ids") or [])
            if str(item or "").strip()
        ]
        if prompt_id and prompt_id not in prompt_ids:
            prompt_ids.insert(0, prompt_id)
        if not prompt_ids:
            return {}
        session = generation_status.get("session") if isinstance(generation_status.get("session"), dict) else {}
        progress = generation_status.get("progress") if isinstance(generation_status.get("progress"), dict) else {}
        pending_prompt_ids = [str(item) for item in list(session.get("pending_prompt_ids") or [])]
        running_prompt_id = str(session.get("running_prompt_id") or "").strip()
        progress_prompt_id = str(progress.get("prompt_id") or "").strip()
        running_prompt_ids = {running_prompt_id} - {""}
        if bool(session.get("queue_active")) and progress_prompt_id:
            running_prompt_ids.add(progress_prompt_id)
        status = "submitted"
        if any(item in running_prompt_ids for item in prompt_ids):
            status = "running"
        elif any(item in pending_prompt_ids for item in prompt_ids):
            status = "queued"
        submitted_at = str(job.get("submitted_at") or "").strip()
        completed_outputs = [item for item in outputs if str(item.get("modified_at") or "") >= submitted_at]
        transparent_background = self._manual_image_job_uses_transparent_background(job=job)
        rgb_fallback_outputs = [
            item for item in completed_outputs if self._manual_image_is_rgb_background_removal_fallback_output(output=item)
        ]
        transparent_outputs = [
            item for item in completed_outputs if not self._manual_image_is_rgb_background_removal_fallback_output(output=item)
        ]
        runtime_failure = None
        if not completed_outputs and status in {"submitted", "queued", "running"}:
            runtime_failure = self._manual_image_runtime_failure(job=job, runtime_service=runtime_service)
            if runtime_failure:
                status = "failed"
        job_inactive = status not in {"running", "queued"}
        bg_removal_fallback_active = bool(transparent_background and rgb_fallback_outputs and not transparent_outputs and job_inactive)
        rgb_fallback_cleanup = None
        if transparent_background and transparent_outputs and rgb_fallback_outputs and job_inactive:
            rgb_fallback_cleanup = self._cleanup_manual_rgb_background_removal_fallback_outputs(outputs=rgb_fallback_outputs)
            deleted = set(rgb_fallback_cleanup.get("deleted") or [])
            if deleted:
                completed_outputs = [
                    item for item in completed_outputs if str(item.get("relative_path") or "").strip() not in deleted
                ]
                rgb_fallback_outputs = [
                    item for item in rgb_fallback_outputs if str(item.get("relative_path") or "").strip() not in deleted
                ]
        latest_output = transparent_outputs[0] if transparent_outputs else (completed_outputs[0] if completed_outputs else None)
        fallback = None
        if bg_removal_fallback_active:
            status = "completed_with_fallback"
            latest_output = rgb_fallback_outputs[0]
            fallback = {
                "active": True,
                "kind": "background_removal_rgb_fallback",
                "reason": "transparent_output_missing",
                "latest_output": latest_output,
            }
        elif completed_outputs and job_inactive:
            status = "completed"
        progress_for_job = self._manual_image_progress_for_job(
            progress=progress,
            prompt_id=prompt_id,
            prompt_ids=prompt_ids,
            status=status,
            running_prompt_id=running_prompt_id,
        )
        lora_metadata = self._materialize_manual_lora_metadata(job=job, completed_outputs=completed_outputs)
        progress_detail = self._manual_image_progress_detail(
            job=job,
            status=status,
            prompt_id=prompt_id,
            prompt_ids=prompt_ids,
            session=session,
            progress=progress_for_job,
            runtime_service=runtime_service,
            runtime_failure=runtime_failure,
            completed_output_count=len(completed_outputs),
        )
        updated = {
            **job,
            "status": status,
            "queue_active": bool(session.get("queue_active")),
            "running_count": int(session.get("running_count") or 0),
            "pending_count": int(session.get("pending_count") or 0),
            "progress": progress_for_job,
            "progress_detail": progress_detail,
            "completed_output_count": len(completed_outputs),
            "latest_output": latest_output,
            "failure": runtime_failure,
            "background_removal_fallback": fallback,
            "rgb_fallback_cleanup": rgb_fallback_cleanup,
            "lora_metadata": lora_metadata,
        }
        if updated != job:
            self._write_manual_image_latest_job(updated)
        return updated

    def _free_manual_image_runtime_models(self, *, socket_path: str) -> dict:
        if not socket_path:
            return {"attempted": False, "reason": "socket_unavailable"}
        try:
            queue = self._uds_json_request(socket_path=socket_path, method="GET", path="/queue")
            running = queue.get("queue_running") if isinstance(queue, dict) else []
            pending = queue.get("queue_pending") if isinstance(queue, dict) else []
            if (isinstance(running, list) and running) or (isinstance(pending, list) and pending):
                return {"attempted": False, "reason": "queue_active"}
            self._uds_json_request(
                socket_path=socket_path,
                method="POST",
                path="/free",
                body={"unload_models": True, "free_memory": True},
            )
            return {"attempted": True, "status": "ok"}
        except Exception as exc:
            self._logger.debug("manual image preflight memory cleanup unavailable: %s", exc)
            return {"attempted": True, "status": "failed", "error": str(exc)}

    def _manual_image_progress_for_job(
        self,
        *,
        progress: dict,
        prompt_id: str,
        prompt_ids: list[str],
        status: str,
        running_prompt_id: str,
    ) -> dict:
        if not isinstance(progress, dict):
            progress = {}
        progress_prompt_id = str(progress.get("prompt_id") or "").strip()
        active_status = status in {"submitted", "queued", "running"}
        if active_status and progress_prompt_id and progress_prompt_id not in set(prompt_ids):
            return {
                "available": bool(progress.get("available", False)),
                "active": True,
                "value": None,
                "max": None,
                "percent": None,
                "prompt_id": running_prompt_id if running_prompt_id in set(prompt_ids) else prompt_id,
                "node": None,
                "fallback_status": status,
                "stale_prompt_id": progress_prompt_id,
                "updated_at_epoch": progress.get("updated_at_epoch"),
            }
        return dict(progress)

    def _manual_image_progress_detail(
        self,
        *,
        job: dict,
        status: str,
        prompt_id: str,
        prompt_ids: list[str],
        session: dict,
        progress: dict,
        runtime_service: dict,
        runtime_failure: dict | None,
        completed_output_count: int,
    ) -> dict:
        now_epoch = time.time()
        submitted_epoch = self._manual_image_parse_epoch(job.get("submitted_at"))
        updated_epoch = self._manual_image_float(progress.get("updated_at_epoch"))
        elapsed_seconds = round(now_epoch - submitted_epoch, 1) if submitted_epoch is not None else None
        updated_ago_seconds = round(now_epoch - updated_epoch, 1) if updated_epoch is not None else None
        node_id = str(progress.get("node") or "").strip()
        node = self._manual_image_template_node(job=job, node_id=node_id) if node_id else {}
        class_type = str(node.get("class_type") or "").strip()
        phase, label = MANUAL_IMAGE_PROGRESS_NODE_LABELS.get(class_type, ("running", class_type or "Working"))
        percent = self._manual_image_float(progress.get("percent"))
        value = progress.get("value")
        maximum = progress.get("max")
        stale = bool(progress.get("stale_prompt_id")) or (
            status in {"submitted", "queued", "running"} and updated_ago_seconds is not None and updated_ago_seconds > 30
        )
        if status == "queued":
            phase = "queued"
            label = "Queued"
        elif status == "submitted":
            phase = "submitted"
            label = "Submitted"
        elif status == "completed":
            phase = "completed"
            label = "Completed"
            percent = 100.0
        elif status == "completed_with_fallback":
            phase = "completed"
            label = "Completed with RGB fallback"
            percent = 100.0
        elif status == "failed":
            phase = "failed"
            label = "Failed"
        elif not node_id and status == "running":
            phase = "running"
            label = "Waiting for ComfyUI progress"
        message = self._manual_image_progress_message(
            status=status,
            label=label,
            value=value,
            maximum=maximum,
            percent=percent,
            runtime_failure=runtime_failure,
            completed_output_count=completed_output_count,
            stale=stale,
        )
        return {
            "status": status,
            "phase": phase,
            "label": label,
            "message": message,
            "prompt_id": str(progress.get("prompt_id") or prompt_id or "").strip() or None,
            "prompt_ids": prompt_ids,
            "node_id": node_id or None,
            "node_class": class_type or None,
            "value": value,
            "max": maximum,
            "percent": percent,
            "elapsed_seconds": elapsed_seconds,
            "updated_ago_seconds": updated_ago_seconds,
            "stale": stale,
            "queue_active": bool(session.get("queue_active")),
            "running_count": int(session.get("running_count") or 0),
            "pending_count": int(session.get("pending_count") or 0),
            "runtime_pid": runtime_service.get("pid"),
            "runtime_restart_count": runtime_service.get("restart_count"),
            "runtime_oom_killed": bool(runtime_service.get("last_oom_killed")),
            "failure_reason": runtime_failure.get("reason") if isinstance(runtime_failure, dict) else None,
            "failure_detail": runtime_failure if isinstance(runtime_failure, dict) else None,
        }

    @staticmethod
    def _manual_image_progress_message(
        *,
        status: str,
        label: str,
        value,
        maximum,
        percent: float | None,
        runtime_failure: dict | None,
        completed_output_count: int,
        stale: bool,
    ) -> str:
        if runtime_failure:
            reason = str(runtime_failure.get("reason") or "comfyui_runtime_failed")
            if reason == "comfyui_runtime_oom":
                return "ComfyUI restarted after an out-of-memory failure during this job."
            return "ComfyUI restarted before this job produced an output."
        if status == "completed":
            return f"Completed with {completed_output_count} output file(s)."
        if status == "completed_with_fallback":
            return "Transparent output was missing; using the RGB fallback image."
        if status == "failed":
            return "Job failed before producing an output."
        if stale:
            return "Waiting for a fresh ComfyUI progress event."
        if label == "Sampling" and value is not None and maximum is not None:
            return f"Sampling step {value} of {maximum}."
        if percent is not None:
            return f"{label} is {percent:.1f}% complete."
        return f"{label} is active."

    def _manual_image_runtime_failure(self, *, job: dict, runtime_service: dict) -> dict | None:
        if not isinstance(runtime_service, dict) or not runtime_service:
            return None
        submitted_epoch = self._manual_image_parse_epoch(job.get("submitted_at"))
        runtime_started_epoch = self._manual_image_parse_epoch(runtime_service.get("started_at"))
        runtime_restarted_after_submit = (
            submitted_epoch is not None
            and runtime_started_epoch is not None
            and runtime_started_epoch > submitted_epoch + 1.0
        )
        job_pid = self._manual_image_int(job.get("runtime_pid"))
        current_pid = self._manual_image_int(runtime_service.get("pid"))
        pid_changed = bool(job_pid and current_pid and job_pid != current_pid)
        job_restart_count = self._manual_image_int(job.get("runtime_restart_count"))
        current_restart_count = self._manual_image_int(runtime_service.get("restart_count"))
        restart_count_increased = (
            job_restart_count is not None
            and current_restart_count is not None
            and current_restart_count > job_restart_count
        )
        if not (runtime_restarted_after_submit or pid_changed or restart_count_increased):
            return None
        oom_killed = bool(runtime_service.get("last_oom_killed"))
        return {
            "reason": "comfyui_runtime_oom" if oom_killed else "comfyui_runtime_restarted",
            "runtime_restarted": True,
            "oom_killed": oom_killed,
            "runtime_pid": current_pid,
            "previous_runtime_pid": job_pid,
            "runtime_restart_count": current_restart_count,
            "previous_runtime_restart_count": job_restart_count,
            "runtime_started_at": runtime_service.get("started_at"),
        }

    def _manual_image_template_node(self, *, job: dict, node_id: str) -> dict:
        template_id = self._manual_image_job_template_id(job=job)
        if not template_id or not node_id:
            return {}
        try:
            template = self.get_comfyui_template_catalog_entry(template_id=template_id)["template"]
            workflow_path = Path(str(template.get("api_workflow_path") or ""))
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            node = workflow.get(str(node_id)) if isinstance(workflow, dict) else {}
            return node if isinstance(node, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _manual_image_job_template_id(*, job: dict) -> str:
        template_id = str(job.get("template_id") or "").strip()
        if template_id:
            return template_id
        metadata = job.get("lora_metadata") if isinstance(job.get("lora_metadata"), dict) else {}
        return str(metadata.get("template_id") or "").strip()

    @staticmethod
    def _manual_image_parse_epoch(value) -> float | None:
        raw = str(value or "").strip()
        if not raw or raw.startswith("0001-01-01"):
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except Exception:
            return None

    @staticmethod
    def _manual_image_float(value) -> float | None:
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _manual_image_int(value) -> int | None:
        try:
            return int(value)
        except Exception:
            return None

    def _manual_image_job_uses_transparent_background(self, *, job: dict) -> bool:
        template_id = str(job.get("template_id") or "").strip()
        if not template_id:
            metadata = job.get("lora_metadata") if isinstance(job.get("lora_metadata"), dict) else {}
            template_id = str(metadata.get("template_id") or "").strip()
        if not template_id:
            return False
        try:
            template = self.get_comfyui_template_catalog_entry(template_id=template_id)["template"]
            metadata = template.get("metadata") if isinstance(template.get("metadata"), dict) else {}
            return bool(metadata.get("transparent_background"))
        except Exception:
            return "transparent" in template_id

    @staticmethod
    def _manual_image_is_rgb_background_removal_fallback_output(*, output: dict) -> bool:
        filename = str(output.get("filename") or Path(str(output.get("relative_path") or "")).name).strip()
        stem = Path(filename).stem
        return stem.endswith("_rgb") or "_rgb_" in stem

    def _cleanup_manual_rgb_background_removal_fallback_outputs(self, *, outputs: list[dict]) -> dict:
        output_dir = self._manual_image_output_dir()
        deleted: list[str] = []
        errors: list[dict] = []
        for output in outputs:
            relative_raw = str(output.get("relative_path") or "").strip()
            if not relative_raw:
                continue
            safe_relative = self._safe_relative_path(relative_raw)
            path = (output_dir / safe_relative).resolve()
            if output_dir not in path.parents and path != output_dir:
                errors.append({"relative_path": safe_relative.as_posix(), "error": "manual_output_path_invalid"})
                continue
            try:
                path.unlink()
                self._delete_manual_lora_sidecars(path=path)
                deleted.append(safe_relative.as_posix())
            except FileNotFoundError:
                self._delete_manual_lora_sidecars(path=path)
                deleted.append(safe_relative.as_posix())
            except PermissionError:
                try:
                    self._delete_manual_image_output_via_container(relative_path=safe_relative.as_posix())
                    self._delete_manual_lora_sidecars(path=path)
                    deleted.append(safe_relative.as_posix())
                except Exception as exc:
                    errors.append({"relative_path": safe_relative.as_posix(), "error": str(exc)})
            except Exception as exc:
                errors.append({"relative_path": safe_relative.as_posix(), "error": str(exc)})
        return {"deleted": deleted, "errors": errors}

    def _read_manual_image_latest_job(self) -> dict:
        try:
            payload = json.loads(self._manual_image_generation_job_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_manual_image_latest_job(self, payload: dict) -> None:
        self._manual_image_generation_job_path.parent.mkdir(parents=True, exist_ok=True)
        self._manual_image_generation_job_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def manual_image_output_response(self, *, relative_path: str) -> FileResponse:
        output_dir = self._manual_image_output_dir()
        safe_relative = self._safe_relative_path(relative_path)
        path = (output_dir / safe_relative).resolve()
        if output_dir not in path.parents and path != output_dir:
            raise ValueError("manual_output_path_invalid")
        if not path.exists() or not path.is_file():
            raise ValueError("manual_output_not_found")
        return FileResponse(path)

    def delete_manual_image_output(self, *, relative_path: str) -> dict:
        output_dir = self._manual_image_output_dir()
        safe_relative = self._safe_relative_path(relative_path)
        path = (output_dir / safe_relative).resolve()
        if output_dir not in path.parents and path != output_dir:
            raise ValueError("manual_output_path_invalid")
        if not path.exists() or not path.is_file():
            raise ValueError("manual_output_not_found")
        try:
            path.unlink()
        except PermissionError:
            self._delete_manual_image_output_via_container(relative_path=safe_relative.as_posix())
        self._delete_manual_lora_sidecars(path=path)
        return {
            "deleted": True,
            "relative_path": safe_relative.as_posix(),
            "outputs": self._manual_image_outputs(limit=24),
        }

    def _materialize_manual_lora_metadata(self, *, job: dict, completed_outputs: list[dict]) -> dict:
        metadata = job.get("lora_metadata") if isinstance(job.get("lora_metadata"), dict) else {}
        if not metadata.get("enabled") or not completed_outputs:
            return metadata if isinstance(metadata, dict) else {"enabled": False}
        output_dir = self._manual_image_output_dir()
        caption = str(metadata.get("caption") or "").strip()
        written: list[str] = []
        for output in completed_outputs:
            relative = self._safe_relative_path(output.get("relative_path"))
            image_path = (output_dir / relative).resolve()
            if output_dir not in image_path.parents or not image_path.exists() or not image_path.is_file():
                continue
            caption_path = image_path.with_suffix(".txt")
            json_path = image_path.with_suffix(".json")
            if caption and not caption_path.exists():
                caption_path.write_text(caption + "\n", encoding="utf-8")
            output_seed = self._manual_image_seed_from_output(output=output)
            payload = {
                "schema_version": "1.0",
                "purpose": "lora_training_metadata",
                "image": image_path.name,
                "caption_file": caption_path.name,
                "caption": caption,
                "negative_prompt": metadata.get("negative_prompt"),
                "template_id": metadata.get("template_id"),
                "mode": metadata.get("mode"),
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "seed": output_seed if output_seed is not None else metadata.get("seed"),
                "steps": metadata.get("steps"),
                "cfg": metadata.get("cfg"),
                "denoise": metadata.get("denoise"),
                "prompt_id": job.get("prompt_id"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if not json_path.exists():
                json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(image_path.relative_to(output_dir).with_suffix(".txt").as_posix())
        return {**metadata, "written": written}

    @staticmethod
    def _manual_image_seed_from_output(*, output: dict) -> int | None:
        filename = str(output.get("filename") or Path(str(output.get("relative_path") or "")).name).strip()
        stem = Path(filename).stem
        marker_index = stem.rfind("seed")
        if marker_index < 0:
            return None
        digits = []
        for character in stem[marker_index + 4 :]:
            if character.isdigit():
                digits.append(character)
                continue
            break
        if not digits:
            return None
        try:
            return int("".join(digits))
        except ValueError:
            return None

    @staticmethod
    def _delete_manual_lora_sidecars(*, path: Path) -> None:
        for suffix in (".txt", ".json"):
            sidecar = path.with_suffix(suffix)
            try:
                sidecar.unlink()
            except FileNotFoundError:
                pass

    def _delete_manual_image_output_via_container(self, *, relative_path: str) -> None:
        services = self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        runtime = str(webui.get("runtime") or "gpu").strip().lower() if isinstance(webui, dict) else "gpu"
        runtime_key = "comfyui_cpu" if runtime == "cpu" else "comfyui_gpu"
        runtime_service = services.get(runtime_key) if isinstance(services, dict) else {}
        container_name = (
            str(runtime_service.get("container_name") or "").strip()
            if isinstance(runtime_service, dict)
            else ""
        )
        if not container_name and isinstance(webui, dict):
            container_name = str(webui.get("container_name") or "").strip()
        if not container_name:
            raise ValueError("manual_output_delete_container_unavailable")
        container_runtime = "cpu" if runtime == "cpu" else "gpu"
        container_path = f"/runtime/{container_runtime}/output/{relative_path}"
        docker_bin = str(os.environ.get("DOCKER_BIN") or "docker").strip() or "docker"
        try:
            subprocess.run([docker_bin, "exec", container_name, "rm", "-f", "--", container_path], check=True)
        except subprocess.CalledProcessError as exc:
            raise ValueError("manual_output_delete_failed") from exc

    def _manual_image_workflow_from_template(self, *, template: dict, payload: "ManualImageGenerationRequest", input_image: str) -> dict:
        workflow, _ = self._manual_image_workflow_and_values_from_template(
            template=template,
            payload=payload,
            input_image=input_image,
        )
        return workflow

    def _manual_image_workflow_and_values_from_template(self, *, template: dict, payload: "ManualImageGenerationRequest", input_image: str) -> tuple[dict, dict]:
        variables = {item["name"]: item for item in list(template.get("variables") or []) if isinstance(item, dict) and item.get("name")}
        values = dict(template.get("defaults") or {})
        seed = self._coerce_manual_image_seed(payload.seed) if payload.seed is not None else values.get("seed")
        if seed is None:
            seed = secrets.randbelow(2**63)
        values.update(
            {
                "positive_prompt": str(payload.prompt or values.get("positive_prompt") or "").strip(),
                "negative_prompt": str(payload.negative_prompt or values.get("negative_prompt") or "").strip(),
                "width": int(payload.width or values.get("width") or 1024),
                "height": int(payload.height or values.get("height") or 1024),
                "seed": seed,
                "steps": int(payload.steps or values.get("steps") or 4),
                "cfg": float(payload.cfg if payload.cfg is not None else values.get("cfg") or 1.6),
                "denoise": float(payload.denoise if payload.denoise is not None else values.get("denoise") or 0.55),
            }
        )
        if isinstance(payload.template_variables, dict):
            for key, value in payload.template_variables.items():
                name = str(key or "").strip()
                if name in variables and name not in {"positive_prompt", "negative_prompt", "input_image"}:
                    values[name] = self._coerce_manual_template_variable_value(variable=variables[name], value=value)
        if "avatar_name" in variables:
            values["avatar_name"] = self._safe_filename_component(values.get("avatar_name") or "avatar")
        if "input_image" in variables:
            values["input_image"] = input_image
        for name, variable in variables.items():
            if bool(variable.get("required")) and values.get(name) in (None, ""):
                raise ValueError(f"manual_image_variable_required:{name}")
        api_workflow = json.loads(Path(str(template.get("api_workflow_path") or "")).read_text(encoding="utf-8"))
        return self._substitute_template_placeholders(api_workflow, variables=values), values

    def _manual_image_batch_item_payload(
        self,
        *,
        template: dict,
        payload: "ManualImageGenerationRequest",
        batch_index: int,
    ) -> "ManualImageGenerationRequest":
        update: dict = {}
        if bool(payload.randomize_seed):
            update["seed"] = secrets.randbelow(2**63)
        if bool(payload.randomize_reference_strengths):
            variables = {item["name"]: item for item in list(template.get("variables") or []) if isinstance(item, dict) and item.get("name")}
            defaults = template.get("defaults") if isinstance(template.get("defaults"), dict) else {}
            template_variables = dict(payload.template_variables or {})
            amount = self._manual_image_reference_strength_jitter_amount(payload.reference_strength_jitter)
            for name in MANUAL_IMAGE_REFERENCE_STRENGTH_VARIABLES:
                if name not in variables:
                    continue
                base_value = template_variables.get(name, defaults.get(name, variables[name].get("default")))
                if base_value in (None, ""):
                    continue
                template_variables[name] = self._jitter_manual_reference_strength(value=base_value, amount=amount)
            update["template_variables"] = template_variables
        if not update:
            return payload
        return payload.model_copy(update=update)

    @staticmethod
    def _manual_image_batch_count(value) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 1
        return min(max(parsed, 1), 25)

    @staticmethod
    def _manual_image_reference_strength_jitter_amount(value) -> float:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            amount = 0.05
        return min(max(amount, 0.0), 1.0)

    @staticmethod
    def _jitter_manual_reference_strength(*, value, amount: float) -> float:
        try:
            base = float(value)
        except (TypeError, ValueError):
            return value
        if amount <= 0:
            return round(min(max(base, 0.0), 1.0), 4)
        delta = ((secrets.randbelow(2_000_001) / 1_000_000.0) - 1.0) * amount
        return round(min(max(base + delta, 0.0), 1.0), 4)

    @staticmethod
    def _coerce_manual_image_seed(value) -> int | None:
        if value in (None, ""):
            return None
        seed = int(str(value).strip())
        if seed < 0:
            raise ValueError("manual_image_seed_invalid")
        return seed

    @staticmethod
    def _coerce_manual_template_variable_value(*, variable: dict, value):
        variable_type = str(variable.get("type") or "").strip().lower()
        if value in (None, ""):
            return value
        if variable_type == "integer":
            return int(value)
        if variable_type == "number":
            return float(value)
        return value

    def _manual_image_output_dir(self) -> Path:
        services = self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        manual_paths = webui.get("manual_paths") if isinstance(webui, dict) else {}
        output_dir = str(manual_paths.get("output_dir") or "runtime/manual/comfyui-gpu/output") if isinstance(manual_paths, dict) else "runtime/manual/comfyui-gpu/output"
        return Path(output_dir).resolve()

    def _manual_image_input_dir(self) -> Path:
        services = self.service_status_payload().get("services", {})
        webui = services.get("comfyui_webui") if isinstance(services, dict) else {}
        manual_paths = webui.get("manual_paths") if isinstance(webui, dict) else {}
        input_dir = str(manual_paths.get("input_dir") or "runtime/manual/comfyui-gpu/input") if isinstance(manual_paths, dict) else "runtime/manual/comfyui-gpu/input"
        return Path(input_dir).resolve()

    def _manual_image_reference_root(self, *, manual_paths: dict | None = None) -> Path:
        if isinstance(manual_paths, dict):
            input_dir = Path(str(manual_paths.get("input_dir") or "runtime/manual/comfyui-gpu/input")).resolve()
        else:
            input_dir = self._manual_image_input_dir()
        return (input_dir / "references").resolve()

    def _manual_image_outputs(self, *, limit: int) -> list[dict]:
        output_dir = self._manual_image_output_dir()
        if not output_dir.exists():
            return []
        allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
        files = [path for path in output_dir.rglob("*") if path.is_file() and path.suffix.lower() in allowed_suffixes]
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        outputs = []
        for path in files[: max(int(limit), 1)]:
            stat = path.stat()
            relative = path.relative_to(output_dir).as_posix()
            outputs.append(
                {
                    "relative_path": relative,
                    "filename": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "url": f"/api/manual-image-generation/outputs/{relative}",
                }
            )
        return outputs

    def _manual_image_references(self, *, limit: int) -> list[dict]:
        root = self._manual_image_reference_root()
        if not root.exists():
            return []
        allowed_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
        files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in allowed_suffixes]
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return [self._manual_image_reference_payload(path=path) for path in files[: max(int(limit), 1)]]

    def _manual_image_reference_payload(self, *, path: Path, metadata: dict | None = None) -> dict:
        root = self._manual_image_reference_root()
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        if metadata is None:
            try:
                sidecar = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))
            except Exception:
                sidecar = {}
            metadata = sidecar if isinstance(sidecar, dict) else {}
        category = str(metadata.get("category") or Path(relative).parts[0] if Path(relative).parts else "reference")
        return {
            "relative_path": relative,
            "filename": path.name,
            "category": category,
            "role": str(metadata.get("role") or "reference"),
            "name": str(metadata.get("name") or path.stem),
            "input_image": str(metadata.get("input_image") or f"references/{relative}"),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "created_at": metadata.get("created_at"),
            "url": f"/api/manual-image-generation/references/{relative}",
        }

    @staticmethod
    def _manual_reference_category(value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"avatar", "scene"}:
            return normalized
        if normalized in {"place", "places", "location"}:
            return "scene"
        return "avatar"

    @staticmethod
    def _safe_relative_path(value: str) -> Path:
        text = str(value or "").replace("\\", "/").strip().lstrip("/")
        candidate = Path(text)
        if not text or candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("invalid_relative_path")
        return candidate

    @staticmethod
    def _safe_filename_component(value: object) -> str:
        text = str(value or "").strip()
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text).strip("_")
        while "__" in safe:
            safe = safe.replace("__", "_")
        return safe[:80] or "avatar"

    def _save_manual_reference_image(self, *, manual_paths: dict, filename: str | None, data_base64: str) -> str:
        input_dir = Path(str(manual_paths.get("input_dir") or "runtime/manual/comfyui-gpu/input")).resolve()
        input_dir.mkdir(parents=True, exist_ok=True)
        raw_name = Path(str(filename or "reference.png")).name
        suffix = Path(raw_name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in Path(raw_name).stem).strip("_") or "reference"
        target_name = f"{safe_stem}_{int(time.time())}{suffix}"
        target_path = input_dir / target_name
        encoded = str(data_base64 or "")
        if "," in encoded and encoded.split(",", 1)[0].lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid_reference_image_data") from exc
        if not data:
            raise ValueError("reference_image_empty")
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("reference_image_too_large")
        target_path.write_bytes(data)
        return target_name

    @staticmethod
    def _uds_json_request(
        *,
        socket_path: str,
        method: str,
        path: str,
        body: dict | None = None,
        host: str = "comfyui",
        error_label: str = "comfyui_request_failed",
        timeout_s: float = 10,
    ) -> dict:
        payload = json.dumps(body or {}).encode("utf-8") if body is not None else b""
        headers = [
            f"{method.upper()} {path} HTTP/1.1",
            f"Host: {host}",
            "Connection: close",
        ]
        if body is not None:
            headers.extend(["Content-Type: application/json", f"Content-Length: {len(payload)}"])
        request = ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8") + payload
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout_s)
            client.connect(socket_path)
            client.sendall(request)
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        raw = b"".join(chunks)
        head, _, response_body = raw.partition(b"\r\n\r\n")
        status_line = head.decode("utf-8", errors="replace").splitlines()[0] if head else ""
        if " 2" not in status_line:
            raise ValueError(error_label)
        parsed = json.loads(response_body.decode("utf-8")) if response_body else {}
        return parsed if isinstance(parsed, dict) else {}

    def register_image_generation_template(
        self,
        *,
        template_id: str,
        service_id: str,
        template_name: str | None = None,
        owner_service: str | None = None,
        owner_client_id: str | None = None,
        privacy_class: str = "internal",
        access_scope: str = "service",
        allowed_services: list[str] | None = None,
        allowed_clients: list[str] | None = None,
        allowed_customers: list[str] | None = None,
        template_version: dict | None = None,
        version: str | None = None,
        metadata: dict | None = None,
        status: str = "active",
    ) -> dict:
        state = self.image_generation_template_state_payload().get("state")
        if not isinstance(state, dict):
            raise ValueError("image generation template state store is not configured")
        registration = create_image_generation_template_registration(
            template_id=template_id,
            service_id=service_id,
            version=version,
            template_name=template_name,
            owner_service=owner_service,
            owner_client_id=owner_client_id,
            privacy_class=privacy_class,
            access_scope=access_scope,
            allowed_services=allowed_services,
            allowed_clients=allowed_clients,
            allowed_customers=allowed_customers,
            template_version=template_version,
            metadata=metadata,
            status=status,
        )
        templates = list(state.get("templates") or [])
        normalized_id = registration["template_id"]
        existing_index = next(
            (
                index
                for index, entry in enumerate(templates)
                if isinstance(entry, dict) and str(entry.get("template_id") or "").strip() == normalized_id
            ),
            None,
        )
        if existing_index is None:
            templates.append(registration)
        else:
            existing = dict(templates[existing_index])
            if str(existing.get("status") or "").strip().lower() == "retired":
                templates[existing_index] = registration
            else:
                version_entry = registration["versions"][0]
                existing_versions = list(existing.get("versions") or [])
                existing_versions = [
                    item
                    for item in existing_versions
                    if isinstance(item, dict) and str(item.get("version") or "").strip() != version_entry["version"]
                ]
                existing_versions.append(version_entry)
                existing.update(
                    {
                        "template_name": registration["template_name"],
                        "service_id": registration["service_id"],
                        "owner_service": registration["owner_service"],
                        "owner_client_id": registration["owner_client_id"],
                        "privacy_class": registration["privacy_class"],
                        "access_scope": registration["access_scope"],
                        "allowed_services": registration["allowed_services"],
                        "allowed_clients": registration["allowed_clients"],
                        "allowed_customers": registration["allowed_customers"],
                        "status": registration["status"],
                        "metadata": registration["metadata"],
                        "current_version": version_entry["version"],
                        "versions": existing_versions,
                        "updated_at": self._now_iso(),
                    }
                )
                history = list(existing.get("lifecycle_history") or [])
                history.append({"state": registration["status"], "reason": "version_registered", "changed_at": self._now_iso()})
                existing["lifecycle_history"] = history
                templates[existing_index] = existing
        state["templates"] = templates
        self._save_image_generation_template_state(state)
        return self.image_generation_template_state_payload()

    def update_image_generation_template(
        self,
        *,
        template_id: str,
        template_name: str | None = None,
        owner_service: str | None = None,
        owner_client_id: str | None = None,
        privacy_class: str | None = None,
        access_scope: str | None = None,
        allowed_services: list[str] | None = None,
        allowed_clients: list[str] | None = None,
        allowed_customers: list[str] | None = None,
        template_version: dict | None = None,
        version: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        index = self._image_generation_template_index(template_id=template_id)
        state = self._image_generation_template_state
        templates = list(state.get("templates") or [])
        existing = dict(templates[index])
        for key, value in {
            "template_name": template_name,
            "owner_service": owner_service,
            "owner_client_id": owner_client_id,
            "privacy_class": privacy_class,
            "access_scope": access_scope,
            "allowed_services": allowed_services,
            "allowed_clients": allowed_clients,
            "allowed_customers": allowed_customers,
            "metadata": metadata,
        }.items():
            if value is not None:
                existing[key] = value
        if template_version is not None:
            version_entry = normalize_template_version(template_version, fallback_version=str(version or "").strip() or "v1")
            versions = [
                item
                for item in list(existing.get("versions") or [])
                if isinstance(item, dict) and str(item.get("version") or "").strip() != version_entry["version"]
            ]
            versions.append(version_entry)
            existing["versions"] = versions
            existing["current_version"] = version_entry["version"]
        existing["updated_at"] = self._now_iso()
        templates[index] = existing
        state["templates"] = templates
        self._save_image_generation_template_state(state)
        return self.image_generation_template_state_payload()

    def transition_image_generation_template(self, *, template_id: str, state: str, reason: str | None = None) -> dict:
        index = self._image_generation_template_index(template_id=template_id)
        payload = self._image_generation_template_state
        templates = list(payload.get("templates") or [])
        template = dict(templates[index])
        normalized_state = str(state or "").strip().lower()
        template["status"] = normalized_state
        template["updated_at"] = self._now_iso()
        if normalized_state == "retired":
            template["retired_at"] = self._now_iso()
        history = list(template.get("lifecycle_history") or [])
        history.append({"state": normalized_state, "reason": str(reason or "").strip() or None, "changed_at": self._now_iso()})
        template["lifecycle_history"] = history
        templates[index] = template
        payload["templates"] = templates
        self._save_image_generation_template_state(payload)
        return self.image_generation_template_state_payload()

    def review_image_generation_template(
        self,
        *,
        template_id: str,
        reviewed_by: str | None = None,
        review_reason: str | None = None,
        state: str | None = "active",
    ) -> dict:
        index = self._image_generation_template_index(template_id=template_id)
        payload = self._image_generation_template_state
        templates = list(payload.get("templates") or [])
        template = dict(templates[index])
        normalized_state = str(state or "active").strip().lower()
        template["status"] = normalized_state
        template["last_reviewed_at"] = self._now_iso()
        template["reviewed_by"] = str(reviewed_by or "").strip() or None
        template["review_reason"] = str(review_reason or "").strip() or None
        template["updated_at"] = self._now_iso()
        history = list(template.get("lifecycle_history") or [])
        history.append({"state": normalized_state, "reason": str(review_reason or "review_complete").strip(), "changed_at": self._now_iso()})
        template["lifecycle_history"] = history
        templates[index] = template
        payload["templates"] = templates
        self._save_image_generation_template_state(payload)
        return self.image_generation_template_state_payload()

    def budget_state_payload(self) -> dict:
        if self._budget_manager is None:
            return {"configured": False, "policy_status": "unconfigured", "grant_count": 0, "grants": []}
        return self._budget_manager.status_payload()

    def client_usage_payload(self) -> dict:
        if self._client_usage_store is None or not hasattr(self._client_usage_store, "summary_payload"):
            return {"configured": False, "current_month": local_now_iso()[:7], "clients": []}
        payload = self._client_usage_store.summary_payload()
        return self._attach_client_grants(payload=payload)

    def _attach_client_grants(self, *, payload: dict) -> dict:
        clients = list(payload.get("clients") or []) if isinstance(payload, dict) else []
        budget_state = self.budget_state_payload()
        grants = list(budget_state.get("grants") or []) if isinstance(budget_state, dict) else []
        if not grants:
            governance_bundle = self._governance_bundle_payload()
            governance_budget_policy = {}
            if isinstance(governance_bundle.get("budget_policy"), dict):
                governance_budget_policy = governance_bundle.get("budget_policy") or {}
            elif isinstance(governance_bundle.get("raw_response"), dict):
                raw_response = governance_bundle.get("raw_response") or {}
                nested_bundle = raw_response.get("governance_bundle") if isinstance(raw_response.get("governance_bundle"), dict) else {}
                governance_budget_policy = nested_bundle.get("budget_policy") if isinstance(nested_bundle.get("budget_policy"), dict) else {}
            grants = list(governance_budget_policy.get("grants") or []) if isinstance(governance_budget_policy, dict) else []
        enriched_clients = []
        for client in clients:
            client_payload = dict(client) if isinstance(client, dict) else {}
            customer_id = str(client_payload.get("customer_id") or "").strip()
            client_id = str(client_payload.get("client_id") or "").strip()
            client_payload["grant"] = self._select_client_grant(
                grants=grants,
                customer_id=customer_id or None,
                client_id=client_id or None,
            )
            enriched_clients.append(client_payload)
        return {**(payload if isinstance(payload, dict) else {}), "clients": enriched_clients}

    @staticmethod
    def _select_client_grant(*, grants: list[dict], customer_id: str | None, client_id: str | None) -> dict | None:
        customer_key = str(customer_id or "").strip()
        client_key = str(client_id or "").strip()
        matched = None
        node_scope_grants: list[dict] = []
        for grant in grants:
            if not isinstance(grant, dict):
                continue
            scope_kind = str(grant.get("scope_kind") or "").strip().lower()
            subject_id = str(grant.get("subject_id") or "").strip()
            if scope_kind == "customer" and customer_key and subject_id == customer_key:
                matched = grant
                break
            if scope_kind == "service" and client_key and subject_id == client_key:
                matched = grant
                break
            if scope_kind == "node" and str(grant.get("status") or "").strip().lower() == "active":
                node_scope_grants.append(grant)
        if matched is None:
            matched = node_scope_grants[0] if len(node_scope_grants) == 1 else None
        if matched is None:
            return None
        return {
            "grant_display_name": _short_grant_name(matched.get("grant_id"), scope_kind=matched.get("scope_kind")),
            "grant_name": _mask_grant_name(matched.get("grant_id")),
            "grant_id": matched.get("grant_id"),
            "scope_kind": matched.get("scope_kind"),
            "subject_id": matched.get("subject_id"),
            "valid_from": matched.get("period_start"),
            "valid_to": matched.get("period_end"),
            "status": matched.get("status"),
            "budget_cents": ((matched.get("limits") or {}).get("max_cost_cents") if isinstance(matched.get("limits"), dict) else None),
        }

    def register_prompt_service(
        self,
        *,
        prompt_id: str,
        service_id: str,
        task_family: str,
        metadata: dict | None = None,
        prompt_name: str | None = None,
        owner_service: str | None = None,
        owner_client_id: str | None = None,
        privacy_class: str = "internal",
        access_scope: str = "service",
        allowed_services: list[str] | None = None,
        allowed_clients: list[str] | None = None,
        allowed_customers: list[str] | None = None,
        execution_policy: dict | None = None,
        provider_preferences: dict | None = None,
        constraints: dict | None = None,
        definition: dict | None = None,
        output_contract: dict | None = None,
        benchmark: dict | None = None,
        version: str | None = None,
        status: str = "active",
    ) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        prompt_metadata = _metadata_with_v2_contracts(
            metadata=metadata,
            output_contract=output_contract,
            benchmark=benchmark,
        )
        self._prompt_service_state = self._prompt_registry.create_prompt(
            prompt_id=prompt_id,
            service_id=service_id,
            task_family=task_family,
            metadata=prompt_metadata,
            prompt_name=prompt_name,
            owner_service=owner_service,
            owner_client_id=owner_client_id,
            privacy_class=privacy_class,
            access_scope=access_scope,
            allowed_services=allowed_services,
            allowed_clients=allowed_clients,
            allowed_customers=allowed_customers,
            execution_policy=execution_policy,
            provider_preferences=provider_preferences,
            constraints=constraints,
            definition=definition,
            version=version,
            status=status,
        )
        return self.prompt_service_state_payload()

    def update_prompt_service(
        self,
        *,
        prompt_id: str,
        prompt_name: str | None = None,
        owner_service: str | None = None,
        owner_client_id: str | None = None,
        task_family: str | None = None,
        privacy_class: str | None = None,
        access_scope: str | None = None,
        allowed_services: list[str] | None = None,
        allowed_clients: list[str] | None = None,
        allowed_customers: list[str] | None = None,
        execution_policy: dict | None = None,
        provider_preferences: dict | None = None,
        constraints: dict | None = None,
        metadata: dict | None = None,
        definition: dict | None = None,
        output_contract: dict | None = None,
        benchmark: dict | None = None,
        version: str | None = None,
    ) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        prompt_metadata = _metadata_with_v2_contracts(
            metadata=metadata,
            output_contract=output_contract,
            benchmark=benchmark,
        )
        self._prompt_service_state = self._prompt_registry.update_prompt(
            prompt_id=prompt_id,
            prompt_name=prompt_name,
            owner_service=owner_service,
            owner_client_id=owner_client_id,
            task_family=task_family,
            privacy_class=privacy_class,
            access_scope=access_scope,
            allowed_services=allowed_services,
            allowed_clients=allowed_clients,
            allowed_customers=allowed_customers,
            execution_policy=execution_policy,
            provider_preferences=provider_preferences,
            constraints=constraints,
            metadata=prompt_metadata,
            definition=definition,
            version=version,
        )
        return self.prompt_service_state_payload()

    def get_prompt_service(self, *, prompt_id: str) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        return {"configured": True, "prompt": self._prompt_registry.get_prompt(prompt_id=prompt_id)}

    def transition_prompt_service(self, *, prompt_id: str, state: str, reason: str | None = None) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.transition_prompt(prompt_id=prompt_id, state=state, reason=reason)
        return self.prompt_service_state_payload()

    def update_prompt_probation(self, *, prompt_id: str, action: str, reason: str | None = None) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.update_probation(prompt_id=prompt_id, action=action, reason=reason)
        return self.prompt_service_state_payload()

    def review_prompt_service(
        self,
        *,
        prompt_id: str,
        reviewed_by: str | None = None,
        review_reason: str | None = None,
        state: str | None = "active",
    ) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.review_prompt(
            prompt_id=prompt_id,
            reviewed_by=reviewed_by,
            review_reason=review_reason,
            state=state,
        )
        return self.prompt_service_state_payload()

    def migrate_prompt_services_to_review_due(self, *, reason: str = "policy_migration_review_due") -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        migrated = self._prompt_registry.migrate_all_to_review_due(reason=reason)
        self._prompt_service_state = {
            key: value for key, value in migrated.items() if key != "migration"
        }
        payload = self.prompt_service_state_payload()
        payload["migration"] = migrated.get("migration") if isinstance(migrated, dict) else None
        return payload

    def authorize_execution(
        self,
        *,
        prompt_id: str,
        task_family: str,
        prompt_version: str | None = None,
        requested_by: str | None = None,
        service_id: str | None = None,
        customer_id: str | None = None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        inputs: dict | None = None,
    ) -> dict:
        if self._prompt_registry is not None:
            self._prompt_service_state = self._prompt_registry.snapshot()
        state = self._prompt_service_state if isinstance(self._prompt_service_state, dict) else None
        result = self._execution_gateway.authorize(
            prompt_id=prompt_id,
            task_family=task_family,
            prompt_services_state=state,
            prompt_version=prompt_version,
            requested_by=requested_by,
            service_id=service_id,
            customer_id=customer_id,
            requested_provider=requested_provider,
            requested_model=requested_model,
            inputs=inputs,
        )
        if self._prompt_registry is not None and prompt_id:
            self._prompt_registry.record_authorization(
                prompt_id=prompt_id,
                allowed=result.allowed,
                reason=result.reason,
                used_at=self._now_iso(),
            )
            self._prompt_service_state = self._prompt_registry.snapshot()
        return {
            "allowed": result.allowed,
            "reason": result.reason,
            "prompt_id": result.prompt_id,
            "task_family": result.task_family,
            "prompt_version": result.prompt_version,
            "prompt_state": result.prompt_state,
        }

    def _accepted_capability_profile_payload(self) -> dict:
        payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        accepted = payload.get("accepted_profile") if isinstance(payload, dict) else {}
        return accepted if isinstance(accepted, dict) else {}

    def _governance_bundle_payload(self) -> dict:
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        governance = capability_payload.get("governance_bundle") if isinstance(capability_payload, dict) else None
        if isinstance(governance, dict):
            return governance
        if self._governance_state_store is not None and hasattr(self._governance_state_store, "load"):
            stored = self._governance_state_store.load()
            if isinstance(stored, dict):
                return stored
        return {}

    def _governance_status_payload(self) -> dict:
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        status = capability_payload.get("governance_status") if isinstance(capability_payload, dict) else {}
        return status if isinstance(status, dict) else {}

    def _trust_state_payload(self) -> dict:
        if self._trust_state_store is None or not hasattr(self._trust_state_store, "load"):
            return {}
        payload = self._trust_state_store.load()
        return payload if isinstance(payload, dict) else {}

    def record_request_metrics(self, *, duration_ms: float, status_code: int) -> None:
        if self._runtime_metrics is None:
            return
        self._runtime_metrics.record_request(duration_ms=duration_ms, status_code=status_code)

    def _resource_usage_payload(self) -> dict:
        if self._runtime_metrics is None:
            return {}
        return dict(self._runtime_metrics.snapshot())

    def direct_execution_admission_payload(self) -> dict:
        if self._direct_execution_admission_guard is None:
            return {"configured": False, "enabled": False}
        return self._direct_execution_admission_guard.snapshot()

    def _acquire_execution_admission(self, *, route: str) -> DirectExecutionAdmissionDecision:
        admission = self._direct_execution_admission_guard.try_acquire(route=route)
        if admission.accepted:
            return admission
        payload = self._direct_execution_admission_guard.busy_payload(decision=admission)
        raise DirectExecutionBusyError(
            payload=payload,
            retry_after_seconds=admission.retry_after_seconds,
            status_code=503,
        )

    def _release_execution_admission(self, *, route: str) -> None:
        self._direct_execution_admission_guard.release(route=route)

    def _supervisor_runtime_state_payload(self) -> dict:
        state = self._lifecycle.get_state()
        runtime_state = "starting"
        lifecycle_state = state.value
        health_status = "unknown"
        running = True
        if state == NodeLifecycleState.OPERATIONAL:
            runtime_state = "running"
            lifecycle_state = "running"
            health_status = "healthy"
        elif state == NodeLifecycleState.DEGRADED:
            runtime_state = "running"
            lifecycle_state = "degraded"
            health_status = "unhealthy"
        elif state == NodeLifecycleState.UNCONFIGURED:
            runtime_state = "stopped"
            lifecycle_state = "stopped"
            health_status = "unknown"
            running = False
        return {
            "runtime_state": runtime_state,
            "lifecycle_state": lifecycle_state,
            "health_status": health_status,
            "running": running,
            "desired_state": "running",
        }

    def _supervisor_runtime_payload(self) -> dict:
        trust_state = self._trust_state_payload()
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        node_name = str(trust_state.get("node_name") or node_id or "Hexe AI Node").strip()
        node_type = str(trust_state.get("node_type") or "ai-node").strip() or "ai-node"
        host_id = socket.gethostname()
        state_payload = self._supervisor_runtime_state_payload()
        runtime_metadata = {
            "node_software_version": self._node_software_version,
            "protocol_version": self._protocol_version,
            "startup_mode": self._startup_mode,
            "paired_core_id": str(trust_state.get("paired_core_id") or "").strip() or None,
            "core_api_endpoint": str(trust_state.get("core_api_endpoint") or "").strip() or None,
            "boot_order": 10,
            "node_dependencies": ["mqtt"],
            "services": self.service_status_payload().get("services"),
        }
        return {
            "node_id": node_id,
            "node_name": node_name,
            "node_type": node_type,
            "host_id": host_id,
            "hostname": self._node_hostname or host_id,
            "api_base_url": self._node_api_base_url,
            "ui_base_url": self._node_ui_endpoint,
            **state_payload,
            "resource_usage": self._resource_usage_payload(),
            "runtime_metadata": runtime_metadata,
        }

    def _declared_task_families_payload(self) -> list[str]:
        accepted_profile = self._accepted_capability_profile_payload()
        accepted_families = accepted_profile.get("declared_task_families") if isinstance(accepted_profile, dict) else []
        if isinstance(accepted_families, list) and accepted_families:
            return [str(item).strip() for item in accepted_families if str(item).strip()]
        node_capabilities = self.node_capabilities_payload()
        resolved = (
            node_capabilities.get("enabled_task_capabilities")
            or node_capabilities.get("resolved_tasks")
            or []
        )
        if isinstance(resolved, list) and resolved:
            return [str(item).strip() for item in resolved if str(item).strip()]
        configured = (
            self._task_capability_selection_config.get("selected_task_families")
            if isinstance(self._task_capability_selection_config, dict)
            else []
        )
        return [str(item).strip() for item in configured if str(item).strip()]

    def _get_task_execution_service(self) -> TaskExecutionService:
        if self._task_execution_service is not None:
            return self._task_execution_service
        if self._provider_runtime_manager is None:
            raise ValueError("direct execution is not configured")
        provider_resolver = ProviderResolver(runtime_manager=self._provider_runtime_manager, logger=self._logger)
        telemetry_publisher = None
        if self._node_id:
            telemetry_publisher = ExecutionTelemetryPublisher(
                logger=self._logger,
                node_id=self._node_id,
                trust_state_provider=self._trust_state_payload,
            )
        self._task_execution_service = TaskExecutionService(
            provider_runtime_manager=self._provider_runtime_manager,
            provider_resolver=provider_resolver,
            logger=self._logger,
            budget_manager=self._budget_manager,
            client_usage_store=self._client_usage_store,
            execution_gateway=self._execution_gateway,
            prompt_registry=self._prompt_registry,
            prompt_services_state_provider=lambda: (
                self._prompt_registry.snapshot() if self._prompt_registry is not None else {}
            ),
            declared_task_families_provider=self._declared_task_families_payload,
            accepted_capability_profile_provider=self._accepted_capability_profile_payload,
            governance_bundle_provider=self._governance_bundle_payload,
            governance_status_provider=self._governance_status_payload,
            execution_telemetry_publisher=telemetry_publisher,
        )
        return self._task_execution_service

    async def execute_direct(self, *, request: TaskExecutionRequest) -> dict:
        request = self._resolve_image_generation_template_request(request=request)
        if request.response_mode == "async_if_queued":
            return await self._enqueue_direct_execution(request=request)
        return await self._execute_direct_now(request=request)

    async def preview_direct_execution_route(self, *, request: TaskExecutionRequest) -> dict:
        request_copy = self._resolve_image_generation_template_request(request=request)
        authorization = self._direct_execution_authorization_snapshot(request=request_copy)
        authorization_payload = None
        if authorization is not None:
            authorization_payload = {
                "allowed": bool(authorization.allowed),
                "reason": authorization.reason,
                "prompt_id": authorization.prompt_id,
                "prompt_version": authorization.prompt_version,
                "privacy_class": authorization.privacy_class,
            }
            if not authorization.allowed:
                return {
                    "status": "preview",
                    "dry_run": True,
                    "would_execute": False,
                    "would_queue": False,
                    "task_id": request_copy.task_id,
                    "authorization": authorization_payload,
                    "rejection_reason": authorization.reason,
                    "provider_resolution": None,
                }

        queue_context = await self._direct_execution_queue_context(request=request_copy)
        runtime_assignment = self.local_runtime_assignment_payload(
            task_family=request_copy.task_family,
            priority=queue_context["importance"],
            requested_provider=request_copy.requested_provider,
            requested_model=request_copy.requested_model,
        )
        execution_request = self._execution_request_for_queue_context(request=request_copy, queue_context=queue_context)
        resolution_preview = self._direct_execution_provider_resolution_preview(
            request=execution_request,
            authorization=authorization,
        )
        return {
            "status": "preview",
            "dry_run": True,
            "would_execute": bool(resolution_preview.get("allowed")),
            "would_queue": request_copy.response_mode == "async_if_queued",
            "task_id": request_copy.task_id,
            "response_mode": request_copy.response_mode,
            "queue": queue_context["queue"],
            "importance": queue_context["importance"],
            "routing_decision": queue_context["routing_decision"],
            "local_runtime_assignment": runtime_assignment,
            "effective_request": {
                "requested_provider": execution_request.requested_provider,
                "requested_model": execution_request.requested_model,
                "constraints": execution_request.constraints,
                "timeout_s": execution_request.timeout_s,
            },
            "authorization": authorization_payload,
            "provider_resolution": resolution_preview,
        }

    def _direct_execution_provider_resolution_preview(self, *, request: TaskExecutionRequest, authorization) -> dict:
        service = self._get_task_execution_service()
        governance_status = service._safe_governance_status()  # noqa: SLF001
        if str(governance_status.get("state") or "").strip().lower() == "stale":
            return {"allowed": False, "rejection_reason": "governance_stale", "resolution_metadata": None}
        governance_constraints = service._safe_governance_constraints(request=request)  # noqa: SLF001
        if authorization is not None:
            governance_constraints = service._merge_prompt_governance_constraints(  # noqa: SLF001
                governance_constraints=governance_constraints,
                authorization=authorization,
            )
        effective_timeout_s = service._effective_timeout_s(request=request, authorization=authorization)  # noqa: SLF001
        resolution = service._provider_resolver.resolve(  # noqa: SLF001
            request=ProviderResolutionRequest(
                task_family=request.task_family,
                requested_provider=service._effective_requested_provider(request=request, authorization=authorization),  # noqa: SLF001
                requested_model=service._effective_requested_model(request=request, authorization=authorization),  # noqa: SLF001
                timeout_s=effective_timeout_s,
                max_cost_cents=service._request_max_cost_cents(request=request),  # noqa: SLF001
            ),
            governance_constraints=governance_constraints,
        )
        metadata = service._resolution_metadata(  # noqa: SLF001
            request=request,
            authorization=authorization,
            resolution=resolution,
            governance_constraints=governance_constraints,
            rejection_reason=resolution.rejection_reason,
        )
        return {
            "allowed": bool(resolution.allowed),
            "selected_provider": resolution.provider_id,
            "selected_model": resolution.model_id,
            "provider_order": list(resolution.provider_order),
            "fallback_provider_ids": list(resolution.fallback_provider_ids),
            "model_allowlist_by_provider": dict(resolution.model_allowlist_by_provider),
            "timeout_s": resolution.timeout_s,
            "retry_count": resolution.retry_count,
            "rejection_reason": resolution.rejection_reason,
            "resolution_metadata": metadata,
        }

    async def _execute_direct_now(self, *, request: TaskExecutionRequest) -> dict:
        self._acquire_execution_admission(route="direct")
        try:
            service = self._get_task_execution_service()
            result = await service.execute(request)
            return result.model_dump(mode="json")
        finally:
            self._release_execution_admission(route="direct")

    async def _enqueue_direct_execution(self, *, request: TaskExecutionRequest) -> dict:
        request_copy = self._resolve_image_generation_template_request(request=request)
        queue_context = await self._direct_execution_queue_context(request=request_copy)
        execution_request = self._execution_request_for_queue_context(request=request_copy, queue_context=queue_context)
        response = await self._execution_queue.enqueue(
            queue=queue_context["queue"],
            importance=queue_context["importance"],
            job_name=request_copy.job_name or request_copy.task_id,
            request_payload=execution_request.model_dump(mode="json"),
            runner=lambda: self._execute_direct_now(request=execution_request),
            routing_decision=queue_context.get("routing_decision") if isinstance(queue_context.get("routing_decision"), dict) else None,
            client_id=request_copy.requested_by,
        )
        if response.get("status") != "queued":
            return response
        return {
            **response,
            "message": f"job queued - check in {response['check_after_seconds']} secs",
        }

    async def execution_job_status(self, *, job_id: str) -> dict:
        return await self._execution_queue.job_status(job_id=job_id)

    async def cancel_execution_job(self, *, job_id: str, reason: str | None = None) -> dict:
        return await self._execution_queue.cancel_job(job_id=job_id, reason=reason)

    async def execution_queue_diagnostics(self) -> dict:
        payload = await self._execution_queue.diagnostics()
        if isinstance(payload, dict):
            payload["cpu_comfyui_policy"] = {
                "enabled": True,
                "queue": "cpu_comfyui",
                "runtime_id": "comfyui_cpu",
                "allowed_task_families": ["task.image_generation", "task.generation.image"],
                "allowed_importance": ["background", "low"],
                "rejected_importance": ["normal", "high", "critical"],
            }
        return payload

    def local_runtime_assignments_payload(self) -> dict:
        default_gpu_preset_id = self.comfyui_gpu_presets_payload().get("default_preset_id")
        assignments = [
            self._local_text_runtime_assignment(task_family=task_family)
            for task_family in (
                "task.chat",
                "task.classification",
                "task.information_extraction",
                "task.reasoning",
                "task.structured_extraction",
                "task.summarization",
                "task.summarization.text",
                "task.translation",
            )
        ]
        assignments.extend(
            self._local_vision_runtime_assignment(task_family=task_family)
            for task_family in (
                "task.document_ocr",
                "task.image_description",
                "task.object_detection",
                "task.vision_analysis",
            )
        )
        assignments.extend(
            [
                self._local_gpu_comfyui_assignment(
                    task_family="task.image_generation",
                    importance="normal",
                    default_preset_id=default_gpu_preset_id,
                ),
                self._local_cpu_comfyui_assignment(task_family="task.image_generation", importance="background"),
                self._local_gpu_comfyui_assignment(
                    task_family="task.generation.image",
                    importance="normal",
                    default_preset_id=default_gpu_preset_id,
                ),
                self._local_cpu_comfyui_assignment(task_family="task.generation.image", importance="background"),
            ]
        )
        return {
            "schema_version": "1.0",
            "status": "configured",
            "generated_at": local_now_iso(),
            "default_text_model_id": self._local_text_default_model_id(),
            "default_vision_model_id": self._vision_default_model_id(),
            "assignments": assignments,
        }

    def local_runtime_assignment_payload(
        self,
        *,
        task_family: str,
        priority: str | None = None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
    ) -> dict:
        task_key = str(task_family or "").strip().lower()
        importance = str(priority or "normal").strip().lower()
        if importance not in {"background", "low", "normal", "high", "critical"}:
            importance = "normal"
        provider_key = str(requested_provider or "").strip().lower()
        if provider_key not in {"", "local", "comfyui", "comfyui_gpu", "comfyui_cpu", "local_vision"}:
            return {
                "status": "not_selected",
                "task_family": task_key or None,
                "importance": importance,
                "requested_provider": provider_key or None,
                "reason": "explicit_nonlocal_provider",
            }
        if task_key in {"task.image_generation", "task.generation.image"}:
            if provider_key == "comfyui_cpu" or (importance in {"background", "low"} and provider_key != "comfyui_gpu"):
                return self._local_cpu_comfyui_assignment(task_family=task_key, importance=importance)
            return self._local_gpu_comfyui_assignment(
                task_family=task_key,
                importance=importance,
                default_preset_id=self.comfyui_gpu_presets_payload().get("default_preset_id"),
            )
        if task_key in {"task.document_ocr", "task.image_description", "task.object_detection", "task.vision_analysis"}:
            return self._local_vision_runtime_assignment(task_family=task_key, requested_model=requested_model)
        if task_key in {
            "task.chat",
            "task.classification",
            "task.information_extraction",
            "task.reasoning",
            "task.structured_extraction",
            "task.summarization",
            "task.summarization.text",
            "task.translation",
        }:
            return self._local_text_runtime_assignment(task_family=task_key, requested_model=requested_model)
        return {
            "status": "unassigned",
            "task_family": task_key or None,
            "importance": importance,
            "requested_provider": provider_key or None,
            "reason": "no_local_runtime_assignment",
        }

    def _local_text_runtime_assignment(self, *, task_family: str, requested_model: str | None = None) -> dict:
        model_id = str(requested_model or "").strip() or self._local_text_default_model_id()
        return {
            "status": "selected",
            "task_family": str(task_family or "").strip() or None,
            "runtime_id": "local_text_llm",
            "runtime_kind": "llamacpp_text",
            "provider_id": "local",
            "model_id": model_id,
            "queue": "local",
            "policy": "always_on_text_llm",
            "reason": "text_task_family",
        }

    def _local_vision_runtime_assignment(self, *, task_family: str, requested_model: str | None = None) -> dict:
        model_id = str(requested_model or "").strip() or self._vision_default_model_id()
        return {
            "status": "selected",
            "task_family": str(task_family or "").strip() or None,
            "runtime_id": "local_vision_llm",
            "runtime_kind": "llamacpp_vision",
            "provider_id": "local_vision",
            "model_id": model_id,
            "queue": "local",
            "policy": "vision_runtime_residency",
            "reason": "vision_task_family",
        }

    @staticmethod
    def _local_gpu_comfyui_assignment(*, task_family: str, importance: str, default_preset_id: str | None = None) -> dict:
        return {
            "status": "selected",
            "task_family": str(task_family or "").strip() or None,
            "runtime_id": "comfyui_gpu",
            "runtime_kind": "comfyui_gpu",
            "provider_id": "local_image",
            "checkpoint": "RealVisXL_V5.0_fp16.safetensors",
            "lora": "sdxl_lightning_4step_lora.safetensors",
            "queue": "local",
            "importance": str(importance or "normal").strip().lower() or "normal",
            "default_preset_id": default_preset_id,
            "policy": "interactive_image_gpu",
            "reason": "image_generation_interactive_or_explicit_gpu",
        }

    @staticmethod
    def _local_cpu_comfyui_assignment(*, task_family: str, importance: str) -> dict:
        return {
            "status": "selected",
            "task_family": str(task_family or "").strip() or None,
            "runtime_id": "comfyui_cpu",
            "runtime_kind": "comfyui_cpu",
            "provider_id": "local_image",
            "checkpoint": "DreamShaper8_LCM.safetensors",
            "queue": "cpu_comfyui",
            "importance": str(importance or "background").strip().lower() or "background",
            "policy": "background_image_cpu",
            "reason": "low_priority_background_image",
        }

    @staticmethod
    def _local_text_default_model_id() -> str:
        return (
            str(
                os.environ.get("HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID")
                or os.environ.get("HEXE_LOCAL_LLM_DEFAULT_MODEL_ID")
                or os.environ.get("LLAMACPP_MODEL_ALIAS")
                or LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID
            ).strip()
            or LOCAL_LLM_BUILTIN_DEFAULT_MODEL_ID
        )

    @staticmethod
    def _vision_default_model_id() -> str:
        return (
            str(
                os.environ.get("HEXE_PROVIDER_VISION_DEFAULT_MODEL_ID")
                or os.environ.get("LLAMACPP_VISION_MODEL_ALIAS")
                or VISION_LLM_BUILTIN_DEFAULT_MODEL_ID
            ).strip()
            or VISION_LLM_BUILTIN_DEFAULT_MODEL_ID
        )

    def comfyui_gpu_presets_payload(self) -> dict:
        path = Path(self._comfyui_gpu_presets_config_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "configured": False,
                "runtime_id": "comfyui_gpu",
                "path": str(path),
                "preset_count": 0,
                "presets": [],
                "error": str(exc).strip() or type(exc).__name__,
            }
        normalized = self._normalize_comfyui_gpu_presets(payload=payload, path=path)
        return normalized

    def comfyui_gpu_preset_payload(self, *, preset_id: str) -> dict:
        normalized_id = str(preset_id or "").strip()
        payload = self.comfyui_gpu_presets_payload()
        for preset in list(payload.get("presets") or []):
            if isinstance(preset, dict) and preset.get("id") == normalized_id:
                return {"status": "found", "preset": preset, "catalog": {key: payload.get(key) for key in ("runtime_id", "schema_version", "path")}}
        return {"status": "not_found", "preset_id": normalized_id, "runtime_id": payload.get("runtime_id"), "path": payload.get("path")}

    @staticmethod
    def _normalize_comfyui_gpu_presets(*, payload: dict, path: Path) -> dict:
        presets = []
        base_workflow = payload.get("base_workflow") if isinstance(payload.get("base_workflow"), dict) else {}
        seen_ids: set[str] = set()
        for item in list(payload.get("presets") or []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            preset_id = str(item.get("id") or "").strip()
            if not preset_id or preset_id in seen_ids:
                continue
            seed_mode = str(item.get("seed_mode") or ("random" if item.get("random_seed") else "fixed")).strip().lower()
            if seed_mode not in {"fixed", "random"}:
                seed_mode = "fixed"
            width = NodeControlState._optional_positive_int(item.get("width"))
            height = NodeControlState._optional_positive_int(item.get("height"))
            steps = NodeControlState._optional_positive_int(item.get("steps"))
            batch_size = NodeControlState._optional_positive_int(item.get("batch_size")) or 1
            if width is None or height is None or steps is None:
                continue
            seed = NodeControlState._optional_positive_int(item.get("seed"))
            random_seed = bool(item.get("random_seed")) or seed_mode == "random"
            presets.append(
                {
                    "id": preset_id,
                    "display_name": str(item.get("display_name") or preset_id).strip(),
                    "description": str(item.get("description") or "").strip() or None,
                    "runtime_id": "comfyui_gpu",
                    "checkpoint": str(item.get("checkpoint") or base_workflow.get("checkpoint") or "").strip() or None,
                    "lora": str(item.get("lora") or base_workflow.get("lora") or "").strip() or None,
                    "lora_strength_model": float(item.get("lora_strength_model", base_workflow.get("lora_strength_model", 1.0))),
                    "lora_strength_clip": float(item.get("lora_strength_clip", base_workflow.get("lora_strength_clip", 1.0))),
                    "seed_mode": seed_mode,
                    "seed": None if random_seed else seed,
                    "random_seed": random_seed,
                    "steps": steps,
                    "cfg": float(item.get("cfg", 1.6)),
                    "sampler_name": str(item.get("sampler_name") or "euler").strip(),
                    "scheduler": str(item.get("scheduler") or "sgm_uniform").strip(),
                    "width": width,
                    "height": height,
                    "batch_size": batch_size,
                    "denoise": float(item.get("denoise", 1.0)),
                }
            )
            seen_ids.add(preset_id)
        default_preset_id = str(payload.get("default_preset_id") or "").strip()
        if default_preset_id not in seen_ids and presets:
            default_preset_id = str(presets[0].get("id") or "")
        return {
            "configured": True,
            "schema_version": str(payload.get("schema_version") or "1.0"),
            "runtime_id": str(payload.get("runtime_id") or "comfyui_gpu"),
            "path": str(path),
            "default_preset_id": default_preset_id or None,
            "base_workflow": base_workflow,
            "preset_count": len(presets),
            "presets": presets,
        }

    async def _direct_execution_queue_context(self, *, request: TaskExecutionRequest) -> dict:
        authorization = self._direct_execution_authorization_snapshot(request=request)
        importance = self._direct_execution_importance(request=request, authorization=authorization)
        routing_mode = self._direct_execution_effective_routing_mode(request=request, authorization=authorization)
        cpu_comfyui_policy = self._cpu_comfyui_queue_policy(request=request, importance=importance)
        if cpu_comfyui_policy.get("selected"):
            return {
                "queue": "cpu_comfyui",
                "importance": importance,
                "routing_mode": routing_mode,
                "spillover": False,
                "execution_routing_mode": "local_only",
                "routing_decision": {
                    "original_routing_mode": routing_mode,
                    "execution_routing_mode": "local_only",
                    "selected_queue": "cpu_comfyui",
                    "original_queue": "local",
                    "spillover": False,
                    "reason": "cpu_comfyui_background_image_policy",
                    "cpu_comfyui_policy": cpu_comfyui_policy,
                },
            }
        queue_key = self._direct_execution_queue_kind(
            request=request,
            authorization=authorization,
            routing_mode=routing_mode,
        )
        original_queue = queue_key
        if await self._should_spill_local_preferred_to_cloud(
            request=request,
            importance=importance,
            routing_mode=routing_mode,
            queue_key=queue_key,
        ):
            queue_key = "cloud"
            spillover = True
            reason = "local_preferred_spillover"
        else:
            spillover = False
            reason = self._direct_execution_queue_reason(
                request=request,
                routing_mode=routing_mode,
                queue_key=queue_key,
            )
        execution_routing_mode = self._direct_execution_execution_routing_mode(
            request=request,
            routing_mode=routing_mode,
            queue_key=queue_key,
            spillover=spillover,
        )
        return {
            "queue": queue_key,
            "importance": importance,
            "routing_mode": routing_mode,
            "spillover": spillover,
            "execution_routing_mode": execution_routing_mode,
            "routing_decision": {
                "original_routing_mode": routing_mode,
                "execution_routing_mode": execution_routing_mode,
                "selected_queue": queue_key,
                "original_queue": original_queue,
                "spillover": spillover,
                "reason": reason,
            },
        }

    def _execution_request_for_queue_context(self, *, request: TaskExecutionRequest, queue_context: dict) -> TaskExecutionRequest:
        execution_routing_mode = TaskExecutionService._normalize_routing_policy_mode(queue_context.get("execution_routing_mode"))
        if not execution_routing_mode or execution_routing_mode == queue_context.get("routing_mode"):
            return request
        constraints = dict(request.constraints or {})
        routing_policy = dict(constraints.get("routing_policy") or {})
        routing_policy["mode"] = execution_routing_mode
        constraints["routing_policy"] = routing_policy
        return request.model_copy(update={"constraints": constraints}, deep=True)

    def _resolve_image_generation_template_request(self, *, request: TaskExecutionRequest) -> TaskExecutionRequest:
        task_key = str(request.task_family or "").strip().lower()
        if task_key not in {"task.image_generation", "task.generation.image"} or not request.prompt_id:
            return request.model_copy(deep=True)
        request_constraints = request.constraints if isinstance(request.constraints, dict) else {}
        if isinstance(request_constraints.get("image_template_resolved"), dict):
            return request.model_copy(deep=True)
        authorization = self._direct_execution_authorization_snapshot(request=request)
        if authorization is None or not getattr(authorization, "allowed", False):
            return request.model_copy(deep=True)
        prompt_constraints = authorization.prompt_constraints if isinstance(authorization.prompt_constraints, dict) else {}
        image_template = (
            prompt_constraints.get("image_template")
            if isinstance(prompt_constraints.get("image_template"), dict)
            else None
        )
        if not image_template or not image_template.get("template_id"):
            return request.model_copy(deep=True)

        registration = self._select_registered_image_template(
            template_id=str(image_template.get("template_id") or ""),
            template_version=image_template.get("template_version"),
            template_runtime=image_template.get("template_runtime"),
            request=request,
        )
        catalog_entry = None
        try:
            catalog_entry = self.get_comfyui_template_catalog_entry(template_id=registration["template_id"]).get("template")
        except ValueError:
            catalog_entry = None
        version_entry = dict(registration["selected_version"])
        variables = self._template_variable_names(
            catalog_entry=catalog_entry,
            version_entry=version_entry,
        )
        defaults = {}
        if isinstance(catalog_entry, dict):
            defaults.update(dict(catalog_entry.get("defaults") or {}))
        defaults.update(dict(version_entry.get("defaults") or {}))
        prompt_definition = authorization.prompt_definition if isinstance(authorization.prompt_definition, dict) else {}
        rendered_prompt = render_prompt_template(prompt_definition=prompt_definition, request_inputs=request.inputs)
        resolved_variables = self._resolve_template_variables(
            variables=variables,
            defaults=defaults,
            request_inputs=request.inputs,
            rendered_prompt=rendered_prompt,
            allowed_parameter_overrides=list(image_template.get("allowed_parameter_overrides") or []),
        )
        api_workflow_path = str(version_entry.get("api_workflow_path") or "").strip()
        try:
            api_workflow = json.loads(Path(api_workflow_path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("image_template_api_workflow_not_found") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("image_template_api_workflow_invalid_json") from exc
        resolved_workflow = self._substitute_template_placeholders(api_workflow, variables=resolved_variables)
        request_inputs = dict(request.inputs or {})
        request_inputs["comfyui_workflow"] = resolved_workflow
        request_inputs["comfyui_template_variables"] = resolved_variables
        constraints = dict(request.constraints or {})
        resolved_template = {
            "template_id": registration["template_id"],
            "template_version": version_entry.get("version"),
            "template_runtime": version_entry.get("runtime_id"),
            "api_workflow_path": api_workflow_path,
            "ui_workflow_path": version_entry.get("ui_workflow_path"),
            "output_scope": version_entry.get("output_scope"),
            "output_folder_policy": "operational",
            "variables": resolved_variables,
            "model_requirements": version_entry.get("model_requirements") or {},
            "catalog_template_available": isinstance(catalog_entry, dict),
        }
        constraints["image_template_resolved"] = resolved_template
        return request.model_copy(update={"inputs": request_inputs, "constraints": constraints}, deep=True)

    def _select_registered_image_template(
        self,
        *,
        template_id: str,
        template_version: object,
        template_runtime: object,
        request: TaskExecutionRequest,
    ) -> dict:
        registration = self.get_image_generation_template(template_id=template_id).get("template")
        if not isinstance(registration, dict):
            raise ValueError("image_generation_template_not_found")
        status = str(registration.get("status") or "").strip().lower()
        if status not in {"active", "review_due"}:
            raise ValueError("image_generation_template_state_invalid")
        if not self._registered_image_template_access_allowed(registration=registration, request=request):
            raise ValueError("image_generation_template_access_denied")
        selected_version = str(template_version or registration.get("current_version") or "").strip()
        versions = [item for item in list(registration.get("versions") or []) if isinstance(item, dict)]
        version_entry = next(
            (item for item in versions if str(item.get("version") or "").strip() == selected_version),
            None,
        )
        if version_entry is None:
            raise ValueError("image_generation_template_version_not_found")
        runtime = str(template_runtime or "").strip()
        if runtime and runtime != str(version_entry.get("runtime_id") or "").strip():
            raise ValueError("image_generation_template_runtime_mismatch")
        return {**registration, "selected_version": version_entry}

    @staticmethod
    def _registered_image_template_access_allowed(*, registration: dict, request: TaskExecutionRequest) -> bool:
        access_scope = str(registration.get("access_scope") or "service").strip().lower()
        requested_by = str(request.requested_by or "").strip()
        service_id = str(request.service_id or request.requested_by or "").strip()
        customer_id = str(request.customer_id or "").strip()
        owner_client_id = str(registration.get("owner_client_id") or "").strip()
        owner_service = str(registration.get("owner_service") or registration.get("service_id") or "").strip()
        if access_scope == "public":
            return True
        if access_scope == "private":
            return bool(owner_client_id and requested_by == owner_client_id)
        if access_scope == "service":
            return bool(owner_service and service_id == owner_service)
        if access_scope == "shared":
            return (
                service_id in {str(item or "").strip() for item in list(registration.get("allowed_services") or [])}
                or requested_by in {str(item or "").strip() for item in list(registration.get("allowed_clients") or [])}
                or customer_id in {str(item or "").strip() for item in list(registration.get("allowed_customers") or [])}
            )
        return False

    @staticmethod
    def _template_variable_names(*, catalog_entry: dict | None, version_entry: dict) -> list[dict]:
        if isinstance(catalog_entry, dict) and isinstance(catalog_entry.get("variables"), list):
            return [
                item
                for item in list(catalog_entry.get("variables") or [])
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
        return [
            {"name": str(item or "").strip(), "required": False, "default": None}
            for item in list(version_entry.get("variables") or [])
            if str(item or "").strip()
        ]

    @staticmethod
    def _resolve_template_variables(
        *,
        variables: list[dict],
        defaults: dict,
        request_inputs: dict,
        rendered_prompt: str | None,
        allowed_parameter_overrides: list[str],
    ) -> dict:
        values = dict(defaults or {})
        allowed_overrides = {str(item or "").strip() for item in allowed_parameter_overrides if str(item or "").strip()}
        variable_names = {str(item.get("name") or "").strip() for item in variables}
        for variable in variables:
            name = str(variable.get("name") or "").strip()
            if not name:
                continue
            if name in request_inputs:
                values[name] = request_inputs[name]
            elif name == "positive_prompt" and rendered_prompt is not None:
                values[name] = rendered_prompt
            elif name == "positive_prompt" and request_inputs.get("prompt") is not None:
                values[name] = request_inputs.get("prompt")
            elif "default" in variable and variable.get("default") is not None and name not in values:
                values[name] = variable.get("default")
            if bool(variable.get("required")) and values.get(name) in (None, ""):
                raise ValueError(f"image_template_variable_required:{name}")
        for name in allowed_overrides:
            if name in request_inputs:
                values[name] = request_inputs[name]
        return {key: value for key, value in values.items() if key in variable_names or key in allowed_overrides}

    @classmethod
    def _substitute_template_placeholders(cls, value, *, variables: dict):
        if isinstance(value, dict):
            return {key: cls._substitute_template_placeholders(item, variables=variables) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._substitute_template_placeholders(item, variables=variables) for item in value]
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{{") and text.endswith("}}") and text.count("{{") == 1 and text.count("}}") == 1:
                key = text[2:-2].strip()
                return variables.get(key)
            rendered = value
            for key, item in variables.items():
                rendered = rendered.replace("{{" + key + "}}", "" if item is None else str(item))
            return rendered
        return value

    def _direct_execution_authorization_snapshot(self, *, request: TaskExecutionRequest):
        if not request.prompt_id:
            return None
        try:
            return self._execution_gateway.authorize(
                prompt_id=request.prompt_id,
                task_family=request.task_family,
                prompt_services_state=self._prompt_registry.snapshot() if self._prompt_registry is not None else {},
                prompt_version=request.prompt_version,
                requested_by=request.requested_by,
                service_id=request.service_id,
                customer_id=request.customer_id,
                requested_provider=request.requested_provider,
                requested_model=request.requested_model,
                inputs=request.inputs,
            )
        except Exception:
            return None

    def _direct_execution_queue_kind(self, *, request: TaskExecutionRequest, authorization, routing_mode: str | None = None) -> str:
        requested_provider = str(request.requested_provider or "").strip().lower()
        if requested_provider == "local":
            return "local"
        if requested_provider and requested_provider != "local":
            return "cloud"

        capability_queue = self._direct_execution_task_capability_queue(request=request)
        if routing_mode in {"local_only", "local_preferred"}:
            if routing_mode == "local_preferred" and capability_queue == "cloud":
                return "cloud"
            return "local"
        if routing_mode in {"cloud_only", "cloud_fallback"}:
            if routing_mode == "cloud_fallback" and capability_queue == "local":
                return "local"
            return "cloud"

        request_constraints = request.constraints if isinstance(request.constraints, dict) else {}
        request_routing = request_constraints.get("routing_policy") if isinstance(request_constraints.get("routing_policy"), dict) else {}
        request_mode = TaskExecutionService._normalize_routing_policy_mode(
            request_routing.get("mode") if isinstance(request_routing, dict) else None
        )
        if request_mode in {"local_only", "local_preferred"}:
            if request_mode == "local_preferred" and capability_queue == "cloud":
                return "cloud"
            return "local"
        if request_mode in {"cloud_only", "cloud_fallback"}:
            if request_mode == "cloud_fallback" and capability_queue == "local":
                return "local"
            return "cloud"
        prompt_constraints = authorization.prompt_constraints if authorization is not None and isinstance(authorization.prompt_constraints, dict) else {}
        prompt_routing = prompt_constraints.get("routing_policy") if isinstance(prompt_constraints.get("routing_policy"), dict) else {}
        prompt_mode = TaskExecutionService._normalize_routing_policy_mode(
            prompt_routing.get("mode") if isinstance(prompt_routing, dict) else None
        )
        if prompt_mode in {"local_only", "local_preferred"}:
            if prompt_mode == "local_preferred" and capability_queue == "cloud":
                return "cloud"
            return "local"
        if prompt_mode in {"cloud_only", "cloud_fallback"}:
            if prompt_mode == "cloud_fallback" and capability_queue == "local":
                return "local"
            return "cloud"

        if capability_queue:
            return capability_queue

        provider_preferences = authorization.provider_preferences if authorization is not None and isinstance(authorization.provider_preferences, dict) else {}
        default_provider = str(provider_preferences.get("default_provider") or "").strip().lower()
        return "local" if default_provider == "local" else "cloud"

    def _direct_execution_execution_routing_mode(
        self,
        *,
        request: TaskExecutionRequest,
        routing_mode: str | None,
        queue_key: str,
        spillover: bool,
    ) -> str | None:
        if spillover:
            return "cloud_only"
        if queue_key == "cpu_comfyui":
            return "local_only"
        capability_queue = self._direct_execution_task_capability_queue(request=request)
        if capability_queue == "local" and queue_key == "local" and routing_mode in {None, "cloud_fallback"}:
            return "local_only"
        if capability_queue == "cloud" and queue_key == "cloud" and routing_mode in {None, "local_preferred"}:
            return "cloud_only"
        return routing_mode

    def _direct_execution_task_capability_queue(self, *, request: TaskExecutionRequest) -> str | None:
        task_family = str(request.task_family or "").strip()
        if not task_family:
            return None
        node_capabilities = self.node_capabilities_payload()
        provider_capabilities = (
            node_capabilities.get("provider_capabilities")
            if isinstance(node_capabilities.get("provider_capabilities"), dict)
            else {}
        )
        if not provider_capabilities:
            return None
        local_has_task = self._provider_capability_has_task(
            provider_capabilities=provider_capabilities,
            provider_id="local",
            task_family=task_family,
        )
        cloud_has_task = any(
            self._provider_capability_has_task(
                provider_capabilities=provider_capabilities,
                provider_id=str(provider_id or ""),
                task_family=task_family,
            )
            for provider_id in provider_capabilities.keys()
            if str(provider_id or "").strip().lower() != "local"
        )
        if local_has_task and not cloud_has_task:
            return "local"
        if cloud_has_task and not local_has_task:
            return "cloud"
        return None

    @staticmethod
    def _provider_capability_has_task(*, provider_capabilities: dict, provider_id: str, task_family: str) -> bool:
        provider_key = str(provider_id or "").strip().lower()
        task_key = str(task_family or "").strip()
        if not provider_key or not task_key:
            return False
        payload = provider_capabilities.get(provider_key)
        if not isinstance(payload, dict):
            return False
        resolved = payload.get("enabled_task_capabilities") or payload.get("resolved_tasks") or []
        if not isinstance(resolved, list):
            return False
        return task_key in {str(item or "").strip() for item in resolved if str(item or "").strip()}

    @staticmethod
    def _direct_execution_importance(*, request: TaskExecutionRequest, authorization) -> str:
        prompt_level = TaskExecutionService._prompt_importance_level(authorization=authorization)
        if prompt_level:
            return prompt_level
        priority = str(request.priority or "normal").strip().lower()
        return priority if priority in {"background", "low", "normal", "high"} else "normal"

    def _direct_execution_queue_reason(self, *, request: TaskExecutionRequest, routing_mode: str | None, queue_key: str) -> str:
        requested_provider = str(request.requested_provider or "").strip().lower()
        if requested_provider:
            return "explicit_provider"
        capability_queue = self._direct_execution_task_capability_queue(request=request)
        if capability_queue == queue_key and routing_mode in {None, "local_preferred", "cloud_fallback"}:
            return f"task_capability_{queue_key}"
        if routing_mode:
            return f"routing_policy_{routing_mode}"
        return "provider_default_local" if queue_key == "local" else "provider_default_cloud"

    @staticmethod
    def _cpu_comfyui_queue_policy(*, request: TaskExecutionRequest, importance: str) -> dict:
        task_family = str(request.task_family or "").strip().lower()
        is_image_generation = task_family in {"task.image_generation", "task.generation.image"}
        importance_key = str(importance or "normal").strip().lower()
        priority_allowed = importance_key in {"background", "low"}
        requested_provider = str(request.requested_provider or "").strip().lower()
        provider_allowed = requested_provider in {"", "local", "comfyui", "comfyui_cpu"}
        selected = bool(is_image_generation and priority_allowed and provider_allowed)
        reason = "eligible"
        if not is_image_generation:
            reason = "not_image_generation"
        elif not priority_allowed:
            reason = "priority_not_low_or_background"
        elif not provider_allowed:
            reason = "explicit_nonlocal_provider"
        return {
            "selected": selected,
            "runtime_id": "comfyui_cpu",
            "queue": "cpu_comfyui",
            "task_family": task_family or None,
            "importance": importance_key,
            "allowed_importance": ["background", "low"],
            "reason": reason,
        }

    @staticmethod
    def _direct_execution_effective_routing_mode(*, request: TaskExecutionRequest, authorization) -> str | None:
        request_constraints = request.constraints if isinstance(request.constraints, dict) else {}
        request_routing = request_constraints.get("routing_policy") if isinstance(request_constraints.get("routing_policy"), dict) else {}
        request_mode = TaskExecutionService._normalize_routing_policy_mode(
            request_routing.get("mode") if isinstance(request_routing, dict) else None
        )
        prompt_constraints = authorization.prompt_constraints if authorization is not None and isinstance(authorization.prompt_constraints, dict) else {}
        prompt_routing = prompt_constraints.get("routing_policy") if isinstance(prompt_constraints.get("routing_policy"), dict) else {}
        prompt_mode = TaskExecutionService._normalize_routing_policy_mode(
            prompt_routing.get("mode") if isinstance(prompt_routing, dict) else None
        )
        privacy_mode = TaskExecutionService._authorization_privacy_routing_mode(authorization=authorization)
        effective_prompt_mode, prompt_privacy_conflict = TaskExecutionService._merge_routing_policy_modes(
            prompt_mode=privacy_mode,
            request_mode=prompt_mode,
        )
        effective_mode, conflict = TaskExecutionService._merge_routing_policy_modes(
            prompt_mode=effective_prompt_mode,
            request_mode=request_mode,
        )
        if prompt_privacy_conflict or conflict:
            return None
        return effective_mode

    async def _should_spill_local_preferred_to_cloud(
        self,
        *,
        request: TaskExecutionRequest,
        importance: str,
        routing_mode: str | None,
        queue_key: str,
    ) -> bool:
        if not self._local_preferred_spillover_enabled:
            return False
        if queue_key != "local" or routing_mode != "local_preferred":
            return False
        if str(request.requested_provider or "").strip():
            return False
        importance_key = str(importance or "normal").strip().lower()
        if importance_key not in {"critical", "high"}:
            return False
        pressure = await self._execution_queue.queue_pressure(queue="local")
        threshold = (
            self._local_preferred_spillover_critical_pending
            if importance_key == "critical"
            else self._local_preferred_spillover_high_pending
        )
        if int(pressure.get("pending_count") or 0) < threshold:
            return False
        return self._cloud_execution_queue_available(request=request)

    def _cloud_execution_queue_available(self, *, request: TaskExecutionRequest) -> bool:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "provider_selection_context_payload"):
            return False
        try:
            context = self._provider_runtime_manager.provider_selection_context_payload()
        except Exception:
            return False
        enabled = {str(item or "").strip().lower() for item in list(context.get("enabled_providers") or [])}
        usable_by_provider = context.get("usable_models_by_provider") if isinstance(context.get("usable_models_by_provider"), dict) else {}
        available_by_provider = context.get("available_models_by_provider") if isinstance(context.get("available_models_by_provider"), dict) else {}
        health_by_provider = context.get("provider_health") if isinstance(context.get("provider_health"), dict) else {}
        provider_budget_limits = context.get("provider_budget_limits") if isinstance(context.get("provider_budget_limits"), dict) else {}
        request_max_cost_cents = TaskExecutionService._request_max_cost_cents(request=request)
        for provider_id in enabled:
            if not provider_id or provider_id == "local":
                continue
            availability = str((health_by_provider.get(provider_id) or {}).get("availability") or "").strip().lower()
            if availability and availability not in {"available", "degraded"}:
                continue
            models = list(usable_by_provider.get(provider_id) or available_by_provider.get(provider_id) or [])
            if not any(str(model_id or "").strip() for model_id in models):
                continue
            if not self._cloud_provider_budget_allows_spillover(
                provider_id=provider_id,
                request_max_cost_cents=request_max_cost_cents,
                provider_budget_limits=provider_budget_limits,
            ):
                continue
            return True
        return False

    def _cloud_provider_budget_allows_spillover(
        self,
        *,
        provider_id: str,
        request_max_cost_cents: int | None,
        provider_budget_limits: dict,
    ) -> bool:
        budget_limit = provider_budget_limits.get(provider_id) if isinstance(provider_budget_limits, dict) else None
        if request_max_cost_cents is not None and isinstance(budget_limit, dict):
            max_cost = self._optional_int(budget_limit.get("max_cost_cents"))
            if max_cost is not None and int(request_max_cost_cents) > max_cost:
                return False
        budget_state = self.budget_state_payload()
        provider_budgets = budget_state.get("provider_budgets") if isinstance(budget_state, dict) else []
        if isinstance(provider_budgets, list):
            for item in provider_budgets:
                if not isinstance(item, dict):
                    continue
                if str(item.get("provider_id") or "").strip().lower() != provider_id:
                    continue
                remaining = self._optional_int(item.get("remaining_cost_cents"))
                if remaining is not None and remaining <= 0:
                    return False
                if request_max_cost_cents is not None and remaining is not None and int(request_max_cost_cents) > remaining:
                    return False
                return True
        return True

    @staticmethod
    def _optional_int(value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_positive_int(value) -> int | None:
        parsed = NodeControlState._optional_int(value)
        if parsed is None or parsed <= 0:
            return None
        return parsed

    @staticmethod
    def _client_ai_v2_schema_dir() -> Path:
        configured = str(os.environ.get("HEXE_CLIENT_AI_V2_SCHEMA_DIR") or "").strip()
        if configured:
            return Path(configured)
        return Path(__file__).resolve().parents[3] / "docs/json-schemas/client-ai-v2"

    def client_ai_v2_schema_catalog(self) -> dict:
        schema_dir = self._client_ai_v2_schema_dir()
        schemas = []
        if schema_dir.exists():
            for path in sorted(schema_dir.glob("*.json")):
                schemas.append(
                    {
                        "name": path.name,
                        "schema_id": f"https://hexe.local/schemas/client-ai-v2/{path.name}",
                        "status": "Partially implemented",
                        "path": str(path),
                        "api_path": f"/api/schemas/client-ai/v2/{path.name}",
                    }
                )
        return {
            "schema_family": "client-ai",
            "version": "v2",
            "generated_at": local_now_iso(),
            "schemas": schemas,
        }

    def client_ai_v2_schema_document(self, *, schema_name: str) -> dict:
        normalized = str(schema_name or "").strip()
        if not normalized or "/" in normalized or "\\" in normalized or not normalized.endswith(".json"):
            raise ValueError("schema_not_found")
        path = self._client_ai_v2_schema_dir() / normalized
        if not path.exists() or not path.is_file():
            raise ValueError("schema_not_found")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("schema_invalid") from exc
        return payload if isinstance(payload, dict) else {}

    def client_ai_v2_communication_markdown(self) -> str:
        path = self._client_ai_v2_schema_dir() / "communication.md"
        if not path.exists() or not path.is_file():
            raise ValueError("schema_guide_not_found")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _parse_output_payload(output_text: object, *, expected_schema: dict | None = None):
        text = str(output_text or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, dict) and isinstance(expected_schema, dict):
            return NodeControlState._unwrap_structured_output_payload(parsed, expected_schema=expected_schema)
        return parsed

    @staticmethod
    def _unwrap_structured_output_payload(parsed: dict, *, expected_schema: dict):
        if not isinstance(parsed, dict):
            return parsed
        wrapper_name = str(parsed.get("name") or parsed.get("function") or "").strip()
        if not wrapper_name:
            return parsed
        wrapper_payload = parsed.get("parameters") if isinstance(parsed.get("parameters"), (dict, str)) else parsed.get("arguments")
        if isinstance(wrapper_payload, str):
            try:
                wrapper_payload = json.loads(wrapper_payload)
            except Exception:
                return parsed
        if not isinstance(wrapper_payload, dict):
            return parsed

        required_fields = expected_schema.get("required") if isinstance(expected_schema.get("required"), list) else []
        required = {str(item) for item in required_fields if str(item or "").strip()}
        if not required:
            return parsed
        if required.issubset(set(wrapper_payload.keys())):
            return wrapper_payload
        return parsed

    async def _ensure_local_benchmark_model(self, *, model_id: str) -> dict:
        if self._local_llm_switch_lock.locked():
            raise LocalLlmBusyError("local LLM runtime is busy loading another benchmark model")
        async with self._local_llm_switch_lock:
            return await asyncio.to_thread(self._service_manager.ensure_local_llm_model, model_id=model_id)

    async def execute_benchmark_v2(
        self,
        *,
        benchmark_id: str,
        prompt_id: str | None,
        prompt_version: str | None,
        task_family: str,
        requested_by: str,
        service_id: str | None,
        customer_id: str | None,
        inputs: dict,
        output_contract: dict | None,
        targets: list[dict],
        timeout_s: int,
        trace_id: str,
        metadata: dict | None = None,
    ) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "execute_explicit"):
            raise ValueError("provider runtime manager is not configured")
        target_specs = [item for item in list(targets or []) if isinstance(item, dict)]
        if not target_specs:
            raise ValueError("targets_required")

        self._acquire_execution_admission(route="benchmark")
        try:
            inputs_payload = inputs if isinstance(inputs, dict) else {}
            output_payload = output_contract if isinstance(output_contract, dict) else {}
            schema = output_payload.get("json_schema") if isinstance(output_payload.get("json_schema"), dict) else None
            execution_inputs = dict(inputs_payload)
            if schema is not None and "json_schema" not in execution_inputs and "structured_output_schema" not in execution_inputs:
                execution_inputs["json_schema"] = schema

            prompt_definition = {}
            authorized_version = prompt_version
            if prompt_id:
                if self._prompt_registry is not None:
                    self._prompt_service_state = self._prompt_registry.snapshot()
                state = self._prompt_service_state if isinstance(self._prompt_service_state, dict) else None
                authorization = self._execution_gateway.authorize(
                    prompt_id=prompt_id,
                    task_family=task_family,
                    prompt_services_state=state,
                    prompt_version=prompt_version,
                    requested_by=requested_by,
                    service_id=service_id,
                    customer_id=customer_id,
                    inputs=execution_inputs,
                )
                if not authorization.allowed:
                    raise ValueError(authorization.reason)
                prompt_definition = authorization.prompt_definition if isinstance(authorization.prompt_definition, dict) else {}
                authorized_version = authorization.prompt_version

            prompt = render_prompt_template(prompt_definition=prompt_definition, request_inputs=execution_inputs)
            if prompt is None:
                prompt = execution_inputs.get("prompt")
            if prompt is None:
                prompt = execution_inputs.get("text")
            system_prompt = execution_inputs.get("system_prompt")
            if system_prompt is None:
                system_prompt = prompt_definition.get("system_prompt")
            messages = execution_inputs.get("messages") if isinstance(execution_inputs.get("messages"), list) else []
            temperature = execution_inputs.get("temperature")
            max_tokens = execution_inputs.get("max_tokens")

            results = []
            for target in target_specs:
                provider_id = str(target.get("provider") or target.get("provider_id") or "").strip().lower()
                model_id = str(target.get("model") or target.get("model_id") or "").strip() or None
                if not provider_id and model_id and hasattr(self._service_manager, "is_local_llm_model"):
                    try:
                        if self._service_manager.is_local_llm_model(model_id=model_id):
                            provider_id = "local"
                    except Exception:
                        provider_id = ""
                target_id = str(target.get("target_id") or f"{provider_id}:{model_id or 'default'}").strip()
                role = str(target.get("role") or "candidate").strip() or "candidate"
                if not provider_id:
                    results.append(
                        {
                            "target_id": target_id or None,
                            "provider": provider_id,
                            "model": model_id,
                            "role": role,
                            "status": "failed",
                            "output_text": None,
                            "parsed_output": None,
                            "usage": None,
                            "latency_ms": None,
                            "cost_usd": None,
                            "runtime_metrics": None,
                            "error": {"code": "provider_required", "message": "provider_required"},
                        }
                    )
                    continue
                if prompt_id:
                    state = self._prompt_service_state if isinstance(self._prompt_service_state, dict) else None
                    target_authorization = self._execution_gateway.authorize(
                        prompt_id=prompt_id,
                        task_family=task_family,
                        prompt_services_state=state,
                        prompt_version=authorized_version,
                        requested_by=requested_by,
                        service_id=service_id,
                        customer_id=customer_id,
                        requested_provider=provider_id,
                        requested_model=model_id,
                        inputs=execution_inputs,
                    )
                    if not target_authorization.allowed:
                        results.append(
                            {
                                "target_id": target_id,
                                "provider": provider_id,
                                "model": model_id,
                                "role": role,
                                "status": "failed",
                                "output_text": None,
                                "parsed_output": None,
                                "usage": None,
                                "latency_ms": None,
                                "cost_usd": None,
                                "runtime_metrics": None,
                                "error": {"code": target_authorization.reason, "message": target_authorization.reason},
                            }
                        )
                        continue
                runtime_metrics = None
                started = time.perf_counter()
                try:
                    if provider_id == "local" and model_id and hasattr(self._service_manager, "ensure_local_llm_model"):
                        switch_result = await self._ensure_local_benchmark_model(model_id=model_id)
                        runtime_metrics = {
                            "vram_used_mib": None,
                            "vram_delta_mib": None,
                            "gpu_util_percent": None,
                            "load_seconds": switch_result.get("load_seconds") if isinstance(switch_result, dict) else None,
                        }
                    started = time.perf_counter()
                    response = await self._provider_runtime_manager.execute_explicit(
                        UnifiedExecutionRequest(
                            task_family=task_family,
                            prompt=str(prompt or "") if prompt is not None else None,
                            system_prompt=str(system_prompt or "") if system_prompt is not None else None,
                            messages=list(messages or []),
                            requested_provider=provider_id,
                            requested_model=model_id,
                            temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
                            max_tokens=int(max_tokens) if isinstance(max_tokens, int) else None,
                            metadata={
                                "benchmark": True,
                                "benchmark_id": benchmark_id,
                                "trace_id": trace_id,
                                "prompt_id": prompt_id,
                                "prompt_version": authorized_version,
                                "structured_output_schema": schema,
                                **(metadata if isinstance(metadata, dict) else {}),
                            },
                        )
                    )
                    parsed_output = (
                        self._parse_output_payload(response.output_text, expected_schema=schema)
                        if output_payload.get("parse_json_output", True)
                        else None
                    )
                    results.append(
                        {
                            "target_id": target_id,
                            "provider": response.provider_id,
                            "model": response.model_id,
                            "role": role,
                            "status": "completed",
                            "output_text": response.output_text,
                            "parsed_output": parsed_output,
                            "usage": response.usage.model_dump(mode="json"),
                            "latency_ms": response.latency_ms,
                            "total_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                            "cost_usd": response.estimated_cost,
                            "runtime_metrics": runtime_metrics,
                            "error": None,
                        }
                    )
                except LocalLlmBusyError as exc:
                    message = str(exc).strip() or "local LLM runtime is busy"
                    results.append(
                        {
                            "target_id": target_id,
                            "provider": provider_id,
                            "model": model_id,
                            "role": role,
                            "status": "failed",
                            "output_text": None,
                            "parsed_output": None,
                            "usage": None,
                            "latency_ms": None,
                            "total_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                            "cost_usd": None,
                            "runtime_metrics": runtime_metrics,
                            "error": {
                                "code": "local_llm_busy",
                                "message": message,
                                "retryable": True,
                            },
                        }
                    )
                except Exception as exc:
                    message = str(exc).strip() or type(exc).__name__
                    results.append(
                        {
                            "target_id": target_id,
                            "provider": provider_id,
                            "model": model_id,
                            "role": role,
                            "status": "failed",
                            "output_text": None,
                            "parsed_output": None,
                            "usage": None,
                            "latency_ms": None,
                            "total_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                            "cost_usd": None,
                            "runtime_metrics": None,
                            "error": {"code": "execution_failed", "message": message},
                        }
                    )
            return {
                "benchmark_id": str(benchmark_id or "").strip(),
                "prompt_id": str(prompt_id or "").strip() or None,
                "prompt_version": authorized_version,
                "task_family": task_family,
                "trace_id": trace_id,
                "generated_at": local_now_iso(),
                "results": results,
            }
        finally:
            self._release_execution_admission(route="benchmark")

    async def compare_provider_execution(
        self,
        *,
        task_family: str,
        prompt: str | None,
        system_prompt: str | None,
        messages: list[dict] | None,
        providers: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "execute_explicit"):
            raise ValueError("provider runtime manager is not configured")
        provider_specs = [item for item in list(providers or []) if isinstance(item, dict)]
        if not provider_specs:
            raise ValueError("providers_required")
        self._acquire_execution_admission(route="compare")
        try:
            results = []
            for provider_spec in provider_specs:
                provider_id = str(provider_spec.get("provider") or provider_spec.get("provider_id") or "").strip().lower()
                model_id = str(provider_spec.get("model") or provider_spec.get("model_id") or "").strip() or None
                if not provider_id:
                    results.append({"status": "failed", "error": "provider_required"})
                    continue
                started = time.perf_counter()
                try:
                    response = await self._provider_runtime_manager.execute_explicit(
                        UnifiedExecutionRequest(
                            task_family=task_family,
                            prompt=prompt,
                            system_prompt=system_prompt,
                            messages=list(messages or []),
                            requested_provider=provider_id,
                            requested_model=model_id,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            metadata={"comparison": True},
                        )
                    )
                    results.append(
                        {
                            "provider": response.provider_id,
                            "model": response.model_id,
                            "status": "completed",
                            "latency_ms": response.latency_ms,
                            "total_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                            "output_text": response.output_text,
                            "usage": response.usage.model_dump(mode="json"),
                            "estimated_cost": response.estimated_cost,
                            "finish_reason": response.finish_reason,
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "provider": provider_id,
                            "model": model_id,
                            "status": "failed",
                            "latency_ms": None,
                            "total_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                            "output_text": None,
                            "usage": None,
                            "estimated_cost": None,
                            "error": str(exc).strip() or type(exc).__name__,
                        }
                    )
            return {
                "status": "completed",
                "task_family": task_family,
                "results": results,
                "generated_at": local_now_iso(),
            }
        finally:
            self._release_execution_admission(route="compare")

    async def refresh_budget_policy(self) -> dict:
        if self._budget_manager is None:
            raise ValueError("budget manager is not configured")
        return await self._budget_manager.refresh_policy_from_core(
            trust_state=self._trust_state_payload(),
            governance_bundle=self._governance_bundle_payload(),
        )

    @staticmethod
    def _build_budget_declaration_available_models(report: dict | None, provider_id: str) -> list[dict]:
        if not isinstance(report, dict):
            return []
        normalized_provider_id = str(provider_id or "").strip().lower()
        providers = report.get("providers") if isinstance(report.get("providers"), list) else []
        for provider_entry in providers:
            if not isinstance(provider_entry, dict):
                continue
            entry_provider_id = str(provider_entry.get("provider") or provider_entry.get("provider_id") or "").strip().lower()
            if entry_provider_id != normalized_provider_id:
                continue
            available_models = []
            for model_entry in provider_entry.get("models") or []:
                if not isinstance(model_entry, dict):
                    continue
                model_id = str(model_entry.get("id") or model_entry.get("model_id") or "").strip()
                if not model_id:
                    continue
                status = str(model_entry.get("status") or "available").strip().lower()
                if status not in {"available", "degraded"}:
                    continue
                payload = {"model_id": model_id}
                pricing = model_entry.get("pricing")
                if isinstance(pricing, dict):
                    payload["pricing"] = pricing
                latency_metrics = model_entry.get("latency_metrics")
                if isinstance(latency_metrics, dict):
                    payload["latency_metrics"] = latency_metrics
                available_models.append(payload)
            return available_models
        return []

    def _provider_capability_report_payload(self) -> dict:
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        report = capability_payload.get("provider_capability_report") if isinstance(capability_payload, dict) else {}
        return report if isinstance(report, dict) else {}

    def _build_budget_declaration_payload(self, *, provider_id: str) -> dict:
        provider_payload = self.provider_selection_payload()
        providers = provider_payload.get("config", {}).get("providers") if isinstance(provider_payload, dict) else {}
        enabled_providers = providers.get("enabled") if isinstance(providers, dict) else []
        budget_limits = providers.get("budget_limits") if isinstance(providers, dict) else {}
        normalized_provider_id = str(provider_id or "").strip().lower()
        if normalized_provider_id not in [str(item).strip().lower() for item in (enabled_providers or [])]:
            raise ValueError(f"{normalized_provider_id} must be enabled before declaring budget")
        provider_budget = budget_limits.get(normalized_provider_id) if isinstance(budget_limits, dict) else None
        if not isinstance(provider_budget, dict):
            raise ValueError(f"{normalized_provider_id} budget must be saved before declaring to Core")
        max_cost_cents = provider_budget.get("max_cost_cents")
        if not isinstance(max_cost_cents, int) or max_cost_cents <= 0:
            raise ValueError(f"{normalized_provider_id} budget must be a positive whole number of cents")
        period = str(provider_budget.get("period") or "monthly").strip().lower()
        if period not in {"weekly", "monthly"}:
            raise ValueError("provider budget period must be weekly or monthly")
        report = self._provider_capability_report_payload()
        return {
            "service_capacity": {
                "service": "ai.inference",
                "period": period,
                "limits": {"max_cost_cents": max_cost_cents},
            },
            "provider_intelligence": [
                {
                    "provider": normalized_provider_id,
                    "capacity": {
                        "period": period,
                        "limits": {"max_cost_cents": max_cost_cents},
                    },
                    "available_models": self._build_budget_declaration_available_models(report, normalized_provider_id),
                }
            ],
            "node_available": True,
            "observed_at": str(report.get("generated_at") or local_now_iso()).strip(),
        }

    async def declare_budget_to_core(self, *, provider_id: str = "openai") -> dict:
        trust_state = self._trust_state_payload()
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        trust_token = str(trust_state.get("node_trust_token") or "").strip()
        core_api_endpoint = str(trust_state.get("core_api_endpoint") or "").strip()
        if not node_id or not trust_token or not core_api_endpoint:
            raise ValueError("trusted Core connection is required before declaring budget")
        declaration_payload = self._build_budget_declaration_payload(provider_id=provider_id)
        result = await self._budget_declaration_client.submit_declaration(
            core_api_endpoint=core_api_endpoint,
            trust_token=trust_token,
            node_id=node_id,
            declaration_payload=declaration_payload,
        )
        return {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "provider_id": str(provider_id or "").strip().lower(),
            "declaration_payload": declaration_payload,
            "result": result.payload,
        }

    async def restart_service(self, *, target: str) -> dict:
        if self._service_manager is None or not hasattr(self._service_manager, "restart"):
            raise ValueError("service manager is not configured")
        if str(target or "").strip().lower() == "comfyui_webui":
            if hasattr(self._service_manager, "stop"):
                self._service_manager.stop(target=target)
            await self._assert_manual_comfyui_takeover_ready()
            result = self._service_manager.start(target=target)
            return {"status": "ok", **result, "services": self._service_manager.get_status()}
        result = self._service_manager.restart(target=target)
        return {"status": "ok", **result, "services": self._service_manager.get_status()}

    async def start_service(self, *, target: str) -> dict:
        if self._service_manager is None or not hasattr(self._service_manager, "start"):
            raise ValueError("service manager is not configured")
        if str(target or "").strip().lower() == "comfyui_webui":
            await self._assert_manual_comfyui_takeover_ready()
        result = self._service_manager.start(target=target)
        return {"status": "ok", **result, "services": self._service_manager.get_status()}

    def stop_service(self, *, target: str) -> dict:
        if self._service_manager is None or not hasattr(self._service_manager, "stop"):
            raise ValueError("service manager is not configured")
        result = self._service_manager.stop(target=target)
        return {"status": "ok", **result, "services": self._service_manager.get_status()}

    async def _assert_manual_comfyui_takeover_ready(self) -> dict:
        preflight = await self.manual_comfyui_takeover_preflight()
        if not preflight.get("ready"):
            raise ValueError(json.dumps(preflight, sort_keys=True))
        return preflight

    async def manual_comfyui_takeover_preflight(self) -> dict:
        if self._execution_queue is None or not hasattr(self._execution_queue, "matching_work_snapshot"):
            return {"ready": True, "reason": "execution_queue_not_configured", "vision_work": None}
        snapshot = await self._execution_queue.matching_work_snapshot(
            queue="local",
            task_families={"task.document_ocr", "task.image_description", "task.object_detection", "task.vision_analysis"},
            statuses={"queued", "running"},
        )
        active_count = max(int(snapshot.get("active_count") or 0), 0)
        queued_count = max(int(snapshot.get("queued_count") or 0), 0)
        ready = active_count == 0 and queued_count == 0
        return {
            "ready": ready,
            "reason": "vision_work_drained" if ready else "vision_work_pending",
            "vision_work": snapshot,
            "cloud_reroute": {
                "automatic_reroute_enabled": False,
                "candidate_count": max(int(snapshot.get("cloud_reroute_candidate_count") or 0), 0),
                "reason": "queued_job_runner_rebind_not_supported",
            },
        }

    def update_provider_selection(
        self,
        *,
        openai_enabled: bool,
        local_enabled: bool | None = None,
        provider_budget_limits: dict | None = None,
    ) -> dict:
        if self._provider_selection_store is None or not hasattr(self._provider_selection_store, "save"):
            raise ValueError("provider selection store is not configured")
        payload = self._provider_selection_store.load_or_create(openai_enabled=False)
        providers = payload.setdefault("providers", {})
        supported = providers.setdefault("supported", {})
        cloud_supported = {str(item).strip() for item in list(supported.get("cloud") or []) if str(item).strip()}
        local_supported = {str(item).strip() for item in list(supported.get("local") or []) if str(item).strip()}
        cloud_supported.add("openai")
        local_supported.add("local")
        supported["cloud"] = sorted(cloud_supported)
        supported["local"] = sorted(local_supported)
        supported["future"] = sorted(str(item).strip() for item in list(supported.get("future") or []) if str(item).strip())
        enabled = set(providers.get("enabled") or [])
        if openai_enabled:
            enabled.add("openai")
        else:
            enabled.discard("openai")
        if local_enabled is not None:
            if local_enabled:
                enabled.add("local")
            else:
                enabled.discard("local")
        providers["enabled"] = sorted(enabled)
        normalized_budget_limits: dict[str, dict[str, int | str]] = {}
        if isinstance(provider_budget_limits, dict):
            supported = providers.get("supported") if isinstance(providers.get("supported"), dict) else {}
            supported_ids = {
                str(item).strip().lower()
                for group in ("cloud", "local", "future")
                for item in list(supported.get(group) or [])
                if str(item).strip()
            }
            for provider_id, limit_payload in provider_budget_limits.items():
                normalized_provider_id = str(provider_id or "").strip().lower()
                if normalized_provider_id not in supported_ids or not isinstance(limit_payload, dict):
                    continue
                max_cost_cents = limit_payload.get("max_cost_cents")
                if max_cost_cents in (None, ""):
                    continue
                period = str(limit_payload.get("period") or "monthly").strip().lower()
                if period not in {"weekly", "monthly"}:
                    raise ValueError("provider budget period must be weekly or monthly")
                normalized_budget_limits[normalized_provider_id] = {
                    "max_cost_cents": max(int(max_cost_cents), 0),
                    "period": period,
                }
        providers["budget_limits"] = normalized_budget_limits
        self._provider_selection_store.save(payload)
        self._provider_selection_config = payload
        self._phase2_diag.provider_selection(
            {
                "source": "node_control_api",
                "enabled_providers": providers["enabled"],
                "provider_budget_limits": normalized_budget_limits,
            }
        )
        return self.provider_selection_payload()

    def update_task_capability_selection(self, *, selected_task_families: list[str]) -> dict:
        if self._task_capability_selection_store is None or not hasattr(self._task_capability_selection_store, "save"):
            raise ValueError("task capability selection store is not configured")
        payload = create_task_capability_selection_config({"selected_task_families": selected_task_families})
        self._task_capability_selection_store.save(payload)
        self._task_capability_selection_config = payload
        return self.task_capability_selection_payload()

    def update_openai_credentials(
        self,
        *,
        api_token: str,
        service_token: str,
        project_name: str,
    ) -> dict:
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "upsert_openai_credentials"):
            raise ValueError("provider credentials store is not configured")
        payload = self._provider_credentials_store.upsert_openai_credentials(
            api_token=api_token,
            service_token=service_token,
            project_name=project_name,
        )
        self._provider_credentials_summary = summarize_provider_credentials(payload)
        self._phase2_diag.provider_selection(
            {
                "source": "openai_credentials_saved",
                "provider": "openai",
                "has_api_token": True,
                "has_service_token": True,
                "project_name": bool(str(project_name or "").strip()),
            }
        )
        return self.provider_credentials_payload(provider_id="openai")

    def _has_saved_openai_api_token(self) -> bool:
        credentials = self.provider_credentials_payload(provider_id="openai").get("credentials")
        return bool(isinstance(credentials, dict) and credentials.get("has_api_token"))

    async def refresh_provider_models_after_openai_credentials_save(self) -> None:
        if (
            self._has_saved_openai_api_token()
            and self._provider_runtime_manager is not None
            and hasattr(self._provider_runtime_manager, "refresh_openai_models_from_saved_credentials")
        ):
            await self._provider_runtime_manager.refresh_openai_models_from_saved_credentials()
            return
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "refresh"):
            return
        await self._provider_runtime_manager.refresh()

    def update_openai_preferences(
        self,
        *,
        default_model_id: str | None = None,
        selected_model_ids: list[str] | None = None,
    ) -> dict:
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "update_openai_preferences"):
            raise ValueError("provider credentials store is not configured")
        payload = self._provider_credentials_store.update_openai_preferences(
            default_model_id=default_model_id,
            selected_model_ids=selected_model_ids,
        )
        self._provider_credentials_summary = summarize_provider_credentials(payload)
        return self.provider_credentials_payload(provider_id="openai")

    def latest_provider_models_payload(self, *, provider_id: str, limit: int = 3) -> dict:
        normalized_provider = str(provider_id or "").strip().lower()
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "latest_models_payload"):
            payload = self._provider_runtime_manager.latest_models_payload(provider_id=normalized_provider, limit=limit)
            return self._normalize_latest_models_payload(payload=payload, provider_id=normalized_provider, limit=limit)
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        report = capability_payload.get("provider_capability_report") if isinstance(capability_payload, dict) else None
        return self._normalize_latest_models_payload(
            payload={"provider_id": normalized_provider, "models": self._extract_report_models(report, normalized_provider)},
            provider_id=normalized_provider,
            limit=limit,
        )

    def openai_provider_model_catalog_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_catalog_payload"):
            return {
                "provider_id": "openai",
                "models": [],
                "source": "provider_model_catalog",
                "generated_at": local_now_iso(),
            }
        payload = self._provider_runtime_manager.openai_model_catalog_payload()
        raw_models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        normalized = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id") or "").strip()
            family = str(item.get("family") or "").strip()
            if not model_id or not family:
                continue
            normalized.append(
                {
                    "model_id": model_id,
                    "family": family,
                    "discovered_at": str(item.get("discovered_at") or "").strip() or None,
                    "enabled": bool(item.get("enabled")),
                }
            )
        selected_ui_ids = select_representative_openai_model_ids(
            [str(item.get("model_id") or "").strip().lower() for item in normalized]
        )
        ui_models = [item for item in normalized if str(item.get("model_id") or "").strip().lower() in selected_ui_ids]
        return {
            "provider_id": "openai",
            "models": normalized,
            "ui_models": ui_models,
            "source": str(payload.get("source") or "provider_model_catalog").strip() if isinstance(payload, dict) else "provider_model_catalog",
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
        }

    def openai_provider_model_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_capabilities_payload"):
            return {
                "provider_id": "openai",
                "classification_model": None,
                "entries": [],
                "generated_at": local_now_iso(),
                "source": "provider_model_capabilities",
            }
        payload = self._provider_runtime_manager.openai_model_capabilities_payload()
        entries = payload.get("entries") if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else []
        return {
            "provider_id": "openai",
            "classification_model": payload.get("classification_model") if isinstance(payload, dict) else None,
            "entries": entries,
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
            "source": str(payload.get("source") or "provider_model_capabilities").strip()
            if isinstance(payload, dict)
            else "provider_model_capabilities",
        }

    def openai_model_features_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_features_payload"):
            return {
                "schema_version": "1.0",
                "generated_at": local_now_iso(),
                "entries": [],
                "source": "provider_model_features",
            }
        payload = self._provider_runtime_manager.openai_model_features_payload()
        if not isinstance(payload, dict):
            return {
                "schema_version": "1.0",
                "generated_at": local_now_iso(),
                "entries": [],
                "source": "provider_model_features",
            }
        return payload

    def node_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "node_capabilities_payload"):
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": [],
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_task_capabilities": [],
                "generated_at": local_now_iso(),
                "source": "node_capabilities",
            }
        payload = self._provider_runtime_manager.node_capabilities_payload()
        if not isinstance(payload, dict):
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": [],
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_task_capabilities": [],
                "generated_at": local_now_iso(),
                "source": "node_capabilities",
            }
        return payload

    def openai_enabled_models_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_enabled_models_payload"):
            return {
                "provider_id": "openai",
                "models": [],
                "generated_at": local_now_iso(),
                "source": "provider_enabled_models",
            }
        payload = self._provider_runtime_manager.openai_enabled_models_payload()
        models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        return {
            "provider_id": "openai",
            "models": models,
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
            "source": str(payload.get("source") or "provider_enabled_models").strip()
            if isinstance(payload, dict)
            else "provider_enabled_models",
        }

    @staticmethod
    def _resolved_task_families_from_capability_payload(payload: dict | None) -> list[str]:
        if not isinstance(payload, dict):
            return []
        resolved = payload.get("enabled_task_capabilities") or payload.get("resolved_tasks") or []
        if not isinstance(resolved, list):
            return []
        normalized = sorted({str(item).strip() for item in resolved if str(item).strip()})
        return normalized

    def save_openai_enabled_models(self, *, model_ids: list[str]) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "save_openai_enabled_models"):
            raise ValueError("openai enabled model persistence is not configured")
        payload = self._provider_runtime_manager.save_openai_enabled_models(model_ids=model_ids)
        return {
            "provider_id": "openai",
            **(payload if isinstance(payload, dict) else {}),
        }

    async def update_openai_enabled_models_with_redeclaration(self, *, model_ids: list[str]) -> dict:
        before_payload = self.node_capabilities_payload()
        before_tasks = self._resolved_task_families_from_capability_payload(before_payload)
        response = self.save_openai_enabled_models(model_ids=model_ids)
        after_payload = self.node_capabilities_payload()
        after_tasks = self._resolved_task_families_from_capability_payload(after_payload)
        task_surface_changed = before_tasks != after_tasks
        declaration: dict
        if task_surface_changed:
            declaration = await self.redeclare_capabilities(reason="enabled_models_changed", force=False)
        else:
            declaration = {"status": "unchanged", "reason": "enabled_models_no_task_change"}
        return {
            **response,
            "task_surface_changed": task_surface_changed,
            "previous_resolved_tasks": before_tasks,
            "resolved_tasks": after_tasks,
            "declaration": declaration,
        }

    async def rerun_openai_model_capabilities(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "rerun_openai_model_capabilities"):
            raise ValueError("openai model capability refresh is not configured")
        return await self._provider_runtime_manager.rerun_openai_model_capabilities()

    def openai_resolved_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_resolved_capabilities_payload"):
            return {
                "provider_id": "openai",
                "enabled_model_ids": [],
                "classification_model": None,
                "updated_at": None,
                "capabilities": {
                    "text_generation": False,
                    "reasoning": False,
                    "vision": False,
                    "image_generation": False,
                    "audio_input": False,
                    "audio_output": False,
                    "realtime": False,
                    "tool_calling": False,
                    "structured_output": False,
                    "long_context": False,
                    "coding_strength": "none",
                    "speed_tier": "slow",
                    "cost_tier": "low",
                    "embeddings": False,
                    "moderation": False,
                },
                "enabled_models": [],
            }
        payload = self._provider_runtime_manager.openai_resolved_capabilities_payload()
        return {"provider_id": "openai", **(payload if isinstance(payload, dict) else {})}

    def local_resolved_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "local_resolved_capabilities_payload"):
            return {
                "provider_id": "local",
                "enabled_model_ids": [],
                "classification_model": None,
                "capabilities": {},
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_models": [],
                "source": "local_model_features",
            }
        payload = self._provider_runtime_manager.local_resolved_capabilities_payload()
        return {"provider_id": "local", **(payload if isinstance(payload, dict) else {})}

    def models_for_task_payload(self, *, task_family: str) -> dict:
        canonical_task = canonicalize_task_family(str(task_family or "").strip())
        if not canonical_task:
            raise ValueError("invalid_task_family")
        if canonical_task not in set(DECLARABLE_TASK_FAMILIES):
            raise ValueError(f"unsupported_task_family:{canonical_task}")
        node_capabilities = self.node_capabilities_payload()
        provider_capabilities = (
            node_capabilities.get("provider_capabilities")
            if isinstance(node_capabilities.get("provider_capabilities"), dict)
            else {}
        )
        selection_context = (
            self._provider_runtime_manager.provider_selection_context_payload()
            if self._provider_runtime_manager is not None
            and hasattr(self._provider_runtime_manager, "provider_selection_context_payload")
            else {}
        )
        enabled_providers = [
            str(item or "").strip().lower()
            for item in list(selection_context.get("enabled_providers") or provider_capabilities.keys())
            if str(item or "").strip()
        ]
        default_model_by_provider = (
            selection_context.get("default_model_by_provider")
            if isinstance(selection_context.get("default_model_by_provider"), dict)
            else {}
        )
        usable_models_by_provider = (
            selection_context.get("usable_models_by_provider")
            if isinstance(selection_context.get("usable_models_by_provider"), dict)
            else {}
        )
        available_models_by_provider = (
            selection_context.get("available_models_by_provider")
            if isinstance(selection_context.get("available_models_by_provider"), dict)
            else {}
        )
        providers = []
        for provider_id in enabled_providers:
            capability_payload = provider_capabilities.get(provider_id)
            if not isinstance(capability_payload, dict):
                continue
            resolved_tasks = self._resolved_task_families_from_capability_payload(capability_payload)
            if canonical_task not in set(resolved_tasks):
                continue
            usable_models = [
                str(item or "").strip()
                for item in list(usable_models_by_provider.get(provider_id) or [])
                if str(item or "").strip()
            ]
            available_models = [
                str(item or "").strip()
                for item in list(available_models_by_provider.get(provider_id) or [])
                if str(item or "").strip()
            ]
            capability_models = [
                str(item or "").strip()
                for item in list(capability_payload.get("enabled_models") or [])
                if str(item or "").strip()
            ]
            model_ids = usable_models or available_models or capability_models
            default_model = str(default_model_by_provider.get(provider_id) or "").strip() or None
            providers.append(
                {
                    "provider_id": provider_id,
                    "queue": "local" if provider_id == "local" else "cloud",
                    "resolved_tasks": resolved_tasks,
                    "models": [
                        {
                            "model_id": model_id,
                            "default": bool(default_model and model_id == default_model),
                            "usable": model_id in set(usable_models) if usable_models else True,
                        }
                        for model_id in model_ids
                    ],
                }
            )
        return {
            "task_family": canonical_task,
            "providers": providers,
            "provider_count": len(providers),
            "model_count": sum(len(provider.get("models") or []) for provider in providers),
            "generated_at": local_now_iso(),
            "source": "provider_task_capability_maps",
        }

    @staticmethod
    def _extract_report_models(report: dict | None, provider_id: str) -> list[dict]:
        if not isinstance(report, dict):
            return []
        providers = report.get("providers")
        if not isinstance(providers, list):
            return []
        for provider_payload in providers:
            if not isinstance(provider_payload, dict):
                continue
            provider_name = str(provider_payload.get("provider_id") or provider_payload.get("provider") or "").strip().lower()
            if provider_name != provider_id:
                continue
            models = provider_payload.get("models")
            return models if isinstance(models, list) else []
        return []

    @staticmethod
    def _normalize_latest_models_payload(*, payload: dict | None, provider_id: str, limit: int) -> dict:
        raw_models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        normalized = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id") or item.get("id") or "").strip()
            if not model_id:
                continue
            pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
            pricing_input = item.get("pricing_input")
            pricing_output = item.get("pricing_output")
            normalized.append(
                {
                    "model_id": model_id,
                    "display_name": str(item.get("display_name") or model_id).strip(),
                    "created": item.get("created") if isinstance(item.get("created"), int) else None,
                    "status": str(item.get("status") or "available").strip(),
                    "pricing": {
                        "currency": str(pricing.get("currency") or "usd").strip().lower(),
                        "input_per_1m_tokens": (
                            pricing.get("input_per_1m_tokens")
                            if isinstance(pricing.get("input_per_1m_tokens"), (int, float))
                            else pricing_input
                        ),
                        "output_per_1m_tokens": (
                            pricing.get("output_per_1m_tokens")
                            if isinstance(pricing.get("output_per_1m_tokens"), (int, float))
                            else pricing_output
                        ),
                    },
                }
            )
        normalized.sort(
            key=lambda item: (int(item.get("created") or 0), str(item.get("model_id") or "")),
            reverse=True,
        )
        return {
            "provider_id": provider_id,
            "models": normalized[: max(int(limit), 0)],
            "source": str(payload.get("source") or "provider_capability_report").strip()
            if isinstance(payload, dict)
            else "provider_capability_report",
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
        }

    async def refresh_openai_pricing(self, *, force_refresh: bool) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "refresh_pricing"):
            raise ValueError("provider pricing refresh is not configured")
        payload = await self._provider_runtime_manager.refresh_pricing(force=force_refresh)
        return {
            "provider_id": "openai",
            "force_refresh": bool(force_refresh),
            **(payload if isinstance(payload, dict) else {}),
        }

    def save_openai_manual_pricing(
        self,
        *,
        model_id: str,
        display_name: str | None = None,
        input_price_per_1m: float | None = None,
        output_price_per_1m: float | None = None,
    ) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "save_manual_openai_pricing"):
            raise ValueError("manual pricing save is not configured")
        payload = self._provider_runtime_manager.save_manual_openai_pricing(
            model_id=model_id,
            display_name=display_name,
            input_price_per_1m=input_price_per_1m,
            output_price_per_1m=output_price_per_1m,
        )
        return {"provider_id": "openai", **(payload if isinstance(payload, dict) else {})}

    def openai_pricing_diagnostics_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "pricing_diagnostics_payload"):
            return {
                "provider_id": "openai",
                "configured": False,
                "refresh_state": "unavailable",
                "stale": True,
                "entry_count": 0,
                "source_urls": [],
                "source_url_used": None,
                "last_refresh_time": None,
                "unknown_models": [],
                "last_error": None,
            }
        payload = self._provider_runtime_manager.pricing_diagnostics_payload()
        return {
            "provider_id": "openai",
            **(payload if isinstance(payload, dict) else {"configured": False}),
        }

    async def submit_capability_declaration(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "submit_once"):
            raise ValueError("capability declaration runner is not configured")
        setup_contract = self._build_capability_setup_contract()
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[capability-declare-gate-check] %s",
                {
                    "status": self._lifecycle.get_state().value,
                    "declaration_allowed": setup_contract.get("declaration_allowed"),
                    "blocking_reasons": setup_contract.get("blocking_reasons"),
                },
            )
        if not setup_contract.get("declaration_allowed"):
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[capability-declare-gate-failed] %s",
                    {
                        "status": self._lifecycle.get_state().value,
                        "blocking_reasons": setup_contract.get("blocking_reasons"),
                        "readiness_flags": setup_contract.get("readiness_flags"),
                    },
                )
            raise CapabilityDeclarationPrerequisiteError(
                payload={
                    "error_code": "capability_setup_prerequisites_unmet",
                    "message": "capability declaration prerequisites are not satisfied",
                    "blocking_reasons": setup_contract.get("blocking_reasons") or [],
                    "readiness_flags": setup_contract.get("readiness_flags") or {},
                }
            )
        return await self._capability_runner.submit_once()

    async def redeclare_capabilities(self, *, reason: str, force: bool = False) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "redeclare_if_needed"):
            return {"status": "skipped", "reason": "capability_redeclaration_not_configured"}
        return await self._capability_runner.redeclare_if_needed(reason=reason, force=force)

    async def notify_workflow_request(self, *, workflow_request: str, workflow_status: str, details: dict | None = None) -> dict | None:
        if self._capability_runner is None or not hasattr(self._capability_runner, "emit_workflow_status_telemetry"):
            return None
        try:
            return await self._capability_runner.emit_workflow_status_telemetry(
                workflow_request=workflow_request,
                workflow_status=workflow_status,
                details=details,
            )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[workflow-request-telemetry-failed] %s",
                    {"workflow_request": workflow_request, "workflow_status": workflow_status, "error": str(exc)},
                )
            return None

    async def rebuild_node_capabilities(self) -> dict:
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "rebuild_node_capabilities"):
            payload = self._provider_runtime_manager.rebuild_node_capabilities()
            if isinstance(payload, dict):
                return payload
        resolved = self.openai_resolved_capabilities_payload()
        node_capabilities = self.node_capabilities_payload()
        return {
            "status": "rebuilt",
            "provider_id": "openai",
            "resolved_capabilities": resolved,
            "resolved_tasks": list(node_capabilities.get("enabled_task_capabilities") or node_capabilities.get("resolved_tasks") or []),
            "node_capabilities": node_capabilities,
        }

    def capability_diagnostics_payload(self) -> dict:
        capability_status = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        resolved = self.openai_resolved_capabilities_payload()
        model_features = self.openai_model_features_payload()
        node_capabilities = self.node_capabilities_payload()
        try:
            capability_graph = load_task_graph()
        except Exception as exc:
            capability_graph = {"error": str(exc)}
        pricing_catalog = (
            self._provider_runtime_manager.openai_pricing_catalog_payload()
            if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "openai_pricing_catalog_payload")
            else {"entries": [], "source": "openai_pricing_catalog", "generated_at": self._now_iso()}
        )
        pricing_diagnostics = self.openai_pricing_diagnostics_payload()
        return {
            "admin": True,
            "generated_at": self._now_iso(),
            "discovered_models": self.openai_provider_model_catalog_payload(),
            "feature_catalog": model_features,
            "capability_graph": capability_graph,
            "enabled_models": self.openai_enabled_models_payload(),
            "capability_catalog": self.openai_provider_model_capabilities_payload(),
            "resolved_capabilities": resolved,
            "resolved_tasks": (
                node_capabilities.get("enabled_task_capabilities")
                or node_capabilities.get("resolved_tasks")
                or []
            ),
            "pricing_catalog": pricing_catalog,
            "pricing_diagnostics": pricing_diagnostics,
            "node_capabilities": node_capabilities,
            "internal_scheduler": self.internal_scheduler_payload(),
            "classification_model": resolved.get("classification_model"),
            "last_declaration_payload": capability_status.get("last_manifest_payload"),
            "last_declaration_result": capability_status.get("last_declaration_result"),
        }

    def _register_background_scheduler_tasks(self) -> None:
        if self._internal_scheduler is None or not hasattr(self._internal_scheduler, "register_interval_task"):
            return
        self._internal_scheduler.register_interval_task(
            task_id="provider_capability_refresh",
            display_name="Provider Capability Refresh",
            interval_seconds=self._provider_refresh_interval_seconds,
            schedule_name="4_times_a_day",
            task_kind="provider_specific_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="heartbeat",
            display_name="HB",
            interval_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            schedule_name="heartbeat_5_seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="supervisor_heartbeat",
            display_name="Supervisor HB",
            interval_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            schedule_name="heartbeat_5_seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="telemetry",
            display_name="Telemetry",
            interval_seconds=STATUS_TELEMETRY_INTERVAL_SECONDS,
            schedule_name="telemetry_60_seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="local_llm_default_revert",
            display_name="Local LLM Default Revert",
            interval_seconds=self._local_llm_default_revert_check_interval_seconds,
            schedule_name="interval_seconds",
            schedule_detail=f"Every {self._local_llm_default_revert_check_interval_seconds} seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="local_llm_always_on",
            display_name="Local LLM Always On",
            interval_seconds=self._local_llm_always_on_check_interval_seconds,
            schedule_name="interval_seconds",
            schedule_detail=f"Every {self._local_llm_always_on_check_interval_seconds} seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="vision_runtime_residency",
            display_name="Vision Runtime Residency",
            interval_seconds=self._vision_runtime_residency_check_interval_seconds,
            schedule_name="interval_seconds",
            schedule_detail=f"Every {self._vision_runtime_residency_check_interval_seconds} seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="comfyui_webui_idle_close",
            display_name="ComfyUI Web UI Idle Close",
            interval_seconds=self._comfyui_webui_idle_check_interval_seconds,
            schedule_name="interval_seconds",
            schedule_detail=f"Every {self._comfyui_webui_idle_check_interval_seconds} seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._sync_operational_mqtt_health_schedule()

    def _operational_mqtt_health_schedule_definition(self) -> dict:
        lifecycle_state = self._lifecycle.get_state()
        recovery_snapshot = self.operational_mqtt_recovery_payload()
        within_fast_window = local_now() < self._operational_mqtt_fast_until
        fast_states = {
            NodeLifecycleState.TRUSTED,
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS,
            NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED,
            NodeLifecycleState.DEGRADED,
        }
        fast_mode = (
            lifecycle_state in fast_states
            or bool(recovery_snapshot.get("active"))
            or bool(recovery_snapshot.get("exhausted"))
            or (lifecycle_state == NodeLifecycleState.OPERATIONAL and within_fast_window)
        )
        if fast_mode:
            interval_seconds = self._operational_mqtt_health_check_interval_seconds
            if interval_seconds == 10:
                return {
                    "interval_seconds": interval_seconds,
                    "schedule_name": "every_10_seconds",
                    "schedule_detail": "Every 10 seconds",
                }
            return {
                "interval_seconds": interval_seconds,
                "schedule_name": "interval_seconds",
                "schedule_detail": f"Every {interval_seconds} seconds",
            }
        interval_seconds = self._operational_mqtt_health_normal_interval_seconds
        if interval_seconds == 300:
            return {
                "interval_seconds": interval_seconds,
                "schedule_name": "every_5_minutes",
                "schedule_detail": "00:05, 00:10, 00:15, ...",
            }
        return {
            "interval_seconds": interval_seconds,
            "schedule_name": "interval_seconds",
            "schedule_detail": f"Every {interval_seconds} seconds",
        }

    def _sync_operational_mqtt_health_schedule(self) -> None:
        if self._internal_scheduler is None or not hasattr(self._internal_scheduler, "register_interval_task"):
            return
        schedule = self._operational_mqtt_health_schedule_definition()
        self._internal_scheduler.register_interval_task(
            task_id="operational_mqtt_health",
            display_name="Operational MQTT Health",
            interval_seconds=int(schedule["interval_seconds"]),
            schedule_name=str(schedule["schedule_name"]),
            schedule_detail=schedule.get("schedule_detail"),
            task_kind="local_recurring",
            readiness_critical=False,
        )

    def _extend_operational_mqtt_fast_window(self) -> None:
        self._operational_mqtt_fast_until = local_now() + timedelta(
            seconds=self._operational_mqtt_health_fast_window_seconds
        )

    async def refresh_governance(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "refresh_governance_once"):
            raise ValueError("governance refresh is not configured")
        return await self._capability_runner.refresh_governance_once()

    async def refresh_provider_capabilities(self, *, force_refresh: bool) -> dict:
        openai_reload = None
        if (
            force_refresh
            and self._has_saved_openai_api_token()
            and self._provider_runtime_manager is not None
            and hasattr(self._provider_runtime_manager, "refresh_openai_models_from_saved_credentials")
        ):
            openai_reload = await self._provider_runtime_manager.refresh_openai_models_from_saved_credentials()
        if self._capability_runner is not None and hasattr(self._capability_runner, "refresh_provider_capabilities_once"):
            result = await self._capability_runner.refresh_provider_capabilities_once(force_refresh=force_refresh)
            if openai_reload is not None:
                return {**result, "openai_model_reload": openai_reload}
            return result
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "refresh"):
            result = {
                "source": "provider_runtime_manager",
                "force_refresh": force_refresh,
                "report": await self._provider_runtime_manager.refresh(),
            }
            if openai_reload is not None:
                result["openai_model_reload"] = openai_reload
            return result
        if self._capability_runner is None or not hasattr(self._capability_runner, "refresh_provider_capabilities_once"):
            raise ValueError("provider capability refresh is not configured")
        return await self._capability_runner.refresh_provider_capabilities_once(force_refresh=force_refresh)

    async def start_background_jobs(self) -> None:
        self._start_bootstrap_listener_if_available()
        try:
            result = await self.refresh_provider_capabilities(force_refresh=False)
            if hasattr(self._logger, "info"):
                self._logger.info(
                    "[provider-intelligence-refresh-startup] %s",
                    {
                        "status": result.get("status"),
                        "changed": result.get("changed"),
                        "core_submission": result.get("core_submission"),
                    },
                )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[provider-intelligence-refresh-startup-error] %s", {"error": str(exc)})
        self._notify_back_online()
        if self._internal_scheduler is not None and hasattr(self._internal_scheduler, "start_interval_task"):
            self._internal_scheduler.start_interval_task(
                task_id="provider_capability_refresh",
                coroutine_factory=self._provider_refresh_job_once,
                initial_delay_seconds=self._provider_refresh_interval_seconds,
            )
            self._internal_scheduler.start_interval_task(
                task_id="heartbeat",
                coroutine_factory=self._heartbeat_job_once,
                initial_delay_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            )
            self._internal_scheduler.start_interval_task(
                task_id="supervisor_heartbeat",
                coroutine_factory=self._supervisor_heartbeat_job_once,
                initial_delay_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            )
            self._internal_scheduler.start_interval_task(
                task_id="telemetry",
                coroutine_factory=self._status_telemetry_job_once,
                initial_delay_seconds=STATUS_TELEMETRY_INTERVAL_SECONDS,
            )
            self._internal_scheduler.start_interval_task(
                task_id="local_llm_default_revert",
                coroutine_factory=self._local_llm_default_revert_job_once,
                initial_delay_seconds=self._local_llm_default_revert_check_interval_seconds,
            )
            self._internal_scheduler.start_interval_task(
                task_id="local_llm_always_on",
                coroutine_factory=self._local_llm_always_on_job_once,
                initial_delay_seconds=0,
            )
            self._internal_scheduler.start_interval_task(
                task_id="vision_runtime_residency",
                coroutine_factory=self._vision_runtime_residency_job_once,
                initial_delay_seconds=0,
            )
            self._internal_scheduler.start_interval_task(
                task_id="comfyui_webui_idle_close",
                coroutine_factory=self._comfyui_webui_idle_close_job_once,
                initial_delay_seconds=self._comfyui_webui_idle_check_interval_seconds,
            )
            self._internal_scheduler.start_interval_task(
                task_id="operational_mqtt_health",
                coroutine_factory=self._operational_mqtt_health_job_once,
                initial_delay_seconds=0,
            )

    def _notify_back_online(self) -> None:
        if self._notification_service is None or not hasattr(self._notification_service, "notify"):
            return
        trust_state = self._trust_state_payload()
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        node_name = str(trust_state.get("node_name") or "").strip() or node_id
        if not node_id:
            return
        self._notification_service.notify(
            title=f"{node_name} is back online",
            message=f"{node_name} {node_id} is back online.",
            kind="event",
            severity="success",
            priority="high",
            urgency="notification",
            component="node_control_api",
            label="Hexe AI Node",
            event_type="node_back_online",
            dedupe_key=f"node-back-online:{node_id}",
            data={"node_id": node_id, "node_name": node_name},
            trust_state=trust_state,
        )

    async def stop_background_jobs(self) -> None:
        if self._internal_scheduler is not None and hasattr(self._internal_scheduler, "stop_all"):
            await self._internal_scheduler.stop_all()

    async def _provider_refresh_job_once(self) -> dict:
        result = await self.refresh_provider_capabilities(force_refresh=False)
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[provider-intelligence-refresh-job] %s",
                {
                    "status": result.get("status"),
                    "changed": result.get("changed"),
                    "core_submission": result.get("core_submission"),
                },
            )
        return result

    async def _status_telemetry_job_once(self) -> dict | None:
        if self._capability_runner is None or not hasattr(self._capability_runner, "emit_periodic_status_telemetry"):
            return {"status": "skipped", "reason": "capability_runner_not_configured"}
        result = await self._capability_runner.emit_periodic_status_telemetry()
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[status-telemetry-job] %s",
                {"published": bool((result or {}).get("published")), "result": result},
            )
        return result

    async def _local_llm_default_revert_job_once(self) -> dict | None:
        if self._service_manager is None or not hasattr(self._service_manager, "revert_local_llm_to_default_if_idle"):
            return {"status": "skipped", "reason": "service_manager_not_configured"}
        admission = self.direct_execution_admission_payload()
        local_in_flight = max(int(admission.get("in_flight") or 0), 0)
        if self._local_llm_switch_lock.locked():
            local_in_flight = max(local_in_flight, 1)
        result = await asyncio.to_thread(
            self._service_manager.revert_local_llm_to_default_if_idle,
            local_in_flight=local_in_flight,
        )
        return {"status": "ok", "result": result if isinstance(result, dict) else {}}

    async def _local_llm_always_on_job_once(self) -> dict | None:
        if self._service_manager is None or not hasattr(self._service_manager, "ensure_local_llm_always_on"):
            return {"status": "skipped", "reason": "service_manager_not_configured"}
        admission = self.direct_execution_admission_payload()
        local_in_flight = max(int(admission.get("in_flight") or 0), 0)
        if self._local_llm_switch_lock.locked():
            local_in_flight = max(local_in_flight, 1)
        result = await asyncio.to_thread(
            self._service_manager.ensure_local_llm_always_on,
            local_in_flight=local_in_flight,
        )
        return {"status": "ok", "result": result if isinstance(result, dict) else {}}

    async def _vision_runtime_residency_job_once(self) -> dict | None:
        if self._service_manager is None or not hasattr(self._service_manager, "ensure_vision_runtime_resident"):
            return {"status": "skipped", "reason": "service_manager_not_configured"}
        admission = self.direct_execution_admission_payload()
        local_in_flight = max(int(admission.get("in_flight") or 0), 0)
        if self._local_llm_switch_lock.locked():
            local_in_flight = max(local_in_flight, 1)
        gpu_comfyui_critical_in_flight = await self._gpu_comfyui_critical_work_pending()
        result = await asyncio.to_thread(
            self._service_manager.ensure_vision_runtime_resident,
            local_in_flight=local_in_flight,
            gpu_comfyui_critical_in_flight=gpu_comfyui_critical_in_flight,
        )
        return {"status": "ok", "result": result if isinstance(result, dict) else {}}

    async def _comfyui_webui_idle_close_job_once(self) -> dict | None:
        if self._service_manager is None or not hasattr(self._service_manager, "close_comfyui_webui_if_idle"):
            return {"status": "skipped", "reason": "service_manager_not_configured"}
        result = await asyncio.to_thread(self._service_manager.close_comfyui_webui_if_idle)
        return {"status": "ok", "result": result if isinstance(result, dict) else {}}

    async def _gpu_comfyui_critical_work_pending(self) -> bool:
        if self._execution_queue is None or not hasattr(self._execution_queue, "has_matching_work"):
            return False
        return await self._execution_queue.has_matching_work(
            queue="local",
            importance="critical",
            task_families={"task.image_generation", "task.generation.image"},
            statuses={"queued", "running"},
        )

    async def _heartbeat_job_once(self) -> dict | None:
        if self._capability_runner is None or not hasattr(self._capability_runner, "emit_periodic_heartbeat"):
            return {"status": "skipped", "reason": "capability_runner_not_configured"}
        result = await self._capability_runner.emit_periodic_heartbeat()
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[heartbeat-job] %s",
                {"published": bool((result or {}).get("published")), "result": result},
            )
        return result

    async def _supervisor_heartbeat_job_once(self) -> dict | None:
        if self._supervisor_client is None:
            return {"status": "skipped", "reason": "supervisor_client_not_configured"}
        payload = self._supervisor_runtime_payload()
        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            return {"status": "skipped", "reason": "missing_node_id"}
        health = await asyncio.to_thread(self._supervisor_client.health)
        if not isinstance(health, dict):
            self._supervisor_registered = False
            self._supervisor_last_error = "supervisor_unreachable"
            return {"status": "skipped", "reason": "supervisor_unreachable"}
        status = str(health.get("status") or "").strip().lower()
        ready = health.get("ready")
        if status not in {"ok", "healthy"} or (ready is not None and not bool(ready)):
            self._supervisor_registered = False
            self._supervisor_last_error = "supervisor_not_ready"
            return {"status": "skipped", "reason": "supervisor_not_ready"}
        if not self._supervisor_registered:
            registered = await asyncio.to_thread(self._supervisor_client.register_runtime, payload)
            if not isinstance(registered, dict):
                self._supervisor_last_error = "supervisor_register_failed"
                return {"status": "error", "reason": "supervisor_register_failed"}
            self._supervisor_registered = True
        heartbeat_payload = {
            "node_id": payload.get("node_id"),
            "host_id": payload.get("host_id"),
            "hostname": payload.get("hostname"),
            "api_base_url": payload.get("api_base_url"),
            "ui_base_url": payload.get("ui_base_url"),
            "runtime_state": payload.get("runtime_state"),
            "lifecycle_state": payload.get("lifecycle_state"),
            "health_status": payload.get("health_status"),
            "running": payload.get("running"),
            "resource_usage": payload.get("resource_usage", {}),
            "runtime_metadata": payload.get("runtime_metadata", {}),
        }
        heartbeat = await asyncio.to_thread(self._supervisor_client.heartbeat_runtime, heartbeat_payload)
        if not isinstance(heartbeat, dict):
            self._supervisor_registered = False
            self._supervisor_last_error = "supervisor_heartbeat_failed"
            return {"status": "error", "reason": "supervisor_heartbeat_failed"}
        self._supervisor_last_error = None
        self._supervisor_last_seen = local_now_iso()
        return {"status": "ok", "supervisor": {"last_seen_at": self._supervisor_last_seen}}

    async def _operational_mqtt_health_job_once(self) -> dict | None:
        result = await self.check_operational_mqtt_health_once()
        if hasattr(self._logger, "info") and result is not None:
            self._logger.info("[operational-mqtt-health-job] %s", result)
        return result

    async def check_operational_mqtt_health_once(self) -> dict | None:
        lifecycle_state = self._lifecycle.get_state()
        self._sync_operational_mqtt_health_schedule()
        monitorable_states = {
            NodeLifecycleState.TRUSTED,
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED,
            NodeLifecycleState.OPERATIONAL,
            NodeLifecycleState.DEGRADED,
        }
        recovery_snapshot = self.operational_mqtt_recovery_payload()
        if lifecycle_state not in monitorable_states:
            if recovery_snapshot.get("configured") and recovery_snapshot.get("active"):
                self._mqtt_recovery_store.clear()
            return {
                "status": "skipped",
                "reason": "lifecycle_not_monitorable",
                "lifecycle_state": lifecycle_state.value,
            }
        if self._capability_runner is None or not hasattr(self._capability_runner, "check_operational_mqtt_health_once"):
            return {
                "status": "skipped",
                "reason": "capability_runner_not_configured",
                "lifecycle_state": lifecycle_state.value,
            }

        health = await self._capability_runner.check_operational_mqtt_health_once()
        if not isinstance(health, dict):
            return {
                "status": "skipped",
                "reason": "trust_state_unavailable",
                "lifecycle_state": lifecycle_state.value,
            }
        if health.get("healthy"):
            if recovery_snapshot.get("active") or recovery_snapshot.get("exhausted"):
                if self._mqtt_recovery_store is not None and hasattr(self._mqtt_recovery_store, "clear"):
                    self._mqtt_recovery_store.clear()
                if (
                    lifecycle_state == NodeLifecycleState.DEGRADED
                    and self._capability_runner is not None
                    and hasattr(self._capability_runner, "recover_from_degraded")
                ):
                    try:
                        recovery = self._capability_runner.recover_from_degraded()
                    except ValueError:
                        recovery = {"status": "skipped", "reason": "degraded_recovery_unavailable"}
                    if self._lifecycle.get_state() == NodeLifecycleState.OPERATIONAL:
                        self._extend_operational_mqtt_fast_window()
                    self._sync_operational_mqtt_health_schedule()
                    return {
                        "status": "healthy",
                        "lifecycle_state": self._lifecycle.get_state().value,
                        "health": health,
                        "recovery": recovery,
                    }
            self._sync_operational_mqtt_health_schedule()
            return {"status": "healthy", "lifecycle_state": lifecycle_state.value, "health": health}

        error = str(health.get("last_error") or "operational_mqtt_not_ready")
        if (
            lifecycle_state != NodeLifecycleState.DEGRADED
            and self._lifecycle.can_transition_to(NodeLifecycleState.DEGRADED)
        ):
            self._lifecycle.transition_to(
                NodeLifecycleState.DEGRADED,
                {"source": "operational_mqtt_health_monitor", "reason": error},
            )
        if self._capability_runner is not None and hasattr(self._capability_runner, "mark_operational_mqtt_unhealthy"):
            self._capability_runner.mark_operational_mqtt_unhealthy(error=error)
        self._sync_operational_mqtt_health_schedule()

        if self._mqtt_recovery_store is None or not hasattr(self._mqtt_recovery_store, "record_restart_requested"):
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "reason": "mqtt_recovery_store_not_configured",
            }

        active_snapshot = self._mqtt_recovery_store.note_unhealthy(
            error=error,
            max_attempts=self._operational_mqtt_restart_max_attempts,
        )
        if int(active_snapshot.get("attempt_count") or 0) >= int(active_snapshot.get("max_attempts") or 0):
            exhausted = self._mqtt_recovery_store.mark_exhausted(
                error=error,
                max_attempts=self._operational_mqtt_restart_max_attempts,
            )
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "recovery": exhausted,
                "reason": "restart_attempts_exhausted",
            }

        if self._service_manager is None or not hasattr(self._service_manager, "schedule_restart"):
            exhausted = self._mqtt_recovery_store.mark_exhausted(
                error=error,
                max_attempts=self._operational_mqtt_restart_max_attempts,
            )
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "recovery": exhausted,
                "reason": "service_manager_cannot_schedule_restart",
            }
        try:
            scheduled_restart = self._service_manager.schedule_restart(
                target="backend",
                delay_seconds=self._operational_mqtt_restart_delay_seconds,
            )
        except Exception as exc:
            exhausted = self._mqtt_recovery_store.mark_exhausted(
                error=f"{error}; restart_schedule_failed: {exc}",
                max_attempts=self._operational_mqtt_restart_max_attempts,
            )
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "recovery": exhausted,
                "reason": "restart_schedule_failed",
            }

        recovery = self._mqtt_recovery_store.record_restart_requested(
            error=error,
            delay_seconds=self._operational_mqtt_restart_delay_seconds,
            max_attempts=self._operational_mqtt_restart_max_attempts,
        )
        await asyncio.sleep(self._operational_mqtt_restart_delay_seconds + 1)
        return {
            "status": "unhealthy",
            "lifecycle_state": self._lifecycle.get_state().value,
            "health": health,
            "restart_scheduled": True,
            "scheduled_restart": scheduled_restart,
            "recovery": recovery,
        }

    def debug_providers_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "providers_snapshot"):
            return {"configured": False, "providers": []}
        snapshot = self._provider_runtime_manager.providers_snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {"providers": []})}

    def debug_provider_models_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "models_snapshot"):
            return {"configured": False, "providers": []}
        snapshot = self._provider_runtime_manager.models_snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {"providers": []})}

    def debug_provider_metrics_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "metrics_snapshot"):
            return {"configured": False, "providers": {}}
        snapshot = self._provider_runtime_manager.metrics_snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {"providers": {}})}

    def execution_observability_payload(self) -> dict:
        service = self._task_execution_service
        if service is None and self._provider_runtime_manager is not None:
            try:
                service = self._get_task_execution_service()
            except Exception:
                service = None
        if service is None or not hasattr(service, "lifecycle_tracker"):
            return {
                "configured": False,
                "active_tasks": [],
                "recent_history": [],
                "failure_reasons": {},
                "provider_usage": {},
                "model_usage": {},
                "admission": self.direct_execution_admission_payload(),
            }

        lifecycle_tracker = service.lifecycle_tracker
        active_payload = (
            lifecycle_tracker.active_payload()
            if hasattr(lifecycle_tracker, "active_payload")
            else {"active_tasks": [], "active_count": 0}
        )
        history_payload = (
            lifecycle_tracker.history_payload()
            if hasattr(lifecycle_tracker, "history_payload")
            else {"history": [], "history_count": 0}
        )
        metrics_payload = self.debug_provider_metrics_payload()
        providers = metrics_payload.get("providers") if isinstance(metrics_payload, dict) else {}
        failure_reasons: dict[str, int] = {}
        provider_usage: dict[str, dict] = {}
        model_usage: dict[str, dict] = {}

        if isinstance(providers, dict):
            for provider_id, provider_payload in providers.items():
                if not isinstance(provider_payload, dict):
                    continue
                provider_models = provider_payload.get("models")
                provider_totals = provider_payload.get("totals")
                if isinstance(provider_totals, dict):
                    provider_usage[str(provider_id)] = {
                        "total_requests": int(provider_totals.get("total_requests") or 0),
                        "successful_requests": int(provider_totals.get("successful_requests") or 0),
                        "failed_requests": int(provider_totals.get("failed_requests") or 0),
                        "success_rate": provider_totals.get("success_rate"),
                    }
                if not isinstance(provider_models, dict):
                    continue
                for model_id, model_payload in provider_models.items():
                    if not isinstance(model_payload, dict):
                        continue
                    failure_classes = model_payload.get("failure_classes")
                    if isinstance(failure_classes, dict):
                        for reason, count in failure_classes.items():
                            key = str(reason or "").strip()
                            if not key:
                                continue
                            failure_reasons[key] = failure_reasons.get(key, 0) + int(count or 0)
                    model_usage_key = f"{provider_id}:{model_id}"
                    model_usage[model_usage_key] = {
                        "provider_id": str(provider_id),
                        "model_id": str(model_id),
                        "total_requests": int(model_payload.get("total_requests") or 0),
                        "successful_requests": int(model_payload.get("successful_requests") or 0),
                        "failed_requests": int(model_payload.get("failed_requests") or 0),
                        "success_rate": model_payload.get("success_rate"),
                        "avg_latency": model_payload.get("avg_latency"),
                        "p95_latency": model_payload.get("p95_latency"),
                    }

        return {
            "configured": True,
            "active_tasks": list(active_payload.get("active_tasks") or []),
            "recent_history": list(history_payload.get("history") or []),
            "failure_reasons": failure_reasons,
            "provider_usage": provider_usage,
            "model_usage": model_usage,
            "admission": self.direct_execution_admission_payload(),
        }

    def recover_from_degraded(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "recover_from_degraded"):
            raise ValueError("degraded recovery is not configured")
        result = self._capability_runner.recover_from_degraded()
        self._phase2_diag.degraded_recovery(
            {
                "source": "node_control_api",
                "event": "recover_invoked",
                "result": result.get("status"),
                "target_state": result.get("target_state"),
            }
        )
        return result

    def governance_status_payload(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "status_payload"):
            return {"configured": False, "status": None}
        status = self._capability_runner.status_payload()
        return {"configured": True, "status": status.get("governance_status")}

    def _start_bootstrap_runner_if_available(self) -> None:
        if self._bootstrap_runner is None or self._bootstrap_config is None:
            return
        self._bootstrap_runner.start(
            bootstrap_host=self._bootstrap_config.bootstrap_host,
            port=self._bootstrap_config.port,
            topic=self._bootstrap_config.topic,
            node_name=self._bootstrap_config.node_name,
        )

    def _start_bootstrap_listener_if_available(self) -> None:
        if self._bootstrap_runner is None:
            return
        if self._bootstrap_config is not None:
            self._start_bootstrap_runner_if_available()
            return
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        if not isinstance(trust_state, dict):
            return
        bootstrap_host = str(
            trust_state.get("bootstrap_mqtt_host") or trust_state.get("operational_mqtt_host") or ""
        ).strip()
        node_name = str(trust_state.get("node_name") or "").strip()
        if not bootstrap_host or not node_name:
            return
        self._bootstrap_runner.start(
            bootstrap_host=bootstrap_host,
            port=BOOTSTRAP_PORT,
            topic=BOOTSTRAP_TOPIC,
            node_name=node_name,
        )

    def initiate_onboarding(self, *, mqtt_host: str, node_name: str) -> dict:
        if self._lifecycle.get_state() != NodeLifecycleState.UNCONFIGURED:
            raise ValueError("node is not in unconfigured state")

        config = create_bootstrap_config(
            {
                "bootstrap_host": mqtt_host,
                "node_name": node_name,
            }
        )
        self._bootstrap_config = config
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(
                {
                    "bootstrap_host": config.bootstrap_host,
                    "node_name": config.node_name,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._lifecycle.transition_to(
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            {"source": "setup_ui"},
        )
        self._start_bootstrap_runner_if_available()
        return self.status_payload()

    def restart_setup(self) -> dict:
        if self._bootstrap_runner is not None and hasattr(self._bootstrap_runner, "stop"):
            self._bootstrap_runner.stop()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "cancel"):
            self._onboarding_runtime.cancel()

        self._bootstrap_config = None
        if self._config_path.exists():
            self._config_path.unlink()
        self._lifecycle.reset_to_unconfigured({"source": "setup_ui_restart"})
        return self.status_payload()

    def handle_node_identity_change(self, node_id: str) -> None:
        normalized = str(node_id or "").strip()
        if not normalized:
            raise ValueError("node_id is required")
        self._node_id = normalized
        self._identity_state = "valid"
        if self._capability_runner is not None and hasattr(self._capability_runner, "update_node_id"):
            self._capability_runner.update_node_id(normalized)

    def rerequest_trust(self) -> dict:
        current_state = self._lifecycle.get_state()
        if current_state in {
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            NodeLifecycleState.BOOTSTRAP_CONNECTED,
            NodeLifecycleState.CORE_DISCOVERED,
            NodeLifecycleState.REGISTRATION_PENDING,
            NodeLifecycleState.PENDING_APPROVAL,
        }:
            raise ValueError("trust re-request is unavailable while onboarding is already in progress")

        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        bootstrap_host = ""
        node_name = ""
        if isinstance(trust_state, dict):
            bootstrap_host = str(
                trust_state.get("bootstrap_mqtt_host") or trust_state.get("operational_mqtt_host") or ""
            ).strip()
            node_name = str(trust_state.get("node_name") or "").strip()
        if not bootstrap_host and self._bootstrap_config is not None:
            bootstrap_host = str(self._bootstrap_config.bootstrap_host or "").strip()
        if not node_name and self._bootstrap_config is not None:
            node_name = str(self._bootstrap_config.node_name or "").strip()
        if not bootstrap_host:
            raise ValueError("bootstrap host is unavailable for trust re-request")
        if not node_name:
            raise ValueError("node name is unavailable for trust re-request")

        if self._bootstrap_runner is not None and hasattr(self._bootstrap_runner, "stop"):
            self._bootstrap_runner.stop()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "cancel"):
            self._onboarding_runtime.cancel()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "prepare_retrust"):
            self._onboarding_runtime.prepare_retrust(allow_identity_reset_on_duplicate=True)

        self._bootstrap_config = create_bootstrap_config(
            {
                "bootstrap_host": bootstrap_host,
                "node_name": node_name,
            }
        )
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(
                {
                    "bootstrap_host": self._bootstrap_config.bootstrap_host,
                    "node_name": self._bootstrap_config.node_name,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._clear_persisted_store(self._trust_state_store)
        self._clear_persisted_store(self._governance_state_store)
        if self._capability_runner is not None and hasattr(self._capability_runner, "clear_local_state_for_reonboarding"):
            self._capability_runner.clear_local_state_for_reonboarding()
        self._trusted_runtime_context = {}
        self._startup_mode = "bootstrap_onboarding"
        self._lifecycle.reset_to_unconfigured({"source": "trust_rerequest"})
        self._lifecycle.transition_to(
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            {"source": "trust_rerequest"},
        )
        self._start_bootstrap_runner_if_available()
        return {
            "status": "started",
            "flow": "trust_rerequest",
            "lifecycle_state": self._lifecycle.get_state().value,
            "bootstrap_host": self._bootstrap_config.bootstrap_host,
            "node_name": self._bootstrap_config.node_name,
            "node_id": self._node_id,
        }


class OnboardingInitiateRequest(BaseModel):
    mqtt_host: str
    node_name: str


class ProviderSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openai_enabled: bool
    local_enabled: bool | None = None
    provider_budget_limits: dict[str, dict[str, int | str | None]] | None = None


class OpenAICredentialsRequest(BaseModel):
    api_token: str
    service_token: str
    project_name: str


class OpenAIPreferencesRequest(BaseModel):
    default_model_id: str | None = None
    selected_model_ids: list[str] | None = None


class TaskCapabilitySelectionRequest(BaseModel):
    selected_task_families: list[str]


class ServiceRestartRequest(BaseModel):
    target: str


class ProviderCapabilityRefreshRequest(BaseModel):
    force_refresh: bool = False


class OpenAIPricingRefreshRequest(BaseModel):
    force_refresh: bool = True


class OpenAIManualPricingRequest(BaseModel):
    model_id: str
    display_name: str | None = None
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None


class OpenAIEnabledModelsRequest(BaseModel):
    model_ids: list[str]


class BudgetDeclarationRequest(BaseModel):
    provider_id: str = "openai"


class RefreshTriggerRequest(BaseModel):
    force_refresh: bool = True


class PromptServiceRegisterRequest(BaseModel):
    prompt_id: str
    service_id: str
    task_family: str
    prompt_name: str | None = None
    owner_service: str | None = None
    owner_client_id: str | None = None
    privacy_class: str = "internal"
    access_scope: str = "service"
    allowed_services: list[str] | None = None
    allowed_clients: list[str] | None = None
    allowed_customers: list[str] | None = None
    execution_policy: dict | None = None
    provider_preferences: dict | None = None
    constraints: dict | None = None
    definition: dict | None = None
    output_contract: dict | None = None
    benchmark: dict | None = None
    version: str | None = None
    status: str = "active"
    metadata: dict | None = None


class PromptServiceUpdateRequest(BaseModel):
    prompt_name: str | None = None
    owner_service: str | None = None
    owner_client_id: str | None = None
    task_family: str | None = None
    privacy_class: str | None = None
    access_scope: str | None = None
    allowed_services: list[str] | None = None
    allowed_clients: list[str] | None = None
    allowed_customers: list[str] | None = None
    execution_policy: dict | None = None
    provider_preferences: dict | None = None
    constraints: dict | None = None
    definition: dict | None = None
    output_contract: dict | None = None
    benchmark: dict | None = None
    version: str | None = None
    metadata: dict | None = None


class PromptProbationRequest(BaseModel):
    action: str
    reason: str | None = None


class PromptLifecycleRequest(BaseModel):
    state: str
    reason: str | None = None


class PromptReviewRequest(BaseModel):
    reviewed_by: str | None = None
    review_reason: str | None = None
    state: str | None = "active"


class PromptReviewDueMigrationRequest(BaseModel):
    reason: str | None = "policy_migration_review_due"


class ImageGenerationTemplateVersionRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    version: str | None = None
    runtime_id: str | None = "comfyui_gpu"
    api_workflow_path: str
    ui_workflow_path: str | None = None
    variables: list[str] | None = None
    defaults: dict | None = None
    model_requirements: dict | None = None
    output_scope: str | None = "normal"
    metadata: dict | None = None


class ImageGenerationTemplateRegisterRequest(BaseModel):
    template_id: str
    service_id: str
    template_name: str | None = None
    owner_service: str | None = None
    owner_client_id: str | None = None
    privacy_class: str = "internal"
    access_scope: str = "service"
    allowed_services: list[str] | None = None
    allowed_clients: list[str] | None = None
    allowed_customers: list[str] | None = None
    template_version: ImageGenerationTemplateVersionRequest
    version: str | None = None
    status: str = "active"
    metadata: dict | None = None


class ImageGenerationTemplateUpdateRequest(BaseModel):
    template_name: str | None = None
    owner_service: str | None = None
    owner_client_id: str | None = None
    privacy_class: str | None = None
    access_scope: str | None = None
    allowed_services: list[str] | None = None
    allowed_clients: list[str] | None = None
    allowed_customers: list[str] | None = None
    template_version: ImageGenerationTemplateVersionRequest | None = None
    version: str | None = None
    metadata: dict | None = None


class ImageGenerationTemplateLifecycleRequest(BaseModel):
    state: str
    reason: str | None = None


class ImageGenerationTemplateReviewRequest(BaseModel):
    reviewed_by: str | None = None
    review_reason: str | None = None
    state: str | None = "active"


class ManualImageGenerationRequest(BaseModel):
    template_id: str | None = None
    mode: str = "txt2img"
    prompt: str
    negative_prompt: str | None = None
    width: int | None = None
    height: int | None = None
    seed: int | str | None = None
    steps: int | None = None
    cfg: float | None = None
    denoise: float | None = None
    batch_count: int | str | None = 1
    randomize_seed: bool | None = False
    randomize_reference_strengths: bool | None = False
    reference_strength_jitter: float | str | None = 0.05
    input_image: str | None = None
    reference_image_filename: str | None = None
    reference_image_data_base64: str | None = None
    template_variables: dict | None = None
    create_lora_metadata: bool | None = False


class ManualImagePromptHelperRequest(BaseModel):
    template_id: str | None = None
    mode: str = "txt2img"
    prompt: str | None = None
    negative_prompt: str | None = None
    width: int | None = None
    height: int | None = None
    reference_image_provided: bool | None = False


class ManualImagePoseHelperRequest(BaseModel):
    template_id: str | None = None
    pose_text: str
    current_pose_prompt: str | None = None
    avatar_name: str | None = None
    width: int | None = None
    height: int | None = None
    generate_reference: bool | None = True


class ManualImageReferenceUploadRequest(BaseModel):
    category: str = "avatar"
    role: str | None = "reference"
    name: str | None = None
    filename: str | None = None
    data_base64: str


class ManualImageVisionDescribeRequest(BaseModel):
    mode: str = "avatar"
    custom_prompt: str | None = None
    reference_relative_path: str | None = None
    image_filename: str | None = None
    image_data_base64: str | None = None


class AvatarProfileSaveRequest(BaseModel):
    name: str
    description: str | None = None
    gender: str | None = None
    skin_color: str | None = None
    hair_color: str | None = None
    character_type: str | None = None
    visual_style: str | None = None
    initial_data: str | None = None
    nsfw: bool | None = None
    face_image_filename: str | None = None
    face_image_data_base64: str | None = None
    body_image_filename: str | None = None
    body_image_data_base64: str | None = None


class AvatarProfileExtractionUpdateRequest(BaseModel):
    face_description: str | None = None
    body_description: str | None = None
    structured: dict | None = None


class AvatarProfileHeadPromptRefineRequest(BaseModel):
    current_prompt: str | None = None
    prompt_parts: dict | None = None
    negative_prompt: str | None = None
    user_message: str


class AvatarProfileHeadPreviewRequest(BaseModel):
    prompt: str | None = None
    prompt_parts: dict | None = None
    negative_prompt: str | None = None


class AvatarProfileReferenceUploadRequest(BaseModel):
    role: str
    name: str | None = None
    filename: str | None = None
    data_base64: str


class AvatarPrimaryFaceRequest(BaseModel):
    filename: str


class AvatarFaceProfileExtractRequest(BaseModel):
    source_filenames: list[str] | None = None


class AvatarBodyDepthProfileGenerateRequest(BaseModel):
    source_filenames: list[str] | None = None
    width: int | None = 768
    height: int | None = 1152
    depth_resolution: int | None = 1024
    depth_model: str | None = "depth_anything_v2_vits.pth"
    bg_removal_model: str | None = "birefnet.safetensors"
    replace_source_images: bool | None = True


class ExecutionAuthorizeRequest(BaseModel):
    prompt_id: str
    task_family: str
    prompt_version: str | None = None
    requested_by: str | None = None
    service_id: str | None = None
    customer_id: str | None = None
    requested_provider: str | None = None
    requested_model: str | None = None
    inputs: dict | None = None


class ExecutionJobCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class ExecutionCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_family: str
    prompt: str | None = None
    system_prompt: str | None = None
    messages: list[dict] | None = None
    providers: list[dict]
    temperature: float | None = None
    max_tokens: int | None = None


class BenchmarkExecutionTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str | None = None
    provider: str | None = None
    model: str | None = None
    role: str = "candidate"
    timeout_s: int | None = None


class BenchmarkExecutionV2Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_id: str
    prompt_id: str | None = None
    prompt_version: str | None = None
    task_family: str
    requested_by: str
    service_id: str | None = None
    customer_id: str | None = None
    inputs: dict
    output_contract: dict | None = None
    targets: list[BenchmarkExecutionTargetRequest]
    timeout_s: int = 120
    trace_id: str
    metadata: dict | None = None


def _metadata_with_v2_contracts(
    *,
    metadata: dict | None,
    output_contract: dict | None = None,
    benchmark: dict | None = None,
) -> dict | None:
    merged = dict(metadata or {}) if isinstance(metadata, dict) else {}
    if isinstance(output_contract, dict):
        merged["output_contract"] = output_contract
    if isinstance(benchmark, dict):
        merged["benchmark"] = benchmark
    return merged or None


def create_node_control_app(*, state: NodeControlState, logger) -> FastAPI:
    app = FastAPI(title="Hexe AI Node Control API", version="0.1.0")
    configured_admin_token = str(os.environ.get("HEXE_ADMIN_TOKEN") or "").strip()

    def require_admin(admin_token: str | None) -> None:
        if not configured_admin_token:
            return
        if str(admin_token or "").strip() != configured_admin_token:
            raise HTTPException(status_code=403, detail="admin access required")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _metrics_middleware(request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            if hasattr(state, "record_request_metrics"):
                state.record_request_metrics(duration_ms=duration_ms, status_code=status_code)

    @app.on_event("startup")
    async def _startup_jobs():
        if hasattr(state, "start_background_jobs"):
            await state.start_background_jobs()

    @app.on_event("shutdown")
    async def _shutdown_jobs():
        if hasattr(state, "stop_background_jobs"):
            await state.stop_background_jobs()

    @app.get("/")
    def root():
        return {
            "service": "hexe-ai-node-control-api",
            "status": "ok",
            "version": "0.1.0",
            "endpoints": [
                "/api/node/status",
                "/api/onboarding/initiate",
                "/api/onboarding/restart",
                "/api/providers/config",
                "/api/providers/openai/credentials",
                "/api/providers/openai/preferences",
                "/api/providers/openai/models/latest",
                "/api/providers/openai/pricing/diagnostics",
                "/api/providers/openai/pricing/manual",
                "/api/providers/openai/pricing/refresh",
                "/api/providers/local/capability-resolution",
                "/api/providers/models/by-task/{task_family}",
                "/api/capabilities/config",
                "/api/capabilities/declare",
                "/api/governance/status",
                "/api/governance/refresh",
                "/api/budgets/state",
                "/api/budgets/declare",
                "/api/budgets/refresh",
                "/api/capabilities/providers/refresh",
                "/api/node/retrust",
                "/api/node/recover",
                "/api/prompts/services",
                "/api/prompts/services/{prompt_id}",
                "/api/prompts/services/{prompt_id}/lifecycle",
                "/api/prompts/services/{prompt_id}/probation",
                "/api/image-templates",
                "/api/image-templates/{template_id}",
                "/api/image-templates/{template_id}/lifecycle",
                "/api/image-templates/{template_id}/review",
                "/api/schemas/client-ai/v2",
                "/api/schemas/client-ai/v2/communication.md",
                "/api/schemas/client-ai/v2/{schema_name}",
                "/api/execution/authorize",
                "/api/execution/admission",
                "/api/execution/route-preview",
                "/api/execution/jobs/{job_id}",
                "DELETE /api/execution/jobs/{job_id}",
                "/api/execution/queues",
                "/api/local-runtimes/assignments",
                "/api/local-runtimes/assignments/{task_family}",
                "/api/comfyui/templates",
                "/api/comfyui/templates/{template_id}",
                "/api/comfyui/gpu/presets",
                "/api/comfyui/gpu/presets/{preset_id}",
                "/api/execution/compare",
                "/api/benchmarks/execution/v2",
                "/api/services/status",
                "/api/services/comfyui-webui/preflight",
                "/api/services/start",
                "/api/services/stop",
                "/api/services/restart",
                "/debug/providers",
                "/debug/providers/models",
                "/debug/providers/metrics",
                "/debug/prompts",
                "/debug/execution",
                "/debug/execution/admission",
                "/api/health",
            ],
        }

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/schemas/client-ai/v2")
    def get_client_ai_v2_schema_catalog():
        return state.client_ai_v2_schema_catalog()

    @app.get("/api/schemas/client-ai/v2/communication.md")
    def get_client_ai_v2_communication_markdown():
        try:
            return Response(
                content=state.client_ai_v2_communication_markdown(),
                media_type="text/markdown; charset=utf-8",
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/schemas/client-ai/v2/{schema_name}")
    def get_client_ai_v2_schema(schema_name: str):
        try:
            return state.client_ai_v2_schema_document(schema_name=schema_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/node/status")
    def get_node_status():
        return state.status_payload()

    @app.post("/api/onboarding/initiate")
    def post_onboarding_initiate(payload: OnboardingInitiateRequest):
        try:
            return state.initiate_onboarding(
                mqtt_host=payload.mqtt_host,
                node_name=payload.node_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/onboarding/restart")
    def post_onboarding_restart():
        return state.restart_setup()

    @app.get("/api/providers/config")
    def get_provider_config():
        return state.provider_selection_payload()

    @app.post("/api/providers/config")
    async def post_provider_config(payload: ProviderSelectionRequest):
        try:
            response = state.update_provider_selection(
                openai_enabled=payload.openai_enabled,
                local_enabled=payload.local_enabled,
                provider_budget_limits=payload.provider_budget_limits,
            )
            return {**response, "declaration": {"status": "pending_manual", "reason": "provider_configuration_changed"}}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/providers/openai/credentials")
    def get_openai_credentials():
        return state.provider_credentials_payload(provider_id="openai")

    @app.post("/api/providers/openai/credentials")
    async def post_openai_credentials(payload: OpenAICredentialsRequest):
        try:
            response = state.update_openai_credentials(
                api_token=payload.api_token,
                service_token=payload.service_token,
                project_name=payload.project_name,
            )
            await state.refresh_provider_models_after_openai_credentials_save()
            return response
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/providers/openai/preferences")
    def post_openai_preferences(payload: OpenAIPreferencesRequest):
        try:
            return state.update_openai_preferences(
                default_model_id=payload.default_model_id,
                selected_model_ids=payload.selected_model_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/providers/openai/models/latest")
    def get_openai_latest_models(limit: int = 3):
        return state.latest_provider_models_payload(provider_id="openai", limit=limit)

    @app.get("/api/providers/openai/models/catalog")
    def get_openai_model_catalog():
        return state.openai_provider_model_catalog_payload()

    @app.get("/api/providers/openai/models/capabilities")
    def get_openai_model_capabilities():
        return state.openai_provider_model_capabilities_payload()

    @app.get("/api/providers/openai/models/features")
    def get_openai_model_features():
        return state.openai_model_features_payload()

    @app.get("/api/providers/openai/models/enabled")
    def get_openai_enabled_models():
        return state.openai_enabled_models_payload()

    @app.post("/api/providers/openai/models/enabled")
    async def post_openai_enabled_models(payload: OpenAIEnabledModelsRequest):
        try:
            response = await state.update_openai_enabled_models_with_redeclaration(model_ids=payload.model_ids)
            await state.notify_workflow_request(
                workflow_request="openai_enabled_models_update",
                workflow_status="done",
                details={
                    "model_count": len(response.get("models") or []),
                    "task_surface_changed": bool(response.get("task_surface_changed")),
                    "resolved_task_count": len(response.get("resolved_tasks") or []),
                    "declaration_status": (response.get("declaration") or {}).get("status"),
                    "declaration_reason": (response.get("declaration") or {}).get("reason"),
                },
            )
            return response
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="openai_enabled_models_update",
                workflow_status="stopped",
                details={"error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/providers/openai/capability-resolution")
    def get_openai_capability_resolution():
        return state.openai_resolved_capabilities_payload()

    @app.get("/api/providers/local/capability-resolution")
    def get_local_capability_resolution():
        return state.local_resolved_capabilities_payload()

    @app.get("/api/providers/models/by-task/{task_family}")
    def get_provider_models_by_task(task_family: str):
        try:
            return state.models_for_task_payload(task_family=task_family)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/capabilities/node/resolved")
    def get_node_capabilities():
        return state.node_capabilities_payload()

    @app.get("/api/providers/openai/pricing/diagnostics")
    def get_openai_pricing_diagnostics():
        return state.openai_pricing_diagnostics_payload()

    @app.post("/api/providers/openai/pricing/refresh")
    async def post_openai_pricing_refresh(payload: OpenAIPricingRefreshRequest):
        try:
            response = await state.refresh_openai_pricing(force_refresh=payload.force_refresh)
            await state.notify_workflow_request(
                workflow_request="openai_pricing_refresh",
                workflow_status="done",
                details={"force_refresh": payload.force_refresh, "status": response.get("status")},
            )
            return response
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="openai_pricing_refresh",
                workflow_status="stopped",
                details={"force_refresh": payload.force_refresh, "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/providers/openai/models/classification/refresh")
    async def post_openai_model_capabilities_refresh(
        x_admin_token: str | None = Header(default=None, alias="X-Hexe-Admin-Token")
    ):
        try:
            require_admin(x_admin_token)
            response = await state.rerun_openai_model_capabilities()
            payload = {**response, "declaration": {"status": "pending_manual", "reason": "capability_catalog_refresh"}}
            await state.notify_workflow_request(
                workflow_request="openai_model_classification_refresh",
                workflow_status="done",
                details={
                    "status": payload.get("status"),
                    "classification_model": payload.get("classification_model"),
                    "entry_count": len(payload.get("entries") or []),
                },
            )
            return payload
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="openai_model_classification_refresh",
                workflow_status="stopped",
                details={"error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/providers/openai/pricing/manual")
    def post_openai_manual_pricing(payload: OpenAIManualPricingRequest):
        try:
            return state.save_openai_manual_pricing(
                model_id=payload.model_id,
                display_name=payload.display_name,
                input_price_per_1m=payload.input_price_per_1m,
                output_price_per_1m=payload.output_price_per_1m,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/capabilities/config")
    def get_capabilities_config():
        return state.task_capability_selection_payload()

    @app.post("/api/capabilities/config")
    def post_capabilities_config(payload: TaskCapabilitySelectionRequest):
        try:
            return state.update_task_capability_selection(selected_task_families=payload.selected_task_families)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/declare")
    async def post_capability_declare():
        try:
            return await state.submit_capability_declaration()
        except CapabilityDeclarationPrerequisiteError as exc:
            raise HTTPException(status_code=409, detail=exc.payload) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/rebuild")
    async def post_capability_rebuild(
        x_admin_token: str | None = Header(default=None, alias="X-Hexe-Admin-Token")
    ):
        try:
            require_admin(x_admin_token)
            response = await state.rebuild_node_capabilities()
            await state.notify_workflow_request(
                workflow_request="node_capability_rebuild",
                workflow_status="done",
                details={"status": response.get("status"), "resolved_task_count": len(response.get("resolved_tasks") or [])},
            )
            return response
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="node_capability_rebuild",
                workflow_status="stopped",
                details={"error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/redeclare")
    async def post_capability_redeclare(
        payload: RefreshTriggerRequest,
        x_admin_token: str | None = Header(default=None, alias="X-Hexe-Admin-Token"),
    ):
        try:
            require_admin(x_admin_token)
            return await state.redeclare_capabilities(reason="manual_redeclare", force=payload.force_refresh)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/governance/status")
    def get_governance_status():
        return state.governance_status_payload()

    @app.post("/api/governance/refresh")
    async def post_governance_refresh():
        try:
            return await state.refresh_governance()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/budgets/state")
    def get_budget_state():
        return state.budget_state_payload()

    @app.get("/api/usage/clients")
    def get_client_usage():
        return state.client_usage_payload()

    @app.post("/api/budgets/declare")
    async def post_budget_declare(payload: BudgetDeclarationRequest):
        try:
            return await state.declare_budget_to_core(provider_id=payload.provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/budgets/refresh")
    async def post_budget_refresh():
        try:
            return await state.refresh_budget_policy()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/providers/refresh")
    async def post_provider_capability_refresh(
        payload: ProviderCapabilityRefreshRequest,
        x_admin_token: str | None = Header(default=None, alias="X-Hexe-Admin-Token"),
    ):
        try:
            require_admin(x_admin_token)
            response = await state.refresh_provider_capabilities(force_refresh=payload.force_refresh)
            result = {**response, "declaration": {"status": "pending_manual", "reason": "provider_capability_refresh"}}
            await state.notify_workflow_request(
                workflow_request="provider_capability_refresh",
                workflow_status="done",
                details={"force_refresh": payload.force_refresh, "status": result.get("status"), "changed": result.get("changed")},
            )
            return result
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="provider_capability_refresh",
                workflow_status="stopped",
                details={"force_refresh": payload.force_refresh, "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/node/recover")
    def post_node_recover():
        try:
            return state.recover_from_degraded()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/node/retrust")
    def post_node_retrust():
        try:
            return state.rerequest_trust()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/prompts/services")
    def get_prompt_services():
        return state.prompt_service_state_payload()

    @app.post("/api/prompts/services")
    def post_prompt_services(payload: PromptServiceRegisterRequest):
        try:
            return state.register_prompt_service(
                prompt_id=payload.prompt_id,
                service_id=payload.service_id,
                task_family=payload.task_family,
                metadata=payload.metadata,
                prompt_name=payload.prompt_name,
                owner_service=payload.owner_service,
                owner_client_id=payload.owner_client_id,
                privacy_class=payload.privacy_class,
                access_scope=payload.access_scope,
                allowed_services=payload.allowed_services,
                allowed_clients=payload.allowed_clients,
                allowed_customers=payload.allowed_customers,
                execution_policy=payload.execution_policy,
                provider_preferences=payload.provider_preferences,
                constraints=payload.constraints,
                definition=payload.definition,
                output_contract=payload.output_contract,
                benchmark=payload.benchmark,
                version=payload.version,
                status=payload.status,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/prompts/services/{prompt_id}")
    def get_prompt_service(prompt_id: str):
        try:
            return state.get_prompt_service(prompt_id=prompt_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/prompts/services/{prompt_id}")
    def put_prompt_service(prompt_id: str, payload: PromptServiceUpdateRequest):
        try:
            return state.update_prompt_service(
                prompt_id=prompt_id,
                prompt_name=payload.prompt_name,
                owner_service=payload.owner_service,
                owner_client_id=payload.owner_client_id,
                task_family=payload.task_family,
                privacy_class=payload.privacy_class,
                access_scope=payload.access_scope,
                allowed_services=payload.allowed_services,
                allowed_clients=payload.allowed_clients,
                allowed_customers=payload.allowed_customers,
                execution_policy=payload.execution_policy,
                provider_preferences=payload.provider_preferences,
                constraints=payload.constraints,
                metadata=payload.metadata,
                definition=payload.definition,
                output_contract=payload.output_contract,
                benchmark=payload.benchmark,
                version=payload.version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/services/{prompt_id}/lifecycle")
    def post_prompt_lifecycle(prompt_id: str, payload: PromptLifecycleRequest):
        try:
            return state.transition_prompt_service(prompt_id=prompt_id, state=payload.state, reason=payload.reason)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/services/{prompt_id}/probation")
    def post_prompt_probation(prompt_id: str, payload: PromptProbationRequest):
        try:
            return state.update_prompt_probation(
                prompt_id=prompt_id,
                action=payload.action,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/services/{prompt_id}/review")
    def post_prompt_review(prompt_id: str, payload: PromptReviewRequest):
        try:
            return state.review_prompt_service(
                prompt_id=prompt_id,
                reviewed_by=payload.reviewed_by,
                review_reason=payload.review_reason,
                state=payload.state,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/services/migrations/review-due")
    def post_prompt_review_due_migration(payload: PromptReviewDueMigrationRequest):
        try:
            return state.migrate_prompt_services_to_review_due(reason=payload.reason or "policy_migration_review_due")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/image-templates")
    def get_image_generation_templates():
        return state.image_generation_template_state_payload()

    @app.post("/api/image-templates")
    def post_image_generation_template(payload: ImageGenerationTemplateRegisterRequest):
        try:
            return state.register_image_generation_template(
                template_id=payload.template_id,
                service_id=payload.service_id,
                template_name=payload.template_name,
                owner_service=payload.owner_service,
                owner_client_id=payload.owner_client_id,
                privacy_class=payload.privacy_class,
                access_scope=payload.access_scope,
                allowed_services=payload.allowed_services,
                allowed_clients=payload.allowed_clients,
                allowed_customers=payload.allowed_customers,
                template_version=payload.template_version.model_dump(exclude_none=True),
                version=payload.version,
                status=payload.status,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/image-templates/{template_id}")
    def get_image_generation_template(template_id: str):
        try:
            return state.get_image_generation_template(template_id=template_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/image-templates/{template_id}")
    def put_image_generation_template(template_id: str, payload: ImageGenerationTemplateUpdateRequest):
        try:
            return state.update_image_generation_template(
                template_id=template_id,
                template_name=payload.template_name,
                owner_service=payload.owner_service,
                owner_client_id=payload.owner_client_id,
                privacy_class=payload.privacy_class,
                access_scope=payload.access_scope,
                allowed_services=payload.allowed_services,
                allowed_clients=payload.allowed_clients,
                allowed_customers=payload.allowed_customers,
                template_version=payload.template_version.model_dump(exclude_none=True)
                if payload.template_version is not None
                else None,
                version=payload.version,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/image-templates/{template_id}/lifecycle")
    def post_image_generation_template_lifecycle(template_id: str, payload: ImageGenerationTemplateLifecycleRequest):
        try:
            return state.transition_image_generation_template(
                template_id=template_id,
                state=payload.state,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/image-templates/{template_id}/review")
    def post_image_generation_template_review(template_id: str, payload: ImageGenerationTemplateReviewRequest):
        try:
            return state.review_image_generation_template(
                template_id=template_id,
                reviewed_by=payload.reviewed_by,
                review_reason=payload.review_reason,
                state=payload.state,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/execution/authorize")
    def post_execution_authorize(payload: ExecutionAuthorizeRequest):
        return state.authorize_execution(
            prompt_id=payload.prompt_id,
            task_family=payload.task_family,
            prompt_version=payload.prompt_version,
            requested_by=payload.requested_by,
            service_id=payload.service_id,
            customer_id=payload.customer_id,
            requested_provider=payload.requested_provider,
            requested_model=payload.requested_model,
            inputs=payload.inputs,
        )

    @app.get("/api/execution/admission")
    def get_execution_admission():
        return state.direct_execution_admission_payload()

    @app.post("/api/execution/direct")
    async def post_execution_direct(payload: TaskExecutionRequest):
        try:
            return await state.execute_direct(request=payload)
        except DirectExecutionBusyError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.payload,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/execution/route-preview")
    async def post_execution_route_preview(payload: TaskExecutionRequest):
        try:
            return await state.preview_direct_execution_route(request=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/execution/jobs/{job_id}")
    async def get_execution_job(job_id: str):
        payload = await state.execution_job_status(job_id=job_id)
        if payload.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="job_not_found")
        return payload

    @app.delete("/api/execution/jobs/{job_id}")
    async def delete_execution_job(job_id: str, payload: ExecutionJobCancelRequest | None = None):
        response = await state.cancel_execution_job(
            job_id=job_id,
            reason=payload.reason if payload is not None else None,
        )
        if response.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="job_not_found")
        if response.get("cancel_rejected_reason"):
            raise HTTPException(status_code=409, detail=response)
        return response

    @app.get("/api/execution/queues")
    async def get_execution_queues():
        return await state.execution_queue_diagnostics()

    @app.get("/api/local-runtimes/assignments")
    def get_local_runtime_assignments():
        return state.local_runtime_assignments_payload()

    @app.get("/api/local-runtimes/assignments/{task_family}")
    def get_local_runtime_assignment(
        task_family: str,
        priority: str | None = None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
    ):
        return state.local_runtime_assignment_payload(
            task_family=task_family,
            priority=priority,
            requested_provider=requested_provider,
            requested_model=requested_model,
        )

    @app.get("/api/comfyui/templates")
    def get_comfyui_templates():
        return state.comfyui_template_catalog_payload()

    @app.get("/api/comfyui/templates/{template_id}")
    def get_comfyui_template(template_id: str):
        try:
            return state.get_comfyui_template_catalog_entry(template_id=template_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/comfyui/gpu/presets")
    def get_comfyui_gpu_presets():
        return state.comfyui_gpu_presets_payload()

    @app.get("/api/comfyui/gpu/presets/{preset_id}")
    def get_comfyui_gpu_preset(preset_id: str):
        payload = state.comfyui_gpu_preset_payload(preset_id=preset_id)
        if payload.get("status") == "not_found":
            raise HTTPException(status_code=404, detail=payload)
        return payload

    @app.get("/api/manual-image-generation")
    def get_manual_image_generation():
        return state.manual_image_generation_status()

    @app.post("/api/manual-image-generation")
    async def post_manual_image_generation(payload: ManualImageGenerationRequest):
        try:
            return await state.submit_manual_image_generation(payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/manual-image-generation/prompt-helper")
    def post_manual_image_generation_prompt_helper(payload: ManualImagePromptHelperRequest):
        try:
            return state.manual_image_prompt_helper(payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/manual-image-generation/pose-helper")
    def post_manual_image_generation_pose_helper(payload: ManualImagePoseHelperRequest):
        try:
            return state.manual_image_pose_helper(payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/manual-image-generation/references")
    def post_manual_image_generation_reference(payload: ManualImageReferenceUploadRequest):
        try:
            return state.upload_manual_image_reference(payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/manual-image-generation/references/{relative_path:path}")
    def get_manual_image_generation_reference(relative_path: str):
        try:
            return state.manual_image_reference_response(relative_path=relative_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/manual-image-generation/references/{relative_path:path}")
    def delete_manual_image_generation_reference(relative_path: str):
        try:
            return state.delete_manual_image_reference(relative_path=relative_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/manual-image-generation/vision-describe")
    def post_manual_image_generation_vision_describe(payload: ManualImageVisionDescribeRequest):
        try:
            return state.manual_image_vision_describe(payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/manual-image-generation/outputs/{relative_path:path}")
    def get_manual_image_generation_output(relative_path: str):
        try:
            return state.manual_image_output_response(relative_path=relative_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/manual-image-generation/outputs/{relative_path:path}")
    def delete_manual_image_generation_output(relative_path: str):
        try:
            return state.delete_manual_image_output(relative_path=relative_path)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/avatar-generation")
    def get_avatar_generation():
        return state.avatar_generation_status()

    @app.post("/api/avatar-generation/profiles")
    def post_avatar_generation_profile(payload: AvatarProfileSaveRequest):
        try:
            return state.save_avatar_profile(payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/select")
    def post_avatar_generation_profile_select(profile_id: str):
        try:
            return state.select_avatar_profile(profile_id=profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/references")
    def post_avatar_generation_profile_reference(profile_id: str, payload: AvatarProfileReferenceUploadRequest):
        try:
            return state.upload_avatar_profile_reference(profile_id=profile_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/face/primary")
    def post_avatar_generation_profile_primary_face(profile_id: str, payload: AvatarPrimaryFaceRequest):
        try:
            return state.set_avatar_profile_primary_face(profile_id=profile_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/face/extract")
    def post_avatar_generation_profile_face_extract(profile_id: str, payload: AvatarFaceProfileExtractRequest):
        try:
            return state.extract_avatar_face_profile(profile_id=profile_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/body-depth/generate")
    async def post_avatar_generation_profile_body_depth(profile_id: str, payload: AvatarBodyDepthProfileGenerateRequest):
        try:
            return await state.generate_avatar_body_depth_profile(profile_id=profile_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/extract")
    def post_avatar_generation_profile_extract(profile_id: str):
        try:
            return state.extract_avatar_profile_data(profile_id=profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/avatar-generation/profiles/{profile_id}/extraction")
    def put_avatar_generation_profile_extraction(profile_id: str, payload: AvatarProfileExtractionUpdateRequest):
        try:
            return state.update_avatar_profile_extraction(profile_id=profile_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/head-face/refine")
    def post_avatar_generation_profile_head_refine(profile_id: str, payload: AvatarProfileHeadPromptRefineRequest):
        try:
            return state.refine_avatar_profile_head_prompt(profile_id=profile_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar-generation/profiles/{profile_id}/head-face/previews")
    async def post_avatar_generation_profile_head_preview(profile_id: str, payload: AvatarProfileHeadPreviewRequest):
        try:
            return await state.create_avatar_profile_head_preview(profile_id=profile_id, payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/avatar-generation/profiles/{profile_id}")
    def delete_avatar_generation_profile(profile_id: str):
        try:
            return state.delete_avatar_profile(profile_id=profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/avatar-generation/profiles/{profile_id}/references/{role}/{asset_name:path}")
    def get_avatar_generation_profile_reference(profile_id: str, role: str, asset_name: str):
        try:
            return state.avatar_profile_reference_response(profile_id=profile_id, role=role, asset_name=asset_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/avatar-generation/profiles/{profile_id}/references/{role}/{asset_name}")
    def delete_avatar_generation_profile_reference(profile_id: str, role: str, asset_name: str):
        try:
            return state.delete_avatar_profile_reference(profile_id=profile_id, role=role, asset_name=asset_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/avatar-generation/profiles/{profile_id}/assets/{asset_name}")
    def get_avatar_generation_profile_asset(profile_id: str, asset_name: str):
        try:
            return state.avatar_profile_asset_response(profile_id=profile_id, asset_name=asset_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/execution/compare")
    async def post_execution_compare(payload: ExecutionCompareRequest):
        try:
            return await state.compare_provider_execution(
                task_family=payload.task_family,
                prompt=payload.prompt,
                system_prompt=payload.system_prompt,
                messages=payload.messages,
                providers=payload.providers,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
            )
        except DirectExecutionBusyError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.payload,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/benchmarks/execution/v2")
    async def post_benchmark_execution_v2(payload: BenchmarkExecutionV2Request):
        try:
            return await state.execute_benchmark_v2(
                benchmark_id=payload.benchmark_id,
                prompt_id=payload.prompt_id,
                prompt_version=payload.prompt_version,
                task_family=payload.task_family,
                requested_by=payload.requested_by,
                service_id=payload.service_id,
                customer_id=payload.customer_id,
                inputs=payload.inputs,
                output_contract=payload.output_contract,
                targets=[target.model_dump(mode="json") for target in payload.targets],
                timeout_s=payload.timeout_s,
                trace_id=payload.trace_id,
                metadata=payload.metadata,
            )
        except DirectExecutionBusyError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.payload,
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/services/status")
    def get_services_status():
        return state.service_status_payload()

    @app.get("/api/services/comfyui-webui/preflight")
    async def get_comfyui_webui_preflight():
        return await state.manual_comfyui_takeover_preflight()

    @app.post("/api/services/start")
    async def post_services_start(payload: ServiceRestartRequest):
        try:
            return await state.start_service(target=payload.target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/services/stop")
    def post_services_stop(payload: ServiceRestartRequest):
        try:
            return state.stop_service(target=payload.target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/services/restart")
    async def post_services_restart(payload: ServiceRestartRequest):
        try:
            return await state.restart_service(target=payload.target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/debug/providers")
    def get_debug_providers():
        return state.debug_providers_payload()

    @app.get("/debug/providers/models")
    def get_debug_provider_models():
        return state.debug_provider_models_payload()

    @app.get("/debug/providers/metrics")
    def get_debug_provider_metrics():
        return state.debug_provider_metrics_payload()

    @app.get("/debug/prompts")
    def get_debug_prompts():
        return state.prompt_service_state_payload()

    @app.get("/debug/budgets")
    def get_debug_budgets():
        return state.budget_state_payload()

    @app.get("/debug/execution")
    def get_debug_execution():
        return state.execution_observability_payload()

    @app.get("/debug/execution/admission")
    def get_debug_execution_admission():
        return state.direct_execution_admission_payload()

    @app.get("/api/capabilities/diagnostics")
    def get_capability_diagnostics(x_admin_token: str | None = Header(default=None, alias="X-Hexe-Admin-Token")):
        require_admin(x_admin_token)
        return state.capability_diagnostics_payload()

    if hasattr(logger, "info"):
        logger.info("[node-control-api] FastAPI app initialized")
    return app
