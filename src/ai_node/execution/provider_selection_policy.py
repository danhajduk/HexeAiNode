from dataclasses import dataclass, field


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


def _normalize_provider_models(value: object) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for provider_id, models in value.items():
        key = _normalize_string(provider_id).lower()
        if not key:
            continue
        normalized[key] = [item.lower() for item in _normalize_string_list(models)]
    return normalized


def _normalize_provider_budget_limits(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for provider_id, payload in value.items():
        key = _normalize_string(provider_id).lower()
        if not key or not isinstance(payload, dict):
            continue
        max_cost_cents = payload.get("max_cost_cents")
        if max_cost_cents is None:
            continue
        normalized[key] = max(int(max_cost_cents), 0)
    return normalized


@dataclass(frozen=True)
class ProviderSelectionPolicyInput:
    enabled_providers: list[str]
    default_provider: str | None = None
    requested_provider: str | None = None
    requested_model: str | None = None
    provider_health: dict[str, dict] = field(default_factory=dict)
    usable_models_by_provider: dict[str, list[str]] = field(default_factory=dict)
    provider_retry_count: dict[str, int] = field(default_factory=dict)
    provider_budget_limits: dict[str, dict] = field(default_factory=dict)
    request_timeout_s: int = 60
    request_max_cost_cents: int | None = None
    governance_constraints: dict | None = None


@dataclass(frozen=True)
class ProviderSelectionPolicyDecision:
    provider_order: list[str]
    model_allowlist_by_provider: dict[str, list[str]]
    timeout_s: int
    retry_count_by_provider: dict[str, int]
    fallback_allowed: bool
    rejection_reason: str | None = None


def build_provider_selection_policy(policy: ProviderSelectionPolicyInput) -> ProviderSelectionPolicyDecision:
    enabled = [item.lower() for item in _normalize_string_list(policy.enabled_providers)]
    if not enabled:
        return ProviderSelectionPolicyDecision(
            provider_order=[],
            model_allowlist_by_provider={},
            timeout_s=max(int(policy.request_timeout_s), 1),
            retry_count_by_provider={},
            fallback_allowed=False,
            rejection_reason="no_enabled_providers",
        )

    governance = policy.governance_constraints if isinstance(policy.governance_constraints, dict) else {}
    approved_providers = [item.lower() for item in _normalize_string_list(governance.get("approved_providers"))]
    allowed_provider_set = set(approved_providers) if approved_providers else set(enabled)
    eligible_providers = [provider_id for provider_id in enabled if provider_id in allowed_provider_set]
    if not eligible_providers:
        return ProviderSelectionPolicyDecision(
            provider_order=[],
            model_allowlist_by_provider={},
            timeout_s=max(int(policy.request_timeout_s), 1),
            retry_count_by_provider={},
            fallback_allowed=False,
            rejection_reason="no_governance_approved_providers",
        )

    provider_health = {
        _normalize_string(provider_id).lower(): (payload if isinstance(payload, dict) else {})
        for provider_id, payload in (policy.provider_health or {}).items()
    }
    provider_budget_limits = _normalize_provider_budget_limits(policy.provider_budget_limits)
    usable_models_by_provider = _normalize_provider_models(policy.usable_models_by_provider)
    approved_models_by_provider = _normalize_provider_models(governance.get("approved_models"))
    routing_policy = governance.get("routing_policy_constraints") if isinstance(governance.get("routing_policy_constraints"), dict) else {}
    max_timeout = routing_policy.get("max_timeout_s")
    governance_max_retries = routing_policy.get("max_retry_count")

    requested_provider = _normalize_string(policy.requested_provider).lower()
    default_provider = _normalize_string(policy.default_provider).lower()
    provider_order: list[str] = []
    for candidate in [requested_provider, default_provider, *eligible_providers]:
        if not candidate or candidate in provider_order:
            continue
        if candidate not in eligible_providers:
            continue
        availability = str((provider_health.get(candidate) or {}).get("availability") or "unavailable").strip().lower()
        if availability not in {"available", "degraded", ""}:
            continue
        if policy.request_max_cost_cents is not None and candidate in provider_budget_limits:
            if int(policy.request_max_cost_cents) > int(provider_budget_limits.get(candidate) or 0):
                continue
        provider_order.append(candidate)

    if not provider_order:
        return ProviderSelectionPolicyDecision(
            provider_order=[],
            model_allowlist_by_provider={},
            timeout_s=max(int(policy.request_timeout_s), 1),
            retry_count_by_provider={},
            fallback_allowed=False,
            rejection_reason="no_eligible_provider_available",
        )

    requested_model = _normalize_string(policy.requested_model).lower()
    model_allowlist_by_provider: dict[str, list[str]] = {}
    for provider_id in provider_order:
        usable_models = usable_models_by_provider.get(provider_id, [])
        approved_models = approved_models_by_provider.get(provider_id, [])
        if usable_models and approved_models:
            allowed_models = [model_id for model_id in usable_models if model_id in set(approved_models)]
        elif usable_models:
            allowed_models = list(usable_models)
        elif approved_models:
            allowed_models = list(approved_models)
        else:
            allowed_models = []
        if requested_model:
            if allowed_models and requested_model in set(allowed_models):
                allowed_models = [requested_model]
            elif not allowed_models:
                allowed_models = [requested_model]
        model_allowlist_by_provider[provider_id] = allowed_models

    timeout_s = max(int(policy.request_timeout_s), 1)
    if max_timeout is not None:
        timeout_s = min(timeout_s, max(int(max_timeout), 1))

    retry_count_by_provider: dict[str, int] = {}
    for provider_id in provider_order:
        configured_retries = max(int((policy.provider_retry_count or {}).get(provider_id) or 0), 0)
        if governance_max_retries is not None:
            configured_retries = min(configured_retries, max(int(governance_max_retries), 0))
        retry_count_by_provider[provider_id] = configured_retries

    return ProviderSelectionPolicyDecision(
        provider_order=provider_order,
        model_allowlist_by_provider=model_allowlist_by_provider,
        timeout_s=timeout_s,
        retry_count_by_provider=retry_count_by_provider,
        fallback_allowed=len(provider_order) > 1,
        rejection_reason=None,
    )
