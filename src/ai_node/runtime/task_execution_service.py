import time
from datetime import datetime, timezone

from ai_node.execution.gateway import ExecutionGateway
from ai_node.execution.failure_codes import classify_failure_code
from ai_node.execution.governance import evaluate_execution_governance
from ai_node.execution.lifecycle import ExecutionLifecycleTracker
from ai_node.execution.task_families import validate_execution_task_family
from ai_node.execution.task_models import TaskExecutionMetrics, TaskExecutionRequest, TaskExecutionResult
from ai_node.providers.models import UnifiedExecutionRequest
from ai_node.providers.task_execution import RuntimeManagerProviderTaskExecutor
from ai_node.runtime.provider_resolver import ProviderResolutionRequest
from ai_node.runtime.task_handlers import (
    CLASSIFICATION_TASK_FAMILIES,
    SUMMARIZATION_TASK_FAMILIES,
    ClassificationTaskHandler,
    SummarizationTaskHandler,
)
from ai_node.runtime.task_router import TaskRouter


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskExecutionService:
    def __init__(
        self,
        *,
        provider_runtime_manager,
        provider_resolver,
        logger,
        lifecycle_tracker: ExecutionLifecycleTracker | None = None,
        execution_gateway: ExecutionGateway | None = None,
        task_router: TaskRouter | None = None,
        prompt_services_state_provider=None,
        declared_task_families_provider=None,
        accepted_capability_profile_provider=None,
        governance_bundle_provider=None,
        governance_status_provider=None,
        execution_telemetry_publisher=None,
    ) -> None:
        self._provider_runtime_manager = provider_runtime_manager
        self._provider_resolver = provider_resolver
        self._logger = logger
        self._task_executor = RuntimeManagerProviderTaskExecutor(provider_runtime_manager=self._provider_runtime_manager)
        self._lifecycle_tracker = lifecycle_tracker or ExecutionLifecycleTracker()
        self._execution_gateway = execution_gateway or ExecutionGateway()
        self._prompt_services_state_provider = prompt_services_state_provider or (lambda: {"prompt_services": []})
        self._declared_task_families_provider = declared_task_families_provider or (lambda: [])
        self._accepted_capability_profile_provider = accepted_capability_profile_provider or (lambda: {})
        self._governance_bundle_provider = governance_bundle_provider or (lambda: {})
        self._governance_status_provider = governance_status_provider or (lambda: {})
        self._execution_telemetry_publisher = execution_telemetry_publisher
        self._task_router = task_router or TaskRouter(
            default_handler=self._execute_provider_handler,
            routable_task_families_provider=self._declared_task_families_provider,
        )
        if task_router is None:
            self._task_router.register_handler(
                task_families=list(CLASSIFICATION_TASK_FAMILIES),
                handler=ClassificationTaskHandler(task_executor=self._task_executor),
            )
            self._task_router.register_handler(
                task_families=list(SUMMARIZATION_TASK_FAMILIES),
                handler=SummarizationTaskHandler(task_executor=self._task_executor),
            )

    @property
    def lifecycle_tracker(self) -> ExecutionLifecycleTracker:
        return self._lifecycle_tracker

    async def execute(self, request: TaskExecutionRequest) -> TaskExecutionResult:
        started = time.perf_counter()
        await self._emit_execution_event(
            event_type="task_received",
            request=request,
            details={"priority": request.priority, "timeout_s": request.timeout_s},
        )
        self._lifecycle_tracker.update(task_id=request.task_id, state="receiving_task", lease_id=request.lease_id)
        self._lifecycle_tracker.update(task_id=request.task_id, state="validating_task", lease_id=request.lease_id)

        family_validation = validate_execution_task_family(
            task_family=request.task_family,
            declared_task_families=self._safe_declared_task_families(),
            accepted_capability_profile=self._safe_accepted_capability_profile(),
        )
        if not family_validation.allowed:
            return self._terminal_result(
                request=request,
                started=started,
                state="rejected" if family_validation.reason != "unsupported_task_family" else "unsupported",
                error_code=family_validation.reason,
                error_message=family_validation.reason,
            )

        authorization = self._authorize_prompt_if_present(request=request)
        if authorization is not None and not authorization.allowed:
            return self._terminal_result(
                request=request,
                started=started,
                state="rejected",
                error_code=authorization.reason,
                error_message=authorization.reason,
            )

        governance_status = self._safe_governance_status()
        if str(governance_status.get("state") or "").strip().lower() == "stale":
            return self._terminal_result(
                request=request,
                started=started,
                state="degraded",
                error_code="governance_stale",
                error_message="governance_stale",
            )

        governance_constraints = self._safe_governance_constraints(request=request)
        pre_resolution_governance = evaluate_execution_governance(
            task_family=request.task_family,
            timeout_s=request.timeout_s,
            inputs=request.inputs,
            governance_bundle=self._safe_governance_bundle(),
            request_governance_constraints=governance_constraints,
        )
        if not pre_resolution_governance.allowed:
            return self._terminal_result(
                request=request,
                started=started,
                state="rejected",
                error_code=pre_resolution_governance.reason,
                error_message=pre_resolution_governance.reason,
            )

        resolution = self._provider_resolver.resolve(
            request=ProviderResolutionRequest(
                task_family=request.task_family,
                requested_provider=request.requested_provider,
                requested_model=request.requested_model,
                timeout_s=request.timeout_s,
            ),
            governance_constraints=governance_constraints,
        )
        if not resolution.allowed:
            rejection_reason = str(resolution.rejection_reason or "provider_resolution_failed")
            failure_category = classify_failure_code(rejection_reason)
            return self._terminal_result(
                request=request,
                started=started,
                state="degraded" if failure_category in {"provider_unavailable", "model_unavailable"} else "rejected",
                error_code=rejection_reason,
                error_message=rejection_reason,
                provider_id=resolution.provider_id,
                model_id=resolution.model_id,
                retries=resolution.retry_count,
                fallback_used=bool(resolution.fallback_provider_ids),
            )

        await self._emit_execution_event(
            event_type="provider_selected",
            request=request,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
            details={"provider_order": list(resolution.provider_order)},
        )
        if resolution.fallback_provider_ids:
            await self._emit_execution_event(
                event_type="provider_fallback",
                request=request,
                provider_id=resolution.provider_id,
                model_id=resolution.model_id,
                details={"fallback_provider_ids": list(resolution.fallback_provider_ids)},
            )

        post_resolution_governance = evaluate_execution_governance(
            task_family=request.task_family,
            timeout_s=request.timeout_s,
            inputs=request.inputs,
            governance_bundle=self._safe_governance_bundle(),
            request_governance_constraints=governance_constraints,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
        )
        if not post_resolution_governance.allowed:
            return self._terminal_result(
                request=request,
                started=started,
                state="rejected",
                error_code=post_resolution_governance.reason,
                error_message=post_resolution_governance.reason,
                provider_id=resolution.provider_id,
                model_id=resolution.model_id,
            )

        self._lifecycle_tracker.update(
            task_id=request.task_id,
            state="queued_local",
            lease_id=request.lease_id,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
        )
        self._lifecycle_tracker.update(
            task_id=request.task_id,
            state="executing",
            lease_id=request.lease_id,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
        )
        await self._emit_execution_event(
            event_type="task_started",
            request=request,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
        )

        try:
            response = await self._task_router.dispatch(
                task_family=request.task_family,
                request=request,
                resolution=resolution,
            )
        except ValueError as exc:
            failure_reason = str(exc)
            failure_category = classify_failure_code(failure_reason)
            return self._terminal_result(
                request=request,
                started=started,
                state="degraded" if failure_category in {"provider_unavailable", "model_unavailable"} else "rejected",
                error_code=failure_reason,
                error_message=failure_reason,
                provider_id=resolution.provider_id,
                model_id=resolution.model_id,
                retries=resolution.retry_count,
                fallback_used=bool(resolution.fallback_provider_ids),
            )
        except Exception as exc:
            failure_reason = str(exc).strip() or "internal_execution_error"
            failure_category = classify_failure_code(failure_reason)
            return self._terminal_result(
                request=request,
                started=started,
                state="degraded" if failure_category == "provider_unavailable" else "failed",
                error_code="internal_execution_error" if failure_category is None else failure_reason,
                error_message=failure_reason,
                provider_id=resolution.provider_id,
                model_id=resolution.model_id,
                retries=resolution.retry_count,
                fallback_used=bool(resolution.fallback_provider_ids),
            )

        completed_at = _iso_now()
        self._lifecycle_tracker.update(
            task_id=request.task_id,
            state="completed",
            lease_id=request.lease_id,
            provider_id=response.provider_id,
            model_id=response.model_id,
            details={"finish_reason": response.finish_reason},
        )
        await self._emit_execution_event(
            event_type="task_completed",
            request=request,
            provider_id=response.provider_id,
            model_id=response.model_id,
            details={"finish_reason": response.finish_reason},
        )
        metric_context = self._provider_metric_context(provider_id=response.provider_id, model_id=response.model_id)
        return TaskExecutionResult.model_validate(
            {
                "task_id": request.task_id,
                "status": "completed",
                "output": {"text": response.output_text},
                "metrics": {
                    "execution_duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "provider_latency_ms": response.latency_ms,
                    "retries": resolution.retry_count,
                    "fallback_used": bool(resolution.fallback_provider_ids),
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "estimated_cost": response.estimated_cost,
                    **metric_context,
                },
                "provider_used": response.provider_id,
                "model_used": response.model_id,
                "completed_at": completed_at,
            }
        )

    def _authorize_prompt_if_present(self, *, request: TaskExecutionRequest):
        if not request.prompt_id:
            return None
        return self._execution_gateway.authorize(
            prompt_id=request.prompt_id,
            task_family=request.task_family,
            prompt_services_state=self._safe_prompt_services_state(),
        )

    def _safe_prompt_services_state(self) -> dict:
        payload = self._prompt_services_state_provider() if callable(self._prompt_services_state_provider) else {}
        return payload if isinstance(payload, dict) else {}

    def _safe_declared_task_families(self) -> list[str]:
        payload = self._declared_task_families_provider() if callable(self._declared_task_families_provider) else []
        return list(payload or []) if isinstance(payload, list) else []

    def _safe_accepted_capability_profile(self) -> dict:
        payload = self._accepted_capability_profile_provider() if callable(self._accepted_capability_profile_provider) else {}
        return payload if isinstance(payload, dict) else {}

    def _safe_governance_bundle(self) -> dict:
        payload = self._governance_bundle_provider() if callable(self._governance_bundle_provider) else {}
        return payload if isinstance(payload, dict) else {}

    def _safe_governance_status(self) -> dict:
        payload = self._governance_status_provider() if callable(self._governance_status_provider) else {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _safe_governance_constraints(*, request: TaskExecutionRequest) -> dict:
        constraints = request.constraints if isinstance(request.constraints, dict) else {}
        governance = constraints.get("governance") if isinstance(constraints.get("governance"), dict) else {}
        return governance

    @staticmethod
    def _build_unified_request(*, request: TaskExecutionRequest, resolution) -> UnifiedExecutionRequest:
        inputs = request.inputs if isinstance(request.inputs, dict) else {}
        messages = inputs.get("messages") if isinstance(inputs.get("messages"), list) else []
        prompt = inputs.get("prompt")
        if prompt is None:
            prompt = inputs.get("text")
        system_prompt = inputs.get("system_prompt")
        max_tokens = inputs.get("max_tokens")
        temperature = inputs.get("temperature")
        return UnifiedExecutionRequest(
            task_family=request.task_family,
            prompt=str(prompt or "") if prompt is not None else None,
            system_prompt=str(system_prompt or "") if system_prompt is not None else None,
            messages=messages,
            requested_provider=resolution.provider_id,
            requested_model=resolution.model_id,
            temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
            max_tokens=int(max_tokens) if isinstance(max_tokens, int) else None,
            metadata={
                "task_id": request.task_id,
                "requested_by": request.requested_by,
                "trace_id": request.trace_id,
                "prompt_id": request.prompt_id,
                "lease_id": request.lease_id,
            },
        )

    def _terminal_result(
        self,
        *,
        request: TaskExecutionRequest,
        started: float,
        state: str,
        error_code: str,
        error_message: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        retries: int = 0,
        fallback_used: bool = False,
    ) -> TaskExecutionResult:
        lifecycle_state = "rejected" if state == "unsupported" else state
        self._lifecycle_tracker.update(
            task_id=request.task_id,
            state=lifecycle_state,
            lease_id=request.lease_id,
            provider_id=provider_id,
            model_id=model_id,
            details={"error_code": error_code},
        )
        event_type = "task_rejected" if state in {"rejected", "unsupported"} else "task_failed"
        if error_code == "execution_timeout":
            timeout_event_request = request
            # execution timeout is emitted in addition to the terminal failure event.
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._emit_execution_event(
                        event_type="execution_timeout",
                        request=timeout_event_request,
                        provider_id=provider_id,
                        model_id=model_id,
                        details={"error_code": error_code},
                    )
                )
            except Exception:
                pass
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(
                self._emit_execution_event(
                    event_type=event_type,
                    request=request,
                    provider_id=provider_id,
                    model_id=model_id,
                    details={"error_code": error_code, "task_status": state},
                )
            )
        except Exception:
            pass
        metric_context = self._provider_metric_context(provider_id=provider_id, model_id=model_id)
        return TaskExecutionResult.model_validate(
            {
                "task_id": request.task_id,
                "status": state,
                "output": {"error": error_message} if state == "degraded" else None,
                "metrics": TaskExecutionMetrics(
                    execution_duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
                    retries=max(int(retries), 0),
                    fallback_used=bool(fallback_used),
                    **metric_context,
                ).model_dump(),
                "error_code": error_code,
                "error_message": error_message,
                "provider_used": provider_id,
                "model_used": model_id,
                "completed_at": _iso_now(),
            }
        )

    async def _execute_provider_handler(self, *, request: TaskExecutionRequest, resolution):
        return await self._provider_runtime_manager.execute(self._build_unified_request(request=request, resolution=resolution))

    def _provider_metric_context(self, *, provider_id: str | None, model_id: str | None) -> dict:
        if not provider_id or not model_id:
            return {}
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "metrics_snapshot"):
            return {}
        snapshot = self._provider_runtime_manager.metrics_snapshot()
        providers = snapshot.get("providers") if isinstance(snapshot, dict) else {}
        provider_payload = providers.get(provider_id) if isinstance(providers, dict) else {}
        models = provider_payload.get("models") if isinstance(provider_payload, dict) else {}
        model_payload = models.get(model_id) if isinstance(models, dict) else {}
        if not isinstance(model_payload, dict):
            return {}
        return {
            "provider_avg_latency_ms": model_payload.get("avg_latency"),
            "provider_p95_latency_ms": model_payload.get("p95_latency"),
            "provider_success_rate": model_payload.get("success_rate"),
            "provider_total_requests": int(model_payload.get("total_requests") or 0),
            "provider_failed_requests": int(model_payload.get("failed_requests") or 0),
        }

    async def _emit_execution_event(
        self,
        *,
        event_type: str,
        request: TaskExecutionRequest,
        provider_id: str | None = None,
        model_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        if self._execution_telemetry_publisher is None or not hasattr(self._execution_telemetry_publisher, "publish_event"):
            return
        payload = {
            "task_id": request.task_id,
            "task_family": request.task_family,
            "requested_by": request.requested_by,
            "trace_id": request.trace_id,
            "prompt_id": request.prompt_id,
            "lease_id": request.lease_id,
            "provider_id": provider_id,
            "model_id": model_id,
            "details": details if isinstance(details, dict) else {},
        }
        try:
            await self._execution_telemetry_publisher.publish_event(event_type=event_type, payload=payload)
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[execution-telemetry-failed] %s",
                    {"event_type": event_type, "task_id": request.task_id, "error": str(exc)},
                )
