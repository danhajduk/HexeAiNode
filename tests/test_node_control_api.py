import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.node_control_api import NodeControlState


class NodeControlApiTests(unittest.TestCase):
    class _FakeBootstrapRunner:
        def __init__(self):
            self.calls = []

        def start(self, **kwargs):
            self.calls.append(kwargs)

    def test_status_is_unconfigured_without_bootstrap_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(Path(tmp) / "bootstrap_config.json"),
                logger=logging.getLogger("node-control-test"),
            )
            payload = state.status_payload()
            self.assertEqual(payload["status"], "unconfigured")
            self.assertFalse(payload["bootstrap_configured"])

    def test_initiate_onboarding_persists_config_and_moves_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bootstrap_config.json"
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runner = self._FakeBootstrapRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(path),
                logger=logging.getLogger("node-control-test"),
                bootstrap_runner=runner,
            )
            payload = state.initiate_onboarding(
                mqtt_host="10.0.0.100",
                node_name="main-ai-node",
            )
            self.assertEqual(payload["status"], "bootstrap_connecting")
            self.assertTrue(path.exists())
            self.assertEqual(lifecycle.get_state(), NodeLifecycleState.BOOTSTRAP_CONNECTING)
            self.assertEqual(len(runner.calls), 1)
            self.assertEqual(runner.calls[0]["topic"], "synthia/bootstrap/core")

    def test_existing_config_load_moves_state_to_bootstrap_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bootstrap_config.json"
            path.write_text(
                '{"bootstrap_host":"10.0.0.100","node_name":"main-ai-node"}',
                encoding="utf-8",
            )
            lifecycle = NodeLifecycle(logger=logging.getLogger("node-control-test"))
            runner = self._FakeBootstrapRunner()
            state = NodeControlState(
                lifecycle=lifecycle,
                config_path=str(path),
                logger=logging.getLogger("node-control-test"),
                bootstrap_runner=runner,
            )
            payload = state.status_payload()
            self.assertEqual(payload["status"], "bootstrap_connecting")
            self.assertTrue(payload["bootstrap_configured"])
            self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
