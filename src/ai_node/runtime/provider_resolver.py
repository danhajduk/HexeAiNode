from dataclasses import dataclass

from ai_node.execution.provider_selection_policy import (
    ProviderSelectionPolicyInput,
    build_provider_selection_policy,
)


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ProviderResolutionRequest:
    task_family: str
    requested_provider: str | None = None
    requested_model: str | None = None
    timeout_s: int = 60


@dataclass(frozen=True)
class ProviderResolutionResult:
    allowed: bool
    provider_id: str | None
    model_id: str | None
    provider_order: list[str]
    fallback_provider_ids: list[str]
    model_allowlist_by_provider: dict[str, list[str]]
    timeout_s: int
    retry_count: int
    rejection_reason: str | None = None


class ProviderResolver:
    def __init__(self, *, runtime_manager, logger) -> None:
        self._runtime_manager = runtime_manager
        self._logger = logger

    def resolve(self, *, request: ProviderResolutionRequest, governance_constraints: dict | None = None) -> ProviderResolutionResult:
        context = (
            self._runtime_manager.provider_selection_context_payload()
            if self._runtime_manager is not None and hasattr(self._runtime_manager, "provider_selection_context_payload")
            else {}
        )
        decision = build_provider_selection_policy(
            ProviderSelectionPolicyInput(
                enabled_providers=list(context.get("enabled_providers") or []),
                default_provider=context.get("default_provider"),
                requested_provider=request.requested_provider,
                requested_model=request.requested_model,
                provider_health=context.get("provider_health") or {},
                usable_models_by_provider=context.get("usable_models_by_provider") or {},
                provider_retry_count=context.get("provider_retry_count") or {},
                request_timeout_s=request.timeout_s,
                governance_constraints=governance_constraints,
            )
        )
        if decision.rejection_reason is not None or not decision.provider_order:
            return ProviderResolutionResult(
                allowed=False,
                provider_id=None,
                model_id=None,
                provider_order=list(decision.provider_order),
                fallback_provider_ids=list(decision.provider_order[1:]),
                model_allowlist_by_provider=dict(decision.model_allowlist_by_provider),
                timeout_s=decision.timeout_s,
                retry_count=0,
                rejection_reason=decision.rejection_reason or "provider_resolution_failed",
            )

        default_model_by_provider = context.get("default_model_by_provider") or {}
        available_models_by_provider = context.get("available_models_by_provider") or {}
        requested_provider_id = _normalize_string(request.requested_provider)
        provider_id = None
        model_id = None
        for candidate_provider in decision.provider_order:
            candidate_provider_id = str(candidate_provider).strip()
            candidate_model_id = self._select_model_for_provider(
                provider_id=candidate_provider_id,
                allowlist=decision.model_allowlist_by_provider.get(candidate_provider_id) or [],
                requested_model=request.requested_model if candidate_provider_id == requested_provider_id else None,
                default_model_id=default_model_by_provider.get(candidate_provider_id),
                available_models=available_models_by_provider.get(candidate_provider_id) or [],
            )
            if candidate_model_id is None:
                continue
            provider_id = candidate_provider_id
            model_id = candidate_model_id
            break
        if model_id is None or provider_id is None:
            return ProviderResolutionResult(
                allowed=False,
                provider_id=str(decision.provider_order[0]).strip() if decision.provider_order else None,
                model_id=None,
                provider_order=list(decision.provider_order),
                fallback_provider_ids=list(decision.provider_order[1:]),
                model_allowlist_by_provider=dict(decision.model_allowlist_by_provider),
                timeout_s=decision.timeout_s,
                retry_count=int(decision.retry_count_by_provider.get(str(decision.provider_order[0]).strip()) or 0)
                if decision.provider_order
                else 0,
                rejection_reason="no_eligible_model_available",
            )

        if hasattr(self._logger, "info"):
            self._logger.info(
                "[provider-resolution] %s",
                {
                    "task_family": request.task_family,
                    "provider_id": provider_id,
                    "model_id": model_id,
                    "fallback_provider_ids": list(decision.provider_order[1:]),
                    "timeout_s": decision.timeout_s,
                },
            )

        return ProviderResolutionResult(
            allowed=True,
            provider_id=provider_id,
            model_id=model_id,
            provider_order=list(decision.provider_order),
            fallback_provider_ids=[item for item in list(decision.provider_order) if item != provider_id],
            model_allowlist_by_provider=dict(decision.model_allowlist_by_provider),
            timeout_s=decision.timeout_s,
            retry_count=int(decision.retry_count_by_provider.get(provider_id) or 0),
            rejection_reason=None,
        )

    @staticmethod
    def _select_model_for_provider(
        *,
        provider_id: str,
        allowlist: list[str],
        requested_model: str | None,
        default_model_id: str | None,
        available_models: list[str],
    ) -> str | None:
        allowed = [_normalize_string(item) for item in list(allowlist or []) if _normalize_string(item)]
        available = [_normalize_string(item) for item in list(available_models or []) if _normalize_string(item)]
        requested = _normalize_string(requested_model)
        if requested:
            if allowed and requested in set(allowed):
                return requested
            if not allowed and requested in set(available):
                return requested
            return None
        if allowed:
            return allowed[0]

        default_model = _normalize_string(default_model_id)
        if default_model and (not available or default_model in set(available)):
            return default_model

        if available:
            return available[0]
        return None
