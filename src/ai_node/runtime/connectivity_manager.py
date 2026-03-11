import asyncio
from typing import Awaitable, Callable

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


class ConnectivityManager:
    def __init__(self, *, lifecycle: NodeLifecycle, logger) -> None:
        self._lifecycle = lifecycle
        self._logger = logger

    async def reconnect_bootstrap(
        self,
        connect_fn: Callable[[], Awaitable[bool]],
        *,
        max_attempts: int = 5,
        backoff_seconds: float = 0.5,
    ) -> bool:
        for attempt in range(1, max_attempts + 1):
            if self._lifecycle.get_state() == NodeLifecycleState.UNCONFIGURED:
                self._lifecycle.transition_to(
                    NodeLifecycleState.BOOTSTRAP_CONNECTING,
                    {"attempt": attempt, "flow": "bootstrap_reconnect"},
                )
            success = await connect_fn()
            if success:
                if self._lifecycle.get_state() == NodeLifecycleState.BOOTSTRAP_CONNECTING:
                    self._lifecycle.transition_to(
                        NodeLifecycleState.BOOTSTRAP_CONNECTED,
                        {"attempt": attempt, "flow": "bootstrap_reconnect"},
                    )
                return True

            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[bootstrap-reconnect-failed] %s",
                    {"attempt": attempt, "max_attempts": max_attempts},
                )
            if attempt < max_attempts:
                await asyncio.sleep(backoff_seconds * attempt)
        return False

    async def recover_trusted_connectivity(
        self,
        check_fn: Callable[[], Awaitable[bool]],
        *,
        max_checks: int = 10,
        interval_seconds: float = 1.0,
    ) -> bool:
        if self._lifecycle.get_state() != NodeLifecycleState.DEGRADED:
            self._lifecycle.transition_to(
                NodeLifecycleState.DEGRADED,
                {"flow": "trusted_connectivity_outage"},
            )

        for check_index in range(1, max_checks + 1):
            healthy = await check_fn()
            if healthy:
                self._lifecycle.transition_to(
                    NodeLifecycleState.OPERATIONAL,
                    {"flow": "trusted_connectivity_recovered", "check_index": check_index},
                )
                return True

            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[trusted-connectivity-check-failed] %s",
                    {"check_index": check_index, "max_checks": max_checks},
                )
            if check_index < max_checks:
                await asyncio.sleep(interval_seconds)
        return False
