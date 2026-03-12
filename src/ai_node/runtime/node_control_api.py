import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_node.config.bootstrap_config import create_bootstrap_config
from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


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
        self._startup_mode = startup_mode
        self._trusted_runtime_context = trusted_runtime_context or {}
        self._phase2_diag = Phase2DiagnosticsLogger(logger)
        self._bootstrap_config = None
        self._provider_selection_config = None
        self._node_id = None
        self._identity_state = "unknown"
        self._load_identity()
        self._load_provider_selection_config()
        self._load_existing_config()

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
            "capability_declaration": capability_context,
        }

    def provider_selection_payload(self) -> dict:
        if self._provider_selection_config is None:
            return {"configured": False, "config": None}
        return {"configured": True, "config": self._provider_selection_config}

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

    async def submit_capability_declaration(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "submit_once"):
            raise ValueError("capability declaration runner is not configured")
        return await self._capability_runner.submit_once()

    async def refresh_governance(self) -> dict:
        if self._capability_runner is None or not hasattr(self._capability_runner, "refresh_governance_once"):
            raise ValueError("governance refresh is not configured")
        return await self._capability_runner.refresh_governance_once()

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


def create_node_control_app(*, state: NodeControlState, logger) -> FastAPI:
    app = FastAPI(title="Synthia AI Node Control API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
                "/api/capabilities/declare",
                "/api/governance/status",
                "/api/governance/refresh",
                "/api/node/recover",
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

    @app.post("/api/capabilities/declare")
    async def post_capability_declare():
        try:
            return await state.submit_capability_declaration()
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

    @app.post("/api/node/recover")
    def post_node_recover():
        try:
            return state.recover_from_degraded()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if hasattr(logger, "info"):
        logger.info("[node-control-api] FastAPI app initialized")
    return app
