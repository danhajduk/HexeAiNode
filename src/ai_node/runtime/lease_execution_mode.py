import asyncio

from ai_node.execution.task_models import TaskExecutionRequest


class LeaseExecutionModeRunner:
    def __init__(
        self,
        *,
        lease_integration,
        task_execution_service,
        logger,
        heartbeat_interval_s: float = 5.0,
        execution_telemetry_publisher=None,
    ) -> None:
        self._lease_integration = lease_integration
        self._task_execution_service = task_execution_service
        self._logger = logger
        self._heartbeat_interval_s = max(float(heartbeat_interval_s), 0.5)
        self._execution_telemetry_publisher = execution_telemetry_publisher

    async def run_once(self, *, core_api_endpoint: str, trust_token: str | None = None, max_units: int = 1) -> dict:
        lease_result = await self._lease_integration.request_lease(
            core_api_endpoint=core_api_endpoint,
            trust_token=trust_token,
            max_units=max_units,
        )
        if lease_result.status != "ok":
            return {"status": "lease_not_granted", "lease_result": lease_result.payload, "retryable": lease_result.retryable}

        lease = lease_result.payload.get("lease") if isinstance(lease_result.payload, dict) else None
        job = lease_result.payload.get("job") if isinstance(lease_result.payload, dict) else None
        if not isinstance(lease, dict) or not isinstance(job, dict):
            return {"status": "lease_not_granted", "lease_result": lease_result.payload, "retryable": False}

        lease_id = str(lease.get("lease_id") or "").strip()
        if not lease_id:
            return {"status": "lease_not_granted", "lease_result": lease_result.payload, "retryable": False}

        request = self._build_task_request(job=job, lease_id=lease_id)
        if request is None:
            await self._lease_integration.complete(
                core_api_endpoint=core_api_endpoint,
                lease_id=lease_id,
                status="failed",
                error="invalid_lease_job_payload",
                trust_token=trust_token,
            )
            return {"status": "invalid_lease_job_payload", "lease_id": lease_id}

        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                core_api_endpoint=core_api_endpoint,
                lease_id=lease_id,
                trust_token=trust_token,
                stop_event=stop_event,
            )
        )
        try:
            await self._emit_progress_event(request=request, progress=0.1, message="execution_started")
            await self._lease_integration.report_progress(
                core_api_endpoint=core_api_endpoint,
                lease_id=lease_id,
                progress=0.1,
                message="execution_started",
                trust_token=trust_token,
            )
            result = await self._task_execution_service.execute(request)
            stop_event.set()
            heartbeat_result = await heartbeat_task
            if heartbeat_result.get("status") == "lease_lost":
                return {
                    "status": "lease_lost",
                    "lease_id": lease_id,
                    "task_id": request.task_id,
                    "reason": heartbeat_result.get("reason"),
                }
            completion_status = "completed" if result.status in {"completed", "degraded"} else "failed"
            await self._lease_integration.complete(
                core_api_endpoint=core_api_endpoint,
                lease_id=lease_id,
                status=completion_status,
                result=result.model_dump(),
                error=None if completion_status == "completed" else result.error_message,
                trust_token=trust_token,
            )
            return {
                "status": "completed" if completion_status == "completed" else "failed",
                "lease_id": lease_id,
                "task_id": request.task_id,
                "result": result.model_dump(),
            }
        finally:
            stop_event.set()
            if not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except Exception:
                    pass

    async def _heartbeat_loop(self, *, core_api_endpoint: str, lease_id: str, trust_token: str | None, stop_event: asyncio.Event) -> dict:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._heartbeat_interval_s)
                break
            except asyncio.TimeoutError:
                heartbeat_result = await self._lease_integration.heartbeat(
                    core_api_endpoint=core_api_endpoint,
                    lease_id=lease_id,
                    trust_token=trust_token,
                )
                if heartbeat_result.status != "ok":
                    return {
                        "status": "lease_lost",
                        "reason": heartbeat_result.error or heartbeat_result.status,
                        "payload": heartbeat_result.payload,
                    }
        return {"status": "stopped"}

    def _build_task_request(self, *, job: dict, lease_id: str) -> TaskExecutionRequest | None:
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        task_payload = payload.get("task_request") if isinstance(payload.get("task_request"), dict) else payload
        if not isinstance(task_payload, dict) or not task_payload:
            return None
        try:
            request = TaskExecutionRequest.model_validate(task_payload)
        except Exception:
            return None
        return self._lease_integration.bind_lease_to_task_request(request=request, lease_id=lease_id)

    async def _emit_progress_event(self, *, request: TaskExecutionRequest, progress: float, message: str) -> None:
        if self._execution_telemetry_publisher is None or not hasattr(self._execution_telemetry_publisher, "publish_event"):
            return
        try:
            await self._execution_telemetry_publisher.publish_event(
                event_type="task_progress",
                payload={
                    "task_id": request.task_id,
                    "task_family": request.task_family,
                    "requested_by": request.requested_by,
                    "trace_id": request.trace_id,
                    "prompt_id": request.prompt_id,
                    "lease_id": request.lease_id,
                    "progress": float(progress),
                    "message": message,
                },
            )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[execution-progress-telemetry-failed] %s",
                    {"task_id": request.task_id, "error": str(exc)},
                )
