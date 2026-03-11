import json
import threading

import paho.mqtt.client as mqtt

from ai_node.bootstrap.bootstrap_parser import validate_bootstrap_payload
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


class BootstrapMqttRunner:
    def __init__(self, *, lifecycle: NodeLifecycle, logger) -> None:
        self._lifecycle = lifecycle
        self._logger = logger
        self._client = None
        self._lock = threading.Lock()
        self._active_topic = None

    def start(self, *, bootstrap_host: str, port: int, topic: str, node_name: str) -> None:
        with self._lock:
            self.stop()

            client = mqtt.Client(client_id=node_name, clean_session=True)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.user_data_set({"topic": topic})
            client.connect_async(bootstrap_host, port, keepalive=30)
            client.loop_start()

            self._client = client
            self._active_topic = topic
            if hasattr(self._logger, "info"):
                self._logger.info(
                    "[bootstrap-mqtt-runner] started host=%s port=%s topic=%s",
                    bootstrap_host,
                    port,
                    topic,
                )

    def stop(self) -> None:
        with self._lock:
            if self._client is None:
                return
            try:
                self._client.loop_stop()
                self._client.disconnect()
            finally:
                self._client = None
                self._active_topic = None

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
        if hasattr(self._logger, "info"):
            self._logger.info("[bootstrap-mqtt-runner] core discovered id=%s", parsed.get("core_id"))
