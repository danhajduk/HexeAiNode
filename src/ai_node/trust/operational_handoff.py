from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapChannelContext:
    host: str
    port: int
    topic: str
    anonymous: bool
    publish_allowed: bool


@dataclass(frozen=True)
class OperationalChannelContext:
    host: str
    port: int
    identity: str
    token: str
    anonymous: bool


@dataclass(frozen=True)
class OperationalMqttHandoff:
    bootstrap: BootstrapChannelContext
    operational: OperationalChannelContext


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def prepare_operational_mqtt_handoff(*, trust_state: dict, bootstrap_config: dict) -> OperationalMqttHandoff:
    if not isinstance(trust_state, dict):
        raise ValueError("trust_state is required")
    if not isinstance(bootstrap_config, dict):
        raise ValueError("bootstrap_config is required")

    bootstrap_context = BootstrapChannelContext(
        host=_require_non_empty_string(bootstrap_config.get("bootstrap_host"), "bootstrap_host"),
        port=int(bootstrap_config.get("port", 1884)),
        topic=_require_non_empty_string(bootstrap_config.get("topic"), "topic"),
        anonymous=True,
        publish_allowed=False,
    )
    operational_context = OperationalChannelContext(
        host=_require_non_empty_string(trust_state.get("operational_mqtt_host"), "operational_mqtt_host"),
        port=int(trust_state.get("operational_mqtt_port")),
        identity=_require_non_empty_string(
            trust_state.get("operational_mqtt_identity"), "operational_mqtt_identity"
        ),
        token=_require_non_empty_string(trust_state.get("operational_mqtt_token"), "operational_mqtt_token"),
        anonymous=False,
    )

    if operational_context.host == bootstrap_context.host and operational_context.port == bootstrap_context.port:
        raise ValueError("bootstrap and operational MQTT endpoints must remain logically separated")

    return OperationalMqttHandoff(
        bootstrap=bootstrap_context,
        operational=operational_context,
    )
