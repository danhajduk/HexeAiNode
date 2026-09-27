import asyncio
import heapq
import itertools
import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

from ai_node.execution.queue_contract import (
    RUNTIME_LANES,
    infer_runtime_lane,
    lane_capacity,
    lane_contract_snapshot,
    normalize_runtime_lane,
    residency_component_for_lane,
)
from ai_node.time_utils import local_now, local_now_iso


IMPORTANCE_RANK = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
    "background": 4,
}


class ExecutionQueueService:
    def __init__(
        self,
        *,
        logger,
        local_concurrency: int = 1,
        cloud_concurrency: int = 4,
        check_after_seconds: int = 5,
        job_ttl_seconds: int = 3600,
        state_path: str | None = None,
        max_pending_per_client: int = 20,
        extra_queue_concurrency: dict[str, int] | None = None,
        lane_admission_provider: Callable[[dict], dict] | None = None,
    ) -> None:
        self._logger = logger
        self._local_concurrency = max(int(local_concurrency), 1)
        self._cloud_concurrency = max(int(cloud_concurrency), 1)
        self._check_after_seconds = max(int(check_after_seconds), 1)
        self._job_ttl_seconds = max(int(job_ttl_seconds), 60)
        self._max_pending_per_client = max(int(max_pending_per_client), 0)
        self._lane_admission_provider = lane_admission_provider
        self._sequence = itertools.count(1)
        self._lock = asyncio.Lock()
        self._jobs: dict[str, dict] = {}
        self._queue_concurrency: dict[str, int] = {
            "local": self._local_concurrency,
            "cloud": self._cloud_concurrency,
            "text_llm": 1,
            "vision_llm": 1,
            "visual_gpu": 1,
            "visual_cpu": 1,
            "training_runtime": 1,
        }
        for queue_name, concurrency in (extra_queue_concurrency or {}).items():
            normalized = self._normalize_queue_key(queue_name)
            if normalized not in {"local", "cloud"}:
                self._queue_concurrency[normalized] = max(int(concurrency), 1)
        self._queues: dict[str, list[tuple[int, int, str]]] = {queue_key: [] for queue_key in self._queue_concurrency}
        self._active_counts: dict[str, int] = {queue_key: 0 for queue_key in self._queue_concurrency}
        self._dispatcher_tasks: dict[str, asyncio.Task] = {}
        self._state_path = Path(state_path) if str(state_path or "").strip() else None
        self._recovered_unfinished_count = 0
        self._load_persisted_jobs()

    def queued_response(self, *, job_id: str, base_path: str = "/api/execution/jobs") -> dict:
        job = self._jobs.get(job_id) or {}
        eta = self._queue_eta(job_id=job_id)
        queue_state = self._queue_state(job=job, eta=eta)
        return {
            "status": "queued",
            "job_id": job_id,
            "job_name": job.get("job_name"),
            "check_after_seconds": self._check_after_seconds,
            "status_url": f"{base_path}/{job_id}",
            "queue": job.get("queue"),
            "queue_position": self._queue_position(job_id=job_id),
            "eta": eta,
            "importance": job.get("importance"),
            "queue_intent": deepcopy(job.get("queue_intent")) if isinstance(job.get("queue_intent"), dict) else None,
            "routing_decision": deepcopy(job.get("routing_decision")) if isinstance(job.get("routing_decision"), dict) else None,
            "queue_state": queue_state,
            "expires_at": job.get("expires_at"),
        }

    async def enqueue(
        self,
        *,
        queue: str,
        importance: str,
        job_name: str,
        request_payload: dict,
        runner: Callable[[], Awaitable[dict]],
        routing_decision: dict | None = None,
        queue_intent: dict | None = None,
        client_id: str | None = None,
    ) -> dict:
        queue_key = self._normalize_queue_key(queue)
        importance_key = str(importance or "normal").strip().lower()
        rank = IMPORTANCE_RANK.get(importance_key, IMPORTANCE_RANK["normal"])
        sequence = next(self._sequence)
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        now = local_now()
        client_key = str(client_id or "").strip()
        normalized_queue_intent = deepcopy(queue_intent) if isinstance(queue_intent, dict) else {}
        runtime_lane = self._runtime_lane_for_job(
            queue_key=queue_key,
            request_payload=request_payload,
            queue_intent=normalized_queue_intent,
        )
        normalized_queue_intent.setdefault("runtime_lane", runtime_lane)
        normalized_queue_intent.setdefault("priority", importance_key if importance_key in IMPORTANCE_RANK else "normal")
        deadline_sort = self._deadline_sort_value(queue_intent=normalized_queue_intent)
        job = {
            "job_id": job_id,
            "job_name": str(job_name or job_id).strip() or job_id,
            "client_id": client_key or None,
            "queue": queue_key,
            "runtime_lane": runtime_lane,
            "importance": importance_key if importance_key in IMPORTANCE_RANK else "normal",
            "priority": normalized_queue_intent.get("priority"),
            "queue_intent": normalized_queue_intent or None,
            "routing_decision": deepcopy(routing_decision) if isinstance(routing_decision, dict) else None,
            "status": "queued",
            "request": deepcopy(request_payload) if isinstance(request_payload, dict) else {},
            "result": None,
            "error": None,
            "created_at": now.isoformat(),
            "queued_at": now.isoformat(),
            "staged_at": None,
            "started_at": None,
            "completed_at": None,
            "expires_at": (now + timedelta(seconds=self._job_ttl_seconds)).isoformat(),
            "sequence": sequence,
            "_runner": runner,
        }
        async with self._lock:
            self._monitor_deadlines_locked()
            if client_key and self._max_pending_per_client:
                pending_count = self._client_pending_count_locked(client_id=client_key)
                if pending_count >= self._max_pending_per_client:
                    return {
                        "status": "rejected",
                        "error_code": "queue_client_limit_exceeded",
                        "error_message": "queue_client_limit_exceeded",
                        "client_id": client_key,
                        "queue": queue_key,
                        "pending_count": pending_count,
                        "max_pending_per_client": self._max_pending_per_client,
                        "check_after_seconds": self._check_after_seconds,
                    }
            estimated_start_seconds = self._estimated_start_seconds_locked(
                queue_key=queue_key,
                position=len(self._queues.get(queue_key) or []) + 1,
            )
            max_wait_seconds = self._queue_intent_max_wait_seconds(normalized_queue_intent)
            if max_wait_seconds is not None and estimated_start_seconds > max_wait_seconds:
                return {
                    "status": "rejected",
                    "error_code": "rejected_deadline_unreachable",
                    "error_message": "queue_wait_budget_unreachable",
                    "queue": queue_key,
                    "importance": job["importance"],
                    "queue_intent": normalized_queue_intent or None,
                    "estimated_start_seconds": estimated_start_seconds,
                    "max_wait_seconds": max_wait_seconds,
                    "check_after_seconds": self._check_after_seconds,
                }
            self._jobs[job_id] = job
            heapq.heappush(self._queues[queue_key], self._queue_entry(rank=rank, deadline_sort=deadline_sort, sequence=sequence, job_id=job_id))
            self._persist_jobs_locked()
            self._ensure_dispatcher_locked(queue_key)
        return self.queued_response(job_id=job_id)

    async def job_status(self, *, job_id: str) -> dict:
        async with self._lock:
            self._monitor_deadlines_locked()
            job = self._jobs.get(str(job_id or "").strip())
            if not isinstance(job, dict):
                return {"status": "not_found", "job_id": job_id}
            return self._public_job_payload(job)

    async def acknowledge_artifacts(self, *, job_id: str, acknowledgement: dict) -> dict:
        normalized_job_id = str(job_id or "").strip()
        async with self._lock:
            job = self._jobs.get(normalized_job_id)
            if not isinstance(job, dict):
                return {"status": "not_found", "job_id": job_id}
            if str(job.get("status") or "").strip().lower() != "completed":
                return {"status": "not_ready", "job_id": normalized_job_id}
            existing = job.get("artifact_acknowledgement")
            if isinstance(existing, dict):
                return deepcopy(existing)
            recorded = deepcopy(acknowledgement) if isinstance(acknowledgement, dict) else {}
            recorded["status"] = "acknowledged"
            recorded["job_id"] = normalized_job_id
            recorded.setdefault("acknowledged_at", local_now_iso())
            job["artifact_acknowledgement"] = recorded
            self._persist_jobs_locked()
            return deepcopy(recorded)

    async def cancel_job(self, *, job_id: str, reason: str | None = None) -> dict:
        normalized_job_id = str(job_id or "").strip()
        async with self._lock:
            job = self._jobs.get(normalized_job_id)
            if not isinstance(job, dict):
                return {"status": "not_found", "job_id": job_id}
            current_status = str(job.get("status") or "").strip().lower()
            if current_status == "queued":
                queue_key = str(job.get("queue") or "")
                self._queues[queue_key] = [
                    item for item in list(self._queues.get(queue_key) or []) if self._job_id_from_queue_entry(item) != normalized_job_id
                ]
                heapq.heapify(self._queues[queue_key])
                cancelled_at = local_now_iso()
                cancel_reason = str(reason or "cancelled_by_client").strip() or "cancelled_by_client"
                job["status"] = "cancelled"
                job["completed_at"] = cancelled_at
                job["error"] = {"code": "cancelled", "message": cancel_reason}
                job["_runner"] = None
                self._persist_jobs_locked()
                return self._public_job_payload(job)
            if current_status in {"running"}:
                payload = self._public_job_payload(job)
                payload["cancellable"] = False
                payload["cancel_rejected_reason"] = "job_already_running"
                return payload
            payload = self._public_job_payload(job)
            payload["cancellable"] = False
            payload["cancel_rejected_reason"] = f"job_already_{current_status or 'terminal'}"
            return payload

    async def diagnostics(self) -> dict:
        async with self._lock:
            self._monitor_deadlines_locked()
            queues = {}
            for queue_key, entries in self._queues.items():
                queued_ids = [self._job_id_from_queue_entry(item) for item in sorted(entries)]
                per_importance: dict[str, int] = {}
                per_client_pending: dict[str, int] = {}
                oldest_queued_at = None
                active_job = None
                staged_job = None
                for job_id in queued_ids:
                    job = self._jobs.get(job_id) or {}
                    importance = str(job.get("importance") or "normal")
                    per_importance[importance] = per_importance.get(importance, 0) + 1
                    client_id = str(job.get("client_id") or "").strip()
                    if client_id:
                        per_client_pending[client_id] = per_client_pending.get(client_id, 0) + 1
                    queued_at = job.get("queued_at")
                    if queued_at and (oldest_queued_at is None or str(queued_at) < str(oldest_queued_at)):
                        oldest_queued_at = queued_at
                for job in self._jobs.values():
                    if str(job.get("queue") or "") != queue_key or str(job.get("status") or "") != "running":
                        continue
                    if active_job is None:
                        active_job = {
                            "job_id": job.get("job_id"),
                            "job_name": job.get("job_name"),
                            "task_id": (job.get("request") or {}).get("task_id") if isinstance(job.get("request"), dict) else None,
                            "importance": job.get("importance"),
                            "started_at": job.get("started_at"),
                            "client_id": job.get("client_id"),
                            "queue_state": self._queue_state(job=job, eta=self._queue_eta(job_id=str(job.get("job_id") or ""))),
                        }
                    client_id = str(job.get("client_id") or "").strip()
                    if client_id:
                        per_client_pending[client_id] = per_client_pending.get(client_id, 0) + 1
                oldest_queued_age_seconds = None
                if oldest_queued_at:
                    oldest_queued_age_seconds = self._age_seconds(iso_value=str(oldest_queued_at))
                next_job = self._jobs.get(queued_ids[0]) if queued_ids else None
                staged_job = self._queue_job_summary(next_job) if isinstance(next_job, dict) else None
                staged_count = 1 if staged_job is not None else 0
                queues[queue_key] = {
                    "queued_count": len(queued_ids),
                    "active_count": self._active_counts.get(queue_key, 0),
                    "staged_count": staged_count,
                    "backlog_count": max(len(queued_ids) - staged_count, 0),
                    "concurrency": self._concurrency(queue_key),
                    "runtime_lane": self._queue_runtime_lane(queue_key=queue_key, next_job=next_job),
                    "oldest_queued_at": oldest_queued_at,
                    "oldest_queued_age_seconds": oldest_queued_age_seconds,
                    "active_job": active_job,
                    "staged_job": staged_job,
                    "next_job": staged_job,
                    "per_importance": per_importance,
                    "per_client_pending": per_client_pending,
                }
            lanes = self._lane_diagnostics_locked(queues=queues)
            global_queue = self._global_queue_diagnostics_locked(queues=queues, lanes=lanes)
            return {
                "configured": True,
                "schema_version": "2.0",
                "dispatch_model": {
                    "backlog_owner": "scheduler",
                    "max_active_per_runtime_lane": 1,
                    "max_staged_per_runtime_lane": 1,
                },
                "fairness": {
                    "max_pending_per_client": self._max_pending_per_client,
                    "scope": "all_queues",
                },
                "lane_contract": lane_contract_snapshot(),
                "global_queue": global_queue,
                "lanes": lanes,
                "global_backlog_count": global_queue.get("backlog_count"),
                "persistence": {
                    "configured": self._state_path is not None,
                    "path": str(self._state_path) if self._state_path is not None else None,
                    "recovered_unfinished_count": self._recovered_unfinished_count,
                },
                "queues": queues,
                "job_count": len(self._jobs),
                "generated_at": local_now_iso(),
            }

    async def queue_pressure(self, *, queue: str) -> dict:
        queue_key = self._normalize_queue_key(queue)
        async with self._lock:
            self._monitor_deadlines_locked()
            queued_count = len(self._queues.get(queue_key) or [])
            active_count = self._active_counts.get(queue_key, 0)
            return {
                "queue": queue_key,
                "queued_count": queued_count,
                "active_count": active_count,
                "concurrency": self._concurrency(queue_key),
                "pending_count": queued_count + active_count,
            }

    async def queue_start_estimate(self, *, queue: str, new_job_position: int | None = None) -> dict:
        queue_key = self._normalize_queue_key(queue)
        async with self._lock:
            self._monitor_deadlines_locked()
            position = int(new_job_position or (len(self._queues.get(queue_key) or []) + 1))
            estimated_seconds = self._estimated_start_seconds_locked(queue_key=queue_key, position=position)
            return {
                "queue": queue_key,
                "position": position,
                "estimated_start_seconds": estimated_seconds,
                "estimated_start_at": (local_now() + timedelta(seconds=estimated_seconds)).isoformat(),
                "confidence": "rough",
            }

    async def has_matching_work(
        self,
        *,
        queue: str,
        importance: str,
        task_families: set[str],
        statuses: set[str] | None = None,
    ) -> bool:
        queue_key = self._normalize_queue_key(queue)
        importance_key = str(importance or "").strip().lower()
        family_keys = {str(item or "").strip().lower() for item in task_families if str(item or "").strip()}
        status_keys = {str(item or "").strip().lower() for item in (statuses or {"queued", "running"}) if str(item or "").strip()}
        async with self._lock:
            for job in self._jobs.values():
                if str(job.get("queue") or "").strip().lower() != queue_key:
                    continue
                if str(job.get("importance") or "").strip().lower() != importance_key:
                    continue
                if str(job.get("status") or "").strip().lower() not in status_keys:
                    continue
                request = job.get("request") if isinstance(job.get("request"), dict) else {}
                task_family = str(request.get("task_family") or "").strip().lower()
                if task_family in family_keys:
                    return True
        return False

    async def matching_work_snapshot(
        self,
        *,
        queue: str,
        task_families: set[str],
        statuses: set[str] | None = None,
    ) -> dict:
        queue_key = self._normalize_queue_key(queue)
        family_keys = {str(item or "").strip().lower() for item in task_families if str(item or "").strip()}
        status_keys = {str(item or "").strip().lower() for item in (statuses or {"queued", "running"}) if str(item or "").strip()}
        async with self._lock:
            return self._matching_work_snapshot_from_jobs_locked(
                queue_key=queue_key,
                family_keys=family_keys,
                status_keys=status_keys,
            )

    def matching_work_snapshot_nowait(
        self,
        *,
        queue: str,
        task_families: set[str],
        statuses: set[str] | None = None,
    ) -> dict:
        queue_key = self._normalize_queue_key(queue)
        family_keys = {str(item or "").strip().lower() for item in task_families if str(item or "").strip()}
        status_keys = {str(item or "").strip().lower() for item in (statuses or {"queued", "running"}) if str(item or "").strip()}
        return self._matching_work_snapshot_from_jobs_locked(
            queue_key=queue_key,
            family_keys=family_keys,
            status_keys=status_keys,
            jobs_snapshot=self._jobs_snapshot_nowait(),
        )

    def _matching_work_snapshot_from_jobs_locked(
        self,
        *,
        queue_key: str,
        family_keys: set[str],
        status_keys: set[str],
        jobs_snapshot: list[dict] | None = None,
    ) -> dict:
        jobs = []
        for job in jobs_snapshot if jobs_snapshot is not None else self._jobs.values():
            if str(job.get("queue") or "").strip().lower() != queue_key:
                continue
            status_key = str(job.get("status") or "").strip().lower()
            if status_key not in status_keys:
                continue
            request = job.get("request") if isinstance(job.get("request"), dict) else {}
            task_family = str(request.get("task_family") or "").strip().lower()
            if task_family not in family_keys:
                continue
            constraints = request.get("constraints") if isinstance(request.get("constraints"), dict) else {}
            routing_policy = constraints.get("routing_policy") if isinstance(constraints.get("routing_policy"), dict) else {}
            requested_provider = str(request.get("requested_provider") or "").strip().lower()
            routing_mode = str(routing_policy.get("mode") or "").strip().lower()
            jobs.append(
                {
                    "job_id": job.get("job_id"),
                    "job_name": job.get("job_name"),
                    "status": status_key,
                    "queue": queue_key,
                    "importance": job.get("importance"),
                    "task_id": request.get("task_id"),
                    "task_family": task_family,
                    "requested_provider": requested_provider or None,
                    "routing_policy_mode": routing_mode or None,
                    "cloud_reroute_candidate": bool(
                        status_key == "queued"
                        and requested_provider not in {"local", "local_vision"}
                        and routing_mode not in {"local_only"}
                    ),
                }
            )
        return {
            "queue": queue_key,
            "task_families": sorted(family_keys),
            "statuses": sorted(status_keys),
            "jobs": jobs,
            "queued_count": sum(1 for item in jobs if item.get("status") == "queued"),
            "active_count": sum(1 for item in jobs if item.get("status") == "running"),
            "cloud_reroute_candidate_count": sum(1 for item in jobs if item.get("cloud_reroute_candidate")),
        }

    def _jobs_snapshot_nowait(self) -> list[dict]:
        for _attempt in range(3):
            try:
                return [deepcopy(job) for job in self._jobs.values() if isinstance(job, dict)]
            except RuntimeError:
                continue
        return []

    def _ensure_dispatcher_locked(self, queue_key: str) -> None:
        task = self._dispatcher_tasks.get(queue_key)
        if task is not None and not task.done():
            return
        self._dispatcher_tasks[queue_key] = asyncio.create_task(self._dispatch_loop(queue_key))

    async def _dispatch_loop(self, queue_key: str) -> None:
        while True:
            async with self._lock:
                if self._active_counts.get(queue_key, 0) >= self._concurrency(queue_key):
                    return
                queue_entries = self._queues.get(queue_key) or []
                if not queue_entries:
                    return
                entry = queue_entries[0]
                job_id = self._job_id_from_queue_entry(entry)
                job = self._jobs.get(job_id)
                if not isinstance(job, dict) or job.get("status") != "queued":
                    heapq.heappop(queue_entries)
                    continue
                admission_job = deepcopy(job)
            admission = await asyncio.to_thread(self._lane_admission_for_job, admission_job)
            async with self._lock:
                queue_entries = self._queues.get(queue_key) or []
                if not queue_entries:
                    continue
                entry = queue_entries[0]
                current_job_id = self._job_id_from_queue_entry(entry)
                if current_job_id != job_id:
                    continue
                job = self._jobs.get(job_id)
                if not isinstance(job, dict) or job.get("status") != "queued":
                    heapq.heappop(queue_entries)
                    continue
                if not admission.get("allowed"):
                    job["blocked_reason"] = admission.get("reason") or "runtime_lane_not_ready"
                    job["blocked_detail"] = admission
                    self._persist_jobs_locked()
                    return
                heapq.heappop(queue_entries)
                job["blocked_reason"] = None
                job["blocked_detail"] = None
                job["status"] = "running"
                job["started_at"] = local_now_iso()
                self._active_counts[queue_key] = self._active_counts.get(queue_key, 0) + 1
                runner = job.get("_runner")
                self._persist_jobs_locked()
            asyncio.create_task(self._run_job(queue_key=queue_key, job_id=job_id, runner=runner))

    async def _run_job(self, *, queue_key: str, job_id: str, runner) -> None:
        try:
            if not callable(runner):
                raise RuntimeError("queued_job_runner_missing")
            result = await runner()
            async with self._lock:
                job = self._jobs.get(job_id)
                if isinstance(job, dict):
                    job["status"] = "completed"
                    job["result"] = result if isinstance(result, dict) else {}
                    job["completed_at"] = local_now_iso()
                    job["_runner"] = None
                    self._persist_jobs_locked()
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[execution-queue-job-failed] %s",
                    {"job_id": job_id, "queue": queue_key, "error": str(exc)},
                )
            async with self._lock:
                job = self._jobs.get(job_id)
                if isinstance(job, dict):
                    job["status"] = "failed"
                    job["error"] = {
                        "code": str(exc).strip() or type(exc).__name__,
                        "message": str(exc).strip() or type(exc).__name__,
                    }
                    job["completed_at"] = local_now_iso()
                    job["_runner"] = None
                    self._persist_jobs_locked()
        finally:
            async with self._lock:
                self._active_counts[queue_key] = max(self._active_counts.get(queue_key, 0) - 1, 0)
                for candidate_queue in list(self._queues.keys()):
                    self._ensure_dispatcher_locked(candidate_queue)

    def _queue_position(self, *, job_id: str) -> int | None:
        job = self._jobs.get(job_id)
        if not isinstance(job, dict):
            return None
        queue_key = str(job.get("queue") or "")
        queued_ids = [self._job_id_from_queue_entry(item) for item in sorted(self._queues.get(queue_key) or [])]
        if job_id not in queued_ids:
            return None
        return queued_ids.index(job_id) + 1

    def _queue_eta(self, *, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        if not isinstance(job, dict):
            return None
        status = str(job.get("status") or "").strip().lower()
        if status == "running":
            return {
                "estimated_start_seconds": 0,
                "estimated_start_at": job.get("started_at"),
                "source": "already_running",
                "confidence": "observed",
            }
        if status != "queued":
            return None
        queue_key = str(job.get("queue") or "")
        position = self._queue_position(job_id=job_id)
        if position is None:
            return None
        estimated_seconds = self._estimated_start_seconds_locked(queue_key=queue_key, position=position)
        return {
            "estimated_start_seconds": estimated_seconds,
            "estimated_start_at": (local_now() + timedelta(seconds=estimated_seconds)).isoformat(),
            "source": "queue_position",
            "confidence": "rough",
        }

    def _queue_state(self, *, job: dict, eta: dict | None = None) -> dict | None:
        if not isinstance(job, dict) or not job.get("job_id"):
            return None
        queue_intent = job.get("queue_intent") if isinstance(job.get("queue_intent"), dict) else {}
        routing_decision = job.get("routing_decision") if isinstance(job.get("routing_decision"), dict) else {}
        queued_at = self._job_queued_at(job)
        max_wait_seconds = self._queue_intent_max_wait_seconds(queue_intent)
        deadline_at = self._queue_intent_deadline_at(queue_intent)
        wait_budget_deadline = queued_at + timedelta(seconds=max_wait_seconds) if queued_at is not None and max_wait_seconds is not None else None
        effective_deadline = min([item for item in (deadline_at, wait_budget_deadline) if item is not None], default=None)
        remaining_wait_seconds = None
        if effective_deadline is not None:
            remaining_wait_seconds = round(max((effective_deadline - local_now()).total_seconds(), 0.0), 3)
        return {
            "queue": job.get("queue"),
            "runtime_lane": job.get("runtime_lane") or self._runtime_lane_for_job(
                queue_key=str(job.get("queue") or ""),
                request_payload=job.get("request") if isinstance(job.get("request"), dict) else {},
                queue_intent=queue_intent,
            ),
            "importance": job.get("importance"),
            "priority": job.get("priority") or queue_intent.get("priority") or job.get("importance"),
            "queue_class": queue_intent.get("queue_class"),
            "max_wait_seconds": max_wait_seconds,
            "deadline_at": deadline_at.isoformat() if deadline_at is not None else None,
            "wait_budget_deadline_at": wait_budget_deadline.isoformat() if wait_budget_deadline is not None else None,
            "remaining_wait_seconds": remaining_wait_seconds,
            "estimated_start_seconds": (eta or {}).get("estimated_start_seconds") if isinstance(eta, dict) else None,
            "estimated_start_at": (eta or {}).get("estimated_start_at") if isinstance(eta, dict) else None,
            "staged_at": job.get("staged_at"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "estimated_vram_mib": queue_intent.get("estimated_vram_mib"),
            "estimated_runtime_seconds": queue_intent.get("estimated_runtime_seconds"),
            "lane_capacity": lane_capacity(job.get("runtime_lane") or queue_intent.get("runtime_lane")),
            "spillover_allowed": bool(queue_intent.get("allow_cloud_spillover")),
            "spillover_selected": bool(routing_decision.get("spillover")),
            "routing_reason": routing_decision.get("reason"),
            "local_unavailable_reason": routing_decision.get("local_unavailable_reason"),
            "cloud_selected_reason": routing_decision.get("cloud_selected_reason"),
        }

    def _queue_job_summary(self, job: dict) -> dict:
        job_id = str(job.get("job_id") or "")
        eta = self._queue_eta(job_id=job_id)
        request = job.get("request") if isinstance(job.get("request"), dict) else {}
        return {
            "job_id": job_id,
            "job_name": job.get("job_name"),
            "task_id": request.get("task_id"),
            "task_family": request.get("task_family"),
            "runtime_lane": job.get("runtime_lane"),
            "status": job.get("status"),
            "created_at": job.get("created_at"),
            "queued_at": job.get("queued_at"),
            "staged_at": job.get("staged_at"),
            "started_at": job.get("started_at"),
            "client_id": job.get("client_id"),
            "blocked_reason": job.get("blocked_reason"),
            "blocked_detail": deepcopy(job.get("blocked_detail")) if isinstance(job.get("blocked_detail"), dict) else None,
            "queue_position": self._queue_position(job_id=job_id),
            "queue_state": self._queue_state(job=job, eta=eta),
        }

    def _estimated_start_seconds_locked(self, *, queue_key: str, position: int) -> int:
        concurrency = max(self._concurrency(queue_key), 1)
        active_count = max(int(self._active_counts.get(queue_key, 0) or 0), 0)
        jobs_ahead = max(active_count + max(int(position), 1) - 1, 0)
        waves_ahead = (jobs_ahead + concurrency - 1) // concurrency if jobs_ahead else 0
        return int(waves_ahead * self._check_after_seconds)

    def _monitor_deadlines_locked(self) -> dict:
        now = local_now()
        changed = False
        expired = []
        rerouted = []
        for job_id, job in list(self._jobs.items()):
            if not isinstance(job, dict) or str(job.get("status") or "").strip().lower() != "queued":
                continue
            queue_intent = job.get("queue_intent") if isinstance(job.get("queue_intent"), dict) else {}
            max_wait = self._queue_intent_max_wait_seconds(queue_intent)
            deadline_at = self._queue_intent_deadline_at(queue_intent)
            queued_at = self._job_queued_at(job) or now
            wait_deadline = queued_at + timedelta(seconds=max_wait) if max_wait is not None else None
            effective_deadline = min([item for item in (deadline_at, wait_deadline) if item is not None], default=None)
            if effective_deadline is None or now <= effective_deadline:
                continue
            queue_key = str(job.get("queue") or "")
            if queue_key == "local" and bool(queue_intent.get("allow_cloud_spillover")):
                self._remove_from_queue_locked(queue_key=queue_key, job_id=job_id)
                job["queue"] = "cloud"
                job["status"] = "queued"
                routing_decision = job.get("routing_decision") if isinstance(job.get("routing_decision"), dict) else {}
                job["routing_decision"] = {
                    **routing_decision,
                    "original_queue": routing_decision.get("original_queue") or "local",
                    "selected_queue": "cloud",
                    "spillover": True,
                    "reason": "rerouted_to_cloud",
                    "local_unavailable_reason": "expired_wait_budget",
                }
                heapq.heappush(
                    self._queues["cloud"],
                    self._queue_entry(
                        rank=IMPORTANCE_RANK.get(str(job.get("importance") or "normal"), IMPORTANCE_RANK["normal"]),
                        deadline_sort=self._deadline_sort_value(queue_intent=queue_intent),
                        sequence=int(job.get("sequence") or 0),
                        job_id=job_id,
                    ),
                )
                rerouted.append(job_id)
                changed = True
                self._ensure_dispatcher_locked("cloud")
                continue
            self._remove_from_queue_locked(queue_key=queue_key, job_id=job_id)
            job["status"] = "expired_wait_budget"
            job["completed_at"] = local_now_iso()
            job["error"] = {"code": "expired_wait_budget", "message": "queue wait budget expired before execution"}
            job["_runner"] = None
            expired.append(job_id)
            changed = True
        if changed:
            self._persist_jobs_locked()
        return {"expired": expired, "rerouted_to_cloud": rerouted, "changed": changed}

    def _remove_from_queue_locked(self, *, queue_key: str, job_id: str) -> None:
        entries = [item for item in list(self._queues.get(queue_key) or []) if self._job_id_from_queue_entry(item) != job_id]
        heapq.heapify(entries)
        self._queues[queue_key] = entries

    @staticmethod
    def _job_queued_at(job: dict) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(job.get("queued_at") or ""))
        except Exception:
            return None
        try:
            local_now() - parsed
            return parsed
        except TypeError:
            return parsed.replace(tzinfo=local_now().tzinfo)

    @staticmethod
    def _queue_intent_deadline_at(queue_intent: dict) -> datetime | None:
        if not isinstance(queue_intent, dict) or not queue_intent.get("deadline_at"):
            return None
        try:
            parsed = datetime.fromisoformat(str(queue_intent.get("deadline_at")))
        except Exception:
            return None
        try:
            local_now() - parsed
            return parsed
        except TypeError:
            return parsed.replace(tzinfo=local_now().tzinfo)

    @staticmethod
    def _job_id_from_queue_entry(entry) -> str:
        if isinstance(entry, tuple) and entry:
            return str(entry[-1] or "")
        return ""

    @staticmethod
    def _queue_entry(*, rank: int, deadline_sort: float, sequence: int, job_id: str) -> tuple:
        return (int(rank), float(deadline_sort), int(sequence), str(job_id))

    @staticmethod
    def _queue_intent_max_wait_seconds(queue_intent: dict) -> int | None:
        if not isinstance(queue_intent, dict):
            return None
        value = queue_intent.get("max_wait_seconds")
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    @staticmethod
    def _deadline_sort_value(*, queue_intent: dict) -> float:
        if not isinstance(queue_intent, dict):
            return float("inf")
        deadline = queue_intent.get("deadline_at")
        if deadline:
            try:
                return datetime.fromisoformat(str(deadline)).timestamp()
            except Exception:
                pass
        max_wait = ExecutionQueueService._queue_intent_max_wait_seconds(queue_intent)
        if max_wait is not None:
            return (local_now() + timedelta(seconds=max_wait)).timestamp()
        return float("inf")

    def _concurrency(self, queue_key: str) -> int:
        return max(int(self._queue_concurrency.get(queue_key) or self._cloud_concurrency), 1)

    def _public_job_payload(self, job: dict) -> dict:
        payload = {
            key: deepcopy(job.get(key))
            for key in (
                "job_id",
                "job_name",
                "client_id",
                "queue",
                "runtime_lane",
                "importance",
                "priority",
                "queue_intent",
                "routing_decision",
                "status",
                "created_at",
                "queued_at",
                "staged_at",
                "started_at",
                "completed_at",
                "expires_at",
                "request",
                "result",
                "error",
                "blocked_reason",
                "blocked_detail",
                "artifact_acknowledgement",
            )
        }
        payload["queue_position"] = self._queue_position(job_id=str(job.get("job_id") or ""))
        payload["eta"] = self._queue_eta(job_id=str(job.get("job_id") or ""))
        payload["queue_state"] = self._queue_state(job=job, eta=payload["eta"])
        payload["check_after_seconds"] = self._check_after_seconds
        return payload

    def _load_persisted_jobs(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[execution-queue-state-load-failed] %s",
                    {"path": str(self._state_path), "error": str(exc).strip() or type(exc).__name__},
                )
            return
        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        max_sequence = 0
        now_iso = local_now_iso()
        for item in jobs if isinstance(jobs, list) else []:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("job_id") or "").strip()
            if not job_id:
                continue
            job = deepcopy(item)
            queue_key = self._normalize_queue_key(job.get("queue"))
            importance = str(job.get("importance") or "normal").strip().lower()
            sequence = max(int(job.get("sequence") or 0), 0)
            max_sequence = max(max_sequence, sequence)
            job["queue"] = queue_key
            job["runtime_lane"] = job.get("runtime_lane") or self._runtime_lane_for_job(
                queue_key=queue_key,
                request_payload=job.get("request") if isinstance(job.get("request"), dict) else {},
                queue_intent=job.get("queue_intent") if isinstance(job.get("queue_intent"), dict) else {},
            )
            job["importance"] = importance if importance in IMPORTANCE_RANK else "normal"
            job["priority"] = job.get("priority") or (job.get("queue_intent") or {}).get("priority") or job["importance"]
            job.setdefault("staged_at", None)
            job["_runner"] = None
            if str(job.get("status") or "").strip().lower() in {"queued", "running"}:
                self._recovered_unfinished_count += 1
                job["status"] = "failed"
                job["completed_at"] = job.get("completed_at") or now_iso
                job["error"] = {
                    "code": "execution_queue_recovery_required",
                    "message": "queued job was recovered after restart without an executable runner; resubmit if still needed",
                }
            self._jobs[job_id] = job
        self._sequence = itertools.count(max_sequence + 1)
        if self._recovered_unfinished_count:
            self._persist_jobs_locked()

    def _persist_jobs_locked(self) -> None:
        if self._state_path is None:
            return
        jobs = []
        for job in self._jobs.values():
            public_job = self._public_job_payload(job)
            if job.get("sequence") is not None:
                public_job["sequence"] = int(job.get("sequence") or 0)
            jobs.append(public_job)
        payload = {
            "schema_version": "1.0",
            "generated_at": local_now_iso(),
            "jobs": sorted(jobs, key=lambda item: int(item.get("sequence") or 0)),
        }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[execution-queue-state-save-failed] %s",
                    {"path": str(self._state_path), "error": str(exc).strip() or type(exc).__name__},
                )

    def _client_pending_count_locked(self, *, client_id: str) -> int:
        client_key = str(client_id or "").strip()
        if not client_key:
            return 0
        return sum(
            1
            for job in self._jobs.values()
            if str(job.get("client_id") or "").strip() == client_key
            and str(job.get("status") or "").strip().lower() in {"queued", "running"}
        )

    def _normalize_queue_key(self, value: object) -> str:
        normalized = str(value or "").strip().lower().replace("-", "_")
        if normalized == "local":
            return "local"
        if normalized in RUNTIME_LANES:
            return normalized
        if normalized in {"visual_runtime", "comfyui", "comfyui_gpu", "gpu_comfyui"}:
            return "visual_gpu"
        if normalized in {"visual_cpu", "comfyui_cpu", "cpu_comfyui"}:
            return "visual_cpu"
        if normalized in {"training", "sd_scripts", "sd_scripts_training"}:
            return "training_runtime"
        if normalized in {"vision", "local_vision"}:
            return "vision_llm"
        if normalized in self._queue_concurrency:
            return normalized
        return "cloud"

    @staticmethod
    def _runtime_lane_for_job(*, queue_key: str, request_payload: dict, queue_intent: dict) -> str:
        requested_lane = queue_intent.get("runtime_lane") if isinstance(queue_intent, dict) else None
        if requested_lane:
            return normalize_runtime_lane(requested_lane)
        request = request_payload if isinstance(request_payload, dict) else {}
        return infer_runtime_lane(
            queue=queue_key,
            task_family=request.get("task_family"),
            requested_provider=request.get("requested_provider"),
        )

    @staticmethod
    def _queue_runtime_lane(*, queue_key: str, next_job: dict | None = None) -> str:
        if isinstance(next_job, dict) and next_job.get("runtime_lane"):
            return normalize_runtime_lane(next_job.get("runtime_lane"))
        return infer_runtime_lane(queue=queue_key)

    def _lane_diagnostics_locked(self, *, queues: dict) -> dict:
        lanes = {
            lane: {
                "lane": lane,
                "residency_component_id": residency_component_for_lane(lane),
                "queued_count": 0,
                "active_count": 0,
                "staged_count": 0,
                "backlog_count": 0,
                "capacity": lane_capacity(lane),
                "active_job": None,
                "staged_job": None,
                "next_job": None,
                "blocked_reason": None,
            }
            for lane in RUNTIME_LANES
        }
        queued_by_lane: dict[str, list[dict]] = {lane: [] for lane in RUNTIME_LANES}
        for job in self._jobs.values():
            if not isinstance(job, dict):
                continue
            status = str(job.get("status") or "").strip().lower()
            if status not in {"queued", "running"}:
                continue
            lane = normalize_runtime_lane(job.get("runtime_lane") or job.get("queue"))
            if lane not in lanes:
                continue
            if status == "queued":
                queued_by_lane[lane].append(job)
                lanes[lane]["queued_count"] += 1
                continue
            lanes[lane]["active_count"] += 1
            if lanes[lane]["active_job"] is None:
                lanes[lane]["active_job"] = {
                    "job_id": job.get("job_id"),
                    "job_name": job.get("job_name"),
                    "task_id": (job.get("request") or {}).get("task_id") if isinstance(job.get("request"), dict) else None,
                    "importance": job.get("importance"),
                    "started_at": job.get("started_at"),
                    "client_id": job.get("client_id"),
                    "queue_state": self._queue_state(job=job, eta=self._queue_eta(job_id=str(job.get("job_id") or ""))),
                }
        for lane, jobs in queued_by_lane.items():
            if not jobs:
                continue
            jobs = sorted(
                jobs,
                key=lambda job: self._queue_entry(
                    rank=IMPORTANCE_RANK.get(str(job.get("importance") or "normal"), IMPORTANCE_RANK["normal"]),
                    deadline_sort=self._deadline_sort_value(
                        queue_intent=job.get("queue_intent") if isinstance(job.get("queue_intent"), dict) else {}
                    ),
                    sequence=int(job.get("sequence") or 0),
                    job_id=str(job.get("job_id") or ""),
                ),
            )
            staged_job = self._queue_job_summary(jobs[0])
            lanes[lane]["next_job"] = staged_job
            if staged_job.get("blocked_reason"):
                lanes[lane]["staged_count"] = 0
                lanes[lane]["backlog_count"] = int(lanes[lane]["queued_count"])
                lanes[lane]["blocked_reason"] = staged_job.get("blocked_reason")
                continue
            lanes[lane]["staged_count"] = 1
            lanes[lane]["backlog_count"] = max(int(lanes[lane]["queued_count"]) - 1, 0)
            lanes[lane]["staged_job"] = staged_job
        return lanes

    def _lane_admission_for_job(self, job: dict) -> dict:
        if not callable(self._lane_admission_provider):
            return {"allowed": True, "reason": "no_lane_admission_provider"}
        try:
            payload = self._lane_admission_provider(self._public_job_payload(job))
        except Exception as exc:
            return {
                "allowed": False,
                "reason": "lane_admission_provider_failed",
                "error": str(exc).strip() or type(exc).__name__,
            }
        if not isinstance(payload, dict):
            return {"allowed": True, "reason": "lane_admission_provider_empty"}
        return {**payload, "allowed": bool(payload.get("allowed"))}

    def _global_queue_diagnostics_locked(self, *, queues: dict, lanes: dict) -> dict:
        queued_jobs = []
        for entries in self._queues.values():
            for entry in entries:
                job_id = self._job_id_from_queue_entry(entry)
                job = self._jobs.get(job_id)
                if not isinstance(job, dict) or str(job.get("status") or "") != "queued":
                    continue
                queued_jobs.append((entry, job))
        ordered_jobs = [self._queue_job_summary(job) for _, job in sorted(queued_jobs, key=lambda item: item[0])]
        active_count = sum(int(item.get("active_count") or 0) for item in lanes.values())
        staged_count = sum(int(item.get("staged_count") or 0) for item in lanes.values())
        queued_count = len(ordered_jobs)
        return {
            "queued_count": queued_count,
            "active_count": active_count,
            "staged_count": staged_count,
            "backlog_count": max(queued_count - staged_count, 0),
            "next_dispatch_candidate": ordered_jobs[0] if ordered_jobs else None,
            "queued_jobs": ordered_jobs,
            "lanes": {
                lane_key: {
                    "queued_count": lane.get("queued_count"),
                    "active_count": lane.get("active_count"),
                    "staged_count": lane.get("staged_count"),
                    "backlog_count": lane.get("backlog_count"),
                }
                for lane_key, lane in lanes.items()
            },
        }

    @staticmethod
    def _age_seconds(*, iso_value: str) -> float | None:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except Exception:
            return None
        try:
            age = local_now() - parsed
        except TypeError:
            parsed = parsed.replace(tzinfo=local_now().tzinfo)
            age = local_now() - parsed
        return round(max(age.total_seconds(), 0.0), 3)
