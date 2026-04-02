import asyncio
import json
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from ai_node.time_utils import local_now_iso


STATUS_TOPIC_RETAIN = True
STATUS_TTL_SECONDS = 5 * 60
STATUS_MESSAGE_EXPIRY_SECONDS = 30 * 60


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_non_negative_int(value: object) -> int | None:
    try:
        normalized = int(value)
    except Exception:
        return None
    if normalized < 0:
        return None
    return normalized


def _derive_health_status(*, payload: dict) -> str:
    explicit = str(payload.get("health_status") or "").strip().lower()
    if explicit in {"healthy", "degraded", "unhealthy", "error", "unknown"}:
        return explicit

    lifecycle_state = str(payload.get("lifecycle_state") or "").strip().lower()
    overall_status = str(payload.get("overall_status") or "").strip().lower()
    ready = payload.get("ready")
    if lifecycle_state == "degraded" or overall_status in {"degraded", "governance_stale"}:
        return "degraded"
    if overall_status.startswith("workflow_"):
        return "healthy" if ready is not False else "degraded"
    if lifecycle_state == "operational":
        return "healthy" if ready is not False else "degraded"
    if lifecycle_state in {"capability_declaration_failed_retry_pending", "error"}:
        return "error"
    if lifecycle_state in {"unconfigured", "bootstrap_connecting", "registration_pending", "pending_approval"}:
        return "unknown"
    return "unknown"


def _default_summary(*, payload: dict, health_status: str) -> str | None:
    summary = payload.get("summary")
    if summary is None:
        lifecycle_state = str(payload.get("lifecycle_state") or "").strip()
        overall_status = str(payload.get("overall_status") or "").strip()
        fragments = [fragment for fragment in (lifecycle_state, overall_status or health_status) if fragment]
        summary = " | ".join(fragments[:2]) if fragments else health_status
    normalized = str(summary).strip()
    if not normalized:
        return None
    return normalized[:512]


def normalize_status_topic_payload(*, node_id: str, payload: dict | None) -> dict:
    raw = dict(payload) if isinstance(payload, dict) else {}
    details = raw.pop("details", {})
    checks = raw.pop("checks", {})
    normalized_details = dict(details) if isinstance(details, dict) else {}
    normalized_checks = dict(checks) if isinstance(checks, dict) else {}

    ready = raw.get("ready")
    if not isinstance(ready, bool):
        lifecycle_state = str(raw.get("lifecycle_state") or "").strip().lower()
        ready = lifecycle_state == "operational"

    health_status = _derive_health_status(payload={**raw, "ready": ready})
    reported_at = str(raw.pop("reported_at", "")).strip() or _utc_now_iso()
    ttl_s = _coerce_non_negative_int(raw.pop("ttl_s", STATUS_TTL_SECONDS)) or STATUS_TTL_SECONDS
    uptime_s = _coerce_non_negative_int(raw.pop("uptime_s", None))
    lifecycle_state = str(raw.pop("lifecycle_state", "")).strip() or None
    summary = _default_summary(
        payload={**raw, "lifecycle_state": lifecycle_state, "ready": ready},
        health_status=health_status,
    )

    for key in (
        "trusted",
        "capability_state",
        "governance_state",
        "governance_version",
        "operational_mqtt_ready",
        "registered_count",
        "probation_count",
    ):
        if key in raw:
            normalized_checks[key] = raw.pop(key)

    for key, value in raw.items():
        if key in {"health_status", "overall_status", "ready"}:
            continue
        normalized_details[key] = value

    payload_out = {
        "node_id": node_id,
        "health_status": health_status,
        "reported_at": reported_at,
        "ttl_s": ttl_s,
        "lifecycle_state": lifecycle_state,
        "summary": summary,
        "ready": ready,
        "checks": normalized_checks,
        "details": normalized_details,
    }
    if uptime_s is not None:
        payload_out["uptime_s"] = uptime_s
    return payload_out


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
        retain: bool = False,
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
            info = client.publish(topic, json.dumps(payload), qos=0, retain=retain, **publish_kwargs)
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
        result = normalize_status_topic_payload(node_id=node_id, payload=payload)

        published, error = await self._mqtt_adapter.publish_json(
            host=host,
            port=port,
            identity=identity,
            token=token,
            topic=topic,
            payload=result,
            retain=STATUS_TOPIC_RETAIN,
            message_expiry_interval_seconds=STATUS_MESSAGE_EXPIRY_SECONDS,
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
