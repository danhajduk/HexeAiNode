import asyncio
import json
import re
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


DOMAIN_EVENT_QOS = 1
DOMAIN_EVENT_RETAIN = False
MAXIMUM_DOMAIN_EVENT_PAYLOAD_BYTES = 65536

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)+$")
_LEGACY_PROMOTION_FIELDS = {
    "promotion_id",
    "promoted_event_type",
    "received_at",
    "promoted_at",
    "core",
    "routing",
    "policy",
}
_PRIVATE_RAW_FIELDS = {
    "attachment",
    "attachments",
    "authorization",
    "body",
    "content",
    "cookie",
    "credentials",
    "message_body",
    "password",
    "prompt",
    "raw",
    "raw_body",
    "raw_content",
    "raw_message",
    "secret",
    "token",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_forbidden_field(value: object, *, path: str = "payload") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).strip().lower()
            child_path = f"{path}.{key}"
            if normalized_key in _LEGACY_PROMOTION_FIELDS:
                return f"legacy promotion field: {child_path}"
            if normalized_key in _PRIVATE_RAW_FIELDS or normalized_key.endswith(("_password", "_secret", "_token")):
                return f"private raw-content field: {child_path}"
            forbidden = _find_forbidden_field(child, path=child_path)
            if forbidden:
                return forbidden
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            forbidden = _find_forbidden_field(child, path=f"{path}[{index}]")
            if forbidden:
                return forbidden
    elif isinstance(value, (bytes, bytearray, memoryview)):
        return f"binary or attachment content: {path}"
    return None


def domain_event_topic(event_type: str) -> str:
    normalized = str(event_type or "").strip()
    if not _EVENT_TYPE_PATTERN.fullmatch(normalized):
        raise ValueError("invalid_domain_event_type")
    return f"hexe/events/{normalized.replace('.', '/')}"


def build_node_domain_event(
    *,
    trusted_node_id: str,
    event_type: str,
    event_id: str | None = None,
    component: str = "node",
    node_type: str | None = None,
    subject: dict | None = None,
    data: dict | None = None,
    occurred_at: str | None = None,
    severity: str | None = None,
    priority: str | None = None,
    safety_critical: bool = False,
) -> tuple[str, dict, bytes]:
    node_id = str(trusted_node_id or "").strip()
    normalized_event_id = str(event_id or f"evt-{uuid.uuid4()}").strip()
    normalized_component = str(component or "").strip()
    if not node_id:
        raise ValueError("trusted_node_id_required")
    if not normalized_event_id:
        raise ValueError("event_id_required")
    if not normalized_component:
        raise ValueError("source_component_required")
    if subject is not None and not isinstance(subject, dict):
        raise ValueError("subject_must_be_an_object")
    if data is not None and not isinstance(data, dict):
        raise ValueError("data_must_be_an_object")

    topic = domain_event_topic(event_type)
    source = {"node_id": node_id, "component": normalized_component}
    if node_type is not None:
        normalized_node_type = str(node_type).strip()
        if normalized_node_type:
            source["node_type"] = normalized_node_type
    payload = {
        "schema_version": 1,
        "event_id": normalized_event_id,
        "event_type": str(event_type).strip(),
        "source": source,
        "subject": dict(subject or {}),
        "data": dict(data or {}),
        "occurred_at": str(occurred_at or _utc_now_iso()).strip(),
        "safety_critical": bool(safety_critical),
    }
    if severity is not None:
        payload["severity"] = str(severity).strip()
    if priority is not None:
        payload["priority"] = str(priority).strip()

    forbidden = _find_forbidden_field(payload)
    if forbidden:
        raise ValueError(f"unsafe_domain_event_payload: {forbidden}")
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAXIMUM_DOMAIN_EVENT_PAYLOAD_BYTES:
        raise ValueError("domain_event_payload_too_large")
    if topic.removeprefix("hexe/events/").replace("/", ".") != payload["event_type"]:
        raise ValueError("domain_event_topic_type_mismatch")
    return topic, payload, encoded


class PahoDomainEventAdapter:
    async def publish_json(self, **kwargs) -> tuple[bool, str | None]:
        return await asyncio.to_thread(self._publish_json_blocking, **kwargs)

    def _publish_json_blocking(
        self,
        *,
        host: str,
        port: int,
        identity: str,
        token: str,
        topic: str,
        payload: dict,
        qos: int,
        retain: bool,
    ) -> tuple[bool, str | None]:
        client = mqtt.Client(client_id=identity, protocol=mqtt.MQTTv5)
        client.username_pw_set(identity, token)
        try:
            client.connect(host, int(port), keepalive=15)
            client.loop_start()
            wire_payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            info = client.publish(topic, wire_payload, qos=int(qos), retain=bool(retain))
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


class DomainEventPublisher:
    def __init__(self, *, logger, trust_state_provider, mqtt_adapter=None) -> None:
        self._logger = logger
        self._trust_state_provider = trust_state_provider
        self._mqtt_adapter = mqtt_adapter or PahoDomainEventAdapter()

    async def publish(self, *, event_type: str, **event_fields) -> dict:
        trust = self._trust_state_provider() if callable(self._trust_state_provider) else {}
        trust = trust if isinstance(trust, dict) else {}
        node_id = str(trust.get("node_id") or "").strip()
        host = str(trust.get("operational_mqtt_host") or "").strip()
        identity = str(trust.get("operational_mqtt_identity") or "").strip()
        token = str(trust.get("operational_mqtt_token") or "").strip()
        port = int(trust.get("operational_mqtt_port") or 0)
        if not node_id or not host or not identity or not token or port <= 0:
            return {"published": False, "last_error": "invalid_operational_mqtt_credentials", "last_topic": None}

        topic, payload, _encoded = build_node_domain_event(
            trusted_node_id=node_id,
            event_type=event_type,
            **event_fields,
        )
        published, error = await self._mqtt_adapter.publish_json(
            host=host,
            port=port,
            identity=identity,
            token=token,
            topic=topic,
            payload=payload,
            qos=DOMAIN_EVENT_QOS,
            retain=DOMAIN_EVENT_RETAIN,
        )
        result = {
            "published": bool(published),
            "last_error": error if not published else None,
            "last_topic": topic,
            "event_id": payload["event_id"],
        }
        if hasattr(self._logger, "info"):
            self._logger.info("[domain-event-publisher] %s", result)
        return result
