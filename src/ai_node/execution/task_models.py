from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_node.capabilities.task_families import canonicalize_task_family, validate_task_family_capabilities
from ai_node.execution.queue_contract import (
    QueueRoutingPolicy,
    RuntimeLane,
    infer_runtime_lane,
)


TaskExecutionPriority = Literal["background", "low", "normal", "high", "critical"]
TaskExecutionResponseMode = Literal["sync", "async_if_queued"]
TaskExecutionStatus = Literal["accepted", "completed", "failed", "rejected", "degraded", "unsupported"]
TaskExecutionQueueImportance = Literal["background", "low", "normal", "high", "critical"]
TaskExecutionQueueClass = Literal["interactive", "background", "scheduled"]


def _normalized_non_empty_string(value: object, *, field_name: str, max_length: int = 128) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name}_required")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name}_too_long")
    return normalized


class TaskExecutionQueueIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    importance: TaskExecutionQueueImportance = "normal"
    priority: TaskExecutionPriority | None = None
    queue_class: TaskExecutionQueueClass | None = None
    runtime_lane: RuntimeLane | None = None
    max_wait_seconds: int | None = None
    deadline_at: datetime | None = None
    allow_cloud_spillover: bool | None = None
    local_preferred: bool | None = None
    routing_policy: QueueRoutingPolicy | None = None
    estimated_vram_mib: int | None = None
    estimated_runtime_seconds: int | None = None
    reason: str | None = None

    @field_validator("max_wait_seconds", "estimated_vram_mib", "estimated_runtime_seconds")
    @classmethod
    def _validate_non_negative_int(cls, value: int | None, info) -> int | None:
        if value is None:
            return None
        normalized = int(value)
        if normalized < 0:
            raise ValueError(f"{info.field_name}_must_be_non_negative")
        return normalized

    @field_validator("reason")
    @classmethod
    def _validate_queue_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value or "").strip()
        if len(normalized) > 512:
            raise ValueError("queue_reason_too_long")
        return normalized or None

    @field_validator("deadline_at")
    @classmethod
    def _validate_deadline_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        now = datetime.now(tz=value.tzinfo)
        if value <= now:
            raise ValueError("queue_deadline_at_must_be_in_future")
        return value


class TaskExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    idempotency_key: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    task_family: str
    requested_by: str
    service_id: str | None = None
    customer_id: str | None = None
    requested_provider: str | None = None
    requested_model: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    priority: TaskExecutionPriority = "normal"
    queue: TaskExecutionQueueIntent = Field(default_factory=TaskExecutionQueueIntent)
    response_mode: TaskExecutionResponseMode = "sync"
    job_name: str | None = None
    timeout_s: int = 60
    trace_id: str
    lease_id: str | None = None

    @field_validator("task_id")
    @classmethod
    def _validate_task_id(cls, value: str) -> str:
        return _normalized_non_empty_string(value, field_name="task_id")

    @field_validator("prompt_id", "prompt_version", "idempotency_key")
    @classmethod
    def _validate_prompt_selection_field(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _normalized_non_empty_string(value, field_name=str(info.field_name))

    @field_validator("task_family")
    @classmethod
    def _validate_task_family(cls, value: str) -> str:
        normalized = _normalized_non_empty_string(value, field_name="task_family")
        is_valid, error = validate_task_family_capabilities([normalized])
        if not is_valid:
            raise ValueError(str(error or "invalid_task_family"))
        return canonicalize_task_family(normalized) or normalized

    @field_validator("requested_by")
    @classmethod
    def _validate_requested_by(cls, value: str) -> str:
        return _normalized_non_empty_string(value, field_name="requested_by", max_length=255)

    @field_validator("service_id", "customer_id", "requested_provider", "requested_model")
    @classmethod
    def _validate_optional_selection_string(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _normalized_non_empty_string(value, field_name=str(info.field_name))

    @field_validator("inputs")
    @classmethod
    def _validate_inputs(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("inputs_must_be_object")
        return value

    @field_validator("constraints")
    @classmethod
    def _validate_constraints(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("constraints_must_be_object")
        return value

    @field_validator("timeout_s")
    @classmethod
    def _validate_timeout_s(cls, value: int) -> int:
        timeout = int(value)
        if timeout <= 0:
            raise ValueError("timeout_s_must_be_positive")
        if timeout > 3600:
            raise ValueError("timeout_s_exceeds_phase3_limit")
        return timeout

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, value: str) -> str:
        return _normalized_non_empty_string(value, field_name="trace_id")

    @field_validator("lease_id")
    @classmethod
    def _validate_lease_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_non_empty_string(value, field_name="lease_id")

    @field_validator("job_name")
    @classmethod
    def _validate_job_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_non_empty_string(value, field_name="job_name", max_length=255)

    @model_validator(mode="after")
    def _normalize_identity_fields(self) -> "TaskExecutionRequest":
        if self.service_id is None:
            self.service_id = self.requested_by
        if self.queue.importance == "normal" and self.priority != "normal":
            self.queue.importance = self.priority
        if self.queue.priority is None:
            self.queue.priority = self.queue.importance
        if self.queue.queue_class is None:
            task_key = str(self.task_family or "").strip().lower()
            image_background = task_key in {"task.image_generation", "task.generation.image"} and self.priority in {
                "background",
                "low",
            }
            if self.queue.importance == "background" or image_background:
                self.queue.queue_class = "background"
            else:
                self.queue.queue_class = "interactive"
        if self.queue.max_wait_seconds is None:
            self.queue.max_wait_seconds = 6 * 60 * 60 if self.queue.queue_class == "background" else 5 * 60
        if self.queue.routing_policy is None:
            routing_policy = self.constraints.get("routing_policy") if isinstance(self.constraints.get("routing_policy"), dict) else {}
            mode = str(routing_policy.get("mode") or "").strip().lower()
            if mode in {"local_only", "local_preferred", "cloud_fallback", "cloud_only"}:
                self.queue.routing_policy = mode  # type: ignore[assignment]
            elif self.requested_provider and str(self.requested_provider).strip().lower() not in {"local", "local_vision"}:
                self.queue.routing_policy = "cloud_only"
            else:
                self.queue.routing_policy = "local_preferred"
        if self.queue.local_preferred is None:
            self.queue.local_preferred = self.queue.routing_policy in {"local_preferred", "cloud_fallback"}
        if self.queue.runtime_lane is None:
            self.queue.runtime_lane = infer_runtime_lane(
                queue=None,
                task_family=self.task_family,
                requested_provider=self.requested_provider,
            )  # type: ignore[assignment]
        return self


class TaskExecutionMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_duration_ms: float | None = None
    provider_latency_ms: float | None = None
    provider_avg_latency_ms: float | None = None
    provider_p95_latency_ms: float | None = None
    provider_success_rate: float | None = None
    provider_total_requests: int = 0
    provider_failed_requests: int = 0
    retries: int = 0
    fallback_used: bool = False
    prompt_tokens: int = 0
    cached_input_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float | None = None

    @field_validator(
        "execution_duration_ms",
        "provider_latency_ms",
        "provider_avg_latency_ms",
        "provider_p95_latency_ms",
        "provider_success_rate",
        "estimated_cost",
    )
    @classmethod
    def _validate_non_negative_float(cls, value: float | None) -> float | None:
        if value is None:
            return None
        normalized = float(value)
        if normalized < 0:
            raise ValueError("metrics_value_must_be_non_negative")
        return normalized

    @field_validator("retries", "prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens", "provider_total_requests", "provider_failed_requests")
    @classmethod
    def _validate_non_negative_int(cls, value: int) -> int:
        normalized = int(value)
        if normalized < 0:
            raise ValueError("metrics_value_must_be_non_negative")
        return normalized


class TaskExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: TaskExecutionStatus
    output: dict[str, Any] | None = None
    metrics: TaskExecutionMetrics = Field(default_factory=TaskExecutionMetrics)
    error_code: str | None = None
    error_message: str | None = None
    provider_used: str | None = None
    model_used: str | None = None
    resolution_metadata: dict[str, Any] | None = None
    completed_at: datetime | None = None

    @field_validator("task_id")
    @classmethod
    def _validate_result_task_id(cls, value: str) -> str:
        return _normalized_non_empty_string(value, field_name="task_id")

    @field_validator("output")
    @classmethod
    def _validate_output(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("output_must_be_object")
        return value

    @field_validator("error_code")
    @classmethod
    def _validate_error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_non_empty_string(value, field_name="error_code")

    @field_validator("error_message", "provider_used", "model_used")
    @classmethod
    def _validate_optional_string(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        max_length = 4096 if str(info.field_name) == "error_message" else 128
        return _normalized_non_empty_string(value, field_name=str(info.field_name), max_length=max_length)

    @field_validator("resolution_metadata")
    @classmethod
    def _validate_resolution_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("resolution_metadata_must_be_object")
        return value

    @model_validator(mode="after")
    def _validate_status_consistency(self) -> "TaskExecutionResult":
        error_statuses = {"failed", "rejected", "unsupported"}
        terminal_statuses = {"completed", "failed", "rejected", "degraded", "unsupported"}

        if self.status in error_statuses and not self.error_code:
            raise ValueError("error_code_required_for_non_success_status")
        if self.status in {"completed", "degraded"} and self.output is None:
            raise ValueError("output_required_for_result_status")
        if self.status == "accepted" and self.completed_at is not None:
            raise ValueError("accepted_status_cannot_have_completed_at")
        if self.status in terminal_statuses and self.completed_at is None:
            raise ValueError("completed_at_required_for_terminal_status")
        if self.status == "completed" and isinstance(self.resolution_metadata, dict):
            routing_mode = str(self.resolution_metadata.get("routing_policy_mode") or "").strip().lower()
            if routing_mode == "local_only":
                required_local_evidence = {
                    "provider_class": "local",
                    "execution_location": "local",
                    "cloud_used": False,
                }
                if any(self.resolution_metadata.get(key) != expected for key, expected in required_local_evidence.items()):
                    raise ValueError("local_only_resolution_evidence_required")
        if self.status == "completed" and isinstance(self.output, dict) and "images" in self.output:
            images = self.output.get("images")
            if not isinstance(images, list) or not images:
                raise ValueError("completed_image_artifact_required")
            for image in images:
                if not isinstance(image, dict) or not str(image.get("url") or "").strip():
                    raise ValueError("completed_image_artifact_url_required")
                for field_name in ("width", "height", "size_bytes"):
                    value = image.get(field_name)
                    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                        raise ValueError(f"completed_image_artifact_{field_name}_required")
        return self
