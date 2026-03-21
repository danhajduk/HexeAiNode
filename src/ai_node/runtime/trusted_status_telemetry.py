import asyncio
import json

import paho.mqtt.client as mqtt

from ai_node.time_utils import local_now_iso


class PahoTelemetryAdapter:
    async def publish_json(
        self,
        *,
        host: str,
        port: int,
        identity: str,
        token: str,
        topic: str,
        payload: dict,
    ) -> tuple[bool, str | None]:
        return await asyncio.to_thread(
            self._publish_json_blocking,
            host=host,
            port=port,
            identity=identity,
            token=token,
            topic=topic,
            payload=payload,
        )

    def _publish_json_blocking(
        self,
        *,
        host: str,
        port: int,
        identity: str,
        token: str,
        topic: str,
        payload: dict,
    ) -> tuple[bool, str | None]:
        client = mqtt.Client(client_id=identity, clean_session=True)
        client.username_pw_set(identity, token)
        try:
            client.connect(host, int(port), keepalive=15)
            client.loop_start()
            info = client.publish(topic, json.dumps(payload), qos=0, retain=False)
            info.wait_for_publish(timeout=5.0)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return False, f"publish_rc_{info.rc}"
            return True, None
        except Exception as exc:
            return False, str(exc)
        finally:
            try:
                client.loop_stop()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass


class TrustedStatusTelemetryPublisher:
    def __init__(self, *, logger, mqtt_adapter=None) -> None:
        self._logger = logger
        self._mqtt_adapter = mqtt_adapter or PahoTelemetryAdapter()
        self._last_publish = {
            "published": False,
            "last_error": None,
            "last_topic": None,
            "last_published_at": None,
        }

    def status_payload(self) -> dict:
        return dict(self._last_publish)

    async def publish_status(self, *, trust_state: dict, node_id: str, payload: dict) -> dict:
        host = str(trust_state.get("operational_mqtt_host") or "").strip()
        identity = str(trust_state.get("operational_mqtt_identity") or "").strip()
        token = str(trust_state.get("operational_mqtt_token") or "").strip()
        port = int(trust_state.get("operational_mqtt_port") or 0)
        if not host or not identity or not token or port <= 0:
            return self._record(False, "invalid_operational_mqtt_credentials", None)

        topic = f"hexe/nodes/{node_id}/status"
        result = dict(payload)
        result["node_id"] = node_id
        result["timestamp"] = local_now_iso()

        published, error = await self._mqtt_adapter.publish_json(
            host=host,
            port=port,
            identity=identity,
            token=token,
            topic=topic,
            payload=result,
        )
        return self._record(published, error, topic)

    def _record(self, published: bool, error: str | None, topic: str | None) -> dict:
        self._last_publish = {
            "published": bool(published),
            "last_error": error if not published else None,
            "last_topic": topic,
            "last_published_at": local_now_iso(),
        }
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[trusted-status-telemetry] %s",
                {
                    "published": self._last_publish["published"],
                    "topic": self._last_publish["last_topic"],
                    "error": self._last_publish["last_error"],
                },
            )
        return dict(self._last_publish)
