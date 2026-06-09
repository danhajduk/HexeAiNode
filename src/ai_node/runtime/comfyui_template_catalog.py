import json
from copy import deepcopy
from pathlib import Path


COMFYUI_TEMPLATE_CATALOG_SCHEMA_VERSION = "1.0"
VALID_COMFYUI_TEMPLATE_RUNTIMES = {"comfyui_gpu", "comfyui_cpu"}
VALID_COMFYUI_TEMPLATE_OUTPUT_SCOPES = {"normal", "manual", "normal_and_manual"}


def _optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_string(value: object, *, name: str) -> str:
    text = _optional_string(value)
    if not text:
        raise ValueError(f"{name}_required")
    return text


def _mapping(value: object) -> dict:
    return deepcopy(value) if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _optional_string(item)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _resolve_catalog_path(*, catalog_dir: Path, value: object, name: str) -> str:
    raw = _required_string(value, name=name)
    candidate = Path(raw)
    if candidate.is_absolute():
        return str(candidate)
    return str((catalog_dir / candidate).resolve())


def _load_json_file(path: str, *, name: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{name}_not_found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name}_invalid_json") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{name}_must_be_object")
    return data


def normalize_comfyui_template_variable(value: object) -> dict:
    payload = _mapping(value)
    name = _required_string(payload.get("name"), name="variable_name")
    variable_type = _optional_string(payload.get("type")) or "string"
    return {
        "name": name,
        "type": variable_type,
        "required": bool(payload.get("required", False)),
        "description": _optional_string(payload.get("description")),
        "default": deepcopy(payload.get("default")) if "default" in payload else None,
        "allowed_values": _string_list(payload.get("allowed_values")),
    }


def normalize_comfyui_model_requirements(value: object) -> dict:
    payload = _mapping(value)
    checkpoint = _optional_string(payload.get("checkpoint"))
    loras = _string_list(payload.get("loras") or payload.get("lora"))
    vae = _optional_string(payload.get("vae"))
    controlnets = _string_list(payload.get("controlnets") or payload.get("controlnet"))
    other = _mapping(payload.get("other"))
    return {
        "checkpoint": checkpoint,
        "loras": loras,
        "vae": vae,
        "controlnets": controlnets,
        "other": other,
    }


def normalize_comfyui_template_entry(entry: object, *, catalog_dir: str | Path) -> dict:
    payload = _mapping(entry)
    base_dir = Path(catalog_dir)
    template_id = _required_string(payload.get("template_id"), name="template_id")
    runtime_id = _optional_string(payload.get("runtime_id")) or "comfyui_gpu"
    if runtime_id not in VALID_COMFYUI_TEMPLATE_RUNTIMES:
        raise ValueError("invalid_template_runtime")
    output_scope = _optional_string(payload.get("output_scope")) or "normal"
    if output_scope not in VALID_COMFYUI_TEMPLATE_OUTPUT_SCOPES:
        raise ValueError("invalid_output_scope")
    api_workflow_path = _resolve_catalog_path(
        catalog_dir=base_dir,
        value=payload.get("api_workflow_path"),
        name="api_workflow_path",
    )
    ui_workflow_raw = _optional_string(payload.get("ui_workflow_path"))
    ui_workflow_path = (
        _resolve_catalog_path(catalog_dir=base_dir, value=ui_workflow_raw, name="ui_workflow_path")
        if ui_workflow_raw
        else None
    )
    variables = [normalize_comfyui_template_variable(item) for item in list(payload.get("variables") or [])]
    variable_names = [item["name"] for item in variables]
    if len(variable_names) != len(set(variable_names)):
        raise ValueError("duplicate_template_variable")
    defaults = _mapping(payload.get("defaults"))
    unknown_defaults = sorted(set(defaults) - set(variable_names))
    if unknown_defaults:
        raise ValueError("unknown_template_default")
    api_workflow = _load_json_file(api_workflow_path, name="api_workflow")
    ui_workflow = _load_json_file(ui_workflow_path, name="ui_workflow") if ui_workflow_path else None
    return {
        "template_id": template_id,
        "template_name": _optional_string(payload.get("template_name")) or template_id,
        "description": _optional_string(payload.get("description")),
        "runtime_id": runtime_id,
        "api_workflow_path": api_workflow_path,
        "ui_workflow_path": ui_workflow_path,
        "variables": variables,
        "defaults": defaults,
        "model_requirements": normalize_comfyui_model_requirements(payload.get("model_requirements")),
        "output_scope": output_scope,
        "metadata": _mapping(payload.get("metadata")),
        "validation": {
            "valid": True,
            "api_workflow_node_count": len(api_workflow),
            "ui_workflow_present": ui_workflow is not None,
        },
    }


def load_comfyui_template_catalog(*, catalog_dir: str | Path) -> dict:
    base_dir = Path(catalog_dir)
    catalog_path = base_dir / "catalog.json"
    if not catalog_path.exists():
        return {
            "configured": False,
            "schema_version": COMFYUI_TEMPLATE_CATALOG_SCHEMA_VERSION,
            "catalog_dir": str(base_dir),
            "templates": [],
            "errors": ["catalog_not_found"],
        }
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("template_catalog_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("template_catalog_must_be_object")
    if str(payload.get("schema_version") or "").strip() != COMFYUI_TEMPLATE_CATALOG_SCHEMA_VERSION:
        raise ValueError("invalid_template_catalog_schema_version")
    raw_templates = payload.get("templates")
    if not isinstance(raw_templates, list):
        raise ValueError("invalid_template_catalog_templates")
    templates = [normalize_comfyui_template_entry(entry, catalog_dir=base_dir) for entry in raw_templates]
    template_ids = [item["template_id"] for item in templates]
    if len(template_ids) != len(set(template_ids)):
        raise ValueError("duplicate_template_id")
    return {
        "configured": True,
        "schema_version": COMFYUI_TEMPLATE_CATALOG_SCHEMA_VERSION,
        "catalog_dir": str(base_dir),
        "templates": templates,
        "errors": [],
    }
