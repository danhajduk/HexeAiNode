from copy import deepcopy

from ai_node.prompts.registration import (
    apply_probation_transition,
    create_prompt_service_registration,
    find_prompt_entry,
    record_prompt_review,
    transition_prompt_lifecycle,
    normalize_prompt_lifecycle_state,
    update_prompt_service_definition,
)


class PromptRegistry:
    def __init__(self, *, store, logger) -> None:
        self._store = store
        self._logger = logger
        self._state = self._load_state()

    def _load_state(self) -> dict:
        from ai_node.persistence.prompt_service_state_store import normalize_prompt_service_state

        if self._store is None or not hasattr(self._store, "load_or_create"):
            return normalize_prompt_service_state({"schema_version": "2.0", "prompt_services": [], "updated_at": None})
        loaded = self._store.load_or_create()
        normalized = normalize_prompt_service_state(loaded)
        if hasattr(self._store, "save"):
            self._store.save(normalized)
        return normalized

    def snapshot(self) -> dict:
        return deepcopy(self._state)

    def save(self) -> dict:
        from ai_node.persistence.prompt_service_state_store import normalize_prompt_service_state

        self._state = normalize_prompt_service_state(self._state)
        if self._store is not None and hasattr(self._store, "save"):
            self._store.save(self._state)
        return self.snapshot()

    def list_prompts(self) -> list[dict]:
        return list(self.snapshot().get("prompt_services") or [])

    def get_prompt(self, *, prompt_id: str) -> dict:
        entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if not isinstance(entry, dict):
            raise ValueError("prompt_id is not registered")
        return deepcopy(entry)

    def create_prompt(
        self,
        *,
        prompt_id: str,
        service_id: str,
        task_family: str,
        metadata: dict | None = None,
        prompt_name: str | None = None,
        owner_service: str | None = None,
        owner_client_id: str | None = None,
        privacy_class: str = "internal",
        access_scope: str = "service",
        allowed_services: list[str] | None = None,
        allowed_clients: list[str] | None = None,
        allowed_customers: list[str] | None = None,
        execution_policy: dict | None = None,
        provider_preferences: dict | None = None,
        constraints: dict | None = None,
        definition: dict | None = None,
        version: str | None = None,
        status: str = "active",
    ) -> dict:
        existing_entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if isinstance(existing_entry, dict):
            existing_state = normalize_prompt_lifecycle_state(existing_entry.get("status") or "active")
            if existing_state != "retired":
                raise ValueError("duplicate_prompt_id")
        registration = create_prompt_service_registration(
            prompt_id=prompt_id,
            service_id=service_id,
            task_family=task_family,
            metadata=metadata,
            prompt_name=prompt_name,
            owner_service=owner_service,
            owner_client_id=owner_client_id,
            privacy_class=privacy_class,
            access_scope=access_scope,
            allowed_services=allowed_services,
            allowed_clients=allowed_clients,
            allowed_customers=allowed_customers,
            execution_policy=execution_policy,
            provider_preferences=provider_preferences,
            constraints=constraints,
            definition=definition,
            version=version,
            status=status,
        )
        services = self._state.setdefault("prompt_services", [])
        if isinstance(existing_entry, dict):
            for index, entry in enumerate(services):
                if entry is existing_entry:
                    services[index] = registration
                    break
            else:
                services.append(registration)
        else:
            services.append(registration)
        self._state["updated_at"] = registration["updated_at"]
        return self.save()

    def update_prompt(
        self,
        *,
        prompt_id: str,
        prompt_name: str | None = None,
        owner_service: str | None = None,
        owner_client_id: str | None = None,
        task_family: str | None = None,
        privacy_class: str | None = None,
        access_scope: str | None = None,
        allowed_services: list[str] | None = None,
        allowed_clients: list[str] | None = None,
        allowed_customers: list[str] | None = None,
        execution_policy: dict | None = None,
        provider_preferences: dict | None = None,
        constraints: dict | None = None,
        metadata: dict | None = None,
        definition: dict | None = None,
        version: str | None = None,
    ) -> dict:
        entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if not isinstance(entry, dict):
            raise ValueError("prompt_id is not registered")
        update_prompt_service_definition(
            entry,
            prompt_name=prompt_name,
            owner_service=owner_service,
            owner_client_id=owner_client_id,
            task_family=task_family,
            privacy_class=privacy_class,
            access_scope=access_scope,
            allowed_services=allowed_services,
            allowed_clients=allowed_clients,
            allowed_customers=allowed_customers,
            execution_policy=execution_policy,
            provider_preferences=provider_preferences,
            constraints=constraints,
            metadata=metadata,
            definition=definition,
            version=version,
        )
        self._state["updated_at"] = entry["updated_at"]
        return self.save()

    def review_prompt(
        self,
        *,
        prompt_id: str,
        reviewed_by: str | None = None,
        review_reason: str | None = None,
        state: str | None = "active",
    ) -> dict:
        entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if not isinstance(entry, dict):
            raise ValueError("prompt_id is not registered")
        record_prompt_review(entry=entry, reviewed_by=reviewed_by, review_reason=review_reason, state=state)
        self._state["updated_at"] = entry["updated_at"]
        return self.save()

    def migrate_all_to_review_due(self, *, reason: str = "policy_migration_review_due") -> dict:
        prompts = self._state.get("prompt_services")
        if not isinstance(prompts, list):
            self._state["prompt_services"] = []
            prompts = self._state["prompt_services"]
        changed = 0
        latest_updated_at = None
        for entry in prompts:
            if not isinstance(entry, dict):
                continue
            current_state = normalize_prompt_lifecycle_state(entry.get("status") or "active")
            if current_state in {"retired", "expired"}:
                continue
            if current_state != "review_due":
                transition_prompt_lifecycle(entry=entry, state="review_due", reason=reason)
                changed += 1
            latest_updated_at = entry.get("updated_at") or latest_updated_at
        if latest_updated_at is not None:
            self._state["updated_at"] = latest_updated_at
        payload = self.save()
        payload["migration"] = {"changed": changed, "status": "ok", "target_state": "review_due"}
        return payload

    def transition_prompt(self, *, prompt_id: str, state: str, reason: str | None = None) -> dict:
        entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if not isinstance(entry, dict):
            raise ValueError("prompt_id is not registered")
        transition_prompt_lifecycle(entry=entry, state=state, reason=reason)
        self._state["updated_at"] = entry["updated_at"]
        return self.save()

    def update_probation(self, *, prompt_id: str, action: str, reason: str | None = None) -> dict:
        entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if not isinstance(entry, dict):
            raise ValueError("prompt_id is not registered")
        apply_probation_transition(entry=entry, action=action, reason=reason)
        self._state["updated_at"] = entry["updated_at"]
        return self.save()

    def record_authorization(self, *, prompt_id: str, allowed: bool, reason: str, used_at: str) -> None:
        entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if not isinstance(entry, dict):
            return
        usage = entry.setdefault("usage", {})
        if allowed:
            usage["last_used_at"] = used_at
        else:
            usage["denial_count"] = max(int(usage.get("denial_count") or 0), 0) + 1
            usage["last_denial_reason"] = reason
            usage["last_denied_at"] = used_at
        entry["updated_at"] = used_at
        self._state["updated_at"] = used_at
        self.save()

    def record_execution(self, *, prompt_id: str, status: str, recorded_at: str, error_code: str | None = None) -> None:
        entry = find_prompt_entry(prompt_services_state=self._state, prompt_id=prompt_id)
        if not isinstance(entry, dict):
            return
        usage = entry.setdefault("usage", {})
        usage["execution_count"] = max(int(usage.get("execution_count") or 0), 0) + 1
        usage["last_used_at"] = recorded_at
        usage["last_execution_status"] = status
        if status == "completed":
            usage["success_count"] = max(int(usage.get("success_count") or 0), 0) + 1
        else:
            usage["failure_count"] = max(int(usage.get("failure_count") or 0), 0) + 1
            usage["last_failure_reason"] = error_code
            usage["last_failure_at"] = recorded_at
        entry["updated_at"] = recorded_at
        self._state["updated_at"] = recorded_at
        self.save()
