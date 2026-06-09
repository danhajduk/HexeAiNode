import json
from copy import deepcopy
from pathlib import Path

from ai_node.prompts.registration import (
    normalize_prompt_access_policy,
    normalize_prompt_lifecycle_state,
    normalize_prompt_privacy_class,
)
from ai_node.time_utils import local_now_iso


IMAGE_GENERATION_TEMPLATE_STATE_SCHEMA_VERSION = "1.0"
VALID_TEMPLATE_RUNTIMES = {"comfyui_gpu", "comfyui_cpu"}


def _now_iso() -> str:
    return local_now_iso()


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_string(value: object, *, name: str) -> str:
    text = _optional_string(value)
    if not text:
        raise ValueError(f"{name}_required")
    return text


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _mapping(value: object) -> dict:
    return deepcopy(value) if isinstance(value, dict) else {}


def normalize_template_version(value: object, *, fallback_version: str = "v1") -> dict:
    payload = _mapping(value)
    version = _optional_string(payload.get("version")) or fallback_version
    runtime_id = _optional_string(payload.get("runtime_id")) or "comfyui_gpu"
    if runtime_id not in VALID_TEMPLATE_RUNTIMES:
        raise ValueError("invalid_template_runtime")
    api_workflow_path = _required_string(payload.get("api_workflow_path"), name="api_workflow_path")
    return {
        "version": version,
        "runtime_id": runtime_id,
        "api_workflow_path": api_workflow_path,
        "ui_workflow_path": _optional_string(payload.get("ui_workflow_path")),
        "variables": _string_list(payload.get("variables")),
        "defaults": _mapping(payload.get("defaults")),
        "model_requirements": _mapping(payload.get("model_requirements")),
        "output_scope": _optional_string(payload.get("output_scope")) or "normal",
        "metadata": _mapping(payload.get("metadata")),
        "created_at": _optional_string(payload.get("created_at")) or _now_iso(),
    }


def create_image_generation_template_registration(
    *,
    template_id: str,
    service_id: str,
    version: str | None = None,
    template_name: str | None = None,
    owner_service: str | None = None,
    owner_client_id: str | None = None,
    privacy_class: str = "internal",
    access_scope: str = "service",
    allowed_services: list[str] | None = None,
    allowed_clients: list[str] | None = None,
    allowed_customers: list[str] | None = None,
    template_version: dict | None = None,
    metadata: dict | None = None,
    status: str = "active",
) -> dict:
    template = _required_string(template_id, name="template_id")
    service = _required_string(service_id, name="service_id")
    now = _now_iso()
    lifecycle_state = normalize_prompt_lifecycle_state(status)
    access_policy = normalize_prompt_access_policy(
        access_scope=access_scope,
        owner_client_id=owner_client_id,
        allowed_services=allowed_services,
        allowed_clients=allowed_clients,
        allowed_customers=allowed_customers,
    )
    version_value = _optional_string(version) or "v1"
    version_entry = normalize_template_version(template_version, fallback_version=version_value)
    version_value = version_entry["version"]
    return {
        "template_id": template,
        "template_name": _optional_string(template_name) or template,
        "service_id": service,
        "owner_service": _optional_string(owner_service) or service,
        "owner_client_id": access_policy["owner_client_id"],
        "privacy_class": normalize_prompt_privacy_class(privacy_class),
        "access_scope": access_policy["access_scope"],
        "allowed_services": access_policy["allowed_services"],
        "allowed_clients": access_policy["allowed_clients"],
        "allowed_customers": access_policy["allowed_customers"],
        "status": lifecycle_state,
        "metadata": _mapping(metadata),
        "current_version": version_value,
        "versions": [version_entry],
        "lifecycle_history": [{"state": lifecycle_state, "reason": "created", "changed_at": now}],
        "usage": {"execution_count": 0, "success_count": 0, "failure_count": 0, "last_used_at": None},
        "registered_at": now,
        "updated_at": now,
        "last_reviewed_at": None,
        "reviewed_by": None,
        "review_reason": None,
        "retired_at": None,
    }


def normalize_image_generation_template_state(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("invalid_image_generation_template_state")
    if str(data.get("schema_version") or "").strip() not in {"", IMAGE_GENERATION_TEMPLATE_STATE_SCHEMA_VERSION}:
        raise ValueError("invalid_schema_version")
    templates = data.get("templates")
    if not isinstance(templates, list):
        raise ValueError("invalid_templates")
    normalized = []
    for entry in templates:
        if not isinstance(entry, dict):
            raise ValueError("invalid_template_entry")
        template_id = _required_string(entry.get("template_id"), name="template_id")
        service_id = _required_string(entry.get("service_id"), name="service_id")
        versions = entry.get("versions")
        if not isinstance(versions, list) or not versions:
            versions = [entry.get("template_version") if isinstance(entry.get("template_version"), dict) else {}]
        normalized_versions = [
            normalize_template_version(item, fallback_version=str(item.get("version") or entry.get("current_version") or "v1"))
            for item in versions
            if isinstance(item, dict)
        ]
        if not normalized_versions:
            raise ValueError("invalid_template_versions")
        access_policy = normalize_prompt_access_policy(
            access_scope=entry.get("access_scope") or "service",
            owner_client_id=entry.get("owner_client_id"),
            allowed_services=entry.get("allowed_services"),
            allowed_clients=entry.get("allowed_clients"),
            allowed_customers=entry.get("allowed_customers"),
        )
        current_version = _optional_string(entry.get("current_version")) or normalized_versions[-1]["version"]
        normalized.append(
            {
                "template_id": template_id,
                "template_name": _optional_string(entry.get("template_name")) or template_id,
                "service_id": service_id,
                "owner_service": _optional_string(entry.get("owner_service")) or service_id,
                "owner_client_id": access_policy["owner_client_id"],
                "privacy_class": normalize_prompt_privacy_class(entry.get("privacy_class") or "internal"),
                "access_scope": access_policy["access_scope"],
                "allowed_services": access_policy["allowed_services"],
                "allowed_clients": access_policy["allowed_clients"],
                "allowed_customers": access_policy["allowed_customers"],
                "status": normalize_prompt_lifecycle_state(entry.get("status") or "active"),
                "metadata": _mapping(entry.get("metadata")),
                "current_version": current_version,
                "versions": normalized_versions,
                "lifecycle_history": list(entry.get("lifecycle_history") or []),
                "usage": _mapping(entry.get("usage")) or {"execution_count": 0, "success_count": 0, "failure_count": 0, "last_used_at": None},
                "registered_at": _optional_string(entry.get("registered_at")) or _now_iso(),
                "updated_at": _optional_string(entry.get("updated_at")) or _now_iso(),
                "last_reviewed_at": _optional_string(entry.get("last_reviewed_at")),
                "reviewed_by": _optional_string(entry.get("reviewed_by")),
                "review_reason": _optional_string(entry.get("review_reason")),
                "retired_at": _optional_string(entry.get("retired_at")),
            }
        )
    return {
        "schema_version": IMAGE_GENERATION_TEMPLATE_STATE_SCHEMA_VERSION,
        "templates": normalized,
        "updated_at": _optional_string(data.get("updated_at")) or _now_iso(),
    }


def create_image_generation_template_state() -> dict:
    return {
        "schema_version": IMAGE_GENERATION_TEMPLATE_STATE_SCHEMA_VERSION,
        "templates": [],
        "updated_at": _now_iso(),
    }


class ImageGenerationTemplateStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def load_or_create(self) -> dict:
        if not self._path.exists():
            return create_image_generation_template_state()
        try:
            return normalize_image_generation_template_state(json.loads(self._path.read_text(encoding="utf-8")))
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[image-template-state-load-failed] %s", {"path": str(self._path), "error": str(exc)})
            return create_image_generation_template_state()

    def save(self, payload: dict) -> dict:
        normalized = normalize_image_generation_template_state(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
        return normalized
