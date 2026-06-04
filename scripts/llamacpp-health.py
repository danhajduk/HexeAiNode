#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import subprocess
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _uds_http_get(socket_path: str, path: str, *, timeout_s: float) -> tuple[int | None, dict | None, str | None]:
    request = f"GET {path} HTTP/1.1\r\nHost: llamacpp\r\nConnection: close\r\n\r\n".encode("utf-8")
    try:
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
    except OSError as exc:
        return None, None, str(exc)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status_code = None
    try:
        status_code = int(head.split(maxsplit=2)[1])
    except Exception:
        return None, None, "invalid_http_response"
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    return status_code, payload if isinstance(payload, dict) else {}, None


def _nvidia_smi_summary() -> dict:
    query = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    if result.returncode != 0:
        return {"available": False, "error": (result.stderr or result.stdout or "nvidia_smi_failed").strip()}
    rows = []
    for line in (result.stdout or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            continue
        rows.append(
            {
                "name": parts[0],
                "memory_used_mib": _int_or_none(parts[1]),
                "memory_total_mib": _int_or_none(parts[2]),
                "utilization_gpu_percent": _int_or_none(parts[3]),
                "temperature_c": _int_or_none(parts[4]),
                "power_draw_w": _float_or_none(parts[5]),
            }
        )
    return {"available": bool(rows), "gpus": rows}


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except Exception:
        return None


class LlamaCppHealthHandler(BaseHTTPRequestHandler):
    llama_socket_path = "/run/hexe/ai-node/llamacpp.sock"
    model_id = "qwen3-8b-q4_k_m"
    timeout_s = 2.0

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path != "/health":
            _json_response(self, 404, {"status": "not_found"})
            return
        started = time.perf_counter()
        health_code, health_payload, health_error = _uds_http_get(
            self.llama_socket_path,
            "/health",
            timeout_s=self.timeout_s,
        )
        models_code, models_payload, models_error = _uds_http_get(
            self.llama_socket_path,
            "/v1/models",
            timeout_s=self.timeout_s,
        )
        model_ids = []
        data = models_payload.get("data") if isinstance(models_payload, dict) else []
        if isinstance(data, list):
            model_ids = [
                str(item.get("id") or "").strip()
                for item in data
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            ]
        model_ready = self.model_id in model_ids if model_ids else models_code == 200
        ready = models_code == 200 and model_ready
        blockers = []
        if health_error:
            blockers.append(health_error or f"llamacpp_health_http_{health_code}")
        if models_code != 200:
            blockers.append(models_error or f"llamacpp_models_http_{models_code}")
        if model_ids and self.model_id not in model_ids:
            blockers.append("configured_model_not_listed")
        payload = {
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "service": "hexe-ai-node-llamacpp",
            "model_id": self.model_id,
            "model_ids": model_ids,
            "llamacpp_socket": self.llama_socket_path,
            "blockers": blockers,
            "gpu": _nvidia_smi_summary(),
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _json_response(self, 200 if ready else 503, payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class UnixHTTPServer(socketserver.UnixStreamServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve llama.cpp runtime health over a Unix socket.")
    parser.add_argument("--socket-path", default=os.environ.get("LLAMACPP_HEALTH_SOCKET", "/run/hexe/ai-node/llamacpp-health.sock"))
    parser.add_argument("--llama-socket-path", default=os.environ.get("LLAMACPP_SOCKET_PATH", "/run/hexe/ai-node/llamacpp.sock"))
    parser.add_argument("--model-id", default=os.environ.get("LLAMACPP_MODEL_ALIAS", "qwen3-8b-q4_k_m"))
    parser.add_argument("--timeout-s", type=float, default=float(os.environ.get("LLAMACPP_HEALTH_TIMEOUT_S", "2")))
    args = parser.parse_args()

    socket_path = Path(args.socket_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    LlamaCppHealthHandler.llama_socket_path = str(args.llama_socket_path)
    LlamaCppHealthHandler.model_id = str(args.model_id)
    LlamaCppHealthHandler.timeout_s = max(float(args.timeout_s), 0.2)

    with UnixHTTPServer(str(socket_path), LlamaCppHealthHandler) as server:
        os.chmod(socket_path, 0o660)
        print(f"Serving llama.cpp health on unix://{socket_path}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
