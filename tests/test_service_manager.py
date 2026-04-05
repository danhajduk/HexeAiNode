import logging
import unittest
from unittest.mock import patch

from ai_node.runtime.service_manager import UserSystemdServiceManager


class _Completed:
    def __init__(self, stdout: str):
        self.stdout = stdout


class ServiceManagerTests(unittest.TestCase):
    def test_get_status_maps_systemctl_states(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        calls = {"count": 0}

        def _fake_run(cmd, check, capture_output, text, env):
            self.assertEqual(cmd[:3], ["systemctl", "--user", "is-active"])
            calls["count"] += 1
            return _Completed("active\n" if calls["count"] == 1 else "failed\n")

        with patch("subprocess.run", side_effect=_fake_run):
            payload = manager.get_status()
        self.assertEqual(payload["backend"], "running")
        self.assertEqual(payload["frontend"], "failed")
        self.assertEqual(payload["node"], "degraded")

    def test_restart_node_restarts_both_units(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))
        invoked = []

        def _fake_run(cmd, check, capture_output, text, env):
            invoked.append(cmd)
            if cmd[2] == "is-active":
                return _Completed("active\n")
            return _Completed("")

        with patch("subprocess.run", side_effect=_fake_run):
            result = manager.restart(target="node")
        self.assertEqual(result["target"], "node")
        restart_calls = [cmd for cmd in invoked if cmd[2] == "restart"]
        self.assertEqual(len(restart_calls), 2)

    def test_get_status_treats_activating_as_running(self):
        manager = UserSystemdServiceManager(logger=logging.getLogger("service-manager-test"))

        def _fake_run(cmd, check, capture_output, text, env):
            self.assertEqual(cmd[:3], ["systemctl", "--user", "is-active"])
            return _Completed("activating\n")

        with patch("subprocess.run", side_effect=_fake_run):
            payload = manager.get_status()
        self.assertEqual(payload["backend"], "running")
        self.assertEqual(payload["frontend"], "running")
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
        self.assertIn("systemctl --user restart synthia-ai-node-backend.service", command[2])


if __name__ == "__main__":
    unittest.main()
