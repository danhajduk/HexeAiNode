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

        def _fake_run(cmd, check, capture_output, text):
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

        def _fake_run(cmd, check, capture_output, text):
            invoked.append(cmd)
            if cmd[2] == "is-active":
                return _Completed("active\n")
            return _Completed("")

        with patch("subprocess.run", side_effect=_fake_run):
            result = manager.restart(target="node")
        self.assertEqual(result["target"], "node")
        restart_calls = [cmd for cmd in invoked if cmd[2] == "restart"]
        self.assertEqual(len(restart_calls), 2)


if __name__ == "__main__":
    unittest.main()
