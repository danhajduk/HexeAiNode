#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_JOB_STATES = {"completed", "failed", "cancelled", "expired", "not_found"}
ONE_PIXEL_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def api_request(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - operator-provided local URL
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    return json.loads(body) if body else {}


def execution_payload(*, task_id: str, job_name: str, lane: str, task_family: str, inputs: dict[str, Any]) -> dict[str, Any]:
    queue_class = "background" if lane in {"visual_gpu", "visual_cpu", "training_runtime"} else "interactive"
    max_wait = 21600 if queue_class == "background" else 600
    timeout_s = 240 if lane in {"visual_gpu", "visual_cpu"} else 120
    payload = {
        "task_id": task_id,
        "job_name": job_name,
        "task_family": task_family,
        "requested_by": "model-residency-smoke",
        "requested_provider": "local",
        "inputs": inputs,
        "constraints": {"routing_policy": {"mode": "local_only"}},
        "response_mode": "async_if_queued",
        "timeout_s": timeout_s,
        "priority": "normal",
        "queue": {
            "importance": "normal",
            "queue_class": queue_class,
            "runtime_lane": lane,
            "max_wait_seconds": max_wait,
            "local_preferred": True,
            "routing_policy": "local_only",
            "allow_cloud_spillover": False,
            "reason": "operator model-residency switching smoke",
        },
        "trace_id": task_id,
    }
    if lane == "visual_gpu":
        payload["timeout_s"] = 300
        payload["queue"]["estimated_vram_mib"] = 5120
        payload["queue"]["estimated_runtime_seconds"] = 90
    return payload


def smoke_jobs(prefix: str, visual_steps: int) -> list[dict[str, Any]]:
    visual_inputs = {
        "prompt": "simple polished gray cube on a plain dark background, smoke test image",
        "negative_prompt": "text, watermark, malformed",
        "width": 512,
        "height": 512,
        "steps": visual_steps,
        "cfg": 4,
        "randomize_seed": True,
    }
    vision_inputs = {
        "prompt": "Return strict JSON with keys person_present and description.",
        "image_filename": "one-pixel.png",
        "image_data_base64": ONE_PIXEL_PNG_BASE64,
        "max_tokens": 80,
    }
    return [
        execution_payload(
            task_id=f"{prefix}-text-1",
            job_name="smoke text default",
            lane="text_llm",
            task_family="task.chat",
            inputs={"prompt": "Reply with the single word ready."},
        ),
        execution_payload(
            task_id=f"{prefix}-vision-1",
            job_name="smoke vision default",
            lane="vision_llm",
            task_family="task.vision_analysis",
            inputs=vision_inputs,
        ),
        execution_payload(
            task_id=f"{prefix}-visual-1",
            job_name="smoke visual load",
            lane="visual_gpu",
            task_family="task.image_generation",
            inputs=visual_inputs,
        ),
        execution_payload(
            task_id=f"{prefix}-visual-2",
            job_name="smoke visual before vision",
            lane="visual_gpu",
            task_family="task.image_generation",
            inputs={**visual_inputs, "prompt": "small blue sphere on a neutral background, smoke test image"},
        ),
        execution_payload(
            task_id=f"{prefix}-vision-2",
            job_name="smoke vision after visual",
            lane="vision_llm",
            task_family="task.vision_analysis",
            inputs=vision_inputs,
        ),
        execution_payload(
            task_id=f"{prefix}-vision-3",
            job_name="smoke vision before visual",
            lane="vision_llm",
            task_family="task.vision_analysis",
            inputs=vision_inputs,
        ),
        execution_payload(
            task_id=f"{prefix}-visual-3",
            job_name="smoke visual after vision",
            lane="visual_gpu",
            task_family="task.image_generation",
            inputs={**visual_inputs, "prompt": "small green pyramid on a neutral background, smoke test image"},
        ),
    ]


def summarize_scheduler(payload: dict[str, Any]) -> dict[str, Any]:
    scheduler = payload.get("local_scheduler") if isinstance(payload.get("local_scheduler"), dict) else {}
    components = scheduler.get("components") if isinstance(scheduler.get("components"), list) else []
    return {
        str(component.get("component_id")): {
            "desired_state": component.get("desired_state"),
            "desired_model_state": component.get("desired_model_state"),
            "observed_state": component.get("observed_state"),
            "container_state": component.get("container_state"),
            "model_state": component.get("model_state"),
            "loaded_model": component.get("loaded_model"),
            "vram_mib": ((component.get("usage_statistics") or {}).get("current") or {}).get("vram_mib"),
            "blockers": component.get("blockers"),
        }
        for component in components
        if isinstance(component, dict)
    }


def summarize_queues(payload: dict[str, Any]) -> dict[str, Any]:
    lanes = payload.get("lanes") if isinstance(payload.get("lanes"), dict) else {}
    return {
        lane: {
            "active_count": data.get("active_count"),
            "staged_count": data.get("staged_count"),
            "backlog_count": data.get("backlog_count"),
            "blocked_reason": data.get("blocked_reason"),
            "active_job": (data.get("active_job") or {}).get("job_id") if isinstance(data.get("active_job"), dict) else None,
            "staged_job": (data.get("staged_job") or data.get("next_job") or {}).get("job_id")
            if isinstance(data.get("staged_job") or data.get("next_job"), dict)
            else None,
        }
        for lane, data in lanes.items()
        if isinstance(data, dict)
    }


def snapshot(base_url: str, label: str) -> dict[str, Any]:
    scheduler = api_request(base_url, "GET", "/api/local-scheduler/status")
    queues = api_request(base_url, "GET", "/api/execution/queues")
    return {
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scheduler": summarize_scheduler(scheduler),
        "queues": summarize_queues(queues),
    }


def validate_snapshot(snapshot_payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    scheduler = snapshot_payload.get("scheduler") if isinstance(snapshot_payload.get("scheduler"), dict) else {}
    visual = scheduler.get("visual_gpu") if isinstance(scheduler.get("visual_gpu"), dict) else {}
    vision = scheduler.get("vision_llm") if isinstance(scheduler.get("vision_llm"), dict) else {}
    visual_model_state = str(visual.get("model_state") or "").lower()
    vision_model_state = str(vision.get("model_state") or "").lower()
    if visual_model_state == "loaded" and vision_model_state == "loaded":
        errors.append("visual_gpu and vision_llm models are both loaded")
    return errors


def validate_final_snapshot(snapshot_payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    queues = snapshot_payload.get("queues") if isinstance(snapshot_payload.get("queues"), dict) else {}
    for lane, queue in queues.items():
        if not isinstance(queue, dict):
            continue
        active_count = int(queue.get("active_count") or 0)
        staged_count = int(queue.get("staged_count") or 0)
        backlog_count = int(queue.get("backlog_count") or 0)
        if active_count or staged_count or backlog_count:
            errors.append(
                f"{lane} still has work active={active_count} staged={staged_count} backlog={backlog_count}"
            )
    return errors


def wait_for_jobs(base_url: str, job_ids: list[str], timeout_seconds: int, poll_seconds: float, report: dict[str, Any]) -> None:
    deadline = time.monotonic() + timeout_seconds
    remaining = set(job_ids)
    while remaining and time.monotonic() < deadline:
        report["snapshots"].append(snapshot(base_url, f"poll-{len(report['snapshots'])}"))
        for job_id in list(remaining):
            status = api_request(base_url, "GET", f"/api/execution/jobs/{job_id}")
            report["job_statuses"][job_id] = status
            if str(status.get("status") or "").lower() in TERMINAL_JOB_STATES:
                remaining.remove(job_id)
        time.sleep(poll_seconds)
    if remaining:
        raise TimeoutError(f"timed out waiting for jobs: {', '.join(sorted(remaining))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Live model-residency switching smoke for Hexe AI Node.")
    parser.add_argument("--base-url", default=os.environ.get("HEXE_NODE_API_BASE", "http://127.0.0.1:9002"))
    parser.add_argument("--dry-run", action="store_true", help="Print planned requests without submitting jobs.")
    parser.add_argument("--submit-interval", type=float, default=2.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--visual-steps", type=int, default=4)
    parser.add_argument("--include-training", action="store_true", help="Also request training_runtime residency; off by default.")
    parser.add_argument("--report-dir", default="runtime/smoke-reports")
    args = parser.parse_args()

    prefix = f"residency-smoke-{utc_stamp()}"
    jobs = smoke_jobs(prefix, visual_steps=max(args.visual_steps, 1))
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "dry_run": bool(args.dry_run),
        "submitted_jobs": [],
        "job_statuses": {},
        "snapshots": [],
        "validation_errors": [],
    }

    if args.dry_run:
        print(json.dumps({"jobs": jobs, "include_training": args.include_training}, indent=2, sort_keys=True))
        return 0

    report["snapshots"].append(snapshot(args.base_url, "before"))
    job_ids: list[str] = []
    for index, payload in enumerate(jobs, start=1):
        response = api_request(args.base_url, "POST", "/api/execution/direct", payload)
        report["submitted_jobs"].append({"request": payload, "response": response})
        job_id = str(response.get("job_id") or "").strip()
        if job_id:
            job_ids.append(job_id)
        report["snapshots"].append(snapshot(args.base_url, f"after-submit-{index}"))
        time.sleep(max(args.submit_interval, 0.0))

    if args.include_training:
        training_response = api_request(
            args.base_url,
            "POST",
            "/api/local-scheduler/request",
            {
                "component_id": "training_runtime",
                "importance": "high",
                "request_metadata": {"source": "model_residency_switch_smoke", "operator_only": True},
            },
        )
        report["training_request"] = training_response
        report["snapshots"].append(snapshot(args.base_url, "after-training-request"))

    wait_for_jobs(args.base_url, job_ids, args.timeout_seconds, args.poll_seconds, report)
    report["snapshots"].append(snapshot(args.base_url, "after-jobs"))
    for item in report["snapshots"]:
        report["validation_errors"].extend(validate_snapshot(item))
    report["validation_errors"].extend(validate_final_snapshot(report["snapshots"][-1]))
    for job_id, status in report["job_statuses"].items():
        if str(status.get("status") or "").lower() != "completed":
            report["validation_errors"].append(f"{job_id} finished with status={status.get('status')}")

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{prefix}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"report: {report_path}")
    if report["validation_errors"]:
        print(json.dumps({"validation_errors": report["validation_errors"]}, indent=2))
        return 1
    print("model residency smoke completed without validation errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
