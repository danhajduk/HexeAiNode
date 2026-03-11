import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_node.config.bootstrap_config import create_bootstrap_config
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


class NodeControlState:
    def __init__(self, *, lifecycle: NodeLifecycle, config_path: str, logger, bootstrap_runner=None) -> None:
        self._lifecycle = lifecycle
        self._config_path = Path(config_path)
        self._logger = logger
        self._bootstrap_runner = bootstrap_runner
        self._bootstrap_config = None
        self._load_existing_config()

    def _load_existing_config(self) -> None:
        if not self._config_path.exists():
            return
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
            self._bootstrap_config = create_bootstrap_config(payload)
            if self._lifecycle.get_state() == NodeLifecycleState.UNCONFIGURED:
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

    def status_payload(self) -> dict:
        state = self._lifecycle.get_state()
        return {
            "status": state.value,
            "bootstrap_configured": self._bootstrap_config is not None,
        }

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


class OnboardingInitiateRequest(BaseModel):
    mqtt_host: str
    node_name: str


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

    if hasattr(logger, "info"):
        logger.info("[node-control-api] FastAPI app initialized")
    return app
