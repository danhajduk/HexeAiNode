SENSITIVE_KEYS = {
    "node_trust_token",
    "operational_mqtt_token",
    "token",
    "password",
    "secret",
    "api_key",
    "api_token",
    "service_token",
}


def redact_value(key: str, value):
    if key in SENSITIVE_KEYS and value not in (None, ""):
        return "***REDACTED***"
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    return value


def redact_dict(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}
    return {key: redact_value(key, value) for key, value in data.items()}
