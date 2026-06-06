#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
import socketserver
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _http_json_get(host: str, port: int, path: str, *, timeout_s: float) -> tuple[int | None, dict | None, str | None]:
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
        conn.request("GET", path, headers={"Host": "comfyui"})
        response = conn.getresponse()
        raw = response.read()
    except Exception as exc:
        return None, None, str(exc)
    finally:
        try:
            conn.close()  # type: ignore[name-defined]
        except Exception:
            pass
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        payload = {}
    return response.status, payload if isinstance(payload, dict) else {}, None


class ComfyUISocketProxyHandler(BaseHTTPRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 8188
    runtime_id = "comfyui_gpu"
    runtime_label = "GPU ComfyUI"
    target_checkpoint = ""
    target_lora = ""
    mode = "api"
    timeout_s = 10.0

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/health":
            self._handle_health()
            return
        if self.mode == "health":
            _json_response(self, 404, {"status": "not_found"})
            return
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy_or_reject_health_mode()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy_or_reject_health_mode()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy_or_reject_health_mode()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy_or_reject_health_mode()

    def _proxy_or_reject_health_mode(self) -> None:
        if self.mode == "health":
            _json_response(self, 404, {"status": "not_found"})
            return
        self._proxy()

    def _handle_health(self) -> None:
        started = time.perf_counter()
        status_code, stats_payload, error = _http_json_get(
            self.upstream_host,
            self.upstream_port,
            "/system_stats",
            timeout_s=min(self.timeout_s, 3.0),
        )
        ready = status_code == 200 and error is None
        blockers = []
        if not ready:
            blockers.append(error or f"comfyui_system_stats_http_{status_code}")
        payload = {
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "service": self.runtime_label,
            "runtime_id": self.runtime_id,
            "upstream": f"http://{self.upstream_host}:{self.upstream_port}",
            "api_transport": "unix_socket",
            "target_checkpoint": self.target_checkpoint or None,
            "target_lora": self.target_lora or None,
            "model_residency": "on_demand",
            "system_stats": stats_payload if isinstance(stats_payload, dict) else {},
            "blockers": blockers,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _json_response(self, 200 if ready else 503, payload)

    def _proxy(self) -> None:
        content_length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(content_length) if content_length > 0 else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }
        headers["Host"] = "comfyui"
        try:
            conn = http.client.HTTPConnection(self.upstream_host, self.upstream_port, timeout=self.timeout_s)
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            response_body = response.read()
        except Exception as exc:
            _json_response(
                self,
                502,
                {
                    "status": "upstream_error",
                    "runtime_id": self.runtime_id,
                    "error": str(exc),
                },
            )
            return
        finally:
            try:
                conn.close()  # type: ignore[name-defined]
            except Exception:
                pass
        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class ThreadedUnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose a ComfyUI HTTP runtime through a Unix socket.")
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--runtime-id", required=True)
    parser.add_argument("--runtime-label", required=True)
    parser.add_argument("--target-checkpoint", default="")
    parser.add_argument("--target-lora", default="")
    parser.add_argument("--mode", choices=["api", "health"], default="api")
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--socket-uid", type=int, default=int(os.environ.get("COMFYUI_SOCKET_UID", "1000")))
    parser.add_argument("--socket-gid", type=int, default=int(os.environ.get("COMFYUI_SOCKET_GID", "1000")))
    args = parser.parse_args()

    socket_path = Path(args.socket_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    ComfyUISocketProxyHandler.upstream_host = str(args.upstream_host)
    ComfyUISocketProxyHandler.upstream_port = int(args.upstream_port)
    ComfyUISocketProxyHandler.runtime_id = str(args.runtime_id)
    ComfyUISocketProxyHandler.runtime_label = str(args.runtime_label)
    ComfyUISocketProxyHandler.target_checkpoint = str(args.target_checkpoint)
    ComfyUISocketProxyHandler.target_lora = str(args.target_lora)
    ComfyUISocketProxyHandler.mode = str(args.mode)
    ComfyUISocketProxyHandler.timeout_s = max(float(args.timeout_s), 0.5)

    with ThreadedUnixHTTPServer(str(socket_path), ComfyUISocketProxyHandler) as server:
        os.chmod(socket_path, 0o660)
        try:
            os.chown(socket_path, args.socket_uid, args.socket_gid)
        except PermissionError:
            pass
        print(f"Serving {args.runtime_id} {args.mode} on unix://{socket_path}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
