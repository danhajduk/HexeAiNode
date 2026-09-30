#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


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


class FrontendHandler(BaseHTTPRequestHandler):
    dist_dir: Path
    backend_host: str
    backend_port: int
    trust_state_path: Path
    node_identity_path: Path

    server_version = "HexeFrontend/1.0"

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/ui-config.json":
            self._serve_ui_config(send_body=True)
            return
        if self._is_api_request():
            self._proxy_request()
            return
        self._serve_static(send_body=True)

    def do_HEAD(self) -> None:
        if urlsplit(self.path).path == "/ui-config.json":
            self._serve_ui_config(send_body=False)
            return
        if self._is_api_request():
            self._proxy_request()
            return
        self._serve_static(send_body=False)

    def do_POST(self) -> None:
        self._proxy_request()

    def do_PUT(self) -> None:
        self._proxy_request()

    def do_PATCH(self) -> None:
        self._proxy_request()

    def do_DELETE(self) -> None:
        self._proxy_request()

    def do_OPTIONS(self) -> None:
        if self._is_api_request():
            self._proxy_request()
            return
        self.send_response(204)
        self.send_header("Allow", "GET, HEAD, OPTIONS")
        self.end_headers()

    def _is_api_request(self) -> bool:
        path = urlsplit(self.path).path
        return path == "/api" or path.startswith("/api/")

    def _serve_static(self, *, send_body: bool) -> None:
        target = self._resolve_static_path()
        if target is None:
            self.send_error(404)
            return

        try:
            content = target.read_bytes() if send_body else b""
            content_length = target.stat().st_size
        except OSError:
            self.send_error(404)
            return

        content_type, _ = mimetypes.guess_type(str(target))
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(content_length))
        if "/assets/" in target.as_posix():
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if send_body:
            self.wfile.write(content)

    def _serve_ui_config(self, *, send_body: bool) -> None:
        try:
            payload = build_ui_config(
                trust_state_path=self.trust_state_path,
                node_identity_path=self.node_identity_path,
            )
        except (OSError, ValueError, json.JSONDecodeError):
            self.send_error(503, "UI proxy configuration unavailable")
            return
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if send_body:
            self.wfile.write(content)

    def _resolve_static_path(self) -> Path | None:
        raw_path = urlsplit(self.path).path
        normalized = posixpath.normpath(unquote(raw_path)).lstrip("/")
        if normalized == ".":
            normalized = ""

        candidate = (self.dist_dir / normalized).resolve()
        dist_root = self.dist_dir.resolve()
        if not self._is_relative_to(candidate, dist_root):
            return None
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if candidate.is_file():
            return candidate

        fallback = dist_root / "index.html"
        if fallback.is_file():
            return fallback
        return None

    def _proxy_request(self) -> None:
        body = self._read_body()
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }
        headers["Host"] = f"{self.backend_host}:{self.backend_port}"

        connection = http.client.HTTPConnection(self.backend_host, self.backend_port, timeout=30)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
        except OSError as exc:
            self.send_error(502, f"backend unavailable: {exc}")
            return
        finally:
            connection.close()

        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() not in HOP_BY_HOP_HEADERS:
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response_body)

    def _read_body(self) -> bytes | None:
        length = self.headers.get("Content-Length")
        if not length:
            return None
        try:
            body_length = int(length)
        except ValueError:
            return None
        if body_length <= 0:
            return None
        return self.rfile.read(body_length)

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False


def build_ui_config(*, trust_state_path: Path, node_identity_path: Path) -> dict:
    trust_state = json.loads(trust_state_path.read_text(encoding="utf-8"))
    identity = json.loads(node_identity_path.read_text(encoding="utf-8"))
    node_id = str(identity.get("node_id") or trust_state.get("node_id") or "").strip()
    core_api_endpoint = str(trust_state.get("core_api_endpoint") or "").strip().rstrip("/")
    parsed_core = urlsplit(core_api_endpoint)
    if not node_id or parsed_core.scheme not in {"http", "https"} or not parsed_core.netloc:
        raise ValueError("invalid UI proxy configuration")
    core_origin = f"{parsed_core.scheme}://{parsed_core.netloc}"
    return {
        "node_id": node_id,
        "proxy_ui_url": f"{core_origin}/nodes/proxy/ui/{quote(node_id, safe='')}/",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the built Hexe AI Node frontend.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--dist-dir", default="frontend/dist")
    parser.add_argument("--backend-host", default="127.0.0.1")
    parser.add_argument("--backend-port", type=int, default=9002)
    parser.add_argument("--trust-state-path", default=".run/trust_state.json")
    parser.add_argument("--node-identity-path", default=".run/node_identity.json")
    args = parser.parse_args()

    dist_dir = Path(args.dist_dir).resolve()
    if not (dist_dir / "index.html").is_file():
        raise SystemExit(f"missing frontend build at {dist_dir}; run `npm run build` in frontend first")

    FrontendHandler.dist_dir = dist_dir
    FrontendHandler.backend_host = args.backend_host
    FrontendHandler.backend_port = args.backend_port
    FrontendHandler.trust_state_path = Path(args.trust_state_path).resolve()
    FrontendHandler.node_identity_path = Path(args.node_identity_path).resolve()

    server = ThreadingHTTPServer((args.host, args.port), FrontendHandler)
    print(f"Serving {dist_dir} on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
