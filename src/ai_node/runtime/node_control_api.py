import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_node.capabilities.task_families import CANONICAL_TASK_FAMILIES
from ai_node.config.bootstrap_config import create_bootstrap_config
from ai_node.execution.gateway import ExecutionGateway
from ai_node.prompts.registration import apply_probation_transition, create_prompt_service_registration
from ai_node.config.task_capability_selection_config import create_task_capability_selection_config
from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.service_manager import NullServiceManager


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
        task_capability_selection_store=None,
        trust_state_store=None,
        prompt_service_state_store=None,
        execution_gateway=None,
        provider_runtime_manager=None,
        service_manager=None,
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
        self._task_capability_selection_store = task_capability_selection_store
        self._trust_state_store = trust_state_store
        self._prompt_service_state_store = prompt_service_state_store
        self._execution_gateway = execution_gateway or ExecutionGateway()
        self._provider_runtime_manager = provider_runtime_manager
        self._service_manager = service_manager or NullServiceManager()
        self._provider_refresh_interval_seconds = max(int(provider_refresh_interval_seconds), 60)
        self._provider_refresh_task: asyncio.Task | None = None
        self._startup_mode = startup_mode
        self._trusted_runtime_context = trusted_runtime_context or {}
        self._phase2_diag = Phase2DiagnosticsLogger(logger)
        self._bootstrap_config = None
        self._provider_selection_config = None
        self._task_capability_selection_config = None
        self._prompt_service_state = None
        self._node_id = None
        self._identity_state = "unknown"
        self._load_identity()
        self._load_provider_selection_config()
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

    async def refresh_governance(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "refresh_governance_once"):
            raise ValueError("governance refresh is not configured")
        return await self._capability_runner.refresh_governance_once()

    async def refresh_provider_capabilities(self, *, force_refresh: bool) -> dict:
        if self._capability_runner is not None and hasattr(self._capability_runner, "refresh_provider_capabilities_once"):
            return await self._capability_runner.refresh_provider_capabilities_once(force_refresh=force_refresh)
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "refresh"):
            return {"source": "provider_runtime_manager", "force_refresh": force_refresh, "report": await self._provider_runtime_manager.refresh()}
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


class TaskCapabilitySelectionRequest(BaseModel):
    selected_task_families: list[str]


class ServiceRestartRequest(BaseModel):
    target: str


class ProviderCapabilityRefreshRequest(BaseModel):
    force_refresh: bool = False


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
    def post_provider_config(payload: ProviderSelectionRequest):
        try:
            return state.update_provider_selection(openai_enabled=payload.openai_enabled)
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
    async def post_provider_capability_refresh(payload: ProviderCapabilityRefreshRequest):
        try:
            return await state.refresh_provider_capabilities(force_refresh=payload.force_refresh)
        except ValueError as exc:
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

    if hasattr(logger, "info"):
        logger.info("[node-control-api] FastAPI app initialized")
    return app
