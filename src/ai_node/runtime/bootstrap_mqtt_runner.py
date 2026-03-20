import json
import re
import threading
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from ai_node.bootstrap.bootstrap_parser import validate_bootstrap_payload
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


def _build_bootstrap_client_id(node_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", str(node_name or "").strip()).strip("-").lower()
    if not normalized:
        normalized = "ai-node"
    return f"bootstrap-{normalized}"[:23]


class BootstrapMqttRunner:
    def __init__(
        self,
        *,
        lifecycle: NodeLifecycle,
        logger,
        on_core_discovered: Optional[Callable[[dict, str], None]] = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._logger = logger
        self._on_core_discovered = on_core_discovered
        self._client = None
        self._lock = threading.Lock()
        self._active_topic = None
        self._node_name = None

    def start(self, *, bootstrap_host: str, port: int, topic: str, node_name: str) -> None:
        with self._lock:
            self._stop_locked()

            client = mqtt.Client(client_id=_build_bootstrap_client_id(node_name), clean_session=True)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.user_data_set({"topic": topic})
            client.connect_async(bootstrap_host, port, keepalive=30)
            client.loop_start()

            self._client = client
            self._active_topic = topic
            self._node_name = node_name
            if hasattr(self._logger, "info"):
                self._logger.info(
                    "[bootstrap-mqtt-runner] started host=%s port=%s topic=%s",
                    bootstrap_host,
                    port,
                    topic,
                )

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._client = None
            self._active_topic = None
            self._node_name = None

    def _on_connect(self, client, _userdata, _flags, rc):
        if rc != 0:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[bootstrap-mqtt-runner] connect failed rc=%s", rc)
            return

        topic = client._userdata.get("topic")  # pylint: disable=protected-access
        client.subscribe(topic)
        if self._lifecycle.get_state() == NodeLifecycleState.BOOTSTRAP_CONNECTING:
            self._lifecycle.transition_to(
                NodeLifecycleState.BOOTSTRAP_CONNECTED,
                {"source": "bootstrap_mqtt_runner"},
            )
        if hasattr(self._logger, "info"):
            self._logger.info("[bootstrap-mqtt-runner] subscribed topic=%s", topic)

    def _on_message(self, _client, userdata, msg):
        expected_topic = userdata.get("topic")
        if msg.topic != expected_topic:
            return

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[bootstrap-mqtt-runner] invalid json payload ignored")
            return

        ok, parsed = validate_bootstrap_payload(payload, expected_topic=expected_topic)
        if not ok:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[bootstrap-mqtt-runner] invalid bootstrap payload ignored: %s", parsed)
            return

        if self._lifecycle.get_state() == NodeLifecycleState.BOOTSTRAP_CONNECTED:
            self._lifecycle.transition_to(
                NodeLifecycleState.CORE_DISCOVERED,
                {"source": "bootstrap_mqtt_runner"},
            )
            if callable(self._on_core_discovered) and self._node_name:
                self._on_core_discovered(parsed, self._node_name)
            if hasattr(self._logger, "info"):
                self._logger.info("[bootstrap-mqtt-runner] core discovered id=%s", parsed.get("core_id"))
