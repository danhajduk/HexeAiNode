import asyncio
import json
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties


NOTIFICATION_MESSAGE_EXPIRY_SECONDS = 30 * 60
DEFAULT_EXTERNAL_TARGETS = ["ha"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


class PahoNotificationAdapter:
    async def publish_json(
        self,
        *,
        host: str,
        port: int,
        identity: str,
        token: str,
        topic: str,
        payload: dict,
        retain: bool = False,
        qos: int = 1,
        message_expiry_interval_seconds: int | None = None,
    ) -> tuple[bool, str | None]:
        return await asyncio.to_thread(
            self._publish_json_blocking,
            host=host,
            port=port,
            identity=identity,
            token=token,
            topic=topic,
            payload=payload,
            retain=retain,
            qos=qos,
            message_expiry_interval_seconds=message_expiry_interval_seconds,
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
        retain: bool = False,
        qos: int = 1,
        message_expiry_interval_seconds: int | None = None,
    ) -> tuple[bool, str | None]:
        client = mqtt.Client(client_id=identity, protocol=mqtt.MQTTv5)
        client.username_pw_set(identity, token)
        publish_kwargs = {}
        if message_expiry_interval_seconds is not None:
            properties = Properties(PacketTypes.PUBLISH)
            properties.MessageExpiryInterval = int(message_expiry_interval_seconds)
            publish_kwargs["properties"] = properties
        try:
            client.connect(host, int(port), keepalive=15)
            client.loop_start()
            info = client.publish(topic, json.dumps(payload), qos=int(qos), retain=retain, **publish_kwargs)
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


class UserNotificationService:
    def __init__(self, *, logger, trust_state_provider=None, mqtt_adapter=None) -> None:
        self._logger = logger
        self._trust_state_provider = trust_state_provider or (lambda: {})
        self._mqtt_adapter = mqtt_adapter or PahoNotificationAdapter()
        self._last_publish = {
            "published": False,
            "last_error": None,
            "last_topic": None,
            "last_request_id": None,
            "last_published_at": None,
        }

    def status_payload(self) -> dict:
        return dict(self._last_publish)

    def notify(
        self,
        *,
        title: str,
        message: str,
        kind: str = "event",
        severity: str = "info",
        priority: str = "normal",
        urgency: str | None = None,
        component: str | None = None,
        label: str | None = None,
        event_type: str | None = None,
        summary: str | None = None,
        state_type: str | None = None,
        current: str | None = None,
        previous: str | None = None,
        status: str | None = None,
        retain: bool = False,
        dedupe_key: str | None = None,
        ttl_seconds: int | None = None,
        external_targets: list[str] | None = None,
        broadcast: bool = False,
        data: dict | None = None,
        metadata: dict | None = None,
        trust_state: dict | None = None,
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(
                self.publish(
                    title=title,
                    message=message,
                    kind=kind,
                    severity=severity,
                    priority=priority,
                    urgency=urgency,
                    component=component,
                    label=label,
                    event_type=event_type,
                    summary=summary,
                    state_type=state_type,
                    current=current,
                    previous=previous,
                    status=status,
                    retain=retain,
                    dedupe_key=dedupe_key,
                    ttl_seconds=ttl_seconds,
                    external_targets=external_targets,
                    broadcast=broadcast,
                    data=data,
                    metadata=metadata,
                    trust_state=trust_state,
                )
            )
            return
        loop.create_task(
            self.publish(
                title=title,
                message=message,
                kind=kind,
                severity=severity,
                priority=priority,
                urgency=urgency,
                component=component,
                label=label,
                event_type=event_type,
                summary=summary,
                state_type=state_type,
                current=current,
                previous=previous,
                status=status,
                retain=retain,
                dedupe_key=dedupe_key,
                ttl_seconds=ttl_seconds,
                external_targets=external_targets,
                broadcast=broadcast,
                data=data,
                metadata=metadata,
                trust_state=trust_state,
            )
        )

    async def publish(
        self,
        *,
        title: str,
        message: str,
        kind: str = "event",
        severity: str = "info",
        priority: str = "normal",
        urgency: str | None = None,
        component: str | None = None,
        label: str | None = None,
        event_type: str | None = None,
        summary: str | None = None,
        state_type: str | None = None,
        current: str | None = None,
        previous: str | None = None,
        status: str | None = None,
        retain: bool = False,
        dedupe_key: str | None = None,
        ttl_seconds: int | None = None,
        external_targets: list[str] | None = None,
        broadcast: bool = False,
        data: dict | None = None,
        metadata: dict | None = None,
        trust_state: dict | None = None,
    ) -> dict:
        trust = trust_state if isinstance(trust_state, dict) else self._safe_trust_state()
        node_id = _normalize_string(trust.get("node_id"))
        host = _normalize_string(trust.get("operational_mqtt_host"))
        identity = _normalize_string(trust.get("operational_mqtt_identity"))
        token = _normalize_string(trust.get("operational_mqtt_token"))
        port = int(trust.get("operational_mqtt_port") or 0)
        if not node_id or not host or not identity or not token or port <= 0:
            return self._record(False, "invalid_operational_mqtt_credentials", None, None)

        normalized_kind = _normalize_string(kind).lower() or "event"
        request_id = f"node-notify:{uuid.uuid4()}"
        topic = f"hexe/nodes/{node_id}/notify/request"
        payload = self._build_payload(
            request_id=request_id,
            node_id=node_id,
            kind=normalized_kind,
            title=title,
            message=message,
            severity=severity,
            priority=priority,
            urgency=urgency,
            component=component,
            label=label,
            event_type=event_type,
            summary=summary,
            state_type=state_type,
            current=current,
            previous=previous,
            status=status,
            retain=retain,
            dedupe_key=dedupe_key,
            ttl_seconds=ttl_seconds,
            external_targets=external_targets,
            broadcast=broadcast,
            data=data,
            metadata=metadata,
        )
        published, error = await self._mqtt_adapter.publish_json(
            host=host,
            port=port,
            identity=identity,
            token=token,
            topic=topic,
            payload=payload,
            retain=False,
            qos=1,
            message_expiry_interval_seconds=NOTIFICATION_MESSAGE_EXPIRY_SECONDS,
        )
        return self._record(published, error, topic, request_id)

    def _build_payload(
        self,
        *,
        request_id: str,
        node_id: str,
        kind: str,
        title: str,
        message: str,
        severity: str,
        priority: str,
        urgency: str | None,
        component: str | None,
        label: str | None,
        event_type: str | None,
        summary: str | None,
        state_type: str | None,
        current: str | None,
        previous: str | None,
        status: str | None,
        retain: bool,
        dedupe_key: str | None,
        ttl_seconds: int | None,
        external_targets: list[str] | None,
        broadcast: bool,
        data: dict | None,
        metadata: dict | None,
    ) -> dict:
        payload = {
            "schema_version": 1,
            "request_id": request_id,
            "created_at": _utc_now_iso(),
            "node_id": node_id,
            "kind": kind,
            "targets": self._build_targets(external_targets=external_targets, broadcast=broadcast),
            "delivery": {
                "severity": _normalize_string(severity).lower() or "info",
                "priority": _normalize_string(priority).lower() or "normal",
            },
            "source": {
                "component": _normalize_string(component) or None,
                "label": _normalize_string(label) or None,
                "metadata": metadata if isinstance(metadata, dict) and metadata else None,
            },
            "content": {
                "title": _normalize_string(title) or None,
                "message": _normalize_string(message) or None,
            },
            "data": data if isinstance(data, dict) and data else None,
        }
        if urgency:
            payload["delivery"]["urgency"] = _normalize_string(urgency).lower()
        if dedupe_key:
            payload["delivery"]["dedupe_key"] = _normalize_string(dedupe_key)
        if isinstance(ttl_seconds, int) and ttl_seconds > 0:
            payload["delivery"]["ttl_seconds"] = int(ttl_seconds)
        if kind == "state":
            payload["retain"] = bool(retain)
            payload["state"] = {
                "state_type": _normalize_string(state_type) or "node_status",
                "status": _normalize_string(status) or None,
                "current": _normalize_string(current) or None,
                "previous": _normalize_string(previous) or None,
            }
        else:
            payload["event"] = {
                "event_type": _normalize_string(event_type) or "node_notification",
                "summary": _normalize_string(summary) or _normalize_string(title) or _normalize_string(message),
            }
        return self._prune_none(payload)

    @staticmethod
    def _build_targets(*, external_targets: list[str] | None, broadcast: bool) -> dict:
        normalized_external = [
            _normalize_string(item)
            for item in list(external_targets if external_targets is not None else DEFAULT_EXTERNAL_TARGETS)
            if _normalize_string(item)
        ]
        targets = {}
        if broadcast:
            targets["broadcast"] = True
        if normalized_external:
            targets["external"] = normalized_external
        return targets

    @staticmethod
    def _prune_none(value):
        if isinstance(value, dict):
            normalized = {}
            for key, item in value.items():
                pruned = UserNotificationService._prune_none(item)
                if pruned is not None:
                    normalized[key] = pruned
            return normalized or None
        if isinstance(value, list):
            normalized = [UserNotificationService._prune_none(item) for item in value]
            normalized = [item for item in normalized if item is not None]
            return normalized or None
        return value if value is not None else None

    def _safe_trust_state(self) -> dict:
        payload = self._trust_state_provider() if callable(self._trust_state_provider) else {}
        return payload if isinstance(payload, dict) else {}

    def _record(self, published: bool, error: str | None, topic: str | None, request_id: str | None) -> dict:
        self._last_publish = {
            "published": bool(published),
            "last_error": None if published else (error or "notification_publish_failed"),
            "last_topic": topic,
            "last_request_id": request_id,
            "last_published_at": _utc_now_iso(),
        }
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[user-notification] %s",
                {
                    "published": self._last_publish["published"],
                    "topic": self._last_publish["last_topic"],
                    "request_id": self._last_publish["last_request_id"],
                    "error": self._last_publish["last_error"],
                },
            )
        return dict(self._last_publish)
