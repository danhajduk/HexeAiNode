import logging
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_node.runtime.service_manager import UserSystemdServiceManager


class _Completed:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.stderr = ""


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
