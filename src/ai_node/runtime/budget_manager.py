import math
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


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
        grants = list(policy.get("grants") or []) if isinstance(policy, dict) else []
        active_reservations = 0
        for usage in grant_usage.values():
            reservations = usage.get("reservations") if isinstance(usage, dict) else {}
            if isinstance(reservations, dict):
                active_reservations += len(reservations)
        return {
            "configured": isinstance(policy, dict),
            "policy_status": str((policy or {}).get("status") or "unconfigured"),
            "budget_policy_version": (policy or {}).get("budget_policy_version") if isinstance(policy, dict) else None,
            "governance_version": (policy or {}).get("governance_version") if isinstance(policy, dict) else None,
            "grant_count": len(grants),
            "active_reservations": active_reservations,
            "recent_denials": list(state.get("recent_denials") or [])[-20:],
            "grants": [self._grant_snapshot(grant=grant, usage=grant_usage.get(str(grant.get("grant_id") or "").strip())) for grant in grants],
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
        policy = self.cache_policy_from_governance(governance_bundle=governance_bundle) or self._load_state().get("budget_policy")
        if not isinstance(policy, dict):
            return BudgetReservationResult(allowed=True, reason=None, policy_status="unconfigured")
        policy_status = _normalize_string(policy.get("status")).lower() or "unconfigured"
        if policy_status != "active":
            return BudgetReservationResult(allowed=True, reason=None, policy_status=policy_status)

        applicable_grants = self._applicable_grants(policy=policy, request=request, provider_id=provider_id)
        if not applicable_grants:
            self._record_denial(task_id=task_id, request=request, reason="missing_budget_grant", provider_id=provider_id)
            return BudgetReservationResult(allowed=False, reason="missing_budget_grant", policy_status=policy_status)

        reservation_id = f"budget-reservation:{_normalize_string(task_id)}"
        state = self._load_state()
        reservation_cents = self._reservation_cost_cents(request=request, provider_id=provider_id, model_id=model_id)
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
        if finalized:
            self._save_state(state)
        return {"finalized": finalized}

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
        if released:
            self._save_state(state)
        return {"released": released}

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
            return False
        applicable = self._applicable_grants(policy=policy, request=request, provider_id=provider_id)
        return any(_normalize_int((grant.get("limits") or {}).get("max_cost_cents"), default=0) > 0 for grant in applicable)

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
            scope_kind = _normalize_string(grant.get("scope_kind")).lower()
            subject_id = _normalize_string(grant.get("subject_id"))
            if scope_kind == "node":
                applicable.append(grant)
            elif scope_kind == "customer" and customer_id and subject_id == customer_id:
                applicable.append(grant)
            elif scope_kind == "provider" and provider_key and subject_id == provider_key:
                applicable.append(grant)
        return applicable

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
