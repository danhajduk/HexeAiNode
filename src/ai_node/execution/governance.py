import json
from dataclasses import dataclass


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _normalize_string(item)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _task_family_allowed(*, task_family: str, allowed_families: list[str]) -> bool:
    normalized_task_family = _normalize_string(task_family).lower()
    if not normalized_task_family:
        return False
    if not allowed_families:
        return True
    for item in allowed_families:
        normalized = _normalize_string(item).lower()
        if not normalized:
            continue
        if normalized.startswith("task."):
            if normalized_task_family == normalized:
                return True
            continue
        if (
            normalized_task_family == normalized
            or normalized_task_family == f"task.{normalized}"
            or normalized_task_family.startswith(f"task.{normalized}.")
        ):
            return True
    return False


@dataclass(frozen=True)
class ExecutionGovernanceDecision:
    allowed: bool
    reason: str
    mode: str = "reject"


def evaluate_execution_governance(
    *,
    task_family: str,
    timeout_s: int,
    inputs: dict | None,
    governance_bundle: dict | None = None,
    request_governance_constraints: dict | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> ExecutionGovernanceDecision:
    bundle = governance_bundle if isinstance(governance_bundle, dict) else {}
    request_constraints = request_governance_constraints if isinstance(request_governance_constraints, dict) else {}

    generic_rules = bundle.get("generic_node_class_rules") if isinstance(bundle.get("generic_node_class_rules"), dict) else {}
    routing_policy = request_constraints.get("routing_policy_constraints")
    if not isinstance(routing_policy, dict):
        routing_policy = bundle.get("routing_policy_constraints") if isinstance(bundle.get("routing_policy_constraints"), dict) else {}

    allowed_task_families = _normalize_string_list(generic_rules.get("allow_task_families"))
    if not _task_family_allowed(task_family=task_family, allowed_families=allowed_task_families):
        return ExecutionGovernanceDecision(False, "governance_violation_task_family")

    max_timeout_s = routing_policy.get("max_timeout_s")
    if max_timeout_s is not None and int(timeout_s) > max(int(max_timeout_s), 1):
        return ExecutionGovernanceDecision(False, "governance_violation_timeout")

    max_input_bytes = routing_policy.get("max_input_bytes")
    if max_input_bytes is not None:
        serialized_inputs = json.dumps(inputs if isinstance(inputs, dict) else {}, sort_keys=True)
        if len(serialized_inputs.encode("utf-8")) > max(int(max_input_bytes), 0):
            return ExecutionGovernanceDecision(False, "governance_violation_input_size")

    approved_providers = _normalize_string_list(request_constraints.get("approved_providers") or bundle.get("approved_providers"))
    if provider_id is not None and approved_providers:
        if _normalize_string(provider_id).lower() not in {item.lower() for item in approved_providers}:
            return ExecutionGovernanceDecision(False, "governance_violation_provider")

    approved_models_raw = request_constraints.get("approved_models")
    if approved_models_raw is None:
        approved_models_raw = bundle.get("approved_models")
    approved_models = approved_models_raw if isinstance(approved_models_raw, dict) else {}
    if provider_id is not None and model_id is not None:
        allowed_models = _normalize_string_list(approved_models.get(_normalize_string(provider_id).lower()))
        if not allowed_models:
            allowed_models = _normalize_string_list(approved_models.get(_normalize_string(provider_id)))
        if allowed_models and _normalize_string(model_id).lower() not in {item.lower() for item in allowed_models}:
            return ExecutionGovernanceDecision(False, "governance_violation_model")

    return ExecutionGovernanceDecision(True, "governance_allowed")
