#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from statistics import mean


DEFAULT_HEALTH_SOCKET = "/run/hexe/ai-node/llamacpp-health.sock"
DEFAULT_LLAMA_SOCKET = "/run/hexe/ai-node/llamacpp.sock"


def _uds_json_get(socket_path: str, path: str, *, timeout_s: float) -> dict:
    request = f"GET {path} HTTP/1.1\r\nHost: health\r\nConnection: close\r\n\r\n".encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout_s)
        client.connect(socket_path)
        client.sendall(request)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    _head, _separator, body = raw.partition(b"\r\n\r\n")
    payload = json.loads(body.decode("utf-8")) if body else {}
    if not isinstance(payload, dict):
        raise ValueError("health response was not a JSON object")
    return payload


def _uds_json_post(socket_path: str, path: str, payload: dict, *, timeout_s: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = (
        f"POST {path} HTTP/1.1\r\n"
        "Host: llamacpp\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8") + body
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout_s)
        client.connect(socket_path)
        client.sendall(request)
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _separator, response_body = raw.partition(b"\r\n\r\n")
    status_code = 0
    try:
        status_code = int(head.split(maxsplit=2)[1])
    except Exception as exc:
        raise ValueError("invalid model latency HTTP response") from exc
    response = json.loads(response_body.decode("utf-8")) if response_body else {}
    if status_code >= 400:
        raise RuntimeError(f"model latency request failed with HTTP {status_code}: {response}")
    if not isinstance(response, dict):
        raise ValueError("model latency response was not a JSON object")
    return response


def _model_latency_sample(
    *,
    llama_socket: str,
    model_id: str,
    prompt: str,
    max_tokens: int,
    timeout_s: float,
) -> dict:
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    started = time.perf_counter()
    response = _uds_json_post(llama_socket, "/v1/chat/completions", payload, timeout_s=timeout_s)
    latency_ms = (time.perf_counter() - started) * 1000.0
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    return {
        "model_latency_ms": round(latency_ms, 3),
        "model_prompt_tokens": usage.get("prompt_tokens"),
        "model_completion_tokens": usage.get("completion_tokens"),
        "model_total_tokens": usage.get("total_tokens"),
    }


def _gpu_sample(*, gpu_index: int | None, timeout_s: float) -> dict:
    query = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    command = ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"]
    if gpu_index is not None:
        command.extend(["-i", str(gpu_index)])
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "nvidia-smi failed").strip()
        raise RuntimeError(message)
    first_line = (result.stdout or "").splitlines()[0]
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) < 6:
        raise ValueError(f"unexpected nvidia-smi output: {first_line}")
    return {
        "name": parts[0],
        "vram_used_mib": float(parts[1]),
        "vram_total_mib": float(parts[2]),
        "gpu_utilization_percent": float(parts[3]),
        "temperature_c": float(parts[4]),
        "power_draw_w": float(parts[5]),
    }


def _stats(values: list[float]) -> dict:
    return {
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "avg": round(mean(values), 3),
    }


def _collect_samples(
    *,
    duration_s: float,
    interval_s: float,
    health_socket: str,
    llama_socket: str,
    gpu_index: int | None,
    timeout_s: float,
    include_model_latency: bool,
    model_latency_prompt: str,
    model_latency_max_tokens: int,
    on_sample=None,
) -> list[dict]:
    samples: list[dict] = []
    started = time.time()
    next_at = started
    while True:
        now = time.time()
        if now < next_at:
            time.sleep(next_at - now)
        sampled_at = time.time()
        health = _uds_json_get(health_socket, "/health", timeout_s=timeout_s)
        gpu = _gpu_sample(gpu_index=gpu_index, timeout_s=timeout_s)
        model_id = str(health.get("model_id") or "").strip()
        model_latency = {}
        if include_model_latency:
            if not model_id:
                raise ValueError("health response did not include model_id")
            model_latency = _model_latency_sample(
                llama_socket=llama_socket,
                model_id=model_id,
                prompt=model_latency_prompt,
                max_tokens=model_latency_max_tokens,
                timeout_s=timeout_s,
            )
        sample = {
            "sampled_at_epoch": sampled_at,
            "sampled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sampled_at)),
            "current_local_llm_loaded": model_id or None,
            "ready": bool(health.get("ready")),
            "health_latency_ms": float(health.get("latency_ms") or 0),
            **gpu,
            **model_latency,
        }
        samples.append(sample)
        if on_sample is not None:
            on_sample(sample, len(samples))
        if sampled_at - started >= duration_s:
            return samples
        next_at += interval_s


def _summary(samples: list[dict]) -> dict:
    if not samples:
        raise ValueError("no samples collected")
    latest = samples[-1]
    result = {
        "duration_seconds": round(samples[-1]["sampled_at_epoch"] - samples[0]["sampled_at_epoch"], 3),
        "sample_count": len(samples),
        "gpu": latest["name"],
        "current_local_llm_loaded": latest.get("current_local_llm_loaded"),
        "ready_all_samples": all(bool(sample.get("ready")) for sample in samples),
        "vram_used_mib": _stats([sample["vram_used_mib"] for sample in samples]),
        "vram_total_mib": _stats([sample["vram_total_mib"] for sample in samples]),
        "gpu_utilization_percent": _stats([sample["gpu_utilization_percent"] for sample in samples]),
        "temperature_c": _stats([sample["temperature_c"] for sample in samples]),
        "power_draw_w": _stats([sample["power_draw_w"] for sample in samples]),
        "health_latency_ms": _stats([sample["health_latency_ms"] for sample in samples]),
        "latest": {
            "sampled_at": latest["sampled_at"],
            "vram_used_mib": latest["vram_used_mib"],
            "vram_total_mib": latest["vram_total_mib"],
            "gpu_utilization_percent": latest["gpu_utilization_percent"],
            "temperature_c": latest["temperature_c"],
            "power_draw_w": latest["power_draw_w"],
            "health_latency_ms": latest["health_latency_ms"],
        },
    }
    model_latencies = [sample["model_latency_ms"] for sample in samples if "model_latency_ms" in sample]
    if model_latencies:
        result["model_latency_ms"] = _stats(model_latencies)
        result["latest"]["model_latency_ms"] = latest.get("model_latency_ms")
        result["model_tokens"] = {
            "prompt_tokens_last": latest.get("model_prompt_tokens"),
            "completion_tokens_last": latest.get("model_completion_tokens"),
            "total_tokens_last": latest.get("model_total_tokens"),
        }
    return result


def _format_metric(label: str, unit: str, values: dict, latest: float) -> str:
    return (
        f"{label:<18} "
        f"min={values['min']:>8g} {unit:<4} "
        f"max={values['max']:>8g} {unit:<4} "
        f"avg={values['avg']:>8g} {unit:<4} "
        f"latest={latest:>8g} {unit}"
    )


def _print_first_sample(sample: dict) -> None:
    print(f"GPU: {sample['name']}")
    print(f"Current local LLM loaded: {sample.get('current_local_llm_loaded')}")
    print("First sample:")
    print(f"  VRAM used: {sample['vram_used_mib']:g} MiB")
    print(f"  VRAM total: {sample['vram_total_mib']:g} MiB")
    print(f"  GPU utilization: {sample['gpu_utilization_percent']:g}%")
    print(f"  Temperature: {sample['temperature_c']:g} C")
    print(f"  Power draw: {sample['power_draw_w']:g} W")
    print(f"  Health latency: {sample['health_latency_ms']:g} ms")
    if "model_latency_ms" in sample:
        print(f"  Model latency: {sample['model_latency_ms']:g} ms")
    print()
    print("Sampling", end="", flush=True)


def _progress_printer(sample: dict, sample_count: int) -> None:
    if sample_count == 1:
        _print_first_sample(sample)
        return
    print(".", end="", flush=True)


def _print_human(summary: dict) -> None:
    latest = summary["latest"]
    print(f"GPU: {summary['gpu']}")
    print(f"Current local LLM loaded: {summary['current_local_llm_loaded']}")
    print(f"Duration: {summary['duration_seconds']}s")
    print(f"Samples: {summary['sample_count']}")
    print(f"Ready all samples: {summary['ready_all_samples']}")
    print()
    print(_format_metric("VRAM used", "MiB", summary["vram_used_mib"], latest["vram_used_mib"]))
    print(_format_metric("VRAM total", "MiB", summary["vram_total_mib"], latest["vram_total_mib"]))
    print(
        _format_metric(
            "GPU utilization",
            "%",
            summary["gpu_utilization_percent"],
            latest["gpu_utilization_percent"],
        )
    )
    print(_format_metric("Temperature", "C", summary["temperature_c"], latest["temperature_c"]))
    print(_format_metric("Power draw", "W", summary["power_draw_w"], latest["power_draw_w"]))
    print(_format_metric("Health latency", "ms", summary["health_latency_ms"], latest["health_latency_ms"]))
    if "model_latency_ms" in summary:
        print(_format_metric("Model latency", "ms", summary["model_latency_ms"], latest["model_latency_ms"]))
        tokens = summary.get("model_tokens") if isinstance(summary.get("model_tokens"), dict) else {}
        print(
            "Model tokens last "
            f"prompt={tokens.get('prompt_tokens_last')} "
            f"completion={tokens.get('completion_tokens_last')} "
            f"total={tokens.get('total_tokens_last')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor local LLM GPU and llama.cpp health metrics.")
    parser.add_argument("--duration-s", type=float, default=300.0, help="Monitoring duration in seconds. Default: 300.")
    parser.add_argument("--interval-s", type=float, default=5.0, help="Sampling interval in seconds. Default: 5.")
    parser.add_argument("--health-socket", default=DEFAULT_HEALTH_SOCKET, help=f"llama.cpp health socket. Default: {DEFAULT_HEALTH_SOCKET}.")
    parser.add_argument("--llama-socket", default=DEFAULT_LLAMA_SOCKET, help=f"llama.cpp inference socket. Default: {DEFAULT_LLAMA_SOCKET}.")
    parser.add_argument("--gpu-index", type=int, default=None, help="Optional nvidia-smi GPU index.")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="Per-sample command/socket timeout. Default: 5.")
    parser.add_argument("--include-model-latency", action="store_true", help="Run a tiny inference request each sample and report model latency.")
    parser.add_argument("--model-latency-prompt", default="Reply with exactly: ok", help="Prompt used by --include-model-latency.")
    parser.add_argument("--model-latency-max-tokens", type=int, default=8, help="Max tokens for --include-model-latency. Default: 8.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    args = parser.parse_args()

    if args.duration_s < 0:
        parser.error("--duration-s must be >= 0")
    if args.interval_s <= 0:
        parser.error("--interval-s must be > 0")
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be > 0")
    if args.model_latency_max_tokens <= 0:
        parser.error("--model-latency-max-tokens must be > 0")

    try:
        on_sample = None if args.json else _progress_printer
        samples = _collect_samples(
            duration_s=args.duration_s,
            interval_s=args.interval_s,
            health_socket=args.health_socket,
            llama_socket=args.llama_socket,
            gpu_index=args.gpu_index,
            timeout_s=args.timeout_s,
            include_model_latency=args.include_model_latency,
            model_latency_prompt=args.model_latency_prompt,
            model_latency_max_tokens=args.model_latency_max_tokens,
            on_sample=on_sample,
        )
        result = _summary(samples)
    except Exception as exc:
        if not args.json:
            print()
        print(f"monitor failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("\n")
        _print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
