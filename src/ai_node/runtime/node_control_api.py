import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_node.capabilities.task_families import CANONICAL_TASK_FAMILIES
from ai_node.config.bootstrap_config import create_bootstrap_config
from ai_node.execution.gateway import ExecutionGateway
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.config.provider_credentials_config import summarize_provider_credentials
from ai_node.providers.openai_model_catalog import select_representative_openai_model_ids
from ai_node.prompts.registration import apply_probation_transition, create_prompt_service_registration
from ai_node.config.task_capability_selection_config import create_task_capability_selection_config
from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.provider_resolver import ProviderResolver
from ai_node.runtime.service_manager import NullServiceManager
from ai_node.runtime.capability_resolver import load_task_graph
from ai_node.runtime.execution_telemetry import ExecutionTelemetryPublisher
from ai_node.runtime.task_execution_service import TaskExecutionService


class CapabilityDeclarationPrerequisiteError(ValueError):
    def __init__(self, *, payload: dict) -> None:
        self.payload = payload
        super().__init__(str(payload.get("message") or "capability declaration prerequisites are not satisfied"))


class NodeControlState:
    def __init__(
        self,
        *,
        lifecycle: NodeLifecycle,
        config_path: str,
        logger,
        bootstrap_runner=None,
        onboarding_runtime=None,
        capability_runner=None,
        node_identity_store=None,
        provider_selection_store=None,
        provider_credentials_store=None,
        task_capability_selection_store=None,
        trust_state_store=None,
        governance_state_store=None,
        prompt_service_state_store=None,
        execution_gateway=None,
        provider_runtime_manager=None,
        service_manager=None,
        task_execution_service=None,
        provider_refresh_interval_seconds: int = 900,
        startup_mode: str = "bootstrap_onboarding",
        trusted_runtime_context: dict | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._config_path = Path(config_path)
        self._logger = logger
        self._bootstrap_runner = bootstrap_runner
        self._onboarding_runtime = onboarding_runtime
        self._capability_runner = capability_runner
        self._node_identity_store = node_identity_store
        self._provider_selection_store = provider_selection_store
        self._provider_credentials_store = provider_credentials_store
        self._task_capability_selection_store = task_capability_selection_store
        self._trust_state_store = trust_state_store
        self._governance_state_store = governance_state_store
        self._prompt_service_state_store = prompt_service_state_store
        self._execution_gateway = execution_gateway or ExecutionGateway()
        self._provider_runtime_manager = provider_runtime_manager
        self._service_manager = service_manager or NullServiceManager()
        self._task_execution_service = task_execution_service
        self._provider_refresh_interval_seconds = max(int(provider_refresh_interval_seconds), 60)
        self._provider_refresh_task: asyncio.Task | None = None
        self._startup_mode = startup_mode
        self._trusted_runtime_context = trusted_runtime_context or {}
        self._phase2_diag = Phase2DiagnosticsLogger(logger)
        self._bootstrap_config = None
        self._provider_selection_config = None
        self._provider_credentials_summary = None
        self._task_capability_selection_config = None
        self._prompt_service_state = None
        self._node_id = None
        self._identity_state = "unknown"
        self._load_identity()
        self._load_provider_selection_config()
        self._load_provider_credentials_summary()
        self._load_task_capability_selection_config()
        self._load_prompt_service_state()
        self._load_existing_config()

    @staticmethod
    def _is_non_empty_string(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def _is_provider_selection_valid(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return False
        supported = providers.get("supported")
        if not isinstance(supported, dict):
            return False
        supported_any = bool(
            (supported.get("cloud") or [])
            or (supported.get("local") or [])
            or (supported.get("future") or [])
        )
        return supported_any

    def _is_task_capability_selection_valid(self, payload: dict | None) -> bool:
        if not isinstance(payload, dict):
            return False
        selected = payload.get("selected_task_families")
        if not isinstance(selected, list) or not selected:
            return False
        canonical = set(CANONICAL_TASK_FAMILIES)
        return all(isinstance(item, str) and item.strip() in canonical for item in selected)

    def _build_capability_setup_contract(self) -> dict:
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        trusted_context = self._trusted_runtime_context if isinstance(self._trusted_runtime_context, dict) else {}
        provider_config = self._provider_selection_config if isinstance(self._provider_selection_config, dict) else None
        task_capability_config = (
            self._task_capability_selection_config if isinstance(self._task_capability_selection_config, dict) else None
        )
        enabled_providers = []
        supported_providers = {"cloud": [], "local": [], "future": []}
        selected_task_families = []
        if isinstance(provider_config, dict):
            providers = provider_config.get("providers") if isinstance(provider_config.get("providers"), dict) else {}
            enabled_providers = list(providers.get("enabled") or [])
            supported = providers.get("supported") if isinstance(providers.get("supported"), dict) else {}
            supported_providers = {
                "cloud": list(supported.get("cloud") or []),
                "local": list(supported.get("local") or []),
                "future": list(supported.get("future") or []),
            }
        if isinstance(task_capability_config, dict):
            selected_task_families = list(task_capability_config.get("selected_task_families") or [])

        readiness_flags = {
            "trust_state_valid": isinstance(trust_state, dict),
            "node_identity_valid": self._identity_state == "valid" and self._is_non_empty_string(self._node_id),
            "provider_selection_valid": self._is_provider_selection_valid(provider_config),
            "task_capability_selection_valid": self._is_task_capability_selection_valid(task_capability_config),
            "core_runtime_context_valid": (
                self._is_non_empty_string(trusted_context.get("paired_core_id"))
                and self._is_non_empty_string(trusted_context.get("core_api_endpoint"))
                and self._is_non_empty_string(trusted_context.get("operational_mqtt_host"))
                and trusted_context.get("operational_mqtt_port") is not None
            ),
        }
        openai_ready, openai_blockers, openai_flags = self._openai_declaration_readiness(provider_config=provider_config)
        readiness_flags.update(openai_flags)
        blocking_reasons: list[str] = []
        if not readiness_flags["trust_state_valid"]:
            blocking_reasons.append("missing_or_invalid_trust_state")
        if not readiness_flags["node_identity_valid"]:
            blocking_reasons.append("missing_or_invalid_node_identity")
        if not readiness_flags["provider_selection_valid"]:
            blocking_reasons.append("missing_or_invalid_provider_selection")
        if not readiness_flags["task_capability_selection_valid"]:
            blocking_reasons.append("missing_or_invalid_task_capability_selection")
        if not readiness_flags["core_runtime_context_valid"]:
            blocking_reasons.append("missing_or_invalid_trusted_runtime_context")
        blocking_reasons.extend(openai_blockers)

        lifecycle_state = self._lifecycle.get_state()
        declaration_allowed = (
            lifecycle_state in {
                NodeLifecycleState.CAPABILITY_SETUP_PENDING,
                NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
            }
            and not blocking_reasons
        )
        return {
            "active": lifecycle_state == NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            "readiness_flags": readiness_flags,
            "provider_selection": {
                "configured": provider_config is not None,
                "enabled_count": len(enabled_providers),
                "enabled": enabled_providers,
                "supported": supported_providers,
            },
            "task_capability_selection": {
                "configured": task_capability_config is not None,
                "selected_count": len(selected_task_families),
                "selected": selected_task_families,
                "available": list(CANONICAL_TASK_FAMILIES),
            },
            "blocking_reasons": blocking_reasons,
            "declaration_allowed": declaration_allowed,
            "disallowed_transitions": [
                NodeLifecycleState.UNCONFIGURED.value,
                NodeLifecycleState.BOOTSTRAP_CONNECTING.value,
                NodeLifecycleState.BOOTSTRAP_CONNECTED.value,
                NodeLifecycleState.CORE_DISCOVERED.value,
                NodeLifecycleState.REGISTRATION_PENDING.value,
                NodeLifecycleState.PENDING_APPROVAL.value,
                NodeLifecycleState.TRUSTED.value,
            ],
        }

    def _openai_declaration_readiness(self, *, provider_config: dict | None) -> tuple[bool, list[str], dict]:
        providers = provider_config.get("providers") if isinstance(provider_config, dict) else None
        enabled_providers = providers.get("enabled") if isinstance(providers, dict) else []
        enabled_provider_set = {str(item or "").strip().lower() for item in enabled_providers if str(item or "").strip()}
        if "openai" not in enabled_provider_set:
            return True, [], {
                "openai_enabled_models_ready": True,
                "openai_classification_ready": True,
                "openai_pricing_ready": True,
            }

        blockers: list[str] = []

        enabled_payload = self.openai_enabled_models_payload()
        enabled_models_raw = enabled_payload.get("models") if isinstance(enabled_payload, dict) else []
        enabled_model_ids = sorted(
            {
                str(item.get("model_id") or "").strip().lower()
                for item in (enabled_models_raw if isinstance(enabled_models_raw, list) else [])
                if isinstance(item, dict) and bool(item.get("enabled")) and str(item.get("model_id") or "").strip()
            }
        )
        if not enabled_model_ids:
            blockers.append("openai_enabled_models_required_before_declare")

        capability_payload = self.openai_provider_model_capabilities_payload()
        classified_entries = capability_payload.get("entries") if isinstance(capability_payload, dict) else []
        classified_ids = {
            str(item.get("model_id") or "").strip().lower()
            for item in (classified_entries if isinstance(classified_entries, list) else [])
            if isinstance(item, dict) and str(item.get("model_id") or "").strip()
        }
        missing_classification = sorted(set(enabled_model_ids) - classified_ids)

        pricing_diag = self.openai_pricing_diagnostics_payload()
        pricing_state = str(pricing_diag.get("refresh_state") or "").strip().lower() if isinstance(pricing_diag, dict) else ""
        pricing_state_ready = pricing_state in {"ok", "manual", "failed_preserved"}
        usable_model_ids: list[str] = []
        blocked_models = []
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "openai_usable_models_payload"):
            usable_payload = self._provider_runtime_manager.openai_usable_models_payload()
            usable_model_ids = list(usable_payload.get("usable_model_ids") or [])
            blocked_models = list(usable_payload.get("blocked_models") or [])
        usable_model_set = {str(item or "").strip().lower() for item in usable_model_ids if str(item or "").strip()}
        missing_pricing = sorted(
            item.get("model_id")
            for item in blocked_models
            if isinstance(item, dict)
            and "not_available" in list(item.get("blockers") or [])
            and str(item.get("model_id") or "").strip()
        )
        if enabled_model_ids and not usable_model_set:
            blockers.append("openai_usable_models_required_before_declare")

        ready = not blockers
        return ready, blockers, {
            "openai_enabled_models_ready": bool(enabled_model_ids),
            "openai_classification_ready": not missing_classification and bool(enabled_model_ids),
            "openai_pricing_ready": pricing_state_ready and not missing_pricing and bool(enabled_model_ids),
            "openai_usable_models_ready": bool(usable_model_set),
        }

    def _load_identity(self) -> None:
        if self._node_identity_store is None or not hasattr(self._node_identity_store, "load"):
            self._identity_state = "unknown"
            self._node_id = None
            return
        payload = self._node_identity_store.load()
        if payload is None:
            self._identity_state = "missing"
            self._node_id = None
            return
        self._identity_state = "valid"
        self._node_id = payload.get("node_id")

    def _load_existing_config(self) -> None:
        if not self._config_path.exists():
            return
        if self._lifecycle.get_state() != NodeLifecycleState.UNCONFIGURED:
            if hasattr(self._logger, "info"):
                self._logger.info(
                    "[node-control] skipping persisted bootstrap config load due to startup state=%s",
                    self._lifecycle.get_state().value,
                )
            return
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
            self._bootstrap_config = create_bootstrap_config(payload)
            self._lifecycle.transition_to(
                NodeLifecycleState.BOOTSTRAP_CONNECTING,
                {"source": "persisted_bootstrap_config"},
            )
            self._start_bootstrap_runner_if_available()
        except Exception:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[node-control] invalid persisted bootstrap config ignored: %s", self._config_path
                )

    def _load_provider_selection_config(self) -> None:
        if self._provider_selection_store is None or not hasattr(self._provider_selection_store, "load_or_create"):
            self._provider_selection_config = None
            return
        self._provider_selection_config = self._provider_selection_store.load_or_create(openai_enabled=False)

    def _load_task_capability_selection_config(self) -> None:
        if self._task_capability_selection_store is None or not hasattr(
            self._task_capability_selection_store, "load_or_create"
        ):
            self._task_capability_selection_config = None
            return
        self._task_capability_selection_config = self._task_capability_selection_store.load_or_create()

    def _load_provider_credentials_summary(self) -> None:
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "load_or_create"):
            self._provider_credentials_summary = None
            return
        self._provider_credentials_summary = summarize_provider_credentials(self._provider_credentials_store.load_or_create())

    def _load_prompt_service_state(self) -> None:
        if self._prompt_service_state_store is None or not hasattr(self._prompt_service_state_store, "load_or_create"):
            self._prompt_service_state = None
            return
        self._prompt_service_state = self._prompt_service_state_store.load_or_create()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def status_payload(self) -> dict:
        state = self._lifecycle.get_state()
        runtime_context = {}
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "get_status_context"):
            runtime_context = self._onboarding_runtime.get_status_context()
        capability_context = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        capability_setup_contract = self._build_capability_setup_contract()
        if state == NodeLifecycleState.CAPABILITY_SETUP_PENDING and hasattr(self._logger, "info"):
            self._logger.info(
                "[capability-setup-readiness] %s",
                {
                    "readiness_flags": capability_setup_contract.get("readiness_flags"),
                    "blocking_reasons": capability_setup_contract.get("blocking_reasons"),
                    "declaration_allowed": capability_setup_contract.get("declaration_allowed"),
                },
            )
        return {
            "status": state.value,
            "bootstrap_configured": self._bootstrap_config is not None,
            "pending_approval_url": runtime_context.get("pending_approval_url"),
            "pending_session_id": runtime_context.get("pending_session_id"),
            "pending_node_nonce": runtime_context.get("pending_node_nonce"),
            "node_id": self._node_id,
            "identity_state": self._identity_state,
            "startup_mode": self._startup_mode,
            "trusted_runtime_context": self._trusted_runtime_context,
            "provider_selection_configured": self._provider_selection_config is not None,
            "provider_credentials": self.provider_credentials_payload(provider_id="openai"),
            "task_capability_selection_configured": self._task_capability_selection_config is not None,
            "capability_setup": capability_setup_contract,
            "capability_declaration": capability_context,
            "prompt_service_state": self.prompt_service_state_payload(),
            "services": self.service_status_payload().get("services"),
        }

    def provider_selection_payload(self) -> dict:
        if self._provider_selection_config is None:
            return {"configured": False, "config": None}
        return {"configured": True, "config": self._provider_selection_config}

    def service_status_payload(self) -> dict:
        if self._service_manager is None or not hasattr(self._service_manager, "get_status"):
            return {"configured": False, "services": {"backend": "unknown", "frontend": "unknown", "node": "unknown"}}
        return {"configured": True, "services": self._service_manager.get_status()}

    def provider_credentials_payload(self, *, provider_id: str) -> dict:
        summary = (
            self._provider_credentials_summary
            if isinstance(self._provider_credentials_summary, dict)
            else summarize_provider_credentials(None)
        )
        provider_name = str(provider_id or "").strip().lower()
        providers = summary.get("providers") if isinstance(summary.get("providers"), dict) else {}
        credentials = providers.get(provider_name) if isinstance(providers, dict) else None
        return {
            "provider": provider_name,
            "configured": bool(credentials and credentials.get("configured")),
            "credentials": credentials
            if isinstance(credentials, dict)
            else {
                "configured": False,
                "has_api_token": False,
                "has_service_token": False,
                "api_token_hint": None,
                "service_token_hint": None,
                "project_name": None,
                "default_model_id": None,
                "selected_model_ids": [],
                "updated_at": None,
            },
        }

    def task_capability_selection_payload(self) -> dict:
        if self._task_capability_selection_config is None:
            return {"configured": False, "config": None}
        return {"configured": True, "config": self._task_capability_selection_config}

    def prompt_service_state_payload(self) -> dict:
        if not isinstance(self._prompt_service_state, dict):
            return {"configured": False, "state": None}
        return {"configured": True, "state": self._prompt_service_state}

    def register_prompt_service(
        self,
        *,
        prompt_id: str,
        service_id: str,
        task_family: str,
        metadata: dict | None = None,
    ) -> dict:
        if self._prompt_service_state_store is None or not hasattr(self._prompt_service_state_store, "save"):
            raise ValueError("prompt service state store is not configured")
        state = (
            self._prompt_service_state
            if isinstance(self._prompt_service_state, dict)
            else self._prompt_service_state_store.load_or_create()
        )
        services = state.get("prompt_services")
        if not isinstance(services, list):
            services = []
            state["prompt_services"] = services
        registration = create_prompt_service_registration(
            prompt_id=prompt_id,
            service_id=service_id,
            task_family=task_family,
            metadata=metadata,
        )
        replaced = False
        for index, entry in enumerate(services):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("prompt_id") or "").strip() == registration["prompt_id"]:
                registration["registered_at"] = entry.get("registered_at") or registration["registered_at"]
                services[index] = registration
                replaced = True
                break
        if not replaced:
            services.append(registration)
        state["updated_at"] = self._now_iso()
        self._prompt_service_state_store.save(state)
        self._prompt_service_state = state
        return self.prompt_service_state_payload()

    def update_prompt_probation(self, *, prompt_id: str, action: str, reason: str | None = None) -> dict:
        if self._prompt_service_state_store is None or not hasattr(self._prompt_service_state_store, "save"):
            raise ValueError("prompt service state store is not configured")
        state = (
            self._prompt_service_state
            if isinstance(self._prompt_service_state, dict)
            else self._prompt_service_state_store.load_or_create()
        )
        services = state.get("prompt_services")
        if not isinstance(services, list):
            raise ValueError("prompt_services state is invalid")
        prompt_value = str(prompt_id or "").strip()
        if not prompt_value:
            raise ValueError("prompt_id is required")
        target = None
        for entry in services:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("prompt_id") or "").strip() == prompt_value:
                target = entry
                break
        if not isinstance(target, dict):
            raise ValueError("prompt_id is not registered")
        apply_probation_transition(entry=target, action=action, reason=reason)

        probation = state.get("probation")
        if not isinstance(probation, dict):
            probation = {"active_prompt_ids": [], "reasons": {}, "updated_at": self._now_iso()}
            state["probation"] = probation
        active_prompt_ids = probation.get("active_prompt_ids")
        if not isinstance(active_prompt_ids, list):
            active_prompt_ids = []
        active_set = {str(item).strip() for item in active_prompt_ids if str(item).strip()}
        reasons = probation.get("reasons")
        if not isinstance(reasons, dict):
            reasons = {}

        action_value = str(action or "").strip().lower()
        if action_value == "start":
            active_set.add(prompt_value)
            if reason:
                reasons[prompt_value] = str(reason).strip()
        elif action_value == "clear":
            active_set.discard(prompt_value)
            reasons.pop(prompt_value, None)
        else:
            raise ValueError("unsupported probation action")

        probation["active_prompt_ids"] = sorted(active_set)
        probation["reasons"] = reasons
        probation["updated_at"] = self._now_iso()
        state["updated_at"] = self._now_iso()
        self._prompt_service_state_store.save(state)
        self._prompt_service_state = state
        return self.prompt_service_state_payload()

    def authorize_execution(self, *, prompt_id: str, task_family: str) -> dict:
        state = self._prompt_service_state if isinstance(self._prompt_service_state, dict) else None
        result = self._execution_gateway.authorize(
            prompt_id=prompt_id,
            task_family=task_family,
            prompt_services_state=state,
        )
        return {
            "allowed": result.allowed,
            "reason": result.reason,
            "prompt_id": result.prompt_id,
            "task_family": result.task_family,
        }

    def _accepted_capability_profile_payload(self) -> dict:
        payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        accepted = payload.get("accepted_profile") if isinstance(payload, dict) else {}
        return accepted if isinstance(accepted, dict) else {}

    def _governance_bundle_payload(self) -> dict:
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        governance = capability_payload.get("governance_bundle") if isinstance(capability_payload, dict) else None
        if isinstance(governance, dict):
            return governance
        if self._governance_state_store is not None and hasattr(self._governance_state_store, "load"):
            stored = self._governance_state_store.load()
            if isinstance(stored, dict):
                return stored
        return {}

    def _governance_status_payload(self) -> dict:
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        status = capability_payload.get("governance_status") if isinstance(capability_payload, dict) else {}
        return status if isinstance(status, dict) else {}

    def _trust_state_payload(self) -> dict:
        if self._trust_state_store is None or not hasattr(self._trust_state_store, "load"):
            return {}
        payload = self._trust_state_store.load()
        return payload if isinstance(payload, dict) else {}

    def _declared_task_families_payload(self) -> list[str]:
        accepted_profile = self._accepted_capability_profile_payload()
        accepted_families = accepted_profile.get("declared_task_families") if isinstance(accepted_profile, dict) else []
        if isinstance(accepted_families, list) and accepted_families:
            return [str(item).strip() for item in accepted_families if str(item).strip()]
        node_capabilities = self.node_capabilities_payload()
        resolved = (
            node_capabilities.get("enabled_task_capabilities")
            or node_capabilities.get("resolved_tasks")
            or []
        )
        if isinstance(resolved, list) and resolved:
            return [str(item).strip() for item in resolved if str(item).strip()]
        configured = (
            self._task_capability_selection_config.get("selected_task_families")
            if isinstance(self._task_capability_selection_config, dict)
            else []
        )
        return [str(item).strip() for item in configured if str(item).strip()]

    def _get_task_execution_service(self) -> TaskExecutionService:
        if self._task_execution_service is not None:
            return self._task_execution_service
        if self._provider_runtime_manager is None:
            raise ValueError("direct execution is not configured")
        provider_resolver = ProviderResolver(runtime_manager=self._provider_runtime_manager, logger=self._logger)
        telemetry_publisher = None
        if self._node_id:
            telemetry_publisher = ExecutionTelemetryPublisher(
                logger=self._logger,
                node_id=self._node_id,
                trust_state_provider=self._trust_state_payload,
            )
        self._task_execution_service = TaskExecutionService(
            provider_runtime_manager=self._provider_runtime_manager,
            provider_resolver=provider_resolver,
            logger=self._logger,
            execution_gateway=self._execution_gateway,
            prompt_services_state_provider=lambda: (
                self._prompt_service_state if isinstance(self._prompt_service_state, dict) else {}
            ),
            declared_task_families_provider=self._declared_task_families_payload,
            accepted_capability_profile_provider=self._accepted_capability_profile_payload,
            governance_bundle_provider=self._governance_bundle_payload,
            governance_status_provider=self._governance_status_payload,
            execution_telemetry_publisher=telemetry_publisher,
        )
        return self._task_execution_service

    async def execute_direct(self, *, request: TaskExecutionRequest) -> dict:
        service = self._get_task_execution_service()
        result = await service.execute(request)
        return result.model_dump(mode="json")

    def restart_service(self, *, target: str) -> dict:
        if self._service_manager is None or not hasattr(self._service_manager, "restart"):
            raise ValueError("service manager is not configured")
        result = self._service_manager.restart(target=target)
        return {"status": "ok", **result, "services": self._service_manager.get_status()}

    def update_provider_selection(self, *, openai_enabled: bool) -> dict:
        if self._provider_selection_store is None or not hasattr(self._provider_selection_store, "save"):
            raise ValueError("provider selection store is not configured")
        payload = self._provider_selection_store.load_or_create(openai_enabled=False)
        providers = payload.setdefault("providers", {})
        enabled = set(providers.get("enabled") or [])
        if openai_enabled:
            enabled.add("openai")
        else:
            enabled.discard("openai")
        providers["enabled"] = sorted(enabled)
        self._provider_selection_store.save(payload)
        self._provider_selection_config = payload
        self._phase2_diag.provider_selection(
            {
                "source": "node_control_api",
                "enabled_providers": providers["enabled"],
            }
        )
        return self.provider_selection_payload()

    def update_task_capability_selection(self, *, selected_task_families: list[str]) -> dict:
        if self._task_capability_selection_store is None or not hasattr(self._task_capability_selection_store, "save"):
            raise ValueError("task capability selection store is not configured")
        payload = create_task_capability_selection_config({"selected_task_families": selected_task_families})
        self._task_capability_selection_store.save(payload)
        self._task_capability_selection_config = payload
        return self.task_capability_selection_payload()

    def update_openai_credentials(
        self,
        *,
        api_token: str,
        service_token: str,
        project_name: str,
    ) -> dict:
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "upsert_openai_credentials"):
            raise ValueError("provider credentials store is not configured")
        payload = self._provider_credentials_store.upsert_openai_credentials(
            api_token=api_token,
            service_token=service_token,
            project_name=project_name,
        )
        self._provider_credentials_summary = summarize_provider_credentials(payload)
        self._phase2_diag.provider_selection(
            {
                "source": "openai_credentials_saved",
                "provider": "openai",
                "has_api_token": True,
                "has_service_token": True,
                "project_name": bool(str(project_name or "").strip()),
            }
        )
        return self.provider_credentials_payload(provider_id="openai")

    def _has_saved_openai_api_token(self) -> bool:
        credentials = self.provider_credentials_payload(provider_id="openai").get("credentials")
        return bool(isinstance(credentials, dict) and credentials.get("has_api_token"))

    async def refresh_provider_models_after_openai_credentials_save(self) -> None:
        if (
            self._has_saved_openai_api_token()
            and self._provider_runtime_manager is not None
            and hasattr(self._provider_runtime_manager, "refresh_openai_models_from_saved_credentials")
        ):
            await self._provider_runtime_manager.refresh_openai_models_from_saved_credentials()
            return
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "refresh"):
            return
        await self._provider_runtime_manager.refresh()

    def update_openai_preferences(
        self,
        *,
        default_model_id: str | None = None,
        selected_model_ids: list[str] | None = None,
    ) -> dict:
        if self._provider_credentials_store is None or not hasattr(self._provider_credentials_store, "update_openai_preferences"):
            raise ValueError("provider credentials store is not configured")
        payload = self._provider_credentials_store.update_openai_preferences(
            default_model_id=default_model_id,
            selected_model_ids=selected_model_ids,
        )
        self._provider_credentials_summary = summarize_provider_credentials(payload)
        return self.provider_credentials_payload(provider_id="openai")

    def latest_provider_models_payload(self, *, provider_id: str, limit: int = 3) -> dict:
        normalized_provider = str(provider_id or "").strip().lower()
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "latest_models_payload"):
            payload = self._provider_runtime_manager.latest_models_payload(provider_id=normalized_provider, limit=limit)
            return self._normalize_latest_models_payload(payload=payload, provider_id=normalized_provider, limit=limit)
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        report = capability_payload.get("provider_capability_report") if isinstance(capability_payload, dict) else None
        return self._normalize_latest_models_payload(
            payload={"provider_id": normalized_provider, "models": self._extract_report_models(report, normalized_provider)},
            provider_id=normalized_provider,
            limit=limit,
        )

    def openai_provider_model_catalog_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_catalog_payload"):
            return {
                "provider_id": "openai",
                "models": [],
                "source": "provider_model_catalog",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        payload = self._provider_runtime_manager.openai_model_catalog_payload()
        raw_models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        normalized = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id") or "").strip()
            family = str(item.get("family") or "").strip()
            if not model_id or not family:
                continue
            normalized.append(
                {
                    "model_id": model_id,
                    "family": family,
                    "discovered_at": str(item.get("discovered_at") or "").strip() or None,
                    "enabled": bool(item.get("enabled")),
                }
            )
        selected_ui_ids = select_representative_openai_model_ids(
            [str(item.get("model_id") or "").strip().lower() for item in normalized]
        )
        ui_models = [item for item in normalized if str(item.get("model_id") or "").strip().lower() in selected_ui_ids]
        return {
            "provider_id": "openai",
            "models": normalized,
            "ui_models": ui_models,
            "source": str(payload.get("source") or "provider_model_catalog").strip() if isinstance(payload, dict) else "provider_model_catalog",
            "generated_at": str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat()).strip()
            if isinstance(payload, dict)
            else datetime.now(timezone.utc).isoformat(),
        }

    def openai_provider_model_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_capabilities_payload"):
            return {
                "provider_id": "openai",
                "classification_model": None,
                "entries": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "provider_model_capabilities",
            }
        payload = self._provider_runtime_manager.openai_model_capabilities_payload()
        entries = payload.get("entries") if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else []
        return {
            "provider_id": "openai",
            "classification_model": payload.get("classification_model") if isinstance(payload, dict) else None,
            "entries": entries,
            "generated_at": str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat()).strip()
            if isinstance(payload, dict)
            else datetime.now(timezone.utc).isoformat(),
            "source": str(payload.get("source") or "provider_model_capabilities").strip()
            if isinstance(payload, dict)
            else "provider_model_capabilities",
        }

    def openai_model_features_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_features_payload"):
            return {
                "schema_version": "1.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "entries": [],
                "source": "provider_model_features",
            }
        payload = self._provider_runtime_manager.openai_model_features_payload()
        if not isinstance(payload, dict):
            return {
                "schema_version": "1.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "entries": [],
                "source": "provider_model_features",
            }
        return payload

    def node_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "node_capabilities_payload"):
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": [],
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_task_capabilities": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "node_capabilities",
            }
        payload = self._provider_runtime_manager.node_capabilities_payload()
        if not isinstance(payload, dict):
            return {
                "schema_version": "1.0",
                "capability_graph_version": "1.0",
                "enabled_models": [],
                "feature_union": {},
                "resolved_tasks": [],
                "enabled_task_capabilities": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "node_capabilities",
            }
        return payload

    def openai_enabled_models_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_enabled_models_payload"):
            return {
                "provider_id": "openai",
                "models": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "provider_enabled_models",
            }
        payload = self._provider_runtime_manager.openai_enabled_models_payload()
        models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        return {
            "provider_id": "openai",
            "models": models,
            "generated_at": str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat()).strip()
            if isinstance(payload, dict)
            else datetime.now(timezone.utc).isoformat(),
            "source": str(payload.get("source") or "provider_enabled_models").strip()
            if isinstance(payload, dict)
            else "provider_enabled_models",
        }

    def save_openai_enabled_models(self, *, model_ids: list[str]) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "save_openai_enabled_models"):
            raise ValueError("openai enabled model persistence is not configured")
        payload = self._provider_runtime_manager.save_openai_enabled_models(model_ids=model_ids)
        return {
            "provider_id": "openai",
            **(payload if isinstance(payload, dict) else {}),
        }

    async def rerun_openai_model_capabilities(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "rerun_openai_model_capabilities"):
            raise ValueError("openai model capability refresh is not configured")
        return await self._provider_runtime_manager.rerun_openai_model_capabilities()

    def openai_resolved_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_resolved_capabilities_payload"):
            return {
                "provider_id": "openai",
                "enabled_model_ids": [],
                "classification_model": None,
                "updated_at": None,
                "capabilities": {
                    "text_generation": False,
                    "reasoning": False,
                    "vision": False,
                    "image_generation": False,
                    "audio_input": False,
                    "audio_output": False,
                    "realtime": False,
                    "tool_calling": False,
                    "structured_output": False,
                    "long_context": False,
                    "coding_strength": "none",
                    "speed_tier": "slow",
                    "cost_tier": "low",
                    "embeddings": False,
                    "moderation": False,
                },
                "enabled_models": [],
            }
        payload = self._provider_runtime_manager.openai_resolved_capabilities_payload()
        return {"provider_id": "openai", **(payload if isinstance(payload, dict) else {})}

    @staticmethod
    def _extract_report_models(report: dict | None, provider_id: str) -> list[dict]:
        if not isinstance(report, dict):
            return []
        providers = report.get("providers")
        if not isinstance(providers, list):
            return []
        for provider_payload in providers:
            if not isinstance(provider_payload, dict):
                continue
            provider_name = str(provider_payload.get("provider_id") or provider_payload.get("provider") or "").strip().lower()
            if provider_name != provider_id:
                continue
            models = provider_payload.get("models")
            return models if isinstance(models, list) else []
        return []

    @staticmethod
    def _normalize_latest_models_payload(*, payload: dict | None, provider_id: str, limit: int) -> dict:
        raw_models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        normalized = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("model_id") or item.get("id") or "").strip()
            if not model_id:
                continue
            pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
            pricing_input = item.get("pricing_input")
            pricing_output = item.get("pricing_output")
            normalized.append(
                {
                    "model_id": model_id,
                    "display_name": str(item.get("display_name") or model_id).strip(),
                    "created": item.get("created") if isinstance(item.get("created"), int) else None,
                    "status": str(item.get("status") or "available").strip(),
                    "pricing": {
                        "currency": str(pricing.get("currency") or "usd").strip().lower(),
                        "input_per_1m_tokens": (
                            pricing.get("input_per_1m_tokens")
                            if isinstance(pricing.get("input_per_1m_tokens"), (int, float))
                            else pricing_input
                        ),
                        "output_per_1m_tokens": (
                            pricing.get("output_per_1m_tokens")
                            if isinstance(pricing.get("output_per_1m_tokens"), (int, float))
                            else pricing_output
                        ),
                    },
                }
            )
        normalized.sort(
            key=lambda item: (int(item.get("created") or 0), str(item.get("model_id") or "")),
            reverse=True,
        )
        return {
            "provider_id": provider_id,
            "models": normalized[: max(int(limit), 0)],
            "source": str(payload.get("source") or "provider_capability_report").strip()
            if isinstance(payload, dict)
            else "provider_capability_report",
            "generated_at": str(payload.get("generated_at") or datetime.now(timezone.utc).isoformat()).strip()
            if isinstance(payload, dict)
            else datetime.now(timezone.utc).isoformat(),
        }

    async def refresh_openai_pricing(self, *, force_refresh: bool) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "refresh_pricing"):
            raise ValueError("provider pricing refresh is not configured")
        payload = await self._provider_runtime_manager.refresh_pricing(force=force_refresh)
        return {
            "provider_id": "openai",
            "force_refresh": bool(force_refresh),
            **(payload if isinstance(payload, dict) else {}),
        }

    def save_openai_manual_pricing(
        self,
        *,
        model_id: str,
        display_name: str | None = None,
        input_price_per_1m: float | None = None,
        output_price_per_1m: float | None = None,
    ) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "save_manual_openai_pricing"):
            raise ValueError("manual pricing save is not configured")
        payload = self._provider_runtime_manager.save_manual_openai_pricing(
            model_id=model_id,
            display_name=display_name,
            input_price_per_1m=input_price_per_1m,
            output_price_per_1m=output_price_per_1m,
        )
        return {"provider_id": "openai", **(payload if isinstance(payload, dict) else {})}

    def openai_pricing_diagnostics_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "pricing_diagnostics_payload"):
            return {
                "provider_id": "openai",
                "configured": False,
                "refresh_state": "unavailable",
                "stale": True,
                "entry_count": 0,
                "source_urls": [],
                "source_url_used": None,
                "last_refresh_time": None,
                "unknown_models": [],
                "last_error": None,
            }
        payload = self._provider_runtime_manager.pricing_diagnostics_payload()
        return {
            "provider_id": "openai",
            **(payload if isinstance(payload, dict) else {"configured": False}),
        }

    async def submit_capability_declaration(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "submit_once"):
            raise ValueError("capability declaration runner is not configured")
        setup_contract = self._build_capability_setup_contract()
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[capability-declare-gate-check] %s",
                {
                    "status": self._lifecycle.get_state().value,
                    "declaration_allowed": setup_contract.get("declaration_allowed"),
                    "blocking_reasons": setup_contract.get("blocking_reasons"),
                },
            )
        if not setup_contract.get("declaration_allowed"):
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[capability-declare-gate-failed] %s",
                    {
                        "status": self._lifecycle.get_state().value,
                        "blocking_reasons": setup_contract.get("blocking_reasons"),
                        "readiness_flags": setup_contract.get("readiness_flags"),
                    },
                )
            raise CapabilityDeclarationPrerequisiteError(
                payload={
                    "error_code": "capability_setup_prerequisites_unmet",
                    "message": "capability declaration prerequisites are not satisfied",
                    "blocking_reasons": setup_contract.get("blocking_reasons") or [],
                    "readiness_flags": setup_contract.get("readiness_flags") or {},
                }
            )
        return await self._capability_runner.submit_once()

    async def redeclare_capabilities(self, *, reason: str, force: bool = False) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "redeclare_if_needed"):
            return {"status": "skipped", "reason": "capability_redeclaration_not_configured"}
        return await self._capability_runner.redeclare_if_needed(reason=reason, force=force)

    async def notify_workflow_request(self, *, workflow_request: str, workflow_status: str, details: dict | None = None) -> dict | None:
        if self._capability_runner is None or not hasattr(self._capability_runner, "emit_workflow_status_telemetry"):
            return None
        try:
            return await self._capability_runner.emit_workflow_status_telemetry(
                workflow_request=workflow_request,
                workflow_status=workflow_status,
                details=details,
            )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[workflow-request-telemetry-failed] %s",
                    {"workflow_request": workflow_request, "workflow_status": workflow_status, "error": str(exc)},
                )
            return None

    async def rebuild_node_capabilities(self) -> dict:
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "rebuild_node_capabilities"):
            payload = self._provider_runtime_manager.rebuild_node_capabilities()
            if isinstance(payload, dict):
                return payload
        resolved = self.openai_resolved_capabilities_payload()
        node_capabilities = self.node_capabilities_payload()
        return {
            "status": "rebuilt",
            "provider_id": "openai",
            "resolved_capabilities": resolved,
            "resolved_tasks": list(node_capabilities.get("enabled_task_capabilities") or node_capabilities.get("resolved_tasks") or []),
            "node_capabilities": node_capabilities,
        }

    def capability_diagnostics_payload(self) -> dict:
        capability_status = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        resolved = self.openai_resolved_capabilities_payload()
        model_features = self.openai_model_features_payload()
        node_capabilities = self.node_capabilities_payload()
        try:
            capability_graph = load_task_graph()
        except Exception as exc:
            capability_graph = {"error": str(exc)}
        pricing_catalog = (
            self._provider_runtime_manager.openai_pricing_catalog_payload()
            if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "openai_pricing_catalog_payload")
            else {"entries": [], "source": "openai_pricing_catalog", "generated_at": self._now_iso()}
        )
        pricing_diagnostics = self.openai_pricing_diagnostics_payload()
        return {
            "admin": True,
            "generated_at": self._now_iso(),
            "discovered_models": self.openai_provider_model_catalog_payload(),
            "feature_catalog": model_features,
            "capability_graph": capability_graph,
            "enabled_models": self.openai_enabled_models_payload(),
            "capability_catalog": self.openai_provider_model_capabilities_payload(),
            "resolved_capabilities": resolved,
            "resolved_tasks": (
                node_capabilities.get("enabled_task_capabilities")
                or node_capabilities.get("resolved_tasks")
                or []
            ),
            "pricing_catalog": pricing_catalog,
            "pricing_diagnostics": pricing_diagnostics,
            "node_capabilities": node_capabilities,
            "classification_model": resolved.get("classification_model"),
            "last_declaration_payload": capability_status.get("last_manifest_payload"),
            "last_declaration_result": capability_status.get("last_declaration_result"),
        }

    async def refresh_governance(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "refresh_governance_once"):
            raise ValueError("governance refresh is not configured")
        return await self._capability_runner.refresh_governance_once()

    async def refresh_provider_capabilities(self, *, force_refresh: bool) -> dict:
        openai_reload = None
        if (
            force_refresh
            and self._has_saved_openai_api_token()
            and self._provider_runtime_manager is not None
            and hasattr(self._provider_runtime_manager, "refresh_openai_models_from_saved_credentials")
        ):
            openai_reload = await self._provider_runtime_manager.refresh_openai_models_from_saved_credentials()
        if self._capability_runner is not None and hasattr(self._capability_runner, "refresh_provider_capabilities_once"):
            result = await self._capability_runner.refresh_provider_capabilities_once(force_refresh=force_refresh)
            if openai_reload is not None:
                return {**result, "openai_model_reload": openai_reload}
            return result
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "refresh"):
            result = {
                "source": "provider_runtime_manager",
                "force_refresh": force_refresh,
                "report": await self._provider_runtime_manager.refresh(),
            }
            if openai_reload is not None:
                result["openai_model_reload"] = openai_reload
            return result
        if self._capability_runner is None or not hasattr(self._capability_runner, "refresh_provider_capabilities_once"):
            raise ValueError("provider capability refresh is not configured")
        return await self._capability_runner.refresh_provider_capabilities_once(force_refresh=force_refresh)

    async def start_background_jobs(self) -> None:
        if self._provider_refresh_task is not None and not self._provider_refresh_task.done():
            return
        self._provider_refresh_task = asyncio.create_task(self._provider_refresh_loop())

    async def stop_background_jobs(self) -> None:
        if self._provider_refresh_task is None:
            return
        self._provider_refresh_task.cancel()
        try:
            await self._provider_refresh_task
        except asyncio.CancelledError:
            pass
        self._provider_refresh_task = None

    async def _provider_refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._provider_refresh_interval_seconds)
            try:
                result = await self.refresh_provider_capabilities(force_refresh=False)
                if hasattr(self._logger, "info"):
                    self._logger.info(
                        "[provider-intelligence-refresh-job] %s",
                        {
                            "status": result.get("status"),
                            "changed": result.get("changed"),
                            "core_submission": result.get("core_submission"),
                        },
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if hasattr(self._logger, "warning"):
                    self._logger.warning("[provider-intelligence-refresh-job-error] %s", {"error": str(exc)})

    def debug_providers_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "providers_snapshot"):
            return {"configured": False, "providers": []}
        snapshot = self._provider_runtime_manager.providers_snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {"providers": []})}

    def debug_provider_models_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "models_snapshot"):
            return {"configured": False, "providers": []}
        snapshot = self._provider_runtime_manager.models_snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {"providers": []})}

    def debug_provider_metrics_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "metrics_snapshot"):
            return {"configured": False, "providers": {}}
        snapshot = self._provider_runtime_manager.metrics_snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {"providers": {}})}

    def execution_observability_payload(self) -> dict:
        service = self._task_execution_service
        if service is None and self._provider_runtime_manager is not None:
            try:
                service = self._get_task_execution_service()
            except Exception:
                service = None
        if service is None or not hasattr(service, "lifecycle_tracker"):
            return {
                "configured": False,
                "active_tasks": [],
                "recent_history": [],
                "failure_reasons": {},
                "provider_usage": {},
                "model_usage": {},
            }

        lifecycle_tracker = service.lifecycle_tracker
        active_payload = (
            lifecycle_tracker.active_payload()
            if hasattr(lifecycle_tracker, "active_payload")
            else {"active_tasks": [], "active_count": 0}
        )
        history_payload = (
            lifecycle_tracker.history_payload()
            if hasattr(lifecycle_tracker, "history_payload")
            else {"history": [], "history_count": 0}
        )
        metrics_payload = self.debug_provider_metrics_payload()
        providers = metrics_payload.get("providers") if isinstance(metrics_payload, dict) else {}
        failure_reasons: dict[str, int] = {}
        provider_usage: dict[str, dict] = {}
        model_usage: dict[str, dict] = {}

        if isinstance(providers, dict):
            for provider_id, provider_payload in providers.items():
                if not isinstance(provider_payload, dict):
                    continue
                provider_models = provider_payload.get("models")
                provider_totals = provider_payload.get("totals")
                if isinstance(provider_totals, dict):
                    provider_usage[str(provider_id)] = {
                        "total_requests": int(provider_totals.get("total_requests") or 0),
                        "successful_requests": int(provider_totals.get("successful_requests") or 0),
                        "failed_requests": int(provider_totals.get("failed_requests") or 0),
                        "success_rate": provider_totals.get("success_rate"),
                    }
                if not isinstance(provider_models, dict):
                    continue
                for model_id, model_payload in provider_models.items():
                    if not isinstance(model_payload, dict):
                        continue
                    failure_classes = model_payload.get("failure_classes")
                    if isinstance(failure_classes, dict):
                        for reason, count in failure_classes.items():
                            key = str(reason or "").strip()
                            if not key:
                                continue
                            failure_reasons[key] = failure_reasons.get(key, 0) + int(count or 0)
                    model_usage_key = f"{provider_id}:{model_id}"
                    model_usage[model_usage_key] = {
                        "provider_id": str(provider_id),
                        "model_id": str(model_id),
                        "total_requests": int(model_payload.get("total_requests") or 0),
                        "successful_requests": int(model_payload.get("successful_requests") or 0),
                        "failed_requests": int(model_payload.get("failed_requests") or 0),
                        "success_rate": model_payload.get("success_rate"),
                        "avg_latency": model_payload.get("avg_latency"),
                        "p95_latency": model_payload.get("p95_latency"),
                    }

        return {
            "configured": True,
            "active_tasks": list(active_payload.get("active_tasks") or []),
            "recent_history": list(history_payload.get("history") or []),
            "failure_reasons": failure_reasons,
            "provider_usage": provider_usage,
            "model_usage": model_usage,
        }

    def recover_from_degraded(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "recover_from_degraded"):
            raise ValueError("degraded recovery is not configured")
        result = self._capability_runner.recover_from_degraded()
        self._phase2_diag.degraded_recovery(
            {
                "source": "node_control_api",
                "event": "recover_invoked",
                "result": result.get("status"),
                "target_state": result.get("target_state"),
            }
        )
        return result

    def governance_status_payload(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "status_payload"):
            return {"configured": False, "status": None}
        status = self._capability_runner.status_payload()
        return {"configured": True, "status": status.get("governance_status")}

    def _start_bootstrap_runner_if_available(self) -> None:
        if self._bootstrap_runner is None or self._bootstrap_config is None:
            return
        self._bootstrap_runner.start(
            bootstrap_host=self._bootstrap_config.bootstrap_host,
            port=self._bootstrap_config.port,
            topic=self._bootstrap_config.topic,
            node_name=self._bootstrap_config.node_name,
        )

    def initiate_onboarding(self, *, mqtt_host: str, node_name: str) -> dict:
        if self._lifecycle.get_state() != NodeLifecycleState.UNCONFIGURED:
            raise ValueError("node is not in unconfigured state")

        config = create_bootstrap_config(
            {
                "bootstrap_host": mqtt_host,
                "node_name": node_name,
            }
        )
        self._bootstrap_config = config
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(
                {
                    "bootstrap_host": config.bootstrap_host,
                    "node_name": config.node_name,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._lifecycle.transition_to(
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            {"source": "setup_ui"},
        )
        self._start_bootstrap_runner_if_available()
        return self.status_payload()

    def restart_setup(self) -> dict:
        if self._bootstrap_runner is not None and hasattr(self._bootstrap_runner, "stop"):
            self._bootstrap_runner.stop()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "cancel"):
            self._onboarding_runtime.cancel()

        self._bootstrap_config = None
        if self._config_path.exists():
            self._config_path.unlink()
        self._lifecycle.reset_to_unconfigured({"source": "setup_ui_restart"})
        return self.status_payload()


class OnboardingInitiateRequest(BaseModel):
    mqtt_host: str
    node_name: str


class ProviderSelectionRequest(BaseModel):
    openai_enabled: bool


class OpenAICredentialsRequest(BaseModel):
    api_token: str
    service_token: str
    project_name: str


class OpenAIPreferencesRequest(BaseModel):
    default_model_id: str | None = None
    selected_model_ids: list[str] | None = None


class TaskCapabilitySelectionRequest(BaseModel):
    selected_task_families: list[str]


class ServiceRestartRequest(BaseModel):
    target: str


class ProviderCapabilityRefreshRequest(BaseModel):
    force_refresh: bool = False


class OpenAIPricingRefreshRequest(BaseModel):
    force_refresh: bool = True


class OpenAIManualPricingRequest(BaseModel):
    model_id: str
    display_name: str | None = None
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None


class OpenAIEnabledModelsRequest(BaseModel):
    model_ids: list[str]


class RefreshTriggerRequest(BaseModel):
    force_refresh: bool = True


class PromptServiceRegisterRequest(BaseModel):
    prompt_id: str
    service_id: str
    task_family: str
    metadata: dict | None = None


class PromptProbationRequest(BaseModel):
    action: str
    reason: str | None = None


class ExecutionAuthorizeRequest(BaseModel):
    prompt_id: str
    task_family: str


def create_node_control_app(*, state: NodeControlState, logger) -> FastAPI:
    app = FastAPI(title="Synthia AI Node Control API", version="0.1.0")
    configured_admin_token = str(os.environ.get("SYNTHIA_ADMIN_TOKEN") or "").strip()

    def require_admin(admin_token: str | None) -> None:
        if not configured_admin_token:
            return
        if str(admin_token or "").strip() != configured_admin_token:
            raise HTTPException(status_code=403, detail="admin access required")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup_jobs():
        if hasattr(state, "start_background_jobs"):
            await state.start_background_jobs()

    @app.on_event("shutdown")
    async def _shutdown_jobs():
        if hasattr(state, "stop_background_jobs"):
            await state.stop_background_jobs()

    @app.get("/")
    def root():
        return {
            "service": "synthia-ai-node-control-api",
            "status": "ok",
            "version": "0.1.0",
            "endpoints": [
                "/api/node/status",
                "/api/onboarding/initiate",
                "/api/onboarding/restart",
                "/api/providers/config",
                "/api/providers/openai/credentials",
                "/api/providers/openai/preferences",
                "/api/providers/openai/models/latest",
                "/api/providers/openai/pricing/diagnostics",
                "/api/providers/openai/pricing/manual",
                "/api/providers/openai/pricing/refresh",
                "/api/capabilities/config",
                "/api/capabilities/declare",
                "/api/governance/status",
                "/api/governance/refresh",
                "/api/capabilities/providers/refresh",
                "/api/node/recover",
                "/api/prompts/services",
                "/api/prompts/services/{prompt_id}/probation",
                "/api/execution/authorize",
                "/api/services/status",
                "/api/services/restart",
                "/debug/providers",
                "/debug/providers/models",
                "/debug/providers/metrics",
                "/api/health",
            ],
        }

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/node/status")
    def get_node_status():
        return state.status_payload()

    @app.post("/api/onboarding/initiate")
    def post_onboarding_initiate(payload: OnboardingInitiateRequest):
        try:
            return state.initiate_onboarding(
                mqtt_host=payload.mqtt_host,
                node_name=payload.node_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/onboarding/restart")
    def post_onboarding_restart():
        return state.restart_setup()

    @app.get("/api/providers/config")
    def get_provider_config():
        return state.provider_selection_payload()

    @app.post("/api/providers/config")
    async def post_provider_config(payload: ProviderSelectionRequest):
        try:
            response = state.update_provider_selection(openai_enabled=payload.openai_enabled)
            return {**response, "declaration": {"status": "pending_manual", "reason": "provider_configuration_changed"}}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/providers/openai/credentials")
    def get_openai_credentials():
        return state.provider_credentials_payload(provider_id="openai")

    @app.post("/api/providers/openai/credentials")
    async def post_openai_credentials(payload: OpenAICredentialsRequest):
        try:
            response = state.update_openai_credentials(
                api_token=payload.api_token,
                service_token=payload.service_token,
                project_name=payload.project_name,
            )
            await state.refresh_provider_models_after_openai_credentials_save()
            return response
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/providers/openai/preferences")
    def post_openai_preferences(payload: OpenAIPreferencesRequest):
        try:
            return state.update_openai_preferences(
                default_model_id=payload.default_model_id,
                selected_model_ids=payload.selected_model_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/providers/openai/models/latest")
    def get_openai_latest_models(limit: int = 3):
        return state.latest_provider_models_payload(provider_id="openai", limit=limit)

    @app.get("/api/providers/openai/models/catalog")
    def get_openai_model_catalog():
        return state.openai_provider_model_catalog_payload()

    @app.get("/api/providers/openai/models/capabilities")
    def get_openai_model_capabilities():
        return state.openai_provider_model_capabilities_payload()

    @app.get("/api/providers/openai/models/features")
    def get_openai_model_features():
        return state.openai_model_features_payload()

    @app.get("/api/providers/openai/models/enabled")
    def get_openai_enabled_models():
        return state.openai_enabled_models_payload()

    @app.post("/api/providers/openai/models/enabled")
    async def post_openai_enabled_models(payload: OpenAIEnabledModelsRequest):
        try:
            response = state.save_openai_enabled_models(model_ids=payload.model_ids)
            return {**response, "declaration": {"status": "pending_manual", "reason": "enabled_models_changed"}}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/providers/openai/capability-resolution")
    def get_openai_capability_resolution():
        return state.openai_resolved_capabilities_payload()

    @app.get("/api/capabilities/node/resolved")
    def get_node_capabilities():
        return state.node_capabilities_payload()

    @app.get("/api/providers/openai/pricing/diagnostics")
    def get_openai_pricing_diagnostics():
        return state.openai_pricing_diagnostics_payload()

    @app.post("/api/providers/openai/pricing/refresh")
    async def post_openai_pricing_refresh(payload: OpenAIPricingRefreshRequest):
        try:
            response = await state.refresh_openai_pricing(force_refresh=payload.force_refresh)
            await state.notify_workflow_request(
                workflow_request="openai_pricing_refresh",
                workflow_status="done",
                details={"force_refresh": payload.force_refresh, "status": response.get("status")},
            )
            return response
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="openai_pricing_refresh",
                workflow_status="stopped",
                details={"force_refresh": payload.force_refresh, "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/providers/openai/models/classification/refresh")
    async def post_openai_model_capabilities_refresh(x_synthia_admin_token: str | None = Header(default=None)):
        try:
            require_admin(x_synthia_admin_token)
            response = await state.rerun_openai_model_capabilities()
            payload = {**response, "declaration": {"status": "pending_manual", "reason": "capability_catalog_refresh"}}
            await state.notify_workflow_request(
                workflow_request="openai_model_classification_refresh",
                workflow_status="done",
                details={
                    "status": payload.get("status"),
                    "classification_model": payload.get("classification_model"),
                    "entry_count": len(payload.get("entries") or []),
                },
            )
            return payload
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="openai_model_classification_refresh",
                workflow_status="stopped",
                details={"error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/providers/openai/pricing/manual")
    def post_openai_manual_pricing(payload: OpenAIManualPricingRequest):
        try:
            return state.save_openai_manual_pricing(
                model_id=payload.model_id,
                display_name=payload.display_name,
                input_price_per_1m=payload.input_price_per_1m,
                output_price_per_1m=payload.output_price_per_1m,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/capabilities/config")
    def get_capabilities_config():
        return state.task_capability_selection_payload()

    @app.post("/api/capabilities/config")
    def post_capabilities_config(payload: TaskCapabilitySelectionRequest):
        try:
            return state.update_task_capability_selection(selected_task_families=payload.selected_task_families)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/declare")
    async def post_capability_declare():
        try:
            return await state.submit_capability_declaration()
        except CapabilityDeclarationPrerequisiteError as exc:
            raise HTTPException(status_code=409, detail=exc.payload) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/rebuild")
    async def post_capability_rebuild(x_synthia_admin_token: str | None = Header(default=None)):
        try:
            require_admin(x_synthia_admin_token)
            response = await state.rebuild_node_capabilities()
            await state.notify_workflow_request(
                workflow_request="node_capability_rebuild",
                workflow_status="done",
                details={"status": response.get("status"), "resolved_task_count": len(response.get("resolved_tasks") or [])},
            )
            return response
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="node_capability_rebuild",
                workflow_status="stopped",
                details={"error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/redeclare")
    async def post_capability_redeclare(
        payload: RefreshTriggerRequest,
        x_synthia_admin_token: str | None = Header(default=None),
    ):
        try:
            require_admin(x_synthia_admin_token)
            return await state.redeclare_capabilities(reason="manual_redeclare", force=payload.force_refresh)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/governance/status")
    def get_governance_status():
        return state.governance_status_payload()

    @app.post("/api/governance/refresh")
    async def post_governance_refresh():
        try:
            return await state.refresh_governance()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/providers/refresh")
    async def post_provider_capability_refresh(
        payload: ProviderCapabilityRefreshRequest,
        x_synthia_admin_token: str | None = Header(default=None),
    ):
        try:
            require_admin(x_synthia_admin_token)
            response = await state.refresh_provider_capabilities(force_refresh=payload.force_refresh)
            result = {**response, "declaration": {"status": "pending_manual", "reason": "provider_capability_refresh"}}
            await state.notify_workflow_request(
                workflow_request="provider_capability_refresh",
                workflow_status="done",
                details={"force_refresh": payload.force_refresh, "status": result.get("status"), "changed": result.get("changed")},
            )
            return result
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="provider_capability_refresh",
                workflow_status="stopped",
                details={"force_refresh": payload.force_refresh, "error": str(exc)},
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/node/recover")
    def post_node_recover():
        try:
            return state.recover_from_degraded()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/prompts/services")
    def get_prompt_services():
        return state.prompt_service_state_payload()

    @app.post("/api/prompts/services")
    def post_prompt_services(payload: PromptServiceRegisterRequest):
        try:
            return state.register_prompt_service(
                prompt_id=payload.prompt_id,
                service_id=payload.service_id,
                task_family=payload.task_family,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/services/{prompt_id}/probation")
    def post_prompt_probation(prompt_id: str, payload: PromptProbationRequest):
        try:
            return state.update_prompt_probation(
                prompt_id=prompt_id,
                action=payload.action,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/execution/authorize")
    def post_execution_authorize(payload: ExecutionAuthorizeRequest):
        return state.authorize_execution(prompt_id=payload.prompt_id, task_family=payload.task_family)

    @app.post("/api/execution/direct")
    async def post_execution_direct(payload: TaskExecutionRequest):
        try:
            return await state.execute_direct(request=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/services/status")
    def get_services_status():
        return state.service_status_payload()

    @app.post("/api/services/restart")
    def post_services_restart(payload: ServiceRestartRequest):
        try:
            return state.restart_service(target=payload.target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/debug/providers")
    def get_debug_providers():
        return state.debug_providers_payload()

    @app.get("/debug/providers/models")
    def get_debug_provider_models():
        return state.debug_provider_models_payload()

    @app.get("/debug/providers/metrics")
    def get_debug_provider_metrics():
        return state.debug_provider_metrics_payload()

    @app.get("/debug/execution")
    def get_debug_execution():
        return state.execution_observability_payload()

    @app.get("/api/capabilities/diagnostics")
    def get_capability_diagnostics(x_synthia_admin_token: str | None = Header(default=None)):
        require_admin(x_synthia_admin_token)
        return state.capability_diagnostics_payload()

    if hasattr(logger, "info"):
        logger.info("[node-control-api] FastAPI app initialized")
    return app
