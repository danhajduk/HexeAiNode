import json
from pathlib import Path
from typing import Optional, Tuple

from ai_node.capabilities.provider_intelligence import PROVIDER_INTELLIGENCE_SCHEMA_VERSION


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        if _is_non_empty_string(item):
            normalized.append(str(item).strip())
    return sorted(set(normalized))


def validate_provider_capability_report(payload: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(payload, dict):
        return False, "invalid_provider_capability_report"
    if str(payload.get("schema_version") or "").strip() != PROVIDER_INTELLIGENCE_SCHEMA_VERSION:
        return False, "invalid_schema_version"
    if not _is_non_empty_string(payload.get("report_version")):
        return False, "invalid_report_version"
    if not _is_non_empty_string(payload.get("generated_at")):
        return False, "invalid_generated_at"
    enabled_providers = _normalize_string_list(payload.get("enabled_providers"))
    providers = payload.get("providers")
    if not isinstance(providers, list):
        return False, "invalid_providers"
    seen = set()
    for provider_payload in providers:
        if not isinstance(provider_payload, dict):
            return False, "invalid_provider_entry"
        provider = str(provider_payload.get("provider") or "").strip()
        if not provider:
            return False, "invalid_provider_name"
        if provider in seen:
            return False, "duplicate_provider_entry"
        seen.add(provider)
        if provider not in enabled_providers:
            return False, "provider_not_enabled"
        if not isinstance(provider_payload.get("models"), list):
            return False, "invalid_provider_models"
        if not isinstance(provider_payload.get("latency"), dict):
            return False, "invalid_provider_latency"
    return True, None


class ProviderCapabilityReportStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        is_valid, error = validate_provider_capability_report(payload)
        if not is_valid:
            raise ValueError(f"cannot save invalid provider capability report: {error}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[provider-capability-report-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[provider-capability-report-invalid] %s",
                    {"path": str(self._path), "reason": "invalid_json"},
                )
            return None
        is_valid, error = validate_provider_capability_report(payload)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[provider-capability-report-invalid] %s",
                    {"path": str(self._path), "reason": error},
                )
            return None
        if hasattr(self._logger, "info"):
            self._logger.info("[provider-capability-report-loaded] %s", {"path": str(self._path)})
        return payload
