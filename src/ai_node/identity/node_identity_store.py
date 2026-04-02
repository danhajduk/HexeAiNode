import json
import uuid
from pathlib import Path
from typing import Optional, Tuple

from ai_node.identity.node_ids import is_valid_canonical_node_id, normalize_node_id
from ai_node.time_utils import local_now_iso


REQUIRED_NODE_IDENTITY_FIELDS = (
    "node_id",
    "created_at",
)


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_node_identity(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_node_identity_object"

    for key in REQUIRED_NODE_IDENTITY_FIELDS:
        if key not in data:
            return False, f"missing_{key}"

    node_id = normalize_node_id(data.get("node_id"))
    created_at = data.get("created_at")
    id_format = str(data.get("id_format") or "uuidv4").strip()

    if not _is_non_empty_string(node_id):
        return False, "invalid_node_id"
    if id_format != "uuidv4":
        return False, "invalid_id_format"
    if not is_valid_canonical_node_id(node_id):
        return False, "invalid_node_id"

    if not _is_non_empty_string(created_at):
        return False, "invalid_created_at"

    return True, None


def create_node_identity() -> dict:
    return {
        "node_id": normalize_node_id(str(uuid.uuid4())),
        "created_at": local_now_iso(),
        "id_format": "uuidv4",
    }


class NodeIdentityStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, identity: dict) -> None:
        identity = {
            **identity,
            "node_id": normalize_node_id(identity.get("node_id")),
            "id_format": "uuidv4",
        }
        is_valid, error = validate_node_identity(identity)
        if not is_valid:
            raise ValueError(f"cannot save invalid node identity: {error}")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(identity, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)

        if hasattr(self._logger, "info"):
            self._logger.info("[node-identity-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[node-identity-invalid] %s",
                    {"path": str(self._path), "reason": "invalid_json"},
                )
            return None

        normalized = {
            **data,
            "node_id": normalize_node_id(data.get("node_id")),
            "id_format": "uuidv4",
        }
        is_valid, error = validate_node_identity(normalized)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[node-identity-invalid] %s",
                    {"path": str(self._path), "reason": error},
                )
            return None

        if hasattr(self._logger, "info"):
            self._logger.info("[node-identity-loaded] %s", {"path": str(self._path)})
        if normalized != data:
            self.save(normalized)
        return normalized

    def create(self) -> dict:
        identity = create_node_identity()
        self.save(identity)
        return identity

    def create_from_node_id(self, node_id: str, *, id_format: str = "legacy") -> dict:
        normalized_node_id = normalize_node_id(node_id)
        if not _is_non_empty_string(normalized_node_id):
            raise ValueError("node_id is required")
        identity = {
            "node_id": normalized_node_id,
            "created_at": local_now_iso(),
            "id_format": "uuidv4",
        }
        self.save(identity)
        return identity

    def load_or_create(self, *, migration_node_id: str | None = None) -> dict:
        existing = self.load()
        if existing is not None:
            return existing
        if _is_non_empty_string(migration_node_id):
            return self.create_from_node_id(str(migration_node_id), id_format="uuidv4")
        return self.create()
