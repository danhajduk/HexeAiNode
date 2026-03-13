from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ProviderAvailability = Literal["available", "degraded", "unavailable"]
ProviderType = Literal["cloud", "local", "mock"]
ModelStatus = Literal["available", "degraded", "unavailable", "deprecated"]


class PricingInfo(BaseModel):
    currency: str = "usd"
    input_per_1m_tokens: float | None = None
    output_per_1m_tokens: float | None = None


class LatencyMetrics(BaseModel):
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    execution_count: int = 0
    rolling_samples_ms: list[float] = Field(default_factory=list)


class SuccessMetrics(BaseModel):
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    failure_classes: dict[str, int] = Field(default_factory=dict)
    success_rate: float = 0.0


class UsageMetrics(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    cumulative_spend: float = 0.0


class ModelCapability(BaseModel):
    model_id: str
    display_name: str
    created: int | None = None
    base_model_id: str | None = None
    input_modalities: list[str] = Field(default_factory=lambda: ["text"])
    output_modalities: list[str] = Field(default_factory=lambda: ["text"])
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    pricing_input: float | None = None
    cached_pricing_input: float | None = None
    pricing_output: float | None = None
    batch_pricing_input: float | None = None
    batch_pricing_output: float | None = None
    pricing_status: str = "unknown"
    pricing_source_url: str | None = None
    pricing_scraped_at: str | None = None
    pricing_notes: list[str] = Field(default_factory=list)
    status: ModelStatus = "available"


class ProviderCapability(BaseModel):
    provider_id: str
    provider_type: ProviderType
    availability: ProviderAvailability = "unavailable"
    models: list[ModelCapability] = Field(default_factory=list)
    pricing: PricingInfo = Field(default_factory=PricingInfo)
    latency_metrics: LatencyMetrics = Field(default_factory=LatencyMetrics)
    success_metrics: SuccessMetrics = Field(default_factory=SuccessMetrics)
    usage_metrics: UsageMetrics = Field(default_factory=UsageMetrics)
    context_limits: dict[str, int | None] = Field(default_factory=dict)
    last_updated: datetime


class UnifiedExecutionRequest(BaseModel):
    task_family: str
    prompt: str | None = None
    system_prompt: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    requested_provider: str | None = None
    requested_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedExecutionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class UnifiedExecutionResponse(BaseModel):
    provider_id: str
    model_id: str
    output_text: str
    finish_reason: str | None = None
    usage: UnifiedExecutionUsage = Field(default_factory=UnifiedExecutionUsage)
    latency_ms: float = 0.0
    estimated_cost: float | None = None
    raw_provider_response_ref: str | None = None
