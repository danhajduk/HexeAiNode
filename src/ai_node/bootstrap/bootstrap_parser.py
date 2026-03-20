import json
from typing import Iterable, Tuple
from urllib.parse import urljoin, urlparse

from ai_node.security.boundaries import enforce_bootstrap_security_boundary


REQUIRED_FIELDS = (
    "topic",
    "bootstrap_version",
    "core_id",
    "core_name",
    "core_version",
    "api_base",
    "mqtt_host",
    "mqtt_port",
    "onboarding_endpoints",
    "onboarding_mode",
    "emitted_at",
)


REGISTRATION_ENDPOINT_KEYS = (
    "register_session",
    "ai_node_register",
    "register",
)


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_bootstrap_payload(raw_payload: object) -> Tuple[bool, object]:
    try:
        if isinstance(raw_payload, bytes):
            text = raw_payload.decode("utf-8")
        elif isinstance(raw_payload, str):
            text = raw_payload
        else:
            text = str(raw_payload)
        return True, json.loads(text)
    except Exception:
        return False, "invalid_json"


def resolve_registration_endpoint_path(onboarding_endpoints: object) -> str:
    if not isinstance(onboarding_endpoints, dict):
        raise ValueError("onboarding_endpoints is required")

    for key in REGISTRATION_ENDPOINT_KEYS:
        candidate = onboarding_endpoints.get(key)
        if _is_non_empty_string(candidate):
            return str(candidate).strip()

    raise ValueError("onboarding_endpoints.register_session (or legacy register) is required")


def build_registration_url(api_base: str, register_path: str) -> str:
    api = str(api_base or "").strip()
    path = str(register_path or "").strip()
    if not _is_non_empty_string(api):
        raise ValueError("api_base is required")
    if not _is_non_empty_string(path):
        raise ValueError("registration endpoint path is required")

    parsed = urlparse(api)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("invalid api_base URL")

    base = f"{api.rstrip('/')}/"
    relative_path = path[1:] if path.startswith("/") else path
    base_path = parsed.path.strip("/")
    if base_path and (
        relative_path == base_path or relative_path.startswith(f"{base_path}/")
    ):
        relative_path = relative_path[len(base_path) :].lstrip("/")
    return urljoin(base, relative_path)


def validate_bootstrap_payload(
    payload: object,
    *,
    supported_versions: Iterable[int] = (1,),
    expected_topic: str = "synthia/bootstrap/core",
) -> Tuple[bool, object]:
    if not isinstance(payload, dict):
        return False, "invalid_payload"
    boundary_ok, boundary_error = enforce_bootstrap_security_boundary(payload)
    if not boundary_ok:
        return False, boundary_error
    if any(field not in payload for field in REQUIRED_FIELDS):
        return False, "missing_required_fields"

    topic = str(payload["topic"]).strip()
    bootstrap_version = int(payload["bootstrap_version"])
    core_id = str(payload["core_id"]).strip()
    core_name = str(payload["core_name"]).strip()
    core_version = str(payload["core_version"]).strip()
    api_base = str(payload["api_base"]).strip()
    mqtt_host = str(payload["mqtt_host"]).strip()
    mqtt_port = int(payload["mqtt_port"])
    onboarding_mode = str(payload["onboarding_mode"]).strip()
    emitted_at = str(payload["emitted_at"]).strip()
    try:
        register_endpoint = resolve_registration_endpoint_path(payload.get("onboarding_endpoints"))
    except ValueError:
        return False, "missing_register_endpoint"

    if topic != expected_topic:
        return False, "invalid_topic"
    if bootstrap_version not in tuple(supported_versions):
        return False, "unsupported_bootstrap_version"
    if onboarding_mode != "api":
        return False, "unsupported_onboarding_mode"
    if not _is_non_empty_string(api_base):
        return False, "invalid_api_base"
    if not _is_non_empty_string(core_id) or not _is_non_empty_string(core_name):
        return False, "invalid_core_identity"
    if not _is_non_empty_string(core_version):
        return False, "invalid_core_version"
    if not _is_non_empty_string(mqtt_host) or mqtt_port <= 0:
        return False, "invalid_mqtt_target"
    if not _is_non_empty_string(emitted_at):
        return False, "invalid_emitted_at"

    try:
        registration_url = build_registration_url(api_base, register_endpoint)
    except ValueError:
        return False, "invalid_registration_url"

    return True, {
        "topic": topic,
        "bootstrap_version": bootstrap_version,
        "core_id": core_id,
        "core_name": core_name,
        "core_version": core_version,
        "api_base": api_base,
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "onboarding_endpoints": payload["onboarding_endpoints"],
        "onboarding_mode": onboarding_mode,
        "emitted_at": emitted_at,
        "registration_endpoint_path": register_endpoint,
        "registration_url": registration_url,
    }
