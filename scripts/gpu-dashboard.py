#!/usr/bin/env python3
"""Compact live GPU and ComfyUI terminal dashboard."""

from __future__ import annotations

import argparse
import http.client
import json
import shutil
import socket
import subprocess
import sys
import time
from collections import deque


GPU_FIELDS = (
    "name",
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "memory.total",
    "power.draw",
    "power.limit",
    "temperature.gpu",
    "clocks.sm",
    "clocks.mem",
)
SPARKS = "▁▂▃▄▅▆▇█"


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


def comfy_queue(socket_path: str) -> dict[str, int | str]:
    try:
        connection = UnixHTTPConnection(socket_path)
        connection.request("GET", "/queue")
        response = connection.getresponse()
        payload = json.loads(response.read())
        return {
            "state": "online" if response.status == 200 else f"HTTP {response.status}",
            "running": len(payload.get("queue_running") or []),
            "pending": len(payload.get("queue_pending") or []),
        }
    except (OSError, ValueError, json.JSONDecodeError, http.client.HTTPException):
        return {"state": "offline", "running": 0, "pending": 0}


def color(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def gauge(value: float, maximum: float, width: int, enabled: bool, warning: float = 0.75, danger: float = 0.9) -> str:
    ratio = min(max(value / maximum if maximum else 0.0, 0.0), 1.0)
    filled = round(width * ratio)
    code = "31" if ratio >= danger else "33" if ratio >= warning else "32"
    return color("█" * filled, code, enabled) + color("░" * (width - filled), "90", enabled)


def sparkline(values: deque[float]) -> str:
    return "".join(SPARKS[min(round(max(0.0, min(value, 100.0)) / 100 * (len(SPARKS) - 1)), len(SPARKS) - 1)] for value in values)


def render(sample: dict[str, float | str], queue: dict[str, int | str], history: deque[float], color_enabled: bool) -> str:
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
    queue_text = f"{queue['running']} running / {queue['pending']} pending"
    return "\n".join(
        [
            color("HEXE GPU + COMFYUI", "1;35", color_enabled) + f"  {time.strftime('%H:%M:%S')}  {workload}",
            f"GPU       {sample['name']}",
            "",
            f"Compute   {gauge(util, 100, gauge_width, color_enabled)} {util:5.1f}%",
            f"Memory IO {gauge(memory_activity, 100, gauge_width, color_enabled)} {memory_activity:5.1f}%",
            f"VRAM      {gauge(memory_used, memory_total, gauge_width, color_enabled, 0.8, 0.95)} {memory_used:,.0f} / {memory_total:,.0f} MiB",
            f"Power     {gauge(power, power_limit, gauge_width, color_enabled, 0.7, 0.9)} {power:5.1f} / {power_limit:.0f} W",
            f"Temp      {gauge(temperature, 90, gauge_width, color_enabled, 0.78, 0.9)} {temperature:5.1f} °C",
            "",
            f"Clocks    core {float(sample['clocks.sm']):.0f} MHz · memory {float(sample['clocks.mem']):.0f} MHz",
            f"History   {color(sparkline(history), '36', color_enabled)}  (GPU compute, oldest → newest)",
            f"ComfyUI   {queue['state']} · {queue_text}",
            "",
            color("Ctrl+C to close", "90", color_enabled),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds (default: 1).")
    parser.add_argument("--gpu-index", type=int, default=0, help="NVIDIA GPU index (default: 0).")
    parser.add_argument("--comfy-socket", default="/run/hexe/ai-node/comfyui-gpu.sock", help="ComfyUI Unix socket.")
    parser.add_argument("--history", type=int, default=40, help="Number of utilization samples to show.")
    parser.add_argument("--once", action="store_true", help="Print one sample and exit.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors.")
    args = parser.parse_args()
    if args.interval <= 0 or args.history <= 0:
        parser.error("--interval and --history must be greater than zero")
    color_enabled = sys.stdout.isatty() and not args.no_color
    history: deque[float] = deque([0.0] * args.history, maxlen=args.history)
    try:
        while True:
            sample = gpu_sample(args.gpu_index)
            history.append(float(sample["utilization.gpu"]))
            output = render(sample, comfy_queue(args.comfy_socket), history, color_enabled)
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
