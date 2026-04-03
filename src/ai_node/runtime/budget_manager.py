import math
from datetime import datetime, timedelta

from ai_node.providers.openai_catalog import get_openai_model_pricing
from ai_node.time_utils import local_now, local_now_iso


def _now() -> datetime:
    return local_now()


def _now_iso() -> str:
    return local_now_iso()


def _parse_iso(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _normalize_string(value: object) -> str:
    return str(value or "").strip()


def _normalize_int(value: object, *, default: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized


def _normalize_float(value: object, *, default: float = 0.0) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return default
    if normalized < 0:
        return default
    return normalized


def _estimate_input_tokens(inputs: dict) -> int:
    if not isinstance(inputs, dict):
        return 0
    total_chars = 0
    for key in ("prompt", "text", "content", "body", "subject", "system_prompt"):
        value = inputs.get(key)
        if isinstance(value, str):
            total_chars += len(value)
    messages = inputs.get("messages")
    if isinstance(messages, list):
        for item in messages:
            if not isinstance(item, dict):
                continue
            total_chars += len(str(item.get("content") or ""))
    return max(math.ceil(total_chars / 4), 0)


class BudgetReservationResult:
    def __init__(
        self,
        *,
        allowed: bool,
        reason: str | None = None,
        reservation_id: str | None = None,
        reserved_cost_cents: int = 0,
        applied_grant_ids: list[str] | None = None,
        policy_status: str | None = None,
    ) -> None:
        self.allowed = bool(allowed)
        self.reason = reason
        self.reservation_id = reservation_id
        self.reserved_cost_cents = max(int(reserved_cost_cents), 0)
        self.applied_grant_ids = list(applied_grant_ids or [])
        self.policy_status = policy_status


class BudgetManager:
    def __init__(
        self,
        *,
        store,
        logger,
        provider_runtime_manager=None,
        budget_policy_client=None,
    ) -> None:
        self._store = store
        self._logger = logger
        self._provider_runtime_manager = provider_runtime_manager
        self._budget_policy_client = budget_policy_client

    def _load_state(self) -> dict:
        return self._store.load_or_create()

    def _save_state(self, state: dict) -> None:
        state["updated_at"] = _now_iso()
        self._store.save(state)

    def cache_policy_from_governance(self, *, governance_bundle: dict | None) -> dict | None:
        bundle = governance_bundle if isinstance(governance_bundle, dict) else {}
        budget_policy = bundle.get("budget_policy") if isinstance(bundle.get("budget_policy"), dict) else None
        if not isinstance(budget_policy, dict):
            return None
        state = self._load_state()
        if state.get("budget_policy") == budget_policy:
            return budget_policy
        state["budget_policy"] = budget_policy
        self._save_state(state)
        return budget_policy

    async def refresh_policy_from_core(
        self,
        *,
        trust_state: dict | None,
        governance_bundle: dict | None,
    ) -> dict:
        cached = self.cache_policy_from_governance(governance_bundle=governance_bundle)
        trust = trust_state if isinstance(trust_state, dict) else {}
        if (
            self._budget_policy_client is None
            or not _normalize_string(trust.get("core_api_endpoint"))
            or not _normalize_string(trust.get("node_trust_token"))
            or not _normalize_string(trust.get("node_id"))
        ):
            return {
                "status": "cached_governance_only" if isinstance(cached, dict) else "unavailable",
                "budget_policy": cached,
            }
        result = await self._budget_policy_client.fetch_current_policy(
            core_api_endpoint=_normalize_string(trust.get("core_api_endpoint")),
            trust_token=_normalize_string(trust.get("node_trust_token")),
            node_id=_normalize_string(trust.get("node_id")),
        )
        budget_policy = result.payload.get("budget_policy") if isinstance(result.payload, dict) else None
        if isinstance(budget_policy, dict):
            state = self._load_state()
            state["budget_policy"] = budget_policy
            self._save_state(state)
        return {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "budget_policy": budget_policy if isinstance(budget_policy, dict) else cached,
        }

    def status_payload(self) -> dict:
        state = self._load_state()
        policy = state.get("budget_policy") if isinstance(state.get("budget_policy"), dict) else None
        grant_usage = state.get("grant_usage") if isinstance(state.get("grant_usage"), dict) else {}
        provider_budget_usage = state.get("provider_budget_usage") if isinstance(state.get("provider_budget_usage"), dict) else {}
        runtime_spend_by_provider = self._provider_runtime_exact_spend_by_provider()
        grants = list(policy.get("grants") or []) if isinstance(policy, dict) else []
        active_reservations = 0
        for usage in grant_usage.values():
            reservations = usage.get("reservations") if isinstance(usage, dict) else {}
            if isinstance(reservations, dict):
                active_reservations += len(reservations)
        provider_budgets = []
        for provider_id, settings in self._provider_budget_settings_map().items():
            usage = self._provider_budget_status_entry(
                state=state,
                provider_budget_usage=provider_budget_usage,
                provider_id=provider_id,
                settings=settings,
            )
            used_cost_usd_exact = self._provider_budget_used_cost_usd_exact(
                usage=usage,
                runtime_spend_by_provider=runtime_spend_by_provider,
            )
            used_cost_cents = self._provider_budget_used_cost_cents(
                usage=usage,
                runtime_spend_by_provider=runtime_spend_by_provider,
            )
            reserved_cost_cents = _normalize_int(usage.get("reserved_cost_cents"), default=0)
            reservations = usage.get("reservations") if isinstance(usage, dict) else {}
            if isinstance(reservations, dict):
                active_reservations += len(reservations)
            provider_budgets.append(
                {
                    "provider_id": usage.get("provider_id"),
                    "period": usage.get("period"),
                    "period_start": usage.get("period_start"),
                    "period_end": usage.get("period_end"),
                    "budget_limit_cents": usage.get("budget_limit_cents"),
                    "used_cost_cents": used_cost_cents,
                    "used_cost_usd_exact": used_cost_usd_exact,
                    "reserved_cost_cents": reserved_cost_cents,
                    "remaining_cost_cents": max(
                        _normalize_int(usage.get("budget_limit_cents"), default=0)
                        - used_cost_cents
                        - reserved_cost_cents,
                        0,
                    ),
                    "budget_limit_usd_exact": round(_normalize_int(usage.get("budget_limit_cents"), default=0) / 100.0, 10),
                    "remaining_cost_usd_exact": round(
                        max(
                            (_normalize_int(usage.get("budget_limit_cents"), default=0) / 100.0)
                            - used_cost_usd_exact
                            - (reserved_cost_cents / 100.0),
                            0.0,
                        ),
                        10,
                    ),
                }
            )
        return {
            "configured": isinstance(policy, dict),
            "policy_status": str((policy or {}).get("status") or "unconfigured"),
            "budget_policy_version": (policy or {}).get("budget_policy_version") if isinstance(policy, dict) else None,
            "governance_version": (policy or {}).get("governance_version") if isinstance(policy, dict) else None,
            "grant_count": len(grants),
            "active_reservations": active_reservations,
            "recent_denials": list(state.get("recent_denials") or [])[-20:],
            "grants": [self._grant_snapshot(grant=grant, usage=grant_usage.get(str(grant.get("grant_id") or "").strip())) for grant in grants],
            "provider_budgets": provider_budgets,
        }

    def _grant_snapshot(self, *, grant: dict, usage: dict | None) -> dict:
        limits = grant.get("limits") if isinstance(grant.get("limits"), dict) else {}
        usage_payload = usage if isinstance(usage, dict) else {}
        max_cost_cents = _normalize_int(limits.get("max_cost_cents"), default=0)
        used_cost_cents = _normalize_int(usage_payload.get("used_cost_cents"), default=0)
        reserved_cost_cents = _normalize_int(usage_payload.get("reserved_cost_cents"), default=0)
        return {
            "grant_id": grant.get("grant_id"),
            "scope_kind": grant.get("scope_kind"),
            "subject_id": grant.get("subject_id"),
            "status": grant.get("status"),
            "service": grant.get("service"),
            "period_start": grant.get("period_start"),
            "period_end": grant.get("period_end"),
            "limits": limits,
            "used_cost_cents": used_cost_cents,
            "reserved_cost_cents": reserved_cost_cents,
            "remaining_cost_cents": max(max_cost_cents - used_cost_cents - reserved_cost_cents, 0) if max_cost_cents else None,
            "used_requests": _normalize_int(usage_payload.get("used_requests"), default=0),
            "used_tokens": _normalize_int(usage_payload.get("used_tokens"), default=0),
        }

    def reserve_execution(
        self,
        *,
        task_id: str,
        request,
        provider_id: str,
        model_id: str,
        governance_bundle: dict | None,
    ) -> BudgetReservationResult:
        state = self._load_state()
        policy = self.cache_policy_from_governance(governance_bundle=governance_bundle) or state.get("budget_policy")
        if isinstance(policy, dict):
            state["budget_policy"] = policy
        reservation_id = f"budget-reservation:{_normalize_string(task_id)}"
        reservation_cents = self._reservation_cost_cents(request=request, provider_id=provider_id, model_id=model_id)
        if not isinstance(policy, dict):
            provider_budget_result = self._reserve_provider_budget(
                state=state,
                reservation_id=reservation_id,
                task_id=task_id,
                provider_id=provider_id,
                model_id=model_id,
                reserved_cost_cents=reservation_cents,
            )
            if provider_budget_result is not None and provider_budget_result.get("allowed") is False:
                self._record_denial(task_id=task_id, request=request, reason="provider_budget_exhausted", provider_id=provider_id)
                return BudgetReservationResult(allowed=False, reason="provider_budget_exhausted", policy_status="unconfigured")
            if provider_budget_result is not None:
                self._save_state(state)
            return BudgetReservationResult(
                allowed=True,
                reason=None,
                reservation_id=reservation_id if provider_budget_result is not None else None,
                reserved_cost_cents=reservation_cents if provider_budget_result is not None else 0,
                policy_status="unconfigured",
            )
        policy_status = _normalize_string(policy.get("status")).lower() or "unconfigured"
        if policy_status != "active":
            provider_budget_result = self._reserve_provider_budget(
                state=state,
                reservation_id=reservation_id,
                task_id=task_id,
                provider_id=provider_id,
                model_id=model_id,
                reserved_cost_cents=reservation_cents,
            )
            if provider_budget_result is not None and provider_budget_result.get("allowed") is False:
                self._record_denial(task_id=task_id, request=request, reason="provider_budget_exhausted", provider_id=provider_id)
                return BudgetReservationResult(allowed=False, reason="provider_budget_exhausted", policy_status=policy_status)
            if provider_budget_result is not None:
                self._save_state(state)
            return BudgetReservationResult(
                allowed=True,
                reason=None,
                reservation_id=reservation_id if provider_budget_result is not None else None,
                reserved_cost_cents=reservation_cents if provider_budget_result is not None else 0,
                policy_status=policy_status,
            )

        applicable_grants = self._applicable_grants(policy=policy, request=request, provider_id=provider_id)
        if not applicable_grants:
            self._record_denial(task_id=task_id, request=request, reason="missing_budget_grant", provider_id=provider_id)
            return BudgetReservationResult(allowed=False, reason="missing_budget_grant", policy_status=policy_status)

        applied_grant_ids: list[str] = []
        reserved_usage_entries: list[dict] = []
        for grant in applicable_grants:
            grant_id = _normalize_string(grant.get("grant_id"))
            usage = self._ensure_usage_entry(state=state, grant=grant)
            reservations = usage.setdefault("reservations", {})
            if reservation_id in reservations:
                self._rollback_reservations(
                    usage_entries=reserved_usage_entries,
                    reservation_id=reservation_id,
                    reserved_cost_cents=reservation_cents,
                )
                self._record_denial(task_id=task_id, request=request, reason="reservation_conflict", provider_id=provider_id)
                return BudgetReservationResult(allowed=False, reason="reservation_conflict", policy_status=policy_status)
            max_cost_cents = _normalize_int((grant.get("limits") or {}).get("max_cost_cents"), default=0)
            if max_cost_cents > 0:
                remaining = max_cost_cents - _normalize_int(usage.get("used_cost_cents")) - _normalize_int(usage.get("reserved_cost_cents"))
                if remaining < reservation_cents:
                    self._rollback_reservations(
                        usage_entries=reserved_usage_entries,
                        reservation_id=reservation_id,
                        reserved_cost_cents=reservation_cents,
                    )
                    self._record_denial(task_id=task_id, request=request, reason="budget_exhausted", provider_id=provider_id)
                    return BudgetReservationResult(allowed=False, reason="budget_exhausted", policy_status=policy_status)
            reservations[reservation_id] = {
                "reservation_id": reservation_id,
                "task_id": task_id,
                "reserved_cost_cents": reservation_cents,
                "provider_id": provider_id,
                "model_id": model_id,
                "created_at": _now_iso(),
            }
            usage["reserved_cost_cents"] = _normalize_int(usage.get("reserved_cost_cents")) + reservation_cents
            usage["updated_at"] = _now_iso()
            applied_grant_ids.append(grant_id)
            reserved_usage_entries.append(usage)

        provider_budget_result = self._reserve_provider_budget(
            state=state,
            reservation_id=reservation_id,
            task_id=task_id,
            provider_id=provider_id,
            model_id=model_id,
            reserved_cost_cents=reservation_cents,
        )
        if provider_budget_result is not None and provider_budget_result.get("allowed") is False:
            self._rollback_reservations(
                usage_entries=reserved_usage_entries,
                reservation_id=reservation_id,
                reserved_cost_cents=reservation_cents,
            )
            self._record_denial(task_id=task_id, request=request, reason="provider_budget_exhausted", provider_id=provider_id)
            return BudgetReservationResult(allowed=False, reason="provider_budget_exhausted", policy_status=policy_status)

        self._save_state(state)
        return BudgetReservationResult(
            allowed=True,
            reservation_id=reservation_id,
            reserved_cost_cents=reservation_cents,
            applied_grant_ids=applied_grant_ids,
            policy_status=policy_status,
        )

    def finalize_execution(
        self,
        *,
        task_id: str,
        metrics,
        status: str,
    ) -> dict:
        state = self._load_state()
        reservation_id = f"budget-reservation:{_normalize_string(task_id)}"
        final_cost_cents = self._final_cost_cents(metrics=metrics)
        finalized = []
        for usage in (state.get("grant_usage") or {}).values():
            if not isinstance(usage, dict):
                continue
            reservations = usage.get("reservations")
            if not isinstance(reservations, dict):
                continue
            reservation = reservations.pop(reservation_id, None)
            if not isinstance(reservation, dict):
                continue
            reserved_cost_cents = _normalize_int(reservation.get("reserved_cost_cents"))
            usage["reserved_cost_cents"] = max(_normalize_int(usage.get("reserved_cost_cents")) - reserved_cost_cents, 0)
            applied_cost = final_cost_cents if final_cost_cents is not None else reserved_cost_cents
            if status == "completed":
                usage["used_cost_cents"] = _normalize_int(usage.get("used_cost_cents")) + max(applied_cost, 0)
                usage["used_requests"] = _normalize_int(usage.get("used_requests")) + 1
                total_tokens = getattr(metrics, "total_tokens", 0) if metrics is not None else 0
                usage["used_tokens"] = _normalize_int(usage.get("used_tokens")) + _normalize_int(total_tokens)
                self._queue_usage_summary(state=state, grant_id=_normalize_string(usage.get("grant_id")), usage=usage)
            usage["updated_at"] = _now_iso()
            finalized.append({"grant_id": usage.get("grant_id"), "final_cost_cents": applied_cost})
        provider_finalized = self._finalize_provider_budget(
            state=state,
            reservation_id=reservation_id,
            final_cost_cents=final_cost_cents,
            status=status,
            metrics=metrics,
        )
        if finalized:
            self._save_state(state)
        elif provider_finalized:
            self._save_state(state)
        return {"finalized": finalized, "provider_finalized": provider_finalized}

    def release_execution(self, *, task_id: str, reason: str) -> dict:
        state = self._load_state()
        reservation_id = f"budget-reservation:{_normalize_string(task_id)}"
        released = []
        for usage in (state.get("grant_usage") or {}).values():
            if not isinstance(usage, dict):
                continue
            reservations = usage.get("reservations")
            if not isinstance(reservations, dict):
                continue
            reservation = reservations.pop(reservation_id, None)
            if not isinstance(reservation, dict):
                continue
            reserved_cost_cents = _normalize_int(reservation.get("reserved_cost_cents"))
            usage["reserved_cost_cents"] = max(_normalize_int(usage.get("reserved_cost_cents")) - reserved_cost_cents, 0)
            usage["updated_at"] = _now_iso()
            released.append({"grant_id": usage.get("grant_id"), "released_cost_cents": reserved_cost_cents, "reason": reason})
        provider_released = self._release_provider_budget(state=state, reservation_id=reservation_id, reason=reason)
        if released or provider_released:
            self._save_state(state)
        return {"released": released, "provider_released": provider_released}

    def _final_cost_cents(self, *, metrics) -> int | None:
        estimated_cost = getattr(metrics, "estimated_cost", None) if metrics is not None else None
        if estimated_cost is None:
            return None
        return max(math.ceil(float(estimated_cost) * 100.0), 0)

    def _reservation_cost_cents(self, *, request, provider_id: str, model_id: str) -> int:
        constraints = request.constraints if isinstance(getattr(request, "constraints", None), dict) else {}
        if isinstance(constraints.get("budget"), dict):
            max_cost_cents = constraints["budget"].get("max_cost_cents")
            if max_cost_cents is not None:
                return max(_normalize_int(max_cost_cents), 0)
        if constraints.get("max_cost_cents") is not None:
            return max(_normalize_int(constraints.get("max_cost_cents")), 0)
        if constraints.get("max_cost_usd") is not None:
            return max(math.ceil(float(constraints.get("max_cost_usd")) * 100.0), 0)
        estimated = self._estimate_model_cost_cents(request=request, provider_id=provider_id, model_id=model_id)
        return max(estimated, 1 if self._has_any_money_limits(provider_id=provider_id, request=request) else 0)

    def _estimate_model_cost_cents(self, *, request, provider_id: str, model_id: str) -> int:
        runtime = self._provider_runtime_manager
        registry = getattr(runtime, "_registry", None)
        if registry is None or not hasattr(registry, "get_model"):
            return 0
        model = registry.get_model(provider_id=provider_id, model_id=model_id)
        if model is None:
            return 0
        inputs = request.inputs if isinstance(getattr(request, "inputs", None), dict) else {}
        input_tokens = _estimate_input_tokens(inputs)
        output_tokens = _normalize_int(inputs.get("max_tokens"), default=512)
        input_price = float(getattr(model, "pricing_input", None) or getattr(model, "cached_pricing_input", None) or 0.0)
        output_price = float(getattr(model, "pricing_output", None) or 0.0)
        estimated_usd = ((input_tokens * input_price) + (output_tokens * output_price)) / 1_000_000.0
        return max(math.ceil(estimated_usd * 100.0), 0)

    def _has_any_money_limits(self, *, provider_id: str, request) -> bool:
        policy = self._load_state().get("budget_policy")
        if not isinstance(policy, dict):
            return self._provider_budget_settings(provider_id=provider_id) is not None
        applicable = self._applicable_grants(policy=policy, request=request, provider_id=provider_id)
        return (
            any(_normalize_int((grant.get("limits") or {}).get("max_cost_cents"), default=0) > 0 for grant in applicable)
            or self._provider_budget_settings(provider_id=provider_id) is not None
        )

    def _rollback_reservations(self, *, usage_entries: list[dict], reservation_id: str, reserved_cost_cents: int) -> None:
        for usage in usage_entries:
            reservations = usage.get("reservations")
            if not isinstance(reservations, dict):
                continue
            reservations.pop(reservation_id, None)
            usage["reserved_cost_cents"] = max(_normalize_int(usage.get("reserved_cost_cents")) - reserved_cost_cents, 0)
            usage["updated_at"] = _now_iso()

    def _applicable_grants(self, *, policy: dict, request, provider_id: str) -> list[dict]:
        now = _now()
        service_id = _normalize_string(getattr(request, "service_id", None) or getattr(request, "requested_by", None))
        customer_id = _normalize_string(getattr(request, "customer_id", None))
        provider_key = _normalize_string(provider_id)
        model_key = _normalize_string(getattr(request, "requested_model", None))
        applicable: list[dict] = []
        for grant in list(policy.get("grants") or []):
            if not isinstance(grant, dict):
                continue
            if _normalize_string(grant.get("status")).lower() != "active":
                continue
            start = _parse_iso(grant.get("period_start"))
            end = _parse_iso(grant.get("period_end"))
            if start is not None and now < start:
                continue
            if end is not None and now > end:
                continue
            if service_id and _normalize_string(grant.get("service")) and _normalize_string(grant.get("service")) != service_id:
                continue
            grant_provider = _normalize_string((grant.get("metadata") or {}).get("provider_id"))
            if grant_provider and provider_key and grant_provider != provider_key:
                continue
            grant_model = _normalize_string((grant.get("metadata") or {}).get("model_id"))
            if grant_model and model_key and grant_model != model_key:
                continue
            scope_kind = _normalize_string(grant.get("scope_kind")).lower()
            subject_id = _normalize_string(grant.get("subject_id"))
            if scope_kind == "node":
                applicable.append(grant)
            elif scope_kind == "customer" and customer_id and subject_id == customer_id:
                applicable.append(grant)
            elif scope_kind == "provider" and provider_key and subject_id == provider_key:
                applicable.append(grant)
        return applicable

    def _provider_budget_settings(self, *, provider_id: str) -> dict | None:
        settings_map = self._provider_budget_settings_map()
        settings = settings_map.get(_normalize_string(provider_id))
        return settings if isinstance(settings, dict) and settings.get("max_cost_cents") is not None else None

    def _provider_budget_settings_map(self) -> dict[str, dict]:
        runtime = self._provider_runtime_manager
        if runtime is None or not hasattr(runtime, "provider_selection_context_payload"):
            return {}
        payload = runtime.provider_selection_context_payload()
        budgets = payload.get("provider_budget_limits") if isinstance(payload, dict) else {}
        if not isinstance(budgets, dict):
            return {}
        normalized: dict[str, dict] = {}
        for provider_id, settings in budgets.items():
            normalized_provider_id = _normalize_string(provider_id)
            if not normalized_provider_id or not isinstance(settings, dict) or settings.get("max_cost_cents") is None:
                continue
            normalized[normalized_provider_id] = settings
        return normalized

    def _provider_budget_status_entry(self, *, state: dict, provider_budget_usage: dict, provider_id: str, settings: dict) -> dict:
        period = _normalize_string(settings.get("period")).lower() or "monthly"
        period_start, period_end = self._provider_budget_period_window(period=period)
        usage_key = f"{provider_id}:{period}:{period_start}"
        usage = provider_budget_usage.get(usage_key) if isinstance(provider_budget_usage, dict) else None
        if isinstance(usage, dict):
            return usage
        return {
            "provider_id": provider_id,
            "period": period,
            "period_start": period_start,
            "period_end": period_end,
            "budget_limit_cents": _normalize_int(settings.get("max_cost_cents"), default=0),
            "used_cost_cents": 0,
            "used_cost_usd_exact": 0.0,
            "reserved_cost_cents": 0,
            "reservations": {},
            "updated_at": state.get("updated_at") or _now_iso(),
        }

    def _provider_budget_period_window(self, *, period: str) -> tuple[str, str]:
        now = _now()
        normalized_period = _normalize_string(period).lower() or "monthly"
        if normalized_period == "weekly":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            end = (start + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
            return start.isoformat(), end.isoformat()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(microseconds=1)
        return start.isoformat(), end.isoformat()

    def _ensure_provider_budget_usage_entry(self, *, state: dict, provider_id: str, settings: dict) -> dict:
        period = _normalize_string(settings.get("period")).lower() or "monthly"
        period_start, period_end = self._provider_budget_period_window(period=period)
        usage_key = f"{provider_id}:{period}:{period_start}"
        usage_map = state.setdefault("provider_budget_usage", {})
        usage = usage_map.get(usage_key)
        if not isinstance(usage, dict):
            usage = {
                "provider_id": provider_id,
                "period": period,
                "period_start": period_start,
                "period_end": period_end,
                "budget_limit_cents": _normalize_int(settings.get("max_cost_cents"), default=0),
                "used_cost_cents": 0,
                "used_cost_usd_exact": 0.0,
                "reserved_cost_cents": 0,
                "reservations": {},
                "updated_at": _now_iso(),
            }
            usage_map[usage_key] = usage
        return usage

    def _reserve_provider_budget(self, *, state: dict, reservation_id: str, task_id: str, provider_id: str, model_id: str, reserved_cost_cents: int) -> dict | None:
        settings = self._provider_budget_settings(provider_id=provider_id)
        if settings is None:
            return None
        usage = self._ensure_provider_budget_usage_entry(state=state, provider_id=provider_id, settings=settings)
        if reservation_id in usage["reservations"]:
            return {"allowed": False, "reason": "reservation_conflict"}
        runtime_spend_by_provider = self._provider_runtime_exact_spend_by_provider()
        used_cost_usd_exact = self._provider_budget_used_cost_usd_exact(
            usage=usage,
            runtime_spend_by_provider=runtime_spend_by_provider,
        )
        remaining_exact_cents = (
            _normalize_int(usage.get("budget_limit_cents"))
            - (used_cost_usd_exact * 100.0)
            - _normalize_int(usage.get("reserved_cost_cents"))
        )
        if remaining_exact_cents < reserved_cost_cents:
            return {"allowed": False, "reason": "provider_budget_exhausted"}
        usage["reservations"][reservation_id] = {
            "reservation_id": reservation_id,
            "task_id": task_id,
            "reserved_cost_cents": reserved_cost_cents,
            "provider_id": provider_id,
            "model_id": model_id,
            "created_at": _now_iso(),
        }
        usage["reserved_cost_cents"] = _normalize_int(usage.get("reserved_cost_cents")) + reserved_cost_cents
        usage["updated_at"] = _now_iso()
        return {"allowed": True}

    def _finalize_provider_budget(
        self,
        *,
        state: dict,
        reservation_id: str,
        final_cost_cents: int | None,
        status: str,
        metrics,
    ) -> list[dict]:
        finalized = []
        for usage in (state.get("provider_budget_usage") or {}).values():
            if not isinstance(usage, dict):
                continue
            reservations = usage.get("reservations")
            if not isinstance(reservations, dict):
                continue
            reservation = reservations.pop(reservation_id, None)
            if not isinstance(reservation, dict):
                continue
            reserved_cost_cents = _normalize_int(reservation.get("reserved_cost_cents"))
            usage["reserved_cost_cents"] = max(_normalize_int(usage.get("reserved_cost_cents")) - reserved_cost_cents, 0)
            applied_cost = final_cost_cents if final_cost_cents is not None else reserved_cost_cents
            if status == "completed":
                usage["used_cost_usd_exact"] = round(
                    _normalize_float(usage.get("used_cost_usd_exact"))
                    + self._final_cost_usd_exact(metrics=metrics, fallback_cost_cents=applied_cost),
                    10,
                )
                usage["used_cost_cents"] = max(math.ceil(_normalize_float(usage.get("used_cost_usd_exact")) * 100.0), 0)
            usage["updated_at"] = _now_iso()
            finalized.append({"provider_id": usage.get("provider_id"), "final_cost_cents": applied_cost})
        return finalized

    def _final_cost_usd_exact(self, *, metrics, fallback_cost_cents: int) -> float:
        estimated_cost = getattr(metrics, "estimated_cost", None) if metrics is not None else None
        if isinstance(estimated_cost, (int, float)) and float(estimated_cost) >= 0:
            return float(estimated_cost)
        return max(int(fallback_cost_cents), 0) / 100.0

    def _provider_budget_used_cost_usd_exact(self, *, usage: dict, runtime_spend_by_provider: dict[str, float]) -> float:
        provider_id = _normalize_string(usage.get("provider_id"))
        fallback = runtime_spend_by_provider.get(provider_id)
        if isinstance(fallback, (int, float)) and float(fallback) >= 0:
            return round(float(fallback), 10)
        exact = usage.get("used_cost_usd_exact")
        if isinstance(exact, (int, float)) and float(exact) > 0:
            return round(float(exact), 10)
        return round(_normalize_int(usage.get("used_cost_cents")) / 100.0, 10)

    def _provider_budget_used_cost_cents(self, *, usage: dict, runtime_spend_by_provider: dict[str, float]) -> int:
        used_cost_usd_exact = self._provider_budget_used_cost_usd_exact(
            usage=usage,
            runtime_spend_by_provider=runtime_spend_by_provider,
        )
        if used_cost_usd_exact > 0:
            return max(math.ceil(used_cost_usd_exact * 100.0), 0)
        return max(_normalize_int(usage.get("used_cost_cents")), 0)

    def _provider_runtime_exact_spend_by_provider(self) -> dict[str, float]:
        runtime = self._provider_runtime_manager
        if runtime is None:
            return {}
        spend_by_provider: dict[str, float] = {}
        metrics_collector = getattr(runtime, "_metrics", None)
        metrics_snapshot = metrics_collector.snapshot() if metrics_collector is not None and hasattr(metrics_collector, "snapshot") else {}
        providers = metrics_snapshot.get("providers") if isinstance(metrics_snapshot, dict) else {}
        registry = getattr(runtime, "_registry", None)
        pricing_service = getattr(runtime, "_pricing_catalog_service", None)

        if isinstance(providers, dict):
            for provider_id, provider_payload in providers.items():
                if not isinstance(provider_payload, dict):
                    continue
                models = provider_payload.get("models")
                if not isinstance(models, dict):
                    continue
                total_spend = 0.0
                for model_id, model_metrics in models.items():
                    if not isinstance(model_metrics, dict):
                        continue
                    prompt_tokens = _normalize_int(model_metrics.get("prompt_tokens"), default=0)
                    completion_tokens = _normalize_int(model_metrics.get("completion_tokens"), default=0)
                    input_rate = None
                    output_rate = None
                    if registry is not None and hasattr(registry, "get_model"):
                        registry_model = registry.get_model(provider_id=str(provider_id), model_id=str(model_id))
                        if registry_model is not None:
                            input_rate = getattr(registry_model, "pricing_input", None)
                            output_rate = getattr(registry_model, "pricing_output", None)
                    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
                        pricing = get_openai_model_pricing(str(model_id), pricing_service=pricing_service) if str(provider_id).lower() == "openai" else None
                        if isinstance(pricing, dict):
                            input_rate = pricing.get("input_per_1m_tokens")
                            output_rate = pricing.get("output_per_1m_tokens")
                    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
                        continue
                    total_spend += ((prompt_tokens * float(input_rate)) + (completion_tokens * float(output_rate))) / 1_000_000.0
                spend_by_provider[_normalize_string(provider_id)] = round(total_spend, 10)

        if spend_by_provider:
            return spend_by_provider

        if hasattr(runtime, "intelligence_payload"):
            payload = runtime.intelligence_payload()
            providers_payload = payload.get("providers") if isinstance(payload, dict) else None
            if isinstance(providers_payload, list):
                for provider in providers_payload:
                    if not isinstance(provider, dict):
                        continue
                    provider_id = _normalize_string(provider.get("provider_id"))
                    if not provider_id:
                        continue
                    total_spend = 0.0
                    for model in provider.get("models") or []:
                        if not isinstance(model, dict):
                            continue
                        usage_metrics = model.get("usage_metrics") if isinstance(model.get("usage_metrics"), dict) else {}
                        prompt_tokens = _normalize_int(usage_metrics.get("prompt_tokens"), default=0)
                        completion_tokens = _normalize_int(usage_metrics.get("completion_tokens"), default=0)
                        input_rate = model.get("pricing_input")
                        output_rate = model.get("pricing_output")
                        if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
                            continue
                        total_spend += ((prompt_tokens * float(input_rate)) + (completion_tokens * float(output_rate))) / 1_000_000.0
                    spend_by_provider[provider_id] = round(total_spend, 10)
        return spend_by_provider

    def _release_provider_budget(self, *, state: dict, reservation_id: str, reason: str) -> list[dict]:
        released = []
        for usage in (state.get("provider_budget_usage") or {}).values():
            if not isinstance(usage, dict):
                continue
            reservations = usage.get("reservations")
            if not isinstance(reservations, dict):
                continue
            reservation = reservations.pop(reservation_id, None)
            if not isinstance(reservation, dict):
                continue
            reserved_cost_cents = _normalize_int(reservation.get("reserved_cost_cents"))
            usage["reserved_cost_cents"] = max(_normalize_int(usage.get("reserved_cost_cents")) - reserved_cost_cents, 0)
            usage["updated_at"] = _now_iso()
            released.append({"provider_id": usage.get("provider_id"), "released_cost_cents": reserved_cost_cents, "reason": reason})
        return released

    def _ensure_usage_entry(self, *, state: dict, grant: dict) -> dict:
        grant_id = _normalize_string(grant.get("grant_id"))
        usage = state.setdefault("grant_usage", {}).get(grant_id)
        if not isinstance(usage, dict):
            usage = {
                "grant_id": grant_id,
                "period_start": grant.get("period_start"),
                "period_end": grant.get("period_end"),
                "used_cost_cents": 0,
                "used_requests": 0,
                "used_tokens": 0,
                "reserved_cost_cents": 0,
                "reservations": {},
                "updated_at": _now_iso(),
            }
            state.setdefault("grant_usage", {})[grant_id] = usage
            return usage
        if usage.get("period_start") != grant.get("period_start") or usage.get("period_end") != grant.get("period_end"):
            usage.update(
                {
                    "period_start": grant.get("period_start"),
                    "period_end": grant.get("period_end"),
                    "used_cost_cents": 0,
                    "used_requests": 0,
                    "used_tokens": 0,
                    "reserved_cost_cents": 0,
                    "reservations": {},
                    "updated_at": _now_iso(),
                }
            )
        return usage

    def _queue_usage_summary(self, *, state: dict, grant_id: str, usage: dict) -> None:
        state.setdefault("pending_usage_summaries", []).append(
            {
                "grant_id": grant_id,
                "service": "ai.inference",
                "period_start": usage.get("period_start"),
                "period_end": usage.get("period_end"),
                "used_requests": _normalize_int(usage.get("used_requests")),
                "used_tokens": _normalize_int(usage.get("used_tokens")),
                "used_cost_cents": _normalize_int(usage.get("used_cost_cents")),
                "queued_at": _now_iso(),
            }
        )

    def _record_denial(self, *, task_id: str, request, reason: str, provider_id: str | None) -> None:
        state = self._load_state()
        denials = state.setdefault("recent_denials", [])
        denials.append(
            {
                "task_id": _normalize_string(task_id),
                "reason": _normalize_string(reason),
                "provider_id": _normalize_string(provider_id) or None,
                "requested_by": _normalize_string(getattr(request, "requested_by", None)) or None,
                "customer_id": _normalize_string(getattr(request, "customer_id", None)) or None,
                "recorded_at": _now_iso(),
            }
        )
        state["recent_denials"] = denials[-50:]
        self._save_state(state)
