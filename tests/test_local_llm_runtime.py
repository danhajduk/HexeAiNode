import asyncio
import json
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from ai_node.providers.adapters.local_adapter import LocalProviderAdapter
from ai_node.providers.models import UnifiedExecutionRequest


class _UnixHTTPServer(socketserver.UnixStreamServer):
    allow_reuse_address = True


class _LlamaCompatHandler(BaseHTTPRequestHandler):
    seen_paths = []
    seen_payloads = []

    def do_GET(self):  # noqa: N802
        self.__class__.seen_paths.append(self.path)
        if self.path == "/v1/models":
            self._json(
                200,
                {
                    "data": [
                        {
                            "id": "qwen3-14b-q4_k_m",
                            "created": 1760000000,
                        }
                    ]
                },
            )
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self):  # noqa: N802
        self.__class__.seen_paths.append(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        self.__class__.seen_payloads.append(payload)
        if self.path == "/v1/chat/completions":
            self._json(
                200,
                {
                    "id": "completion-test",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": f"local:{payload.get('model')}"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                },
            )
            return
        self._json(404, {"error": "not_found"})

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class LocalLlmRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_adapter_uses_v1_endpoints_over_unix_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = str(Path(tmp) / "llamacpp.sock")
            _LlamaCompatHandler.seen_paths = []
            _LlamaCompatHandler.seen_payloads = []
            server = _UnixHTTPServer(socket_path, _LlamaCompatHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                adapter = LocalProviderAdapter(
                    default_model_id="qwen3-14b-q4_k_m",
                    transport="socket",
                    socket_path=socket_path,
                    timeout_seconds=5,
                )
                health = await adapter.health_check()
                models = await adapter.list_models()
                response = await adapter.execute_prompt(
                    UnifiedExecutionRequest(
                        task_family="task.classification",
                        prompt="classify",
                        requested_model="qwen3-14b-q4_k_m",
                    )
                )
            finally:
                server.shutdown()
                server.server_close()
                await asyncio.sleep(0)

        self.assertEqual(health["availability"], "available")
        self.assertEqual(models[0].model_id, "qwen3-14b-q4_k_m")
        self.assertEqual(response.output_text, "local:qwen3-14b-q4_k_m")
        self.assertIn("/v1/models", _LlamaCompatHandler.seen_paths)
        self.assertIn("/v1/chat/completions", _LlamaCompatHandler.seen_paths)

    async def test_local_adapter_sends_structured_output_schema_as_response_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = str(Path(tmp) / "llamacpp.sock")
            _LlamaCompatHandler.seen_paths = []
            _LlamaCompatHandler.seen_payloads = []
            server = _UnixHTTPServer(socket_path, _LlamaCompatHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                adapter = LocalProviderAdapter(
                    default_model_id="llama-3.1-8b-instruct-q4_k_m",
                    transport="socket",
                    socket_path=socket_path,
                    timeout_seconds=5,
                )
                await adapter.execute_prompt(
                    UnifiedExecutionRequest(
                        task_family="task.classification",
                        prompt="Classify this email",
                        system_prompt="Return JSON only.",
                        requested_model="llama-3.1-8b-instruct-q4_k_m",
                        metadata={
                            "prompt_id": "mail.classifier",
                            "prompt_version": "v2.0",
                            "structured_output_schema": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "label": {"type": "string"},
                                    "confidence": {"type": "number"},
                                    "rationale": {"type": "string"},
                                },
                                "required": ["label", "confidence", "rationale"],
                            },
                        },
                    )
                )
            finally:
                server.shutdown()
                server.server_close()
                await asyncio.sleep(0)

        payload = _LlamaCompatHandler.seen_payloads[-1]
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(payload["response_format"]["json_schema"]["schema"]["required"], ["label", "confidence", "rationale"])
        self.assertNotIn("tools", payload)
        self.assertNotIn("functions", payload)
        self.assertIn("Do not return a tool call", payload["messages"][0]["content"])

    def test_model_downloader_dry_run_skips_missing_filename_without_full_repo_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "models.json"
            manifest = root / "manifest.json"
            config.write_text(
                json.dumps(
                    {
                        "models": [
                            {"id": "tiny", "repo": "example/tiny", "file": ""},
                            {"id": "qwen", "repo": "example/qwen", "file": "qwen.gguf"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/download-local-llm-models.py",
                    "--config",
                    str(config),
                    "--model-dir",
                    str(root / "models"),
                    "--manifest",
                    str(manifest),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["models"][0]["skipped_missing_file"])
        self.assertIsNone(payload["models"][0]["download_command"])
        self.assertEqual(payload["models"][1]["download_command"][1:4], ["download", "example/qwen", "qwen.gguf"])


if __name__ == "__main__":
    unittest.main()
