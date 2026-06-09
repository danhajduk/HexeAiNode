import asyncio
import heapq
import itertools
import json
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

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
    ) -> None:
        self._logger = logger
        self._local_concurrency = max(int(local_concurrency), 1)
        self._cloud_concurrency = max(int(cloud_concurrency), 1)
        self._check_after_seconds = max(int(check_after_seconds), 1)
        self._job_ttl_seconds = max(int(job_ttl_seconds), 60)
        self._max_pending_per_client = max(int(max_pending_per_client), 0)
        self._sequence = itertools.count(1)
        self._lock = asyncio.Lock()
        self._jobs: dict[str, dict] = {}
        self._queue_concurrency: dict[str, int] = {
            "local": self._local_concurrency,
            "cloud": self._cloud_concurrency,
            "cpu_comfyui": 1,
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
            "routing_decision": deepcopy(job.get("routing_decision")) if isinstance(job.get("routing_decision"), dict) else None,
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
        client_id: str | None = None,
    ) -> dict:
        queue_key = self._normalize_queue_key(queue)
        importance_key = str(importance or "normal").strip().lower()
        rank = IMPORTANCE_RANK.get(importance_key, IMPORTANCE_RANK["normal"])
        sequence = next(self._sequence)
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        now = local_now()
        client_key = str(client_id or "").strip()
        job = {
            "job_id": job_id,
            "job_name": str(job_name or job_id).strip() or job_id,
            "client_id": client_key or None,
            "queue": queue_key,
            "importance": importance_key if importance_key in IMPORTANCE_RANK else "normal",
            "routing_decision": deepcopy(routing_decision) if isinstance(routing_decision, dict) else None,
            "status": "queued",
            "request": deepcopy(request_payload) if isinstance(request_payload, dict) else {},
            "result": None,
            "error": None,
            "created_at": now.isoformat(),
            "queued_at": now.isoformat(),
            "started_at": None,
            "completed_at": None,
            "expires_at": (now + timedelta(seconds=self._job_ttl_seconds)).isoformat(),
            "sequence": sequence,
            "_runner": runner,
        }
        async with self._lock:
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
            self._jobs[job_id] = job
            heapq.heappush(self._queues[queue_key], (rank, sequence, job_id))
            self._persist_jobs_locked()
            self._ensure_dispatcher_locked(queue_key)
        return self.queued_response(job_id=job_id)

    async def job_status(self, *, job_id: str) -> dict:
        async with self._lock:
            job = self._jobs.get(str(job_id or "").strip())
            if not isinstance(job, dict):
                return {"status": "not_found", "job_id": job_id}
            return self._public_job_payload(job)

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
                    item for item in list(self._queues.get(queue_key) or []) if item[2] != normalized_job_id
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
            queues = {}
            for queue_key, entries in self._queues.items():
                queued_ids = [item[2] for item in sorted(entries)]
                per_importance: dict[str, int] = {}
                per_client_pending: dict[str, int] = {}
                oldest_queued_at = None
                active_job = None
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
                        }
                    client_id = str(job.get("client_id") or "").strip()
                    if client_id:
                        per_client_pending[client_id] = per_client_pending.get(client_id, 0) + 1
                oldest_queued_age_seconds = None
                if oldest_queued_at:
                    oldest_queued_age_seconds = self._age_seconds(iso_value=str(oldest_queued_at))
                queues[queue_key] = {
                    "queued_count": len(queued_ids),
                    "active_count": self._active_counts.get(queue_key, 0),
                    "concurrency": self._concurrency(queue_key),
                    "oldest_queued_at": oldest_queued_at,
                    "oldest_queued_age_seconds": oldest_queued_age_seconds,
                    "active_job": active_job,
                    "per_importance": per_importance,
                    "per_client_pending": per_client_pending,
                }
            return {
                "configured": True,
                "fairness": {
                    "max_pending_per_client": self._max_pending_per_client,
                    "scope": "all_queues",
                },
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
            queued_count = len(self._queues.get(queue_key) or [])
            active_count = self._active_counts.get(queue_key, 0)
            return {
                "queue": queue_key,
                "queued_count": queued_count,
                "active_count": active_count,
                "concurrency": self._concurrency(queue_key),
                "pending_count": queued_count + active_count,
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
        jobs = []
        async with self._lock:
            for job in self._jobs.values():
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
                _, _, job_id = heapq.heappop(queue_entries)
                job = self._jobs.get(job_id)
                if not isinstance(job, dict) or job.get("status") != "queued":
                    continue
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
                self._ensure_dispatcher_locked(queue_key)

    def _queue_position(self, *, job_id: str) -> int | None:
        job = self._jobs.get(job_id)
        if not isinstance(job, dict):
            return None
        queue_key = str(job.get("queue") or "")
        queued_ids = [item[2] for item in sorted(self._queues.get(queue_key) or [])]
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
        concurrency = max(self._concurrency(queue_key), 1)
        active_count = max(int(self._active_counts.get(queue_key, 0) or 0), 0)
        jobs_ahead = max(active_count + position - 1, 0)
        waves_ahead = (jobs_ahead + concurrency - 1) // concurrency if jobs_ahead else 0
        estimated_seconds = waves_ahead * self._check_after_seconds
        return {
            "estimated_start_seconds": estimated_seconds,
            "estimated_start_at": (local_now() + timedelta(seconds=estimated_seconds)).isoformat(),
            "source": "queue_position",
            "confidence": "rough",
        }

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
                "importance",
                "routing_decision",
                "status",
                "created_at",
                "queued_at",
                "started_at",
                "completed_at",
                "expires_at",
                "request",
                "result",
                "error",
            )
        }
        payload["queue_position"] = self._queue_position(job_id=str(job.get("job_id") or ""))
        payload["eta"] = self._queue_eta(job_id=str(job.get("job_id") or ""))
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
            job["importance"] = importance if importance in IMPORTANCE_RANK else "normal"
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
        if normalized in self._queue_concurrency or normalized == "cpu_comfyui":
            return normalized
        return "cloud"

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
