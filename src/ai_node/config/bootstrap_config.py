from dataclasses import dataclass


BOOTSTRAP_PORT = 1884
BOOTSTRAP_ANONYMOUS = True
BOOTSTRAP_TOPIC = "hexe/bootstrap/core"


@dataclass(frozen=True)
class BootstrapConfig:
    bootstrap_host: str
    node_name: str
    port: int = BOOTSTRAP_PORT
    anonymous: bool = BOOTSTRAP_ANONYMOUS
    topic: str = BOOTSTRAP_TOPIC


def _require_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def create_bootstrap_config(input_data: dict) -> BootstrapConfig:
    if not isinstance(input_data, dict):
        raise ValueError("bootstrap input is required")

    return BootstrapConfig(
        bootstrap_host=_require_non_empty_string(input_data.get("bootstrap_host"), "bootstrap_host"),
        node_name=_require_non_empty_string(input_data.get("node_name"), "node_name"),
    )
