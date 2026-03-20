from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_node.capabilities.task_families import validate_task_family_capabilities


TaskExecutionPriority = Literal["background", "low", "normal", "high"]
TaskExecutionStatus = Literal["accepted", "completed", "failed", "rejected", "degraded", "unsupported"]


def _normalized_non_empty_string(value: object, *, field_name: str, max_length: int = 128) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name}_required")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name}_too_long")
    return normalized


class TaskExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    prompt_id: str | None = None
    task_family: str
    requested_by: str
    requested_provider: str | None = None
    requested_model: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    priority: TaskExecutionPriority = "normal"
    timeout_s: int = 60
    trace_id: str
    lease_id: str | None = None

    @field_validator("task_id")
    @classmethod
    def _validate_task_id(cls, value: str) -> str:
        return _normalized_non_empty_string(value, field_name="task_id")

    @field_validator("prompt_id")
    @classmethod
    def _validate_prompt_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_non_empty_string(value, field_name="prompt_id")

    @field_validator("task_family")
    @classmethod
    def _validate_task_family(cls, value: str) -> str:
        normalized = _normalized_non_empty_string(value, field_name="task_family")
        is_valid, error = validate_task_family_capabilities([normalized])
        if not is_valid:
            raise ValueError(str(error or "invalid_task_family"))
        return normalized

    @field_validator("requested_by")
    @classmethod
    def _validate_requested_by(cls, value: str) -> str:
        return _normalized_non_empty_string(value, field_name="requested_by", max_length=255)

    @field_validator("requested_provider", "requested_model")
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

    @field_validator("retries", "prompt_tokens", "completion_tokens", "total_tokens", "provider_total_requests", "provider_failed_requests")
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
        return _normalized_non_empty_string(value, field_name=str(info.field_name))

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
        return self
