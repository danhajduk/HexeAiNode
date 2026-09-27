import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


TRUSTED_SCHEMA_ID_PREFIX = "https://hexe.local/schemas/client-node-v2/"
TRUSTED_SCHEMA_URL_PREFIX = "/api/schemas/client-node/v2/"


@dataclass(frozen=True)
class PromptInputValidationFailure(ValueError):
    error_code: str
    diagnostics: list[dict]

    def __str__(self) -> str:
        return self.error_code

    def payload(self) -> dict:
        return {
            "error_code": self.error_code,
            "message": "Prompt inputs do not satisfy the selected prompt version's registered schema.",
            "diagnostics": list(self.diagnostics),
        }


def _schema_name_from_reference(*, schema_id: object, schema_url: object) -> str | None:
    normalized_id = str(schema_id or "").strip()
    normalized_url = str(schema_url or "").strip()
    id_name = None
    url_name = None
    if normalized_id:
        if not normalized_id.startswith(TRUSTED_SCHEMA_ID_PREFIX):
            raise PromptInputValidationFailure("prompt_input_schema_untrusted", [])
        id_name = normalized_id.removeprefix(TRUSTED_SCHEMA_ID_PREFIX)
    if normalized_url:
        parsed = urlparse(normalized_url)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith(TRUSTED_SCHEMA_URL_PREFIX):
            raise PromptInputValidationFailure("prompt_input_schema_untrusted", [])
        url_name = parsed.path.removeprefix(TRUSTED_SCHEMA_URL_PREFIX)
    if id_name and url_name and id_name != url_name:
        raise PromptInputValidationFailure("prompt_input_schema_reference_mismatch", [])
    name = id_name or url_name
    if name is None:
        return None
    if not name.endswith(".json") or "/" in name or "\\" in name or name in {".", ".."}:
        raise PromptInputValidationFailure("prompt_input_schema_untrusted", [])
    return name


def _load_schema_documents(schema_dir: Path) -> tuple[dict[str, dict], Registry]:
    documents: dict[str, dict] = {}
    registry = Registry()
    try:
        paths = sorted(schema_dir.glob("*.json"))
    except OSError as exc:
        raise PromptInputValidationFailure("prompt_input_schema_unavailable", []) from exc
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PromptInputValidationFailure("prompt_input_schema_invalid", []) from exc
        if not isinstance(document, dict):
            raise PromptInputValidationFailure("prompt_input_schema_invalid", [])
        documents[path.name] = document
        schema_id = str(document.get("$id") or "").strip()
        if schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(document))
    return documents, registry


def validate_prompt_inputs(
    *,
    inputs: dict,
    version_metadata: dict | None,
    schema_dir: Path,
) -> None:
    metadata = version_metadata if isinstance(version_metadata, dict) else {}
    schema_name = _schema_name_from_reference(
        schema_id=metadata.get("input_schema_id"),
        schema_url=metadata.get("input_schema_url"),
    )
    if schema_name is None:
        return
    documents, registry = _load_schema_documents(schema_dir)
    schema = documents.get(schema_name)
    if not isinstance(schema, dict):
        raise PromptInputValidationFailure("prompt_input_schema_not_found", [])
    try:
        validator = Draft202012Validator(schema, registry=registry)
        validator.check_schema(schema)
        errors = sorted(validator.iter_errors(inputs), key=lambda item: (list(item.absolute_path), item.validator or ""))
    except Exception as exc:
        raise PromptInputValidationFailure("prompt_input_schema_invalid", []) from exc
    if not errors:
        return
    diagnostics = []
    for error in errors:
        path = "/" + "/".join(str(part) for part in error.absolute_path) if error.absolute_path else "/"
        diagnostics.append(
            {
                "path": path,
                "keyword": str(error.validator or "validation"),
                "message": error.message,
            }
        )
    raise PromptInputValidationFailure("prompt_input_validation_failed", diagnostics)
