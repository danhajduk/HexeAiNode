import json
from pathlib import Path
from typing import Optional, Tuple

from ai_node.time_utils import local_now_iso


BUDGET_STATE_SCHEMA_VERSION = "1.0"
VALID_SCOPE_KINDS = {"node", "customer", "provider"}
VALID_GRANT_STATUS = {"active", "expired"}


def _now_iso() -> str:
    return local_now_iso()


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def create_budget_state() -> dict:
    return {
        "schema_version": BUDGET_STATE_SCHEMA_VERSION,
        "budget_policy": None,
        "grant_usage": {},
        "provider_budget_usage": {},
        "recent_denials": [],
        "pending_usage_summaries": [],
        "updated_at": _now_iso(),
    }


def _validate_budget_policy(policy: object) -> Tuple[bool, Optional[str]]:
    if policy is None:
        return True, None
    if not isinstance(policy, dict):
        return False, "invalid_budget_policy"
    required_string_fields = (
        "node_id",
        "service",
        "status",
        "budget_policy_version",
        "governance_version",
        "period_start",
        "period_end",
        "issued_at",
    )
    for field_name in required_string_fields:
        if not _is_non_empty_string(policy.get(field_name)):
            return False, f"invalid_budget_policy_{field_name}"
    grants = policy.get("grants")
    if not isinstance(grants, list):
        return False, "invalid_budget_policy_grants"
    for index, grant in enumerate(grants):
        if not isinstance(grant, dict):
            return False, f"invalid_budget_policy_grant:{index}"
        for field_name in (
            "grant_id",
            "consumer_node_id",
            "service",
            "period_start",
            "period_end",
            "status",
            "scope_kind",
            "subject_id",
            "governance_version",
            "budget_policy_version",
            "issued_at",
        ):
            if not _is_non_empty_string(grant.get(field_name)):
                return False, f"invalid_budget_policy_grant_{field_name}:{index}"
        if grant.get("status") not in VALID_GRANT_STATUS:
            return False, f"invalid_budget_policy_grant_status:{index}"
        if grant.get("scope_kind") not in VALID_SCOPE_KINDS:
            return False, f"invalid_budget_policy_grant_scope_kind:{index}"
        limits = grant.get("limits")
        if limits is not None and not isinstance(limits, dict):
            return False, f"invalid_budget_policy_grant_limits:{index}"
        metadata = grant.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            return False, f"invalid_budget_policy_grant_metadata:{index}"
    return True, None


def validate_budget_state(data: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "invalid_budget_state_object"
    if str(data.get("schema_version") or "").strip() != BUDGET_STATE_SCHEMA_VERSION:
        return False, "invalid_schema_version"

    is_valid, error = _validate_budget_policy(data.get("budget_policy"))
    if not is_valid:
        return is_valid, error

    grant_usage = data.get("grant_usage")
    if not isinstance(grant_usage, dict):
        return False, "invalid_grant_usage"
    for grant_id, entry in grant_usage.items():
        if not _is_non_empty_string(grant_id) or not isinstance(entry, dict):
            return False, "invalid_grant_usage_entry"
        if not _is_non_empty_string(entry.get("grant_id")):
            return False, "invalid_grant_usage_grant_id"
        for field_name in ("period_start", "period_end", "updated_at"):
            if not _is_non_empty_string(entry.get(field_name)):
                return False, f"invalid_grant_usage_{field_name}"
        for field_name in ("used_cost_cents", "used_requests", "used_tokens", "reserved_cost_cents"):
            value = entry.get(field_name, 0)
            if not isinstance(value, int) or value < 0:
                return False, f"invalid_grant_usage_{field_name}"
        reservations = entry.get("reservations")
        if not isinstance(reservations, dict):
            return False, "invalid_grant_usage_reservations"
        for reservation_id, reservation in reservations.items():
            if not _is_non_empty_string(reservation_id) or not isinstance(reservation, dict):
                return False, "invalid_grant_usage_reservation_entry"
            for field_name in ("reservation_id", "task_id", "created_at"):
                if not _is_non_empty_string(reservation.get(field_name)):
                    return False, f"invalid_grant_usage_reservation_{field_name}"
            reserved_cost_cents = reservation.get("reserved_cost_cents", 0)
            if not isinstance(reserved_cost_cents, int) or reserved_cost_cents < 0:
                return False, "invalid_grant_usage_reservation_reserved_cost_cents"

    provider_budget_usage = data.get("provider_budget_usage")
    if not isinstance(provider_budget_usage, dict):
        return False, "invalid_provider_budget_usage"
    for usage_key, entry in provider_budget_usage.items():
        if not _is_non_empty_string(usage_key) or not isinstance(entry, dict):
            return False, "invalid_provider_budget_usage_entry"
        for field_name in ("provider_id", "period", "period_start", "period_end", "updated_at"):
            if not _is_non_empty_string(entry.get(field_name)):
                return False, f"invalid_provider_budget_usage_{field_name}"
        for field_name in ("used_cost_cents", "reserved_cost_cents"):
            value = entry.get(field_name, 0)
            if not isinstance(value, int) or value < 0:
                return False, f"invalid_provider_budget_usage_{field_name}"
        reservations = entry.get("reservations")
        if not isinstance(reservations, dict):
            return False, "invalid_provider_budget_usage_reservations"
        for reservation_id, reservation in reservations.items():
            if not _is_non_empty_string(reservation_id) or not isinstance(reservation, dict):
                return False, "invalid_provider_budget_usage_reservation_entry"
            for field_name in ("reservation_id", "task_id", "created_at"):
                if not _is_non_empty_string(reservation.get(field_name)):
                    return False, f"invalid_provider_budget_usage_reservation_{field_name}"
            reserved_cost_cents = reservation.get("reserved_cost_cents", 0)
            if not isinstance(reserved_cost_cents, int) or reserved_cost_cents < 0:
                return False, "invalid_provider_budget_usage_reservation_reserved_cost_cents"

    recent_denials = data.get("recent_denials")
    if not isinstance(recent_denials, list):
        return False, "invalid_recent_denials"
    for entry in recent_denials:
        if not isinstance(entry, dict):
            return False, "invalid_recent_denial"
        for field_name in ("task_id", "reason", "recorded_at"):
            if not _is_non_empty_string(entry.get(field_name)):
                return False, f"invalid_recent_denial_{field_name}"

    pending_usage_summaries = data.get("pending_usage_summaries")
    if not isinstance(pending_usage_summaries, list):
        return False, "invalid_pending_usage_summaries"
    for entry in pending_usage_summaries:
        if not isinstance(entry, dict):
            return False, "invalid_pending_usage_summary"
        for field_name in ("grant_id", "period_start", "period_end", "service", "queued_at"):
            if not _is_non_empty_string(entry.get(field_name)):
                return False, f"invalid_pending_usage_summary_{field_name}"

    if not _is_non_empty_string(data.get("updated_at")):
        return False, "invalid_updated_at"
    return True, None


class BudgetStateStore:
    def __init__(self, *, path: str, logger) -> None:
        self._path = Path(path)
        self._logger = logger

    def save(self, payload: dict) -> None:
        is_valid, error = validate_budget_state(payload)
        if not is_valid:
            raise ValueError(f"cannot save invalid budget state: {error}")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._path)
        if hasattr(self._logger, "info"):
            self._logger.info("[budget-state-saved] %s", {"path": str(self._path)})

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[budget-state-invalid] %s", {"path": str(self._path), "reason": "invalid_json"})
            return None
        is_valid, error = validate_budget_state(payload)
        if not is_valid:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[budget-state-invalid] %s", {"path": str(self._path), "reason": error})
            return None
        return payload

    def load_or_create(self) -> dict:
        payload = self.load()
        if isinstance(payload, dict):
            return payload
        created = create_budget_state()
        self.save(created)
        return created
