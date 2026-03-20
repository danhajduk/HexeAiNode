from dataclasses import dataclass

from ai_node.capabilities.task_families import CANONICAL_TASK_FAMILIES, validate_task_family_capabilities

PHASE3_TASK_FAMILY_V1 = tuple(CANONICAL_TASK_FAMILIES)


@dataclass(frozen=True)
class TaskFamilyValidationResult:
    allowed: bool
    reason: str
    requested_task_family: str
    canonical_task_family: str | None


def canonicalize_phase3_task_family(task_family: str) -> str | None:
    normalized = str(task_family or "").strip().lower()
    if not normalized:
        return None
    is_valid, _error = validate_task_family_capabilities([normalized])
    if not is_valid:
        return None
    if normalized not in set(CANONICAL_TASK_FAMILIES):
        return None
    return normalized


def _normalized_capability_families(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    normalized: set[str] = set()
    for item in values:
        canonical = canonicalize_phase3_task_family(str(item or ""))
        if canonical:
            normalized.add(canonical)
    return normalized


def _accepted_profile_families(profile: dict | None) -> set[str]:
    if not isinstance(profile, dict):
        return set()
    normalized: set[str] = set()
    for key in ("declared_task_families", "task_families", "resolved_tasks", "enabled_task_capabilities"):
        normalized.update(_normalized_capability_families(profile.get(key)))
    return normalized


def validate_execution_task_family(
    *,
    task_family: str,
    declared_task_families: list[str] | None = None,
    accepted_capability_profile: dict | None = None,
) -> TaskFamilyValidationResult:
    requested = str(task_family or "").strip()
    canonical = canonicalize_phase3_task_family(requested)
    if canonical is None or canonical not in set(CANONICAL_TASK_FAMILIES):
        return TaskFamilyValidationResult(
            allowed=False,
            reason="unsupported_task_family",
            requested_task_family=requested,
            canonical_task_family=None,
        )

    declared = _normalized_capability_families(declared_task_families or [])
    if declared and canonical not in declared:
        return TaskFamilyValidationResult(
            allowed=False,
            reason="task_family_not_declared",
            requested_task_family=requested,
            canonical_task_family=canonical,
        )

    accepted = _accepted_profile_families(accepted_capability_profile)
    if accepted and canonical not in accepted:
        return TaskFamilyValidationResult(
            allowed=False,
            reason="task_family_not_accepted",
            requested_task_family=requested,
            canonical_task_family=canonical,
        )

    return TaskFamilyValidationResult(
        allowed=True,
        reason="task_family_allowed",
        requested_task_family=requested,
        canonical_task_family=canonical,
    )
