FAILURE_CODE_TAXONOMY = {
    "unsupported_task_family": {
        "canonical_code": "unsupported_task_family",
        "aliases": ["unsupported_task_family", "task_family_not_declared", "task_family_not_accepted"],
    },
    "provider_unavailable": {
        "canonical_code": "provider_unavailable",
        "aliases": [
            "no_enabled_providers",
            "no_governance_approved_providers",
            "no_eligible_provider_available",
            "no_provider_configured",
            "provider_execution_failed",
        ],
    },
    "model_unavailable": {
        "canonical_code": "model_unavailable",
        "aliases": ["no_eligible_model_available"],
    },
    "governance_violation": {
        "canonical_code": "governance_violation",
        "aliases": [
            "prompt_not_registered",
            "prompt_in_probation",
            "task_family_mismatch",
            "governance_stale",
            "governance_violation_task_family",
            "governance_violation_timeout",
            "governance_violation_input_size",
            "governance_violation_provider",
            "governance_violation_model",
        ],
    },
    "budget_violation": {
        "canonical_code": "budget_violation",
        "aliases": [
            "missing_budget_grant",
            "budget_exhausted",
            "reservation_conflict",
            "budget_state_invalid",
        ],
    },
    "invalid_input": {
        "canonical_code": "invalid_input",
        "aliases": ["invalid_input"],
    },
    "execution_timeout": {
        "canonical_code": "execution_timeout",
        "aliases": ["execution_timeout"],
    },
    "lease_expired": {
        "canonical_code": "lease_expired",
        "aliases": ["lease_expired", "lease_lost"],
    },
    "internal_execution_error": {
        "canonical_code": "internal_execution_error",
        "aliases": ["internal_execution_error"],
    },
}


def classify_failure_code(code: str | None) -> str | None:
    normalized = str(code or "").strip()
    if not normalized:
        return None
    for category, payload in FAILURE_CODE_TAXONOMY.items():
        aliases = payload.get("aliases") if isinstance(payload, dict) else []
        if normalized in aliases:
            return category
    if normalized.startswith("governance_violation"):
        return "governance_violation"
    if normalized.startswith("budget_") or normalized in {"missing_budget_grant", "reservation_conflict"}:
        return "budget_violation"
    if normalized.startswith("invalid_input"):
        return "invalid_input"
    return None
