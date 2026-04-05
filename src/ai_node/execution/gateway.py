from dataclasses import dataclass

from ai_node.prompts.registration import find_prompt_entry, find_prompt_version, normalize_prompt_lifecycle_state


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


@dataclass(frozen=True)
class ExecutionAuthorizationResult:
    allowed: bool
    reason: str
    prompt_id: str
    task_family: str
    prompt_version: str | None = None
    prompt_state: str | None = None
    provider_preferences: dict | None = None
    prompt_constraints: dict | None = None
    execution_policy: dict | None = None
    prompt_definition: dict | None = None


class ExecutionGateway:
    @staticmethod
    def _is_caller_allowed(
        *,
        matched: dict,
        requested_by: str | None,
        service_id: str | None,
        customer_id: str | None,
    ) -> bool:
        access_scope = _normalize_string(matched.get("access_scope") or "service").lower() or "service"
        owner_service = _normalize_string(matched.get("owner_service") or matched.get("service_id"))
        owner_client_id = _normalize_string(matched.get("owner_client_id"))
        caller_client = _normalize_string(requested_by)
        caller_service = _normalize_string(service_id) or caller_client
        caller_customer = _normalize_string(customer_id)
        allowed_services = set(_normalize_string_list(matched.get("allowed_services")))
        allowed_clients = set(_normalize_string_list(matched.get("allowed_clients")))
        allowed_customers = set(_normalize_string_list(matched.get("allowed_customers")))

        owner_allowed = bool(
            (owner_client_id and caller_client == owner_client_id)
            or (owner_service and caller_service == owner_service)
        )
        if access_scope == "public":
            return True
        if access_scope == "private":
            return owner_allowed
        if access_scope == "service":
            if not owner_service:
                return True
            return bool(owner_service and caller_service == owner_service)
        if access_scope == "shared":
            return bool(
                owner_allowed
                or (caller_service and caller_service in allowed_services)
                or (caller_client and caller_client in allowed_clients)
                or (caller_customer and caller_customer in allowed_customers)
            )
        return owner_allowed

    def authorize(
        self,
        *,
        prompt_id: str,
        task_family: str,
        prompt_services_state: dict | None,
        prompt_version: str | None = None,
        requested_by: str | None = None,
        service_id: str | None = None,
        customer_id: str | None = None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        inputs: dict | None = None,
    ) -> ExecutionAuthorizationResult:
        prompt = _normalize_string(prompt_id)
        task = _normalize_string(task_family)
        if not prompt:
            return ExecutionAuthorizationResult(False, "missing_prompt_id", prompt, task)
        if not task:
            return ExecutionAuthorizationResult(False, "missing_task_family", prompt, task)

        matched = find_prompt_entry(prompt_services_state=prompt_services_state, prompt_id=prompt)
        if not isinstance(matched, dict):
            return ExecutionAuthorizationResult(False, "prompt_not_registered", prompt, task)

        if _normalize_string(matched.get("task_family")) != task:
            return ExecutionAuthorizationResult(False, "prompt_task_family_mismatch", prompt, task)

        version_entry = find_prompt_version(matched, prompt_version)
        if not isinstance(version_entry, dict):
            return ExecutionAuthorizationResult(False, "invalid_prompt_version", prompt, task)

        prompt_state = normalize_prompt_lifecycle_state(matched.get("status") or "active")
        if prompt_state == "probation":
            return ExecutionAuthorizationResult(False, "prompt_in_probation", prompt, task, prompt_state=prompt_state)
        if prompt_state not in {"active", "review_due"}:
            return ExecutionAuthorizationResult(False, "prompt_state_invalid", prompt, task, prompt_state=prompt_state)

        if not self._is_caller_allowed(
            matched=matched,
            requested_by=requested_by,
            service_id=service_id,
            customer_id=customer_id,
        ):
            return ExecutionAuthorizationResult(False, "prompt_access_denied", prompt, task, prompt_state=prompt_state)

        execution_policy = matched.get("execution_policy") if isinstance(matched.get("execution_policy"), dict) else {}
        if execution_policy.get("allow_direct_execution") is False:
            return ExecutionAuthorizationResult(False, "prompt_state_invalid", prompt, task, prompt_state=prompt_state)

        provider_preferences = matched.get("provider_preferences") if isinstance(matched.get("provider_preferences"), dict) else {}
        preferred_providers = [str(item).strip().lower() for item in list(provider_preferences.get("preferred_providers") or []) if str(item).strip()]
        preferred_models = [str(item).strip().lower() for item in list(provider_preferences.get("preferred_models") or []) if str(item).strip()]
        requested_provider_value = _normalize_string(requested_provider).lower()
        if requested_provider_value and preferred_providers and requested_provider_value not in set(preferred_providers):
            return ExecutionAuthorizationResult(False, "prompt_provider_not_allowed", prompt, task, prompt_state=prompt_state)

        prompt_constraints = matched.get("constraints") if isinstance(matched.get("constraints"), dict) else {}
        allowed_model_overrides = [
            str(item).strip().lower()
            for item in list(prompt_constraints.get("allowed_model_overrides") or [])
            if str(item).strip()
        ]
        requested_model_value = _normalize_string(requested_model).lower()
        if requested_model_value and allowed_model_overrides and requested_model_value not in set(allowed_model_overrides + preferred_models):
            return ExecutionAuthorizationResult(False, "prompt_model_override_not_allowed", prompt, task, prompt_state=prompt_state)

        inputs_payload = inputs if isinstance(inputs, dict) else {}
        structured_output_required = bool(prompt_constraints.get("structured_output_required"))
        if structured_output_required:
            has_schema = isinstance(inputs_payload.get("structured_output_schema"), dict) or isinstance(inputs_payload.get("json_schema"), dict)
            if not has_schema:
                return ExecutionAuthorizationResult(False, "prompt_structured_output_required", prompt, task, prompt_state=prompt_state)

        return ExecutionAuthorizationResult(
            allowed=True,
            reason="authorized",
            prompt_id=prompt,
            task_family=task,
            prompt_version=str(version_entry.get("version") or "").strip() or None,
            prompt_state=prompt_state,
            provider_preferences=provider_preferences,
            prompt_constraints=prompt_constraints,
            execution_policy=execution_policy,
            prompt_definition=version_entry.get("definition") if isinstance(version_entry.get("definition"), dict) else {},
        )
