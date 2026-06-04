#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import threading
import time
from pathlib import Path


def _sample_gpu(stop: threading.Event, samples: list[dict], interval_s: float) -> None:
    query = "timestamp,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    while not stop.is_set():
        try:
            result = subprocess.run(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
            for line in (result.stdout or "").splitlines():
                parts = [part.strip() for part in line.split(",")]
                if len(parts) >= 6:
                    samples.append(
                        {
                            "timestamp": parts[0],
                            "memory_used_mib": _int(parts[1]),
                            "memory_total_mib": _int(parts[2]),
                            "utilization_gpu_percent": _int(parts[3]),
                            "temperature_c": _int(parts[4]),
                            "power_draw_w": _float(parts[5]),
                        }
                    )
        except Exception as exc:
            samples.append({"error": str(exc)})
        stop.wait(interval_s)


def _int(value: object) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _uds_post_json(socket_path: str, path: str, payload: dict, *, timeout_s: float) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    request = (
        f"POST {path} HTTP/1.1\r\n"
        "Host: llamacpp\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
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
    head, _, response_body = raw.partition(b"\r\n\r\n")
    status_code = int(head.split(maxsplit=2)[1])
    return status_code, json.loads(response_body.decode("utf-8")) if response_body else {}


def _worker(socket_path: str, model: str, iterations: int, max_tokens: int, results: list[dict], index: int) -> None:
    for iteration in range(iterations):
        started = time.perf_counter()
        try:
            status, payload = _uds_post_json(
                socket_path,
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": "Classify this as safe or unsafe and explain briefly: turn on local inference benchmarking."}],
                    "temperature": 0.0,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout_s=180.0,
            )
            results.append(
                {
                    "worker": index,
                    "iteration": iteration,
                    "status": "completed" if status < 400 else "failed",
                    "http_status": status,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "usage": payload.get("usage") if isinstance(payload, dict) else {},
                }
            )
        except Exception as exc:
            results.append({"worker": index, "iteration": iteration, "status": "failed", "error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded local LLM GPU load test.")
    parser.add_argument("--socket-path", default="/run/hexe/ai-node/llamacpp.sock")
    parser.add_argument("--model", default="qwen3-8b-q4_k_m")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--sample-interval-s", type=float, default=1.0)
    parser.add_argument("--max-temp-c", type=int, default=83)
    parser.add_argument("--output", default=".run/local_llm_gpu_load.json")
    args = parser.parse_args()

    samples: list[dict] = []
    results: list[dict] = []
    stop = threading.Event()
    sampler = threading.Thread(target=_sample_gpu, args=(stop, samples, args.sample_interval_s), daemon=True)
    sampler.start()
    workers = [
        threading.Thread(target=_worker, args=(args.socket_path, args.model, args.iterations, args.max_tokens, results, idx), daemon=True)
        for idx in range(max(args.concurrency, 1))
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    stop.set()
    sampler.join(timeout=2)

    max_temp = max((sample.get("temperature_c") or 0 for sample in samples if isinstance(sample, dict)), default=0)
    failed = [item for item in results if item.get("status") != "completed"]
    status = "completed" if not failed and max_temp <= args.max_temp_c else "failed"
    payload = {
        "schema_version": "1.0",
        "status": status,
        "model": args.model,
        "concurrency": max(args.concurrency, 1),
        "iterations": max(args.iterations, 1),
        "max_temperature_c": max_temp,
        "temperature_limit_c": args.max_temp_c,
        "results": results,
        "gpu_samples": samples,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
