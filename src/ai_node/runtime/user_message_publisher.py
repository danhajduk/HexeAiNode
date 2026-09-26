import json
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


USER_MESSAGE_TOPIC = "hexe/events/user/message"


class UserMessagePublisher:
    def __init__(self, *, logger) -> None:
        self._logger = logger

    def publish(self, *, trust_state: dict, payload: dict) -> tuple[bool, str | None]:
        host = str(trust_state.get("operational_mqtt_host") or "").strip()
        identity = str(trust_state.get("operational_mqtt_identity") or "").strip()
        token = str(trust_state.get("operational_mqtt_token") or "").strip()
        port = int(trust_state.get("operational_mqtt_port") or 0)
        if not host or not identity or not token or port <= 0:
            return False, "invalid_operational_mqtt_credentials"

        client = mqtt.Client(client_id=identity, protocol=mqtt.MQTTv5)
        client.username_pw_set(identity, token)
        try:
            client.connect(host, port, keepalive=15)
            client.loop_start()
            info = client.publish(USER_MESSAGE_TOPIC, json.dumps(payload), qos=1, retain=False)
            info.wait_for_publish(timeout=5.0)
            if not info.is_published() or info.rc != mqtt.MQTT_ERR_SUCCESS:
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


def preview_completed_user_message(*, node_id: str, profile_id: str, profile_name: str, preview_id: str) -> dict:
    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "event_id": f"interaction-user-message-{preview_id}",
        "event_type": "user.message",
        "occurred_at": occurred_at,
        "source": {
            "node_id": node_id,
            "component": "hexe.image-studio",
        },
        "subject": {
            "family": "user_message",
            "record_id": preview_id,
        },
        "data": {
            "endpoint_id": profile_id,
            "title": "Image preview completed",
            "text": f'The image preview for "{profile_name}" is ready.',
        },
    }
