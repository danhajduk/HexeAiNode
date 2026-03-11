from datetime import datetime, timezone

from ai_node.capabilities.environment_hints import collect_environment_hints
from ai_node.capabilities.manifest_schema import create_capability_manifest
from ai_node.capabilities.node_features import create_node_feature_declarations
from ai_node.capabilities.providers import create_provider_capabilities_from_selection_config
from ai_node.capabilities.task_families import create_declared_task_family_capabilities
from ai_node.core_api.capability_client import CapabilityDeclarationClient
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState


class CapabilityDeclarationRunner:
    def __init__(
        self,
        *,
        lifecycle: NodeLifecycle,
        logger,
        trust_store,
        provider_selection_store,
        node_id: str,
        capability_client=None,
    ) -> None:
        self._lifecycle = lifecycle
        self._logger = logger
        self._trust_store = trust_store
        self._provider_selection_store = provider_selection_store
        self._node_id = str(node_id).strip()
        self._capability_client = capability_client or CapabilityDeclarationClient(logger=logger)
        self._status = "idle"
        self._last_error = None
        self._last_submitted_at = None

    def status_payload(self) -> dict:
        return {
            "status": self._status,
            "last_error": self._last_error,
            "last_submitted_at": self._last_submitted_at,
        }

    async def submit_once(self) -> dict:
        state = self._lifecycle.get_state()
        if state not in {
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
        }:
            raise ValueError(f"cannot declare capabilities from state: {state.value}")

        trust_state = self._trust_store.load() if self._trust_store is not None else None
        if not isinstance(trust_state, dict):
            raise ValueError("missing valid trust state for capability declaration")

        provider_selection = (
            self._provider_selection_store.load_or_create(openai_enabled=False)
            if self._provider_selection_store is not None and hasattr(self._provider_selection_store, "load_or_create")
            else None
        )
        providers = create_provider_capabilities_from_selection_config(provider_selection)
        manifest = create_capability_manifest(
            node_id=self._node_id,
            node_name=str(trust_state.get("node_name") or "ai-node").strip(),
            task_families=create_declared_task_family_capabilities(),
            supported_providers=providers.get("supported"),
            enabled_providers=providers.get("enabled"),
            node_features=create_node_feature_declarations(),
            environment_hints=collect_environment_hints(),
        )

        self._lifecycle.transition_to(
            NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS,
            {"source": "capability_declaration_runner"},
        )
        self._status = "in_progress"
        self._last_error = None
        self._last_submitted_at = datetime.now(timezone.utc).isoformat()

        result = await self._capability_client.submit_manifest(
            core_api_endpoint=str(trust_state.get("core_api_endpoint") or "").strip(),
            trust_token=str(trust_state.get("node_trust_token") or "").strip(),
            node_id=self._node_id,
            capability_manifest=manifest,
        )

        if result.status == "accepted":
            self._lifecycle.transition_to(
                NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED,
                {"source": "capability_declaration_runner"},
            )
            self._lifecycle.transition_to(
                NodeLifecycleState.OPERATIONAL,
                {"source": "capability_declaration_runner"},
            )
            self._status = "accepted"
            self._last_error = None
            return {"status": "accepted", "result": result.payload}

        self._lifecycle.transition_to(
            NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
            {
                "source": "capability_declaration_runner",
                "error": result.error,
                "retryable": result.retryable,
            },
        )
        self._status = "retry_pending" if result.retryable else "rejected"
        self._last_error = result.error
        return {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "result": result.payload,
        }
