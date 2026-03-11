import logging
import unittest

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.connectivity_manager import ConnectivityManager


class ConnectivityManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_reconnect_retries_until_success(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("connectivity-test"))
        manager = ConnectivityManager(lifecycle=lifecycle, logger=logging.getLogger("connectivity-test"))

        attempts = {"count": 0}

        async def _connect():
            attempts["count"] += 1
            return attempts["count"] >= 3

        connected = await manager.reconnect_bootstrap(_connect, max_attempts=5, backoff_seconds=0.001)
        self.assertTrue(connected)
        self.assertEqual(attempts["count"], 3)
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.BOOTSTRAP_CONNECTED)

    async def test_trusted_connectivity_outage_moves_degraded_then_restores_operational(self):
        lifecycle = NodeLifecycle(logger=logging.getLogger("connectivity-test"))
        lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        lifecycle.transition_to(NodeLifecycleState.CAPABILITY_SETUP_PENDING)
        lifecycle.transition_to(NodeLifecycleState.OPERATIONAL)
        manager = ConnectivityManager(lifecycle=lifecycle, logger=logging.getLogger("connectivity-test"))

        checks = {"count": 0}

        async def _check():
            checks["count"] += 1
            return checks["count"] >= 2

        recovered = await manager.recover_trusted_connectivity(_check, max_checks=4, interval_seconds=0.001)
        self.assertTrue(recovered)
        self.assertEqual(lifecycle.get_state(), NodeLifecycleState.OPERATIONAL)


if __name__ == "__main__":
    unittest.main()
