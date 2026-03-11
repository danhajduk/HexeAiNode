import asyncio
from typing import Callable, Optional

from ai_node.bootstrap.bootstrap_parser import parse_bootstrap_payload, validate_bootstrap_payload
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


def _assert_exact_topic(topic: str) -> None:
    if not isinstance(topic, str) or not topic:
        raise ValueError("bootstrap topic is required")
    if "#" in topic or "+" in topic:
        raise ValueError("wildcard bootstrap topic is not allowed")


class BootstrapClient:
    def __init__(
        self,
        *,
        lifecycle: NodeLifecycle,
        mqtt_adapter,
        logger,
        max_attempts: int = 5,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 5.0,
    ) -> None:
        if lifecycle is None:
            raise ValueError("bootstrap client requires lifecycle controller")
        if mqtt_adapter is None or not hasattr(mqtt_adapter, "connect"):
            raise ValueError("bootstrap client requires mqtt_adapter.connect")

        self._lifecycle = lifecycle
        self._mqtt_adapter = mqtt_adapter
        self._logger = logger
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._client = None
        self._running = False

    async def connect(
        self,
        config,
        *,
        on_core_discovered: Optional[Callable[[dict], None]] = None,
        supported_bootstrap_versions=(1,),
    ):
        _assert_exact_topic(config.topic)
        self._running = True
        attempt = 0

        while self._running and attempt < self._max_attempts:
            attempt += 1
            self._lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTING, {"attempt": attempt})
            try:
                self._client = await self._mqtt_adapter.connect(
                    {
                        "host": config.bootstrap_host,
                        "port": config.port,
                        "username": None,
                        "password": None,
                        "client_id": config.node_name,
                        "clean": True,
                    }
                )
                await self._client.subscribe(config.topic)
                self._lifecycle.transition_to(NodeLifecycleState.BOOTSTRAP_CONNECTED, {"attempt": attempt})
                if hasattr(self._logger, "info"):
                    self._logger.info(
                        "[bootstrap-connected] %s",
                        {"host": config.bootstrap_host, "port": config.port, "topic": config.topic},
                    )

                async def _handle_message(topic: str, raw_payload: object) -> None:
                    if topic != config.topic:
                        return

                    parsed_ok, parsed_value = parse_bootstrap_payload(raw_payload)
                    if not parsed_ok:
                        if hasattr(self._logger, "warning"):
                            self._logger.warning("[bootstrap-payload-ignored] %s", {"reason": parsed_value})
                        return

                    valid_ok, valid_value = validate_bootstrap_payload(
                        parsed_value,
                        expected_topic=config.topic,
                        supported_versions=supported_bootstrap_versions,
                    )
                    if not valid_ok:
                        if hasattr(self._logger, "warning"):
                            self._logger.warning("[bootstrap-payload-ignored] %s", {"reason": valid_value})
                        return

                    self._lifecycle.transition_to(NodeLifecycleState.CORE_DISCOVERED)
                    if callable(on_core_discovered):
                        on_core_discovered(valid_value)

                self._client.on_message(_handle_message)
                return self
            except Exception as exc:
                if hasattr(self._logger, "warning"):
                    self._logger.warning(
                        "[bootstrap-connect-failed] %s",
                        {
                            "attempt": attempt,
                            "max_attempts": self._max_attempts,
                            "message": str(exc),
                        },
                    )
                if attempt >= self._max_attempts:
                    self._lifecycle.transition_to(
                        NodeLifecycleState.DEGRADED,
                        {"stage": "bootstrap_connect"},
                    )
                    raise RuntimeError("bootstrap connection failed after bounded retries") from exc

                delay_seconds = min(
                    self._base_delay_seconds * (2 ** (attempt - 1)),
                    self._max_delay_seconds,
                )
                await asyncio.sleep(delay_seconds)

        raise RuntimeError("bootstrap client stopped")

    async def stop(self) -> None:
        self._running = False
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
            self._client = None
