import logging
import json
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch

from ai_node.runtime.service_manager import UserSystemdServiceManager


class _Completed:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.stderr = ""


class _UnixHTTPServer(socketserver.UnixStreamServer):
    allow_reuse_address = True


class _BridgeProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"bridge-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class ServiceManagerTests(unittest.TestCase):
    def _write_local_model_config(self, tmp: str) -> Path:
        config_path = Path(tmp) / "models.json"
        config_path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "id": "qwen3-8b-q4_k_m",
                            "repo": "Qwen/Qwen3-8B-GGUF",
                            "quantization": "Q4_K_M",
                            "ctx_size": 4096,
                        },
                        {
                            "id": "gemma-3-12b-it-q4_k_m",
                            "repo": "bartowski/google_gemma-3-12b-it-GGUF",
                            "quantization": "Q4_K_M",
                            "ctx_size": 4096,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def test_get_status_maps_systemctl_states(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        calls = {"count": 0}

        def _fake_run(cmd, check, capture_output, text, env=None):
            if cmd[:2] == ["docker", "inspect"]:
                return _Completed("0\n")
            if cmd[:3] == ["systemctl", "--user", "show"]:
                return _Completed("MainPID=0\n")
            self.assertEqual(cmd[:3], ["systemctl", "--user", "is-active"])
            calls["count"] += 1
            return _Completed("active\n" if calls["count"] == 1 else "failed\n")

        with patch("subprocess.run", side_effect=_fake_run):
            payload = manager.get_status()
        self.assertEqual(payload["backend"]["state"], "running")
        self.assertEqual(payload["frontend"]["state"], "failed")
        self.assertEqual(payload["local_llm"]["service_id"], "local_llm")
        self.assertEqual(payload["comfyui_gpu"]["service_id"], "comfyui_gpu")
        self.assertEqual(payload["comfyui_cpu"]["service_id"], "comfyui_cpu")
        self.assertEqual(payload["comfyui_webui"]["service_id"], "comfyui_webui")
        self.assertEqual(payload["node"], "degraded")

    def test_restart_node_restarts_both_units(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
        invoked = []

        def _fake_popen(cmd, **_kwargs):
            invoked.append(cmd)

        with patch("subprocess.Popen", side_effect=_fake_popen):
            result = manager.restart(target="node")
        self.assertEqual(result["target"], "node")
        restart_calls = [cmd for cmd in invoked if cmd[2] == "restart"]
        self.assertEqual(len(restart_calls), 2)

    def test_get_status_treats_activating_as_running(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        def _fake_run(cmd, check, capture_output, text, env=None):
            if cmd[:2] == ["docker", "inspect"]:
                return _Completed("0\n")
            if cmd[:3] == ["systemctl", "--user", "show"]:
                return _Completed("MainPID=0\n")
            self.assertEqual(cmd[:3], ["systemctl", "--user", "is-active"])
            return _Completed("activating\n")

        with patch("subprocess.run", side_effect=_fake_run):
            payload = manager.get_status()
        self.assertEqual(payload["backend"]["state"], "running")
        self.assertEqual(payload["frontend"]["state"], "running")
        self.assertEqual(payload["node"], "running")

    def test_schedule_restart_launches_detached_restart_command(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        with patch("subprocess.Popen") as fake_popen:
            result = manager.schedule_restart(target="backend", delay_seconds=10)

        self.assertEqual(result["target"], "backend")
        self.assertEqual(result["result"], "scheduled")
        self.assertEqual(result["delay_seconds"], 10)
        command = fake_popen.call_args.args[0]
        self.assertEqual(command[:2], ["bash", "-lc"])
        self.assertIn("sleep 10;", command[2])
        self.assertIn("systemctl --user restart hexe-ai-node-backend.service", command[2])

    def test_local_llm_status_reports_container_pid_cpu_and_memory(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        def _fake_run(cmd, check, capture_output, text, env=None):
            self.assertEqual(cmd[:3], ["docker", "inspect", "--format"])
            self.assertEqual(cmd[-1], "hexe-ai-node-llamacpp")
            return _Completed("4242\n")

        with (
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", side_effect=_fake_run),
            patch.object(manager, "_read_cpu_total", side_effect=[1000.0, 1100.0]),
            patch.object(manager, "_read_process_cpu", side_effect=[50.0, 75.0]),
            patch.object(manager, "_read_mem_total", return_value=1000.0),
            patch.object(manager, "_read_process_rss", return_value=125.0),
        ):
            first_payload = manager._local_llm_status()
            second_payload = manager._local_llm_status()

        self.assertEqual(first_payload["state"], "running")
        self.assertEqual(first_payload["pid"], 4242)
        self.assertIsNone(first_payload["cpu_percent"])
        self.assertEqual(first_payload["mem_percent"], 12.5)
        self.assertEqual(first_payload["container_name"], "hexe-ai-node-llamacpp")
        self.assertEqual(first_payload["default_model_id"], "qwen3-8b-q4_k_m")
        self.assertIn("default_revert", first_payload)
        self.assertEqual(first_payload["default_revert"]["default_model_id"], "qwen3-8b-q4_k_m")
        self.assertIn("always_on", first_payload)
        self.assertTrue(first_payload["always_on"]["enabled"])
        self.assertEqual(first_payload["always_on"]["reason"], "default_model_ready")
        self.assertIn("model_states", first_payload)
        self.assertEqual(second_payload["cpu_percent"], 25.0)

    def test_comfyui_status_reports_socket_runtime_contract(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        def _fake_exists(path):
            value = str(path)
            return value in {
                "scripts/comfyui-control.sh",
                manager._comfyui_gpu_socket,
                manager._comfyui_gpu_health_socket,
                manager._comfyui_cpu_socket,
                manager._comfyui_cpu_health_socket,
            }

        def _fake_run(cmd, check, capture_output, text, env=None):
            self.assertEqual(cmd[:3], ["docker", "inspect", "--format"])
            self.assertEqual(cmd[-1], "hexe-ai-node-comfyui")
            return _Completed("5151\n")

        with patch("os.path.exists", side_effect=_fake_exists), patch("subprocess.run", side_effect=_fake_run):
            gpu_payload = manager._comfyui_runtime_status(runtime="gpu")
            cpu_payload = manager._comfyui_runtime_status(runtime="cpu")

        self.assertEqual(gpu_payload["state"], "running")
        self.assertEqual(gpu_payload["pid"], 5151)
        self.assertEqual(gpu_payload["api_transport"], "unix_socket")
        self.assertTrue(gpu_payload["socket_ready"])
        self.assertTrue(gpu_payload["health_socket_ready"])
        self.assertEqual(cpu_payload["state"], "running")
        self.assertEqual(cpu_payload["socket_path"], manager._comfyui_cpu_socket)

    def test_comfyui_webui_status_reports_local_bridge_contract(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_WEBUI_HOST": "127.0.0.1",
                "HEXE_COMFYUI_WEBUI_PORT": "18188",
                "HEXE_COMFYUI_WEBUI_PID_FILE": str(Path(tmp) / "bridge.pid"),
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        payload = manager._comfyui_webui_status()

        self.assertEqual(payload["service_id"], "comfyui_webui")
        self.assertEqual(payload["state"], "stopped")
        self.assertEqual(payload["runtime"], "gpu")
        self.assertEqual(payload["host"], "127.0.0.1")
        self.assertEqual(payload["port"], 18188)
        self.assertEqual(payload["url"], "http://localhost:18188")
        self.assertEqual(payload["api_transport"], "tcp_bridge_to_unix_socket")
        self.assertEqual(payload["socket_path"], manager._comfyui_gpu_socket)

    def test_comfyui_webui_defaults_to_node_reachable_bridge_host(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_WEBUI_HOST": "",
                "HEXE_COMFYUI_WEBUI_PORT": "18188",
                "HEXE_COMFYUI_WEBUI_PID_FILE": str(Path(tmp) / "bridge.pid"),
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        payload = manager._comfyui_webui_status()

        self.assertEqual(payload["host"], "0.0.0.0")
        self.assertEqual(payload["url"], "http://0.0.0.0:18188")

    def test_manual_comfyui_webui_session_blocks_vision_residency(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json")},
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="active", reason="test")
            session_file = manager._comfyui_webui_session_file
            with (
                patch.object(manager, "_comfyui_gpu_model_loaded", return_value=False),
                patch.object(manager, "_active_model_ids_for_socket", return_value=[]),
                patch.object(manager, "_query_container_pid", return_value=0),
                patch("os.path.exists", side_effect=lambda path: str(path) == session_file),
                patch.object(manager, "_run_vision_llm_control") as fake_run,
            ):
                status = manager.vision_runtime_status()
                result = manager.ensure_vision_runtime_resident()

        self.assertFalse(status["start_due"])
        self.assertTrue(status["manual_comfyui_webui_active"])
        self.assertEqual(status["reason"], "blocked_by_manual_comfyui_webui")
        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "blocked_by_manual_comfyui_webui")
        fake_run.assert_not_called()

    def test_comfyui_webui_idle_close_closes_after_timeout(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json"),
                "HEXE_COMFYUI_WEBUI_IDLE_TIMEOUT_SECONDS": "300",
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="idle", reason="test", last_active_epoch=100.0)
            calls = []

            def _stop_webui():
                calls.append("stop_comfyui")
                return {"target": "comfyui_webui", "result": "stopped"}

            def _restore_vision(**_kwargs):
                calls.append("restore_vision")
                return {"started": True, "reason": "vision_container_stopped"}

            with (
                patch("time.time", return_value=401.0),
                patch.object(manager, "_uds_json_get", return_value={"queue_running": [], "queue_pending": []}),
                patch.object(manager, "stop_comfyui_webui", side_effect=_stop_webui) as fake_stop,
                patch.object(manager, "ensure_vision_runtime_resident", side_effect=_restore_vision) as fake_restore,
            ):
                result = manager.close_comfyui_webui_if_idle()

        self.assertTrue(result["closed"])
        self.assertEqual(result["reason"], "idle_timeout_reached")
        self.assertTrue(result["vision_restore"]["started"])
        self.assertEqual(calls, ["stop_comfyui", "restore_vision"])
        fake_stop.assert_called_once()
        fake_restore.assert_called_once_with(local_in_flight=0, gpu_comfyui_critical_in_flight=False)

    def test_comfyui_webui_idle_close_resets_when_queue_active(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json")},
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="idle", reason="test", last_active_epoch=100.0)
            with (
                patch("time.time", return_value=500.0),
                patch.object(manager, "_uds_json_get", return_value={"queue_running": [{"prompt_id": "p1"}], "queue_pending": []}),
                patch.object(manager, "stop_comfyui_webui") as fake_stop,
            ):
                result = manager.close_comfyui_webui_if_idle()
                session = manager.comfyui_webui_session_status()

        self.assertFalse(result["closed"])
        self.assertEqual(result["reason"], "queue_active")
        self.assertTrue(session["queue_active"])
        self.assertEqual(session["last_active_epoch"], 500.0)
        fake_stop.assert_not_called()

    def test_comfyui_webui_idle_status_reports_countdown(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json"),
                "HEXE_COMFYUI_WEBUI_IDLE_TIMEOUT_SECONDS": "300",
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="idle", reason="test", last_active_epoch=100.0)
            with (
                patch("time.time", return_value=175.0),
                patch.object(manager, "_uds_json_get", return_value={"queue_running": [], "queue_pending": []}),
            ):
                session = manager.comfyui_webui_session_status()

        self.assertTrue(session["manual_session_active"])
        self.assertFalse(session["queue_active"])
        self.assertEqual(session["idle_seconds"], 75.0)
        self.assertEqual(session["auto_close_at_epoch"], 400.0)

    def test_comfyui_webui_generation_status_reports_queue_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json")},
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="active", reason="test", last_active_epoch=100.0)

            def _fake_uds_get(_socket_path, path):
                if path == "/queue":
                    return {
                        "queue_running": [[0, "prompt-running"]],
                        "queue_pending": [{"prompt_id": "prompt-pending"}],
                    }
                if path == "/progress":
                    return {"value": 3, "max": 12, "prompt_id": "prompt-running", "node": "sampler"}
                return None

            with patch.object(manager, "_uds_json_get", side_effect=_fake_uds_get):
                status = manager.comfyui_webui_generation_status()

        self.assertEqual(status["runtime"], "gpu")
        self.assertTrue(status["session"]["queue_active"])
        self.assertEqual(status["session"]["running_prompt_id"], "prompt-running")
        self.assertEqual(status["session"]["pending_prompt_ids"], ["prompt-pending"])
        self.assertEqual(status["progress"]["percent"], 25.0)
        self.assertEqual(status["progress"]["prompt_id"], "prompt-running")

    def test_comfyui_webui_generation_status_uses_queue_when_progress_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json")},
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="active", reason="test", last_active_epoch=100.0)

            def _fake_uds_get(_socket_path, path):
                if path == "/queue":
                    return {"queue_running": [[0, "prompt-running"]], "queue_pending": []}
                if path == "/progress":
                    return None
                return None

            with patch.object(manager, "_uds_json_get", side_effect=_fake_uds_get):
                status = manager.comfyui_webui_generation_status()

        self.assertTrue(status["session"]["queue_active"])
        self.assertFalse(status["progress"]["available"])
        self.assertTrue(status["progress"]["active"])
        self.assertEqual(status["progress"]["prompt_id"], "prompt-running")
        self.assertEqual(status["progress"]["fallback_status"], "running")

    def test_comfyui_webui_generation_status_uses_queue_when_progress_zero(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json")},
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="active", reason="test", last_active_epoch=100.0)

            def _fake_uds_get(_socket_path, path):
                if path == "/queue":
                    return {"queue_running": [[0, "prompt-running"]], "queue_pending": []}
                if path == "/progress":
                    return {"value": 0, "max": 4, "prompt_id": "prompt-running", "node": "sampler"}
                return None

            with patch.object(manager, "_uds_json_get", side_effect=_fake_uds_get):
                status = manager.comfyui_webui_generation_status()

        self.assertTrue(status["session"]["queue_active"])
        self.assertTrue(status["progress"]["active"])
        self.assertIsNone(status["progress"]["percent"])
        self.assertEqual(status["progress"]["prompt_id"], "prompt-running")
        self.assertEqual(status["progress"]["fallback_status"], "running")

    def test_comfyui_progress_empty_payload_is_unavailable(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        with patch.object(manager, "_uds_json_get", return_value={}):
            progress = manager._comfyui_progress_state()

        self.assertFalse(progress["available"])
        self.assertFalse(progress["active"])

    def test_comfyui_webui_start_refreshes_stale_idle_clock(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"HEXE_COMFYUI_WEBUI_SESSION_FILE": str(Path(tmp) / "session.json")},
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._write_comfyui_webui_session(state="idle", reason="old", last_active_epoch=100.0)
            with patch("time.time", return_value=500.0):
                manager._write_comfyui_webui_session(
                    state="starting",
                    reason="manual_webui_start_requested",
                    last_active_epoch=time.time(),
                )
            with (
                patch("time.time", return_value=501.0),
                patch.object(manager, "_uds_json_get", return_value={"queue_running": [], "queue_pending": []}),
            ):
                session = manager.comfyui_webui_session_status()

        self.assertEqual(session["last_active_epoch"], 500.0)
        self.assertEqual(session["idle_seconds"], 1.0)

    def test_comfyui_manual_runtime_env_uses_separate_artifact_dirs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_MANUAL_GPU_INPUT_DIR": str(Path(tmp) / "manual-gpu" / "input"),
                "HEXE_COMFYUI_MANUAL_GPU_OUTPUT_DIR": str(Path(tmp) / "manual-gpu" / "output"),
                "HEXE_COMFYUI_MANUAL_GPU_USER_DIR": str(Path(tmp) / "manual-gpu" / "user"),
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._prepare_comfyui_manual_dirs(runtime="gpu")
            env = manager._comfyui_manual_runtime_env(runtime="gpu")
            status = manager._comfyui_webui_status()
            self.assertTrue(Path(env["COMFYUI_GPU_INPUT_DIR"]).exists())
            self.assertTrue(Path(env["COMFYUI_GPU_OUTPUT_DIR"]).exists())
            self.assertTrue(Path(env["COMFYUI_GPU_USER_DIR"]).exists())
            self.assertIn("manual-gpu/input", env["COMFYUI_GPU_INPUT_DIR"])
            self.assertIn("manual-gpu/output", status["manual_paths"]["output_dir"])

    def test_comfyui_manual_runtime_env_resolves_relative_dirs_for_compose_binds(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_MANUAL_GPU_INPUT_DIR": "runtime/manual/comfyui-gpu/input",
                "HEXE_COMFYUI_MANUAL_GPU_OUTPUT_DIR": "runtime/manual/comfyui-gpu/output",
                "HEXE_COMFYUI_MANUAL_GPU_USER_DIR": "runtime/manual/comfyui-gpu/user",
            },
            clear=False,
        ), patch("pathlib.Path.cwd", return_value=Path(tmp)):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            env = manager._comfyui_manual_runtime_env(runtime="gpu")

            self.assertTrue(Path(env["COMFYUI_GPU_INPUT_DIR"]).is_absolute())
            self.assertTrue(Path(env["COMFYUI_GPU_OUTPUT_DIR"]).is_absolute())
            self.assertTrue(Path(env["COMFYUI_GPU_USER_DIR"]).is_absolute())
            self.assertNotIn(":", env["COMFYUI_GPU_INPUT_DIR"])

    def test_comfyui_manual_mounts_active_detects_manual_binds(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_MANUAL_GPU_INPUT_DIR": str(Path(tmp) / "manual-gpu" / "input"),
                "HEXE_COMFYUI_MANUAL_GPU_OUTPUT_DIR": str(Path(tmp) / "manual-gpu" / "output"),
                "HEXE_COMFYUI_MANUAL_GPU_USER_DIR": str(Path(tmp) / "manual-gpu" / "user"),
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            mounts = [
                {"Source": str(Path(tmp) / "manual-gpu" / "input"), "Destination": "/runtime/gpu/input"},
                {"Source": str(Path(tmp) / "manual-gpu" / "output"), "Destination": "/runtime/gpu/output"},
                {"Source": str(Path(tmp) / "manual-gpu" / "user"), "Destination": "/runtime/gpu/user"},
            ]

            with patch("subprocess.run", return_value=_Completed(json.dumps(mounts))):
                self.assertTrue(manager._comfyui_manual_mounts_active(runtime="gpu"))

            stale_mounts = [
                {"Source": str(Path(tmp) / "normal-gpu" / "input"), "Destination": "/runtime/gpu/input"},
                {"Source": str(Path(tmp) / "manual-gpu" / "output"), "Destination": "/runtime/gpu/output"},
                {"Source": str(Path(tmp) / "manual-gpu" / "user"), "Destination": "/runtime/gpu/user"},
            ]
            with patch("subprocess.run", return_value=_Completed(json.dumps(stale_mounts))):
                self.assertFalse(manager._comfyui_manual_mounts_active(runtime="gpu"))

    def test_comfyui_webui_start_restarts_when_running_with_non_manual_mounts(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_COMFYUI_WEBUI_BRIDGE_SCRIPT": str(Path(tmp) / "bridge.py"),
                "COMFYUI_GPU_SOCKET_PATH": str(Path(tmp) / "comfyui-gpu.sock"),
                "HEXE_COMFYUI_MANUAL_GPU_INPUT_DIR": str(Path(tmp) / "manual-gpu" / "input"),
                "HEXE_COMFYUI_MANUAL_GPU_OUTPUT_DIR": str(Path(tmp) / "manual-gpu" / "output"),
                "HEXE_COMFYUI_MANUAL_GPU_USER_DIR": str(Path(tmp) / "manual-gpu" / "user"),
            },
            clear=False,
        ):
            Path(tmp, "bridge.py").touch()
            Path(tmp, "comfyui-gpu.sock").touch()
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            running = {"state": "running", "runtime": "gpu", "socket_path": manager._comfyui_gpu_socket}
            with (
                patch.object(manager, "_comfyui_webui_status", side_effect=[running, running]),
                patch.object(manager, "_comfyui_manual_mounts_active", return_value=False),
                patch.object(manager, "stop_comfyui_webui", return_value={"target": "comfyui_webui", "result": "stopped"}) as fake_stop,
                patch.object(manager, "_run_comfyui_control") as fake_run_control,
                patch.object(manager, "_write_comfyui_webui_session"),
                patch("subprocess.Popen") as fake_popen,
                patch("time.sleep"),
            ):
                result = manager.start_comfyui_webui()

        self.assertEqual(result["result"], "started")
        fake_stop.assert_called_once()
        fake_run_control.assert_called_once()
        self.assertEqual(fake_run_control.call_args.args[:2], ("gpu", "ready"))
        env = fake_run_control.call_args.kwargs["env"]
        self.assertIn("manual-gpu/input", env["COMFYUI_GPU_INPUT_DIR"])
        fake_popen.assert_called_once()

    def test_unix_socket_tcp_bridge_forwards_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = str(Path(tmp) / "comfyui.sock")
            pid_file = Path(tmp) / "bridge.pid"
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                bridge_port = probe.getsockname()[1]
            server = _UnixHTTPServer(socket_path, _BridgeProbeHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            process = subprocess.Popen(
                [
                    sys.executable,
                    "scripts/unix-socket-tcp-bridge.py",
                    "--socket-path",
                    socket_path,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(bridge_port),
                    "--pid-file",
                    str(pid_file),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
                for _ in range(30):
                    if manager._tcp_port_ready(host="127.0.0.1", port=bridge_port):
                        break
                    time.sleep(0.1)
                self.assertTrue(manager._tcp_port_ready(host="127.0.0.1", port=bridge_port))
                with urlopen(f"http://127.0.0.1:{bridge_port}/", timeout=5) as response:
                    response_body = response.read().decode("utf-8")
            finally:
                process.terminate()
                process.wait(timeout=5)
                server.shutdown()
                server.server_close()

        self.assertEqual(response_body, "bridge-ok")

    def test_local_llm_always_on_starts_default_when_runtime_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID": "qwen3-8b-q4_k_m",
                "HEXE_LOCAL_LLM_ALWAYS_ON_ENABLED": "true",
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._local_llm_models_config = str(self._write_local_model_config(tmp))
            manager._local_llm_control_script = "scripts/llamacpp-control.sh"
            runtime_ready = {"value": False}
            invoked = []

            def _fake_exists(path):
                value = str(path)
                if value == "scripts/llamacpp-control.sh":
                    return True
                if value in {manager._local_llm_socket, manager._local_llm_health_socket}:
                    return runtime_ready["value"]
                return True

            def _fake_run(cmd, check, capture_output, text, env=None):
                invoked.append((cmd, env))
                runtime_ready["value"] = True
                return _Completed("{}")

            with (
                patch("os.path.exists", side_effect=_fake_exists),
                patch.object(
                    manager,
                    "_active_local_llm_model_ids",
                    side_effect=[[], [], ["qwen3-8b-q4_k_m"], ["qwen3-8b-q4_k_m"]],
                ),
                patch("subprocess.run", side_effect=_fake_run),
            ):
                result = manager.ensure_local_llm_always_on()

        self.assertTrue(result["started"])
        self.assertTrue(result["runtime_ready"])
        self.assertTrue(result["default_model_loaded"])
        self.assertEqual(invoked[0][0], ["scripts/llamacpp-control.sh", "ready"])
        self.assertEqual(invoked[0][1]["LLAMACPP_MODEL_ALIAS"], "qwen3-8b-q4_k_m")

    def test_local_llm_always_on_can_be_disabled(self):
        with patch.dict("os.environ", {"HEXE_LOCAL_LLM_ALWAYS_ON_ENABLED": "false"}, clear=False):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            with (
                patch("os.path.exists", return_value=False),
                patch.object(manager, "_active_local_llm_model_ids", return_value=[]),
                patch("subprocess.run") as fake_run,
            ):
                result = manager.ensure_local_llm_always_on()

        self.assertFalse(result["started"])
        self.assertFalse(result["enabled"])
        self.assertEqual(result["reason"], "disabled")
        fake_run.assert_not_called()

    def test_local_llm_always_on_waits_for_local_work(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
        with (
            patch("os.path.exists", return_value=False),
            patch.object(manager, "_active_local_llm_model_ids", return_value=[]),
            patch("subprocess.run") as fake_run,
        ):
            result = manager.ensure_local_llm_always_on(local_in_flight=1)

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "local_work_in_flight")
        fake_run.assert_not_called()

    def test_vision_runtime_residency_starts_when_model_is_not_loaded(self):
        with patch.dict("os.environ", {"HEXE_VISION_LLM_ALWAYS_ON_ENABLED": "true"}, clear=False):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._vision_llm_control_script = "scripts/llamacpp-vision-control.sh"
            runtime_ready = {"value": False}
            invoked = []

            def _fake_exists(path):
                value = str(path)
                if value == "scripts/llamacpp-vision-control.sh":
                    return True
                if value in {manager._vision_llm_socket, manager._vision_llm_health_socket}:
                    return runtime_ready["value"]
                return True

            def _fake_run(cmd, check, capture_output, text, env=None):
                invoked.append(cmd)
                if cmd[:2] == ["docker", "inspect"]:
                    return _Completed("4243\n" if runtime_ready["value"] else "0\n")
                runtime_ready["value"] = True
                return _Completed("{}")

            with (
                patch("os.path.exists", side_effect=_fake_exists),
                patch.object(
                    manager,
                    "_active_model_ids_for_socket",
                    side_effect=[[], ["qwen2.5-vl-3b-instruct-q4_k_m"]],
                ),
                patch("subprocess.run", side_effect=_fake_run),
            ):
                result = manager.ensure_vision_runtime_resident()

        self.assertTrue(result["started"])
        self.assertEqual(result["residency_state"], "model_loaded")
        self.assertIn(["scripts/llamacpp-vision-control.sh", "ready"], invoked)

    def test_vision_runtime_residency_starts_when_comfyui_has_no_model_loaded(self):
        with patch.dict("os.environ", {"HEXE_VISION_LLM_ALWAYS_ON_ENABLED": "true"}, clear=False):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._vision_llm_control_script = "scripts/llamacpp-vision-control.sh"
            runtime_ready = {"value": False}
            invoked = []

            def _fake_exists(path):
                value = str(path)
                if value == "scripts/llamacpp-vision-control.sh":
                    return True
                if value in {manager._vision_llm_socket, manager._vision_llm_health_socket}:
                    return runtime_ready["value"]
                return True

            def _fake_run(cmd, check, capture_output, text, env=None):
                invoked.append(cmd)
                if cmd[:2] == ["docker", "inspect"]:
                    return _Completed("4243\n" if runtime_ready["value"] else "0\n")
                runtime_ready["value"] = True
                return _Completed("{}")

            with (
                patch("os.path.exists", side_effect=_fake_exists),
                patch.object(
                    manager,
                    "_active_model_ids_for_socket",
                    side_effect=[[], ["qwen2.5-vl-3b-instruct-q4_k_m"]],
                ),
                patch.object(
                    manager,
                    "_uds_json_get",
                    return_value={"model_residency": "on_demand", "system_stats": {"devices": [{"torch_vram_total": 0}]}},
                ),
                patch("subprocess.run", side_effect=_fake_run),
            ):
                result = manager.ensure_vision_runtime_resident()

        self.assertTrue(result["started"])
        self.assertFalse(result["comfyui_gpu_model_loaded"])
        self.assertEqual(result["residency_state"], "model_loaded")
        self.assertIn(["scripts/llamacpp-vision-control.sh", "ready"], invoked)

    def test_vision_runtime_residency_starts_when_comfyui_has_model_loaded_without_critical_work(self):
        with patch.dict("os.environ", {"HEXE_VISION_LLM_ALWAYS_ON_ENABLED": "true"}, clear=False):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._vision_llm_control_script = "scripts/llamacpp-vision-control.sh"
            runtime_ready = {"value": False}
            invoked = []

            def _fake_exists(path):
                value = str(path)
                if value == "scripts/llamacpp-vision-control.sh":
                    return True
                if value in {manager._vision_llm_socket, manager._vision_llm_health_socket}:
                    return runtime_ready["value"]
                return True

            def _fake_run(cmd, check, capture_output, text, env=None):
                invoked.append(cmd)
                if cmd[:2] == ["docker", "inspect"]:
                    return _Completed("4243\n" if runtime_ready["value"] else "0\n")
                runtime_ready["value"] = True
                return _Completed("{}")

            with (
                patch("os.path.exists", side_effect=_fake_exists),
                patch.object(
                    manager,
                    "_active_model_ids_for_socket",
                    side_effect=[[], ["qwen2.5-vl-3b-instruct-q4_k_m"]],
                ),
                patch.object(
                    manager,
                    "_uds_json_get",
                    return_value={"model_residency": "loaded", "system_stats": {"devices": [{"torch_vram_total": 4096}]}},
                ),
                patch("subprocess.run", side_effect=_fake_run),
            ):
                result = manager.ensure_vision_runtime_resident()

        self.assertTrue(result["started"])
        self.assertTrue(result["comfyui_gpu_model_loaded"])
        self.assertFalse(result["gpu_comfyui_critical_in_flight"])
        self.assertEqual(result["residency_state"], "model_loaded")
        self.assertIn(["scripts/llamacpp-vision-control.sh", "ready"], invoked)

    def test_vision_runtime_residency_waits_when_critical_comfyui_work_is_pending(self):
        with patch.dict("os.environ", {"HEXE_VISION_LLM_ALWAYS_ON_ENABLED": "true"}, clear=False):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            def _fake_exists(path):
                value = str(path)
                if value in {manager._vision_llm_socket, manager._vision_llm_health_socket}:
                    return False
                return True

            with (
                patch("os.path.exists", side_effect=_fake_exists),
                patch.object(manager, "_active_model_ids_for_socket", return_value=[]),
                patch.object(
                    manager,
                    "_uds_json_get",
                    return_value={"model_residency": "on_demand", "system_stats": {"devices": [{"torch_vram_total": 0}]}},
                ),
                patch("subprocess.run") as fake_run,
            ):
                result = manager.ensure_vision_runtime_resident(gpu_comfyui_critical_in_flight=True)

        self.assertFalse(result["started"])
        self.assertFalse(result["comfyui_gpu_model_loaded"])
        self.assertTrue(result["gpu_comfyui_critical_in_flight"])
        self.assertEqual(result["reason"], "gpu_comfyui_critical_work_pending")
        control_calls = [
            call.args[0]
            for call in fake_run.call_args_list
            if call.args and call.args[0][:1] == ["scripts/llamacpp-vision-control.sh"]
        ]
        self.assertEqual(control_calls, [])

    def test_vision_runtime_residency_waits_for_local_work(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
        with (
            patch("os.path.exists", return_value=False),
            patch.object(manager, "_active_model_ids_for_socket", return_value=[]),
            patch("subprocess.run") as fake_run,
        ):
            result = manager.ensure_vision_runtime_resident(local_in_flight=1)

        self.assertFalse(result["started"])
        self.assertEqual(result["reason"], "local_work_in_flight")
        control_calls = [
            call.args[0]
            for call in fake_run.call_args_list
            if call.args and call.args[0][:1] == ["scripts/llamacpp-vision-control.sh"]
        ]
        self.assertEqual(control_calls, [])

    def test_unload_vision_model_uses_container_stop_fallback(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
        manager._vision_llm_control_script = "scripts/llamacpp-vision-control.sh"
        invoked = []

        def _fake_run(cmd, check, capture_output, text, env=None):
            invoked.append(cmd)
            if cmd[:2] == ["docker", "inspect"]:
                return _Completed("0\n")
            return _Completed("{}")

        with (
            patch("os.path.exists", side_effect=lambda path: str(path) == "scripts/llamacpp-vision-control.sh"),
            patch.object(manager, "_active_model_ids_for_socket", return_value=[]),
            patch("subprocess.run", side_effect=_fake_run),
        ):
            result = manager.unload_vision_model()

        self.assertIn(["scripts/llamacpp-vision-control.sh", "unload-model"], invoked)
        self.assertEqual(result["result"], "model_unloaded")
        self.assertFalse(result["unload_model_supported"])
        self.assertEqual(result["unload_model_mode"], "container_stop_fallback")
        self.assertEqual(result["residency_state"], "container_stopped")

    def test_local_llm_model_states_reports_loaded_warm_cold_and_swap_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._local_llm_models_config = str(self._write_local_model_config(tmp))

            with patch("os.path.exists", return_value=True):
                warm_payload = manager.local_llm_model_states_payload(active_model_ids=[])
            warm_by_id = {item["model_id"]: item for item in warm_payload["models"]}
            self.assertEqual(warm_by_id["qwen3-8b-q4_k_m"]["warmth_state"], "warm")
            self.assertEqual(warm_by_id["gemma-3-12b-it-q4_k_m"]["warmth_state"], "cold")

            with patch("os.path.exists", return_value=True):
                loaded_payload = manager.local_llm_model_states_payload(active_model_ids=["gemma-3-12b-it-q4_k_m"])
            loaded_by_id = {item["model_id"]: item for item in loaded_payload["models"]}
            self.assertEqual(loaded_by_id["gemma-3-12b-it-q4_k_m"]["warmth_state"], "loaded")
            self.assertTrue(loaded_by_id["gemma-3-12b-it-q4_k_m"]["loaded"])
            self.assertEqual(loaded_by_id["qwen3-8b-q4_k_m"]["warmth_state"], "swap_required")
            self.assertTrue(loaded_by_id["qwen3-8b-q4_k_m"]["swap_required"])

            with patch("os.path.exists", return_value=False):
                cold_payload = manager.local_llm_model_states_payload(active_model_ids=[])
            cold_by_id = {item["model_id"]: item for item in cold_payload["models"]}
            self.assertEqual(cold_by_id["qwen3-8b-q4_k_m"]["warmth_state"], "cold")
            self.assertEqual(cold_by_id["qwen3-8b-q4_k_m"]["health_state"], "cold")

    def test_ensure_local_llm_model_restarts_with_configured_model_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "models.json"
            config_path.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "id": "gemma-3-12b-it-q4_k_m",
                                "repo": "bartowski/google_gemma-3-12b-it-GGUF",
                                "quantization": "Q4_K_M",
                                "ctx_size": 4096,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._local_llm_models_config = str(config_path)
            manager._local_llm_control_script = "scripts/llamacpp-control.sh"
            invoked = []

            def _fake_run(cmd, check, capture_output, text, env=None):
                invoked.append((cmd, env))
                return _Completed("{}")

            with (
                patch("os.path.exists", return_value=True),
                patch.object(manager, "_active_local_llm_model_ids", side_effect=[["qwen3-14b-q4_k_m"], ["gemma-3-12b-it-q4_k_m"]]),
                patch("subprocess.run", side_effect=_fake_run),
            ):
                result = manager.ensure_local_llm_model(model_id="gemma-3-12b-it-q4_k_m")

        self.assertTrue(result["switched"])
        self.assertEqual(invoked[0][0], ["scripts/llamacpp-control.sh", "ready"])
        self.assertEqual(invoked[0][1]["LLAMACPP_MODEL_ALIAS"], "gemma-3-12b-it-q4_k_m")
        self.assertEqual(invoked[0][1]["LLAMACPP_MODEL_HF"], "bartowski/google_gemma-3-12b-it-GGUF:Q4_K_M")
        self.assertEqual(invoked[0][1]["LLAMACPP_CTX_SIZE"], "4096")

    def test_ensure_local_llm_model_skips_restart_when_model_is_active(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
        manager._local_llm_models_config = "config/local-llm-models.json"
        with (
            patch.object(manager, "_active_local_llm_model_ids", return_value=["qwen3-14b-q4_k_m"]),
            patch("subprocess.run") as fake_run,
        ):
            result = manager.ensure_local_llm_model(model_id="qwen3-14b-q4_k_m")
        self.assertFalse(result["switched"])
        fake_run.assert_not_called()

    def test_revert_local_llm_to_default_after_non_default_idle(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {
                "HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID": "qwen3-8b-q4_k_m",
                "HEXE_LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS": "10",
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            manager._local_llm_models_config = str(self._write_local_model_config(tmp))
            manager._local_llm_control_script = "scripts/llamacpp-control.sh"
            invoked = []

            def _fake_run(cmd, check, capture_output, text, env=None):
                invoked.append((cmd, env))
                return _Completed("{}")

            with patch("time.monotonic", return_value=100.0):
                manager.record_local_llm_model_use(model_id="gemma-3-12b-it-q4_k_m")
            with (
                patch("os.path.exists", return_value=True),
                patch("time.monotonic", return_value=111.0),
                patch.object(
                    manager,
                    "_active_local_llm_model_ids",
                    side_effect=[["gemma-3-12b-it-q4_k_m"], ["gemma-3-12b-it-q4_k_m"], ["qwen3-8b-q4_k_m"], ["qwen3-8b-q4_k_m"]],
                ),
                patch("subprocess.run", side_effect=_fake_run),
            ):
                result = manager.revert_local_llm_to_default_if_idle()

        self.assertTrue(result["switched"])
        self.assertEqual(invoked[0][0], ["scripts/llamacpp-control.sh", "ready"])
        self.assertEqual(invoked[0][1]["LLAMACPP_MODEL_ALIAS"], "qwen3-8b-q4_k_m")
        self.assertFalse(result["revert_in_progress"])
        self.assertIsNone(result["active_non_default_model_id"])

    def test_revert_local_llm_to_default_waits_for_in_flight_local_work(self):
        with patch.dict(
            "os.environ",
            {
                "HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID": "qwen3-8b-q4_k_m",
                "HEXE_LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS": "10",
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            with patch("time.monotonic", return_value=100.0):
                manager.record_local_llm_model_use(model_id="gemma-3-12b-it-q4_k_m")
            with (
                patch("time.monotonic", return_value=111.0),
                patch.object(manager, "_active_local_llm_model_ids", return_value=["gemma-3-12b-it-q4_k_m"]),
                patch("subprocess.run") as fake_run,
            ):
                result = manager.revert_local_llm_to_default_if_idle(local_in_flight=1)

        self.assertFalse(result["switched"])
        self.assertFalse(result["revert_due"])
        self.assertEqual(result["reason"], "local_work_in_flight")
        fake_run.assert_not_called()

    def test_revert_local_llm_to_default_waits_when_queue_needs_active_model(self):
        with patch.dict(
            "os.environ",
            {
                "HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID": "qwen3-8b-q4_k_m",
                "HEXE_LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS": "10",
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            with patch("time.monotonic", return_value=100.0):
                manager.record_local_llm_model_use(model_id="gemma-3-12b-it-q4_k_m")
            with (
                patch("time.monotonic", return_value=111.0),
                patch.object(manager, "_active_local_llm_model_ids", return_value=["gemma-3-12b-it-q4_k_m"]),
                patch("subprocess.run") as fake_run,
            ):
                result = manager.revert_local_llm_to_default_if_idle(queued_model_ids=["gemma-3-12b-it-q4_k_m"])

        self.assertFalse(result["switched"])
        self.assertFalse(result["revert_due"])
        self.assertEqual(result["reason"], "queued_work_needs_active_model")
        fake_run.assert_not_called()

    def test_non_default_model_use_resets_default_revert_idle_timer(self):
        with patch.dict(
            "os.environ",
            {
                "HEXE_PROVIDER_LOCAL_DEFAULT_MODEL_ID": "qwen3-8b-q4_k_m",
                "HEXE_LOCAL_LLM_DEFAULT_REVERT_IDLE_SECONDS": "10",
            },
            clear=False,
        ):
            manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
            with patch("time.monotonic", return_value=100.0):
                manager.record_local_llm_model_use(model_id="gemma-3-12b-it-q4_k_m")
            with patch("time.monotonic", return_value=106.0):
                manager.record_local_llm_model_use(model_id="gemma-3-12b-it-q4_k_m")
            with (
                patch("time.monotonic", return_value=115.0),
                patch.object(manager, "_active_local_llm_model_ids", return_value=["gemma-3-12b-it-q4_k_m"]),
            ):
                result = manager.local_llm_default_revert_status()

        self.assertFalse(result["revert_due"])
        self.assertEqual(result["reason"], "idle_threshold_not_reached")
        self.assertEqual(result["idle_seconds"], 9.0)


if __name__ == "__main__":
    unittest.main()
