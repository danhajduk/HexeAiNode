import time

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
from ai_node.time_utils import local_now_iso


def _iso_now() -> str:
    return local_now_iso()


class TaskExecutionService:
    def __init__(
        self,
        *,
        provider_runtime_manager,
        provider_resolver,
        logger,
        budget_manager=None,
        client_usage_store=None,
        prompt_registry=None,
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
        self._budget_manager = budget_manager
        self._client_usage_store = client_usage_store
        self._prompt_registry = prompt_registry
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

    @staticmethod
    def _lifecycle_context_details(*, request: TaskExecutionRequest, extras: dict | None = None) -> dict:
        details = {
            "requested_by": request.requested_by,
            "service_id": request.service_id,
            "customer_id": request.customer_id,
            "prompt_id": request.prompt_id,
            "prompt_version": request.prompt_version,
            "trace_id": request.trace_id,
        }
        if isinstance(extras, dict):
            details.update(extras)
        return {key: value for key, value in details.items() if value not in (None, "")}

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
            self._record_prompt_authorization(request=request, allowed=False, reason=authorization.reason)
            return self._terminal_result(
                request=request,
                started=started,
                state="rejected",
                error_code=authorization.reason,
                error_message=authorization.reason,
            )
        if authorization is not None:
            self._record_prompt_authorization(request=request, allowed=True, reason=authorization.reason)

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
        if authorization is not None:
            governance_constraints = self._merge_prompt_governance_constraints(
                governance_constraints=governance_constraints,
                authorization=authorization,
            )
        effective_timeout_s = self._effective_timeout_s(request=request, authorization=authorization)
        pre_resolution_governance = evaluate_execution_governance(
            task_family=request.task_family,
            timeout_s=effective_timeout_s,
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
                requested_provider=self._effective_requested_provider(request=request, authorization=authorization),
                requested_model=self._effective_requested_model(request=request, authorization=authorization),
                timeout_s=effective_timeout_s,
                max_cost_cents=self._request_max_cost_cents(request=request),
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
            timeout_s=effective_timeout_s,
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

        budget_reservation = None
        if self._budget_manager is not None:
            budget_reservation = self._budget_manager.reserve_execution(
                task_id=request.task_id,
                request=request,
                provider_id=str(resolution.provider_id or ""),
                model_id=str(resolution.model_id or ""),
                governance_bundle=self._safe_governance_bundle(),
            )
            if not budget_reservation.allowed:
                await self._emit_execution_event(
                    event_type="budget_denial",
                    request=request,
                    provider_id=resolution.provider_id,
                    model_id=resolution.model_id,
                    details={"reason": budget_reservation.reason},
                )
                return self._terminal_result(
                    request=request,
                    started=started,
                    state="rejected",
                    error_code=str(budget_reservation.reason or "missing_budget_grant"),
                    error_message=str(budget_reservation.reason or "missing_budget_grant"),
                    provider_id=resolution.provider_id,
                    model_id=resolution.model_id,
                )
            await self._emit_execution_event(
                event_type="budget_reservation",
                request=request,
                provider_id=resolution.provider_id,
                model_id=resolution.model_id,
                details={
                    "reservation_id": budget_reservation.reservation_id,
                    "reserved_cost_cents": budget_reservation.reserved_cost_cents,
                    "grant_ids": budget_reservation.applied_grant_ids,
                },
            )

        self._lifecycle_tracker.update(
            task_id=request.task_id,
            state="queued_local",
            lease_id=request.lease_id,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
            details=self._lifecycle_context_details(request=request),
        )
        self._lifecycle_tracker.update(
            task_id=request.task_id,
            state="executing",
            lease_id=request.lease_id,
            provider_id=resolution.provider_id,
            model_id=resolution.model_id,
            details=self._lifecycle_context_details(request=request),
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
                resolution={"plan": resolution, "authorization": authorization},
            )
        except ValueError as exc:
            failure_reason = str(exc)
            failure_category = classify_failure_code(failure_reason)
            if budget_reservation is not None and self._budget_manager is not None:
                self._budget_manager.release_execution(task_id=request.task_id, reason=failure_reason)
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
            if budget_reservation is not None and self._budget_manager is not None:
                self._budget_manager.release_execution(task_id=request.task_id, reason=failure_reason)
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
            details=self._lifecycle_context_details(
                request=request,
                extras={
                    "finish_reason": response.finish_reason,
                    "estimated_cost": response.estimated_cost,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            ),
        )
        await self._emit_execution_event(
            event_type="task_completed",
            request=request,
            provider_id=response.provider_id,
            model_id=response.model_id,
            details={"finish_reason": response.finish_reason},
        )
        metric_context = self._provider_metric_context(provider_id=response.provider_id, model_id=response.model_id)
        result = TaskExecutionResult.model_validate(
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
        if budget_reservation is not None and self._budget_manager is not None:
            budget_result = self._budget_manager.finalize_execution(
                task_id=request.task_id,
                metrics=result.metrics,
                status="completed",
            )
            await self._emit_execution_event(
                event_type="budget_finalized",
                request=request,
                provider_id=response.provider_id,
                model_id=response.model_id,
                details=budget_result,
            )
        self._record_client_usage(
            request=request,
            metrics=result.metrics,
            completed_at=completed_at,
            model_id=result.model_used,
        )
        self._record_prompt_execution(request=request, status="completed", error_code=None)
        return result

    def _authorize_prompt_if_present(self, *, request: TaskExecutionRequest):
        if not request.prompt_id:
            return None
        return self._execution_gateway.authorize(
            prompt_id=request.prompt_id,
            task_family=request.task_family,
            prompt_services_state=self._safe_prompt_services_state(),
            prompt_version=request.prompt_version,
            requested_provider=request.requested_provider,
            requested_model=request.requested_model,
            inputs=request.inputs,
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
    def _effective_requested_provider(*, request: TaskExecutionRequest, authorization) -> str | None:
        if request.requested_provider:
            return request.requested_provider
        if authorization is None or not isinstance(authorization.provider_preferences, dict):
            return None
        return authorization.provider_preferences.get("default_provider")

    @staticmethod
    def _effective_requested_model(*, request: TaskExecutionRequest, authorization) -> str | None:
        if request.requested_model:
            return request.requested_model
        if authorization is None or not isinstance(authorization.provider_preferences, dict):
            return None
        return authorization.provider_preferences.get("default_model")

    @staticmethod
    def _effective_timeout_s(*, request: TaskExecutionRequest, authorization) -> int:
        timeout_s = int(request.timeout_s)
        if authorization is None or not isinstance(authorization.prompt_constraints, dict):
            return timeout_s
        max_timeout_s = authorization.prompt_constraints.get("max_timeout_s")
        if max_timeout_s is None:
            return timeout_s
        return min(timeout_s, max(int(max_timeout_s), 1))

    @staticmethod
    def _merge_prompt_governance_constraints(*, governance_constraints: dict, authorization) -> dict:
        merged = dict(governance_constraints or {})
        provider_preferences = authorization.provider_preferences if isinstance(authorization.provider_preferences, dict) else {}
        prompt_constraints = authorization.prompt_constraints if isinstance(authorization.prompt_constraints, dict) else {}
        preferred_providers = list(provider_preferences.get("preferred_providers") or [])
        preferred_models = list(provider_preferences.get("preferred_models") or [])
        if preferred_providers:
            approved_providers = list(merged.get("approved_providers") or [])
            if approved_providers:
                merged["approved_providers"] = [item for item in approved_providers if item in set(preferred_providers)]
            else:
                merged["approved_providers"] = preferred_providers
        if preferred_models:
            requested_provider = provider_preferences.get("default_provider")
            approved_models = merged.get("approved_models") if isinstance(merged.get("approved_models"), dict) else {}
            provider_key = str(requested_provider or "").strip().lower() or "*"
            provider_models = list(approved_models.get(provider_key) or [])
            approved_models[provider_key] = [item for item in provider_models if item in set(preferred_models)] if provider_models else preferred_models
            merged["approved_models"] = approved_models
        if prompt_constraints.get("max_timeout_s") is not None:
            routing = merged.get("routing_policy_constraints") if isinstance(merged.get("routing_policy_constraints"), dict) else {}
            current_timeout = routing.get("max_timeout_s")
            prompt_timeout = int(prompt_constraints.get("max_timeout_s"))
            routing["max_timeout_s"] = min(int(current_timeout), prompt_timeout) if current_timeout is not None else prompt_timeout
            merged["routing_policy_constraints"] = routing
        return merged

    @staticmethod
    def _request_max_cost_cents(*, request: TaskExecutionRequest) -> int | None:
        constraints = request.constraints if isinstance(request.constraints, dict) else {}
        budget = constraints.get("budget") if isinstance(constraints.get("budget"), dict) else {}
        if budget.get("max_cost_cents") is not None:
            return max(int(budget.get("max_cost_cents")), 0)
        if constraints.get("max_cost_cents") is not None:
            return max(int(constraints.get("max_cost_cents")), 0)
        if constraints.get("max_cost_usd") is not None:
            return max(int(float(constraints.get("max_cost_usd")) * 100), 0)
        return None

    @staticmethod
    def _build_unified_request(*, request: TaskExecutionRequest, resolution, authorization=None) -> UnifiedExecutionRequest:
        resolution_plan = resolution.get("plan") if isinstance(resolution, dict) else resolution
        inputs = request.inputs if isinstance(request.inputs, dict) else {}
        messages = inputs.get("messages") if isinstance(inputs.get("messages"), list) else []
        prompt = inputs.get("prompt")
        if prompt is None:
            prompt = inputs.get("text")
        system_prompt = inputs.get("system_prompt")
        prompt_definition = authorization.prompt_definition if authorization is not None and isinstance(authorization.prompt_definition, dict) else {}
        if system_prompt is None:
            system_prompt = prompt_definition.get("system_prompt")
        max_tokens = inputs.get("max_tokens")
        temperature = inputs.get("temperature")
        return UnifiedExecutionRequest(
            task_family=request.task_family,
            prompt=str(prompt or "") if prompt is not None else None,
            system_prompt=str(system_prompt or "") if system_prompt is not None else None,
            messages=messages,
            requested_provider=resolution_plan.provider_id,
            requested_model=resolution_plan.model_id,
            temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
            max_tokens=int(max_tokens) if isinstance(max_tokens, int) else None,
            metadata={
                "task_id": request.task_id,
                "requested_by": request.requested_by,
                "trace_id": request.trace_id,
                "prompt_id": request.prompt_id,
                "prompt_version": request.prompt_version,
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
            details=self._lifecycle_context_details(
                request=request,
                extras={
                    "error_code": error_code,
                    "retries": max(int(retries), 0),
                    "fallback_used": bool(fallback_used),
                },
            ),
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
        result = TaskExecutionResult.model_validate(
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
        self._record_prompt_execution(request=request, status=state, error_code=error_code)
        return result

    def _record_prompt_authorization(self, *, request: TaskExecutionRequest, allowed: bool, reason: str) -> None:
        if self._prompt_registry is None or not request.prompt_id:
            return
        try:
            self._prompt_registry.record_authorization(
                prompt_id=request.prompt_id,
                allowed=allowed,
                reason=reason,
                used_at=_iso_now(),
            )
        except Exception:
            pass

    def _record_prompt_execution(self, *, request: TaskExecutionRequest, status: str, error_code: str | None) -> None:
        if self._prompt_registry is None or not request.prompt_id:
            return
        try:
            self._prompt_registry.record_execution(
                prompt_id=request.prompt_id,
                status=status,
                recorded_at=_iso_now(),
                error_code=error_code,
            )
        except Exception:
            pass

    def _record_client_usage(self, *, request: TaskExecutionRequest, metrics, completed_at: str, model_id: str | None) -> None:
        if self._client_usage_store is None or not hasattr(self._client_usage_store, "record_execution"):
            return
        try:
            client_id = str(request.requested_by or request.service_id or "unknown-client").strip() or "unknown-client"
            prompt_id = str(request.prompt_id or "unattributed-prompt").strip() or "unattributed-prompt"
            customer_id = str(request.customer_id or "").strip() or None
            self._client_usage_store.record_execution(
                client_id=client_id,
                prompt_id=prompt_id,
                model_id=str(model_id or request.requested_model or "").strip() or None,
                customer_id=customer_id,
                prompt_tokens=max(int(getattr(metrics, "prompt_tokens", 0) or 0), 0),
                completion_tokens=max(int(getattr(metrics, "completion_tokens", 0) or 0), 0),
                total_tokens=max(int(getattr(metrics, "total_tokens", 0) or 0), 0),
                cost_usd=max(float(getattr(metrics, "estimated_cost", 0.0) or 0.0), 0.0),
                used_at=completed_at,
            )
        except Exception:
            pass

    async def _execute_provider_handler(self, *, request: TaskExecutionRequest, resolution):
        authorization = resolution.get("authorization") if isinstance(resolution, dict) else None
        return await self._provider_runtime_manager.execute(
            self._build_unified_request(request=request, resolution=resolution, authorization=authorization)
        )

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
