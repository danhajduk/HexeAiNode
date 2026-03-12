import asyncio
from datetime import datetime, timezone
import threading

import paho.mqtt.client as mqtt


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


class PahoOperationalMqttAdapter:
    async def connect_and_disconnect(
        self,
        *,
        host: str,
        port: int,
        identity: str,
        token: str,
        timeout_seconds: float,
    ) -> tuple[bool, str | None]:
        return await asyncio.to_thread(
            self._connect_and_disconnect_blocking,
            host=host,
            port=port,
            identity=identity,
            token=token,
            timeout_seconds=timeout_seconds,
        )

    def _connect_and_disconnect_blocking(
        self,
        *,
        host: str,
        port: int,
        identity: str,
        token: str,
        timeout_seconds: float,
    ) -> tuple[bool, str | None]:
        connected_event = threading.Event()
        result = {"rc": None}

        client = mqtt.Client(client_id=identity, clean_session=True)
        client.username_pw_set(identity, token)

        def _on_connect(_client, _userdata, _flags, rc):
            result["rc"] = int(rc)
            connected_event.set()

        client.on_connect = _on_connect
        try:
            client.connect(host, int(port), keepalive=15)
            client.loop_start()
            if not connected_event.wait(timeout=max(float(timeout_seconds), 1.0)):
                return False, "connect_timeout"
            if result["rc"] != 0:
                return False, f"connect_rc_{result['rc']}"
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


class OperationalMqttReadinessChecker:
    def __init__(self, *, logger, mqtt_adapter=None, connect_timeout_seconds: float = 5.0) -> None:
        self._logger = logger
        self._mqtt_adapter = mqtt_adapter or PahoOperationalMqttAdapter()
        self._connect_timeout_seconds = float(connect_timeout_seconds)
        self._status = {
            "ready": False,
            "last_attempt_at": None,
            "last_error": None,
            "endpoint": None,
        }

    def status_payload(self) -> dict:
        return dict(self._status)

    async def check_once(self, *, trust_state: dict) -> dict:
        if not isinstance(trust_state, dict):
            raise ValueError("trust_state is required")

        host = _require_non_empty_string(trust_state.get("operational_mqtt_host"), "operational_mqtt_host")
        identity = _require_non_empty_string(trust_state.get("operational_mqtt_identity"), "operational_mqtt_identity")
        token = _require_non_empty_string(trust_state.get("operational_mqtt_token"), "operational_mqtt_token")
        try:
            port = int(trust_state.get("operational_mqtt_port"))
        except Exception as exc:
            raise ValueError("operational_mqtt_port is required") from exc
        if port <= 0:
            raise ValueError("operational_mqtt_port must be positive")

        ready, error = await self._mqtt_adapter.connect_and_disconnect(
            host=host,
            port=port,
            identity=identity,
            token=token,
            timeout_seconds=self._connect_timeout_seconds,
        )
        return self._update_result(
            ready=ready,
            error=error,
            endpoint={"host": host, "port": port, "identity": identity},
        )

    def _update_result(self, *, ready: bool, error: str | None, endpoint: dict) -> dict:
        self._status = {
            "ready": bool(ready),
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None if ready else (error or "unknown_error"),
            "endpoint": endpoint,
        }
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[operational-mqtt-readiness] %s",
                {"ready": self._status["ready"], "endpoint": endpoint, "error": self._status["last_error"]},
            )
        return dict(self._status)
