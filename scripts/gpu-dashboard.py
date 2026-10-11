#!/usr/bin/env python3
"""Compact live GPU and ComfyUI terminal dashboard."""

from __future__ import annotations

import argparse
from datetime import datetime
import http.client
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


GPU_FIELDS = (
    "name",
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "memory.total",
    "power.draw",
    "power.limit",
    "temperature.gpu",
)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 1.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def number(value: str) -> float:
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return 0.0


def gpu_sample(index: int) -> dict[str, float | str]:
    command = [
        "nvidia-smi",
        f"--id={index}",
        f"--query-gpu={','.join(GPU_FIELDS)}",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    values = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
    return {
        field: values[position] if field == "name" else number(values[position])
        for position, field in enumerate(GPU_FIELDS)
    }


def comfy_queue(socket_path: str) -> dict[str, object]:
    try:
        connection = UnixHTTPConnection(socket_path)
        connection.request("GET", "/queue")
        response = connection.getresponse()
        payload = json.loads(response.read())
        return parse_comfy_queue(payload, state="online" if response.status == 200 else f"HTTP {response.status}")
    except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
        return {"state": "offline", "running": 0, "pending": 0}


def parse_comfy_queue(payload: dict, *, state: str = "online") -> dict[str, object]:
    running = list(payload.get("queue_running") or [])
    pending = list(payload.get("queue_pending") or [])
    current = (running or pending or [None])[0]
    result: dict[str, object] = {
        "state": state,
        "running": len(running),
        "pending": len(pending),
        "job_state": "running" if running else "pending" if pending else "idle",
    }
    if not isinstance(current, list):
        return result
    workflow = current[2] if len(current) > 2 and isinstance(current[2], dict) else {}
    sampler = next((node.get("inputs", {}) for node in workflow.values() if node.get("class_type") == "KSampler"), {})
    checkpoint = next(
        (node.get("inputs", {}).get("ckpt_name") for node in workflow.values() if node.get("class_type") == "CheckpointLoaderSimple"),
        None,
    )
    output_prefix = next(
        (
            node.get("inputs", {}).get("filename_prefix")
            for node in workflow.values()
            if node.get("class_type") in {"SaveImage", "SaveImageWebsocket"}
        ),
        None,
    )
    result.update(
        {
            "queue_number": current[0] if current else None,
            "prompt_id": current[1] if len(current) > 1 else None,
            "seed": sampler.get("seed") or sampler.get("noise_seed"),
            "steps": sampler.get("steps"),
            "cfg": sampler.get("cfg"),
            "sampler": " / ".join(str(value) for value in (sampler.get("sampler_name"), sampler.get("scheduler")) if value),
            "checkpoint": checkpoint,
            "output_prefix": output_prefix,
        }
    )
    return result


def image_studio_backend(profile_root: str, queue: dict[str, object]) -> dict[str, object]:
    root = Path(profile_root)
    candidates: list[tuple[float, Path, dict]] = []
    try:
        profile_paths = root.glob("*/profile.json")
        for path in profile_paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            workspaces = payload.get("prompt_workspaces") if isinstance(payload.get("prompt_workspaces"), dict) else {}
            for section in ("head_face", "upper_torso"):
                workspace = workspaces.get(section) if isinstance(workspaces.get(section), dict) else {}
                dataset = workspace.get("lora_dataset") if isinstance(workspace.get("lora_dataset"), dict) else {}
                poses = [pose for pose in list(dataset.get("poses") or []) if isinstance(pose, dict)]
                active_pose_id = str(dataset.get("active_pose_id") or "").strip()
                pose = next((item for item in poses if str(item.get("pose_id") or "") == active_pose_id), None)
                if not dataset or not isinstance(pose, dict):
                    continue
                timestamp = _iso_epoch(
                    dataset.get("updated_at") or workspace.get("updated_at") or payload.get("updated_at")
                )
                candidates.append(
                    (timestamp, path, {"profile": payload, "section": section, "dataset": dataset, "pose": pose})
                )
    except (OSError, ValueError, json.JSONDecodeError):
        return {"available": False, "state": "unavailable"}
    if not candidates:
        return {"available": False, "state": "idle"}
    _, path, selected = max(candidates, key=lambda item: item[0])
    profile = selected["profile"]
    dataset = selected["dataset"]
    pose = selected["pose"]
    items = [item for item in list(pose.get("items") or []) if isinstance(item, dict)]
    statuses = [str(item.get("status") or "").strip() for item in items]
    local_count = sum(
        status in {"local_queued", "pending"} and not str(item.get("prompt_id") or "").strip()
        for status, item in zip(statuses, items)
    )
    submitted_items = [
        item
        for item in items
        if str(item.get("status") or "") in {"submitted", "queued", "running", "pending"}
        and str(item.get("prompt_id") or "").strip()
    ]
    completed_count = sum(
        status in {"completed", "completed_with_fallback"} and not bool(item.get("placeholder"))
        for status, item in zip(statuses, items)
    )
    approved_count = sum(bool(item.get("approved")) for item in items)
    active_prompt_ids = {str(queue.get("prompt_id") or "").strip()} if queue.get("prompt_id") else set()
    submitted_prompt_ids = {str(item.get("prompt_id") or "").strip() for item in submitted_items}
    if submitted_prompt_ids & active_prompt_ids:
        phase = "rendering"
    elif submitted_items:
        phase = "importing output"
    elif local_count:
        phase = "waiting for Generate" if str(dataset.get("status") or "") == "manual_review" else "local queue waiting"
    elif items and completed_count == len(items):
        phase = "candidate review ready"
    else:
        phase = str((dataset.get("dispatch") or {}).get("status") or dataset.get("status") or "idle").replace("_", " ")
    return {
        "available": True,
        "state": phase,
        "profile": str(profile.get("name") or profile.get("profile_id") or path.parent.name),
        "section": selected["section"],
        "pose": str(pose.get("label") or pose.get("pose_id") or "unknown"),
        "completed": completed_count,
        "total": len(items),
        "approved": approved_count,
        "local_queued": local_count,
        "submitted": len(submitted_items),
        "dispatch": str((dataset.get("dispatch") or {}).get("status") or "unknown").replace("_", " "),
        "updated_at": dataset.get("updated_at"),
    }


def comfy_session(path: str, queue: dict[str, object]) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        last_active_epoch = float(payload.get("last_active_epoch"))
        idle_timeout_seconds = max(float(payload.get("idle_timeout_seconds") or 0), 0.0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {"available": False}
    queue_active = int(queue.get("running") or 0) > 0 or int(queue.get("pending") or 0) > 0
    return {
        "available": True,
        "idle_seconds": 0.0 if queue_active else max(time.time() - last_active_epoch, 0.0),
        "idle_timeout_seconds": idle_timeout_seconds,
        "queue_active": queue_active,
    }


def _iso_epoch(value: object) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def color(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def duration(seconds: object) -> str:
    total = max(int(float(seconds or 0)), 0)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def gauge(value: float, maximum: float, width: int, enabled: bool, warning: float = 0.75, danger: float = 0.9) -> str:
    ratio = min(max(value / maximum if maximum else 0.0, 0.0), 1.0)
    filled = round(width * ratio)
    code = "31" if ratio >= danger else "33" if ratio >= warning else "32"
    return color("█" * filled, code, enabled) + color("░" * (width - filled), "90", enabled)


def render(
    sample: dict[str, float | str],
    queue: dict[str, object],
    backend: dict[str, object],
    session: dict[str, object],
    color_enabled: bool,
) -> str:
    terminal_width = shutil.get_terminal_size((100, 24)).columns
    gauge_width = max(18, min(42, terminal_width - 38))
    util = float(sample["utilization.gpu"])
    memory_activity = float(sample["utilization.memory"])
    memory_used = float(sample["memory.used"])
    memory_total = float(sample["memory.total"])
    power = float(sample["power.draw"])
    power_limit = float(sample["power.limit"])
    temperature = float(sample["temperature.gpu"])
    if util >= 60:
        workload = color("RENDERING", "1;32", color_enabled)
    elif util > 0:
        workload = color("ACTIVE", "1;33", color_enabled)
    elif memory_used > 1024:
        workload = color("WARM / MODELS LOADED", "1;36", color_enabled)
    else:
        workload = color("IDLE", "90", color_enabled)
    idle_label = ""
    if session.get("available") and not session.get("queue_active"):
        idle_label = (
            f" · IDLE {duration(session.get('idle_seconds'))}"
            f" / {duration(session.get('idle_timeout_seconds'))}"
        )
    queue_text = f"{queue['running']} running / {queue['pending']} pending"
    lines = [
            color("HEXE GPU + COMFYUI", "1;35", color_enabled)
            + f"  {time.strftime('%H:%M:%S')}  {workload}{idle_label}",
            f"Compute   {gauge(util, 100, gauge_width, color_enabled)} {util:5.1f}%",
            f"Memory IO {gauge(memory_activity, 100, gauge_width, color_enabled)} {memory_activity:5.1f}%",
            f"VRAM      {gauge(memory_used, memory_total, gauge_width, color_enabled, 0.8, 0.95)} {memory_used:,.0f} / {memory_total:,.0f} MiB",
            f"Power     {gauge(power, power_limit, gauge_width, color_enabled, 0.7, 0.9)} {power:5.1f} / {power_limit:.0f} W",
            f"Temp      {gauge(temperature, 90, gauge_width, color_enabled, 0.78, 0.9)} {temperature:5.1f} °C",
            f"ComfyUI   {queue['state']} · {queue_text}",
    ]
    lines.extend(["", color("IMAGE STUDIO BACKEND", "1;35", color_enabled)])
    if backend.get("available"):
        section = "Face LoRA" if backend.get("section") == "head_face" else "Body LoRA"
        lines.extend(
            [
                f"Phase     {backend.get('state')}",
                f"Context   {backend.get('profile')} · {section} · {backend.get('pose')}",
                f"Candidates {backend.get('completed')}/{backend.get('total')} imported · {backend.get('approved')} approved",
                f"Local     {backend.get('local_queued')} waiting · {backend.get('submitted')} submitted · dispatcher {backend.get('dispatch')}",
                f"Updated   {backend.get('updated_at') or 'unknown'}",
            ]
        )
    else:
        lines.append(f"State     {backend.get('state', 'unavailable')} · no active LoRA pose found")
    if queue.get("job_state") in {"running", "pending"}:
        lines.extend(
            [
                "",
                color("CURRENT COMFYUI JOB", "1;35", color_enabled),
                f"State     {queue.get('job_state')} · queue #{queue.get('queue_number', 'unknown')}",
                f"Sampling  {queue.get('steps') or '?'} steps · CFG {queue.get('cfg') or '?'} · {queue.get('sampler') or 'unknown'}",
                f"Seed      {queue.get('seed') if queue.get('seed') is not None else 'unknown'}",
            ]
        )
    lines.extend(["", color("Ctrl+C to close", "90", color_enabled)])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds (default: 1).")
    parser.add_argument("--gpu-index", type=int, default=0, help="NVIDIA GPU index (default: 0).")
    parser.add_argument("--comfy-socket", default="/run/hexe/ai-node/comfyui-gpu.sock", help="ComfyUI Unix socket.")
    parser.add_argument(
        "--session-file",
        default=".run/comfyui-webui-session.json",
        help="Persisted Image Studio ComfyUI session state.",
    )
    parser.add_argument(
        "--profile-root",
        default="runtime/manual/comfyui-gpu/input/avatar_profiles",
        help="Image Studio avatar profile root.",
    )
    parser.add_argument("--once", action="store_true", help="Print one sample and exit.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    color_enabled = sys.stdout.isatty() and not args.no_color
    try:
        while True:
            sample = gpu_sample(args.gpu_index)
            queue = comfy_queue(args.comfy_socket)
            backend = image_studio_backend(args.profile_root, queue)
            session = comfy_session(args.session_file, queue)
            output = render(sample, queue, backend, session, color_enabled)
            if not args.once and sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            print(output, flush=True)
            if args.once:
                return 0
            time.sleep(args.interval)
    except FileNotFoundError:
        print("nvidia-smi was not found", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print((exc.stderr or "nvidia-smi failed").strip(), file=sys.stderr)
        return exc.returncode or 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
