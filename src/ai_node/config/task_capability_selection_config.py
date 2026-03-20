import json
from pathlib import Path
from typing import Optional, Tuple

from ai_node.capabilities.task_families import CANONICAL_TASK_FAMILIES, canonicalize_task_family


DEFAULT_TASK_CAPABILITY_SELECTION_SCHEMA_VERSION = "1.0"


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if _is_non_empty_string(item):
            canonical = canonicalize_task_family(str(item).strip())
            if canonical:
                normalized.append(canonical)
    return sorted(set(normalized))


def validate_task_capability_selection_config(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_task_capability_selection_config_object"
    if str(data.get("schema_version") or "").strip() != DEFAULT_TASK_CAPABILITY_SELECTION_SCHEMA_VERSION:
        return False, "invalid_schema_version"
    selected = _normalize_string_list(data.get("selected_task_families"))
    if not selected:
        return False, "missing_selected_task_families"
    unknown = [item for item in selected if item not in set(CANONICAL_TASK_FAMILIES)]
    if unknown:
        return False, f"unsupported_task_family:{unknown[0]}"
    return True, None


def create_task_capability_selection_config(input_data: dict | None = None) -> dict:
    raw = input_data if isinstance(input_data, dict) else {}
    selected = _normalize_string_list(raw.get("selected_task_families")) or list(CANONICAL_TASK_FAMILIES)
    config = {
        "schema_version": DEFAULT_TASK_CAPABILITY_SELECTION_SCHEMA_VERSION,
        "selected_task_families": selected,
    }
    is_valid, error = validate_task_capability_selection_config(config)
    if not is_valid:
        raise ValueError(f"invalid task capability selection config: {error}")
    return config


class TaskCapabilitySelectionConfigStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, config: dict) -> None:
        is_valid, error = validate_task_capability_selection_config(config)
        if not is_valid:
            raise ValueError(f"cannot save invalid task capability selection config: {error}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[task-capability-selection-config-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[task-capability-selection-config-invalid] %s",
                    {"path": str(self._path), "reason": "invalid_json"},
                )
            return None
        is_valid, error = validate_task_capability_selection_config(payload)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[task-capability-selection-config-invalid] %s",
                    {"path": str(self._path), "reason": error},
                )
            return None
        normalized = create_task_capability_selection_config(payload)
        if normalized != payload:
            self.save(normalized)
            payload = normalized
        if hasattr(self._logger, "info"):
            self._logger.info("[task-capability-selection-config-loaded] %s", {"path": str(self._path)})
        return payload

    def load_or_create(self) -> dict:
        existing = self.load()
        if existing is not None:
            return existing
        created = create_task_capability_selection_config()
        self.save(created)
        return created
