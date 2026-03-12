from datetime import datetime, timezone

from ai_node.capabilities.environment_hints import collect_environment_hints
from ai_node.capabilities.manifest_schema import create_capability_manifest
from ai_node.capabilities.node_features import create_node_feature_declarations
from ai_node.capabilities.providers import create_provider_capabilities_from_selection_config
from ai_node.capabilities.task_families import create_declared_task_family_capabilities
from ai_node.core_api.capability_client import CapabilityDeclarationClient
from ai_node.core_api.governance_client import GovernanceSyncClient
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
        capability_state_store=None,
        governance_state_store=None,
        capability_client=None,
        governance_client=None,
    ) -> None:
        self._lifecycle = lifecycle
        self._logger = logger
        self._trust_store = trust_store
        self._provider_selection_store = provider_selection_store
        self._capability_state_store = capability_state_store
        self._governance_state_store = governance_state_store
        self._node_id = str(node_id).strip()
        self._capability_client = capability_client or CapabilityDeclarationClient(logger=logger)
        self._governance_client = governance_client or GovernanceSyncClient(logger=logger)
        self._status = "idle"
        self._last_error = None
        self._last_submitted_at = None
        self._accepted_profile = None
        self._governance_bundle = None
        self._load_accepted_profile()
        self._load_governance_bundle()

    def status_payload(self) -> dict:
        return {
            "status": self._status,
            "last_error": self._last_error,
            "last_submitted_at": self._last_submitted_at,
            "accepted_profile": self._accepted_profile,
            "governance_bundle": self._governance_bundle,
        }

    def _load_accepted_profile(self) -> None:
        if self._capability_state_store is None or not hasattr(self._capability_state_store, "load"):
            return
        payload = self._capability_state_store.load()
        if not isinstance(payload, dict):
            return
        self._accepted_profile = payload
        self._status = "accepted"

    def _load_governance_bundle(self) -> None:
        if self._governance_state_store is None or not hasattr(self._governance_state_store, "load"):
            return
        payload = self._governance_state_store.load()
        if not isinstance(payload, dict):
            return
        self._governance_bundle = payload

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
            accepted_payload = {
                "schema_version": "1.0",
                "accepted_declaration_version": str(
                    result.payload.get("accepted_declaration_version") or manifest.get("manifest_version") or "1.0"
                ).strip(),
                "acceptance_timestamp": str(
                    result.payload.get("accepted_at")
                    or result.payload.get("acceptance_timestamp")
                    or datetime.now(timezone.utc).isoformat()
                ).strip(),
                "accepted_profile_id": str(
                    result.payload.get("accepted_profile_id")
                    or result.payload.get("profile_id")
                    or result.payload.get("capability_profile_id")
                    or ""
                ).strip()
                or None,
                "core_restrictions": result.payload.get("core_restrictions") or result.payload.get("restrictions") or {},
                "core_notes": str(result.payload.get("core_notes") or result.payload.get("notes") or "").strip() or None,
                "raw_response": result.payload,
            }
            if self._capability_state_store is not None and hasattr(self._capability_state_store, "save"):
                self._capability_state_store.save(accepted_payload)
            self._accepted_profile = accepted_payload

            governance_result = await self._governance_client.fetch_baseline_governance(
                core_api_endpoint=str(trust_state.get("core_api_endpoint") or "").strip(),
                trust_token=str(trust_state.get("node_trust_token") or "").strip(),
                node_id=self._node_id,
            )
            if governance_result.status != "synced":
                self._lifecycle.transition_to(
                    NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
                    {
                        "source": "governance_sync",
                        "error": governance_result.error,
                        "retryable": governance_result.retryable,
                    },
                )
                self._status = "retry_pending" if governance_result.retryable else "rejected"
                self._last_error = governance_result.error
                return {
                    "status": governance_result.status,
                    "retryable": governance_result.retryable,
                    "error": governance_result.error,
                    "result": governance_result.payload,
                    "accepted_profile": accepted_payload,
                }

            governance_payload = _build_governance_payload(
                governance_payload=governance_result.payload,
                trust_state=trust_state,
            )
            if self._governance_state_store is not None and hasattr(self._governance_state_store, "save"):
                self._governance_state_store.save(governance_payload)
            self._governance_bundle = governance_payload
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
            return {
                "status": "accepted",
                "result": result.payload,
                "accepted_profile": accepted_payload,
                "governance_bundle": governance_payload,
            }

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


def _build_governance_payload(*, governance_payload: dict, trust_state: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    policy_version = str(
        governance_payload.get("policy_version")
        or governance_payload.get("baseline_policy_version")
        or trust_state.get("baseline_policy_version")
        or "1.0"
    ).strip()
    issued_timestamp = str(
        governance_payload.get("issued_timestamp")
        or governance_payload.get("issued_at")
        or governance_payload.get("policy_issued_at")
        or trust_state.get("registration_timestamp")
        or now
    ).strip()
    refresh_expectations = governance_payload.get("refresh_expectations") or {
        "recommended_interval_seconds": 900,
        "max_stale_seconds": 3600,
    }
    generic_node_class_rules = governance_payload.get("generic_node_class_rules") or governance_payload.get(
        "node_class_rules"
    ) or {}
    feature_gating_defaults = governance_payload.get("feature_gating_defaults") or governance_payload.get(
        "feature_flags"
    ) or {}
    telemetry_expectations = governance_payload.get("telemetry_expectations") or {}

    return {
        "schema_version": "1.0",
        "policy_version": policy_version,
        "issued_timestamp": issued_timestamp,
        "synced_at": now,
        "refresh_expectations": refresh_expectations if isinstance(refresh_expectations, dict) else {},
        "generic_node_class_rules": generic_node_class_rules if isinstance(generic_node_class_rules, dict) else {},
        "feature_gating_defaults": feature_gating_defaults if isinstance(feature_gating_defaults, dict) else {},
        "telemetry_expectations": telemetry_expectations if isinstance(telemetry_expectations, dict) else {},
        "raw_response": governance_payload,
    }
