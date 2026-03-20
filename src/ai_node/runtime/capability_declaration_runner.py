from datetime import datetime, timezone

from ai_node.capabilities.environment_hints import collect_environment_hints
from ai_node.capabilities.manifest_schema import create_capability_manifest
from ai_node.capabilities.node_features import create_node_feature_declarations
from ai_node.capabilities.resolved_task_families import derive_declared_task_families
from ai_node.capabilities.provider_intelligence import (
    DEFAULT_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS,
    ProviderIntelligenceService,
    compact_provider_intelligence_report,
)
from ai_node.capabilities.providers import create_provider_capabilities_from_selection_config
from ai_node.capabilities.task_families import create_declared_task_family_capabilities
from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger
from ai_node.core_api.capability_client import CapabilityDeclarationClient
from ai_node.core_api.governance_client import GovernanceSyncClient
from ai_node.governance.freshness import evaluate_governance_freshness
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.operational_mqtt_readiness import OperationalMqttReadinessChecker
from ai_node.runtime.trusted_status_telemetry import TrustedStatusTelemetryPublisher


class CapabilityDeclarationRunner:
    def __init__(
        self,
        *,
        lifecycle: NodeLifecycle,
        logger,
        trust_store,
        provider_selection_store,
        provider_credentials_store=None,
        task_capability_selection_store=None,
        node_id: str,
        node_software_version: str = "0.1.0",
        capability_state_store=None,
        governance_state_store=None,
        phase2_state_store=None,
        provider_capability_report_store=None,
        prompt_service_state_store=None,
        capability_client=None,
        governance_client=None,
        provider_intelligence_service=None,
        provider_runtime_manager=None,
        provider_capability_refresh_interval_seconds: int = DEFAULT_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS,
        operational_readiness_checker=None,
        telemetry_publisher=None,
    ) -> None:
        self._lifecycle = lifecycle
        self._logger = logger
        self._trust_store = trust_store
        self._provider_selection_store = provider_selection_store
        self._provider_credentials_store = provider_credentials_store
        self._task_capability_selection_store = task_capability_selection_store
        self._capability_state_store = capability_state_store
        self._governance_state_store = governance_state_store
        self._phase2_state_store = phase2_state_store
        self._provider_capability_report_store = provider_capability_report_store
        self._prompt_service_state_store = prompt_service_state_store
        self._node_id = str(node_id).strip()
        self._node_software_version = str(node_software_version).strip() or "0.1.0"
        self._capability_client = capability_client or CapabilityDeclarationClient(logger=logger)
        self._governance_client = governance_client or GovernanceSyncClient(logger=logger)
        self._provider_intelligence_service = provider_intelligence_service or ProviderIntelligenceService(
            logger=logger,
            cache_store=provider_capability_report_store,
            provider_credentials_store=provider_credentials_store,
            refresh_interval_seconds=provider_capability_refresh_interval_seconds,
        )
        self._provider_runtime_manager = provider_runtime_manager
        self._operational_readiness_checker = operational_readiness_checker or OperationalMqttReadinessChecker(
            logger=logger
        )
        self._telemetry_publisher = telemetry_publisher or TrustedStatusTelemetryPublisher(logger=logger)
        self._status = "idle"
        self._last_error = None
        self._last_submitted_at = None
        self._accepted_profile = None
        self._governance_bundle = None
        self._last_manifest_summary = None
        self._last_manifest_payload = None
        self._last_declaration_result = None
        self._provider_capability_report = None
        self._provider_intelligence_last_submitted_at = None
        self._governance_status = evaluate_governance_freshness(None)
        self._governance_status["refresh_state"] = "idle"
        self._governance_status["last_refresh_error"] = None
        self._diag = Phase2DiagnosticsLogger(logger)
        self._load_accepted_profile()
        self._load_governance_bundle()
        self._load_provider_capability_report()
        self._load_phase2_state()

    def status_payload(self) -> dict:
        return {
            "status": self._status,
            "last_error": self._last_error,
            "last_submitted_at": self._last_submitted_at,
            "accepted_profile": self._accepted_profile,
            "manifest_summary": self._last_manifest_summary,
            "last_manifest_payload": self._last_manifest_payload,
            "last_declaration_result": self._last_declaration_result,
            "governance_bundle": self._governance_bundle,
            "governance_status": self._governance_status,
            "provider_capability_report": self._provider_report_payload(),
            "provider_intelligence_last_submitted_at": self._provider_intelligence_last_submitted_at,
            "operational_mqtt_readiness": (
                self._operational_readiness_checker.status_payload()
                if hasattr(self._operational_readiness_checker, "status_payload")
                else None
            ),
            "telemetry": (
                self._telemetry_publisher.status_payload() if hasattr(self._telemetry_publisher, "status_payload") else None
            ),
            "prompt_service_registry": self._prompt_service_summary(),
        }

    def _provider_report_payload(self) -> dict | None:
        if not isinstance(self._provider_capability_report, dict):
            return None
        providers = self._provider_capability_report.get("providers")
        if isinstance(providers, list) and any(
            isinstance(item, dict) and str(item.get("provider_id") or "").strip() for item in providers
        ):
            return self._provider_capability_report
        return compact_provider_intelligence_report(self._provider_capability_report)

    def _prompt_service_summary(self) -> dict:
        if self._prompt_service_state_store is None or not hasattr(self._prompt_service_state_store, "load_or_create"):
            return {"registered_count": 0, "probation_count": 0}
        payload = self._prompt_service_state_store.load_or_create()
        entries = payload.get("prompt_services") if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            entries = []
        registered = 0
        probation = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status") or "").strip().lower()
            if status == "registered":
                registered += 1
            elif status == "probation":
                probation += 1
        return {"registered_count": registered, "probation_count": probation}

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
        self._refresh_governance_status(refresh_state="loaded", last_refresh_error=None)

    def _load_provider_capability_report(self) -> None:
        if self._provider_capability_report_store is None or not hasattr(self._provider_capability_report_store, "load"):
            return
        payload = self._provider_capability_report_store.load()
        if not isinstance(payload, dict):
            return
        self._provider_capability_report = payload

    def _load_phase2_state(self) -> None:
        if self._phase2_state_store is None or not hasattr(self._phase2_state_store, "load"):
            return
        payload = self._phase2_state_store.load()
        if not isinstance(payload, dict):
            return
        if isinstance(payload.get("last_manifest_payload"), dict):
            self._last_manifest_payload = payload.get("last_manifest_payload")
        if isinstance(payload.get("last_declaration_result"), dict):
            self._last_declaration_result = payload.get("last_declaration_result")

    def _refresh_governance_status(self, *, refresh_state: str, last_refresh_error: str | None) -> None:
        status = evaluate_governance_freshness(self._governance_bundle)
        status["refresh_state"] = refresh_state
        status["last_refresh_error"] = last_refresh_error
        self._governance_status = status

    @staticmethod
    def _is_operational_mqtt_auth_failure(error: object) -> bool:
        if not isinstance(error, str):
            return False
        normalized = error.strip().lower()
        return normalized in {"connect_rc_5", "not authorised", "not authorized"}

    def _build_manifest_payload(self, *, trust_state: dict, selected_task_families: list[str] | None) -> dict:
        provider_selection = (
            self._provider_selection_store.load_or_create(openai_enabled=False)
            if self._provider_selection_store is not None and hasattr(self._provider_selection_store, "load_or_create")
            else None
        )
        providers = create_provider_capabilities_from_selection_config(provider_selection)
        resolved_provider_capabilities = (
            self._provider_runtime_manager.openai_resolved_capabilities_payload()
            if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "openai_resolved_capabilities_payload")
            else None
        )
        derived_task_families: list[str] = []
        resolved_node_tasks: list[str] = []
        resolved_node_capabilities = (
            self._provider_runtime_manager.node_capabilities_payload()
            if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "node_capabilities_payload")
            else None
        )
        if isinstance(resolved_provider_capabilities, dict):
            derived_task_families = derive_declared_task_families(resolved_capabilities=resolved_provider_capabilities)
        if isinstance(resolved_node_capabilities, dict):
            resolved_node_tasks = list(
                resolved_node_capabilities.get("enabled_task_capabilities")
                or resolved_node_capabilities.get("resolved_tasks")
                or []
            )

        manifest_task_families = (
            resolved_node_tasks
            if resolved_node_tasks
            else (
                derived_task_families
                if derived_task_families
                else create_declared_task_family_capabilities(selected_task_families)
            )
        )
        return create_capability_manifest(
            node_id=self._node_id,
            node_name=str(trust_state.get("node_name") or "ai-node").strip(),
            node_type=str(trust_state.get("node_type") or "ai-node").strip(),
            node_software_version=self._node_software_version,
            task_families=manifest_task_families,
            supported_providers=providers.get("supported"),
            enabled_providers=providers.get("enabled"),
            node_features=create_node_feature_declarations(),
            environment_hints=collect_environment_hints(),
        )

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
        task_capability_selection = (
            self._task_capability_selection_store.load_or_create()
            if self._task_capability_selection_store is not None
            and hasattr(self._task_capability_selection_store, "load_or_create")
            else None
        )
        selected_task_families = (
            list(task_capability_selection.get("selected_task_families") or [])
            if isinstance(task_capability_selection, dict)
            else None
        )
        providers = create_provider_capabilities_from_selection_config(provider_selection)
        self._diag.provider_selection(
            {
                "node_id": self._node_id,
                "enabled_providers": sorted((providers.get("enabled") or [])),
                "supported_providers": sorted((providers.get("supported") or [])),
            }
        )
        manifest = self._build_manifest_payload(trust_state=trust_state, selected_task_families=selected_task_families)
        self._diag.capability_manifest(
            {
                "node_id": self._node_id,
                "task_family_count": len(manifest.get("declared_task_families") or []),
                "enabled_provider_count": len(manifest.get("enabled_providers") or []),
                "feature_count": len((manifest.get("node_features") or {}).keys()),
            }
        )
        self._last_manifest_summary = {
            "task_families": list(manifest.get("declared_task_families") or []),
            "enabled_providers": list(manifest.get("enabled_providers") or []),
            "manifest_version": manifest.get("manifest_version"),
        }
        self._last_manifest_payload = manifest

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
        self._diag.capability_submission(
            {
                "node_id": self._node_id,
                "result_status": result.status,
                "retryable": result.retryable,
                "error": result.error,
            }
        )
        self._last_declaration_result = {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "payload": result.payload,
            "submitted_at": self._last_submitted_at,
        }

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
                "submitted_manifest": manifest,
            }
            if self._capability_state_store is not None and hasattr(self._capability_state_store, "save"):
                self._capability_state_store.save(accepted_payload)
            self._accepted_profile = accepted_payload

            governance_result = await self._governance_client.fetch_baseline_governance(
                core_api_endpoint=str(trust_state.get("core_api_endpoint") or "").strip(),
                trust_token=str(trust_state.get("node_trust_token") or "").strip(),
                node_id=self._node_id,
            )
            self._diag.governance_sync(
                {
                    "node_id": self._node_id,
                    "result_status": governance_result.status,
                    "retryable": governance_result.retryable,
                    "error": governance_result.error,
                }
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
                self._lifecycle.transition_to(
                    NodeLifecycleState.DEGRADED,
                    {"source": "governance_sync", "reason": governance_result.error or "governance_sync_failed"},
                )
                self._diag.degraded_recovery(
                    {"node_id": self._node_id, "event": "degraded", "source": "governance_sync", "error": governance_result.error}
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
            self._refresh_governance_status(refresh_state="synced", last_refresh_error=None)
            self._diag.governance_freshness(
                {
                    "node_id": self._node_id,
                    "state": self._governance_status.get("state"),
                    "active_governance_version": self._governance_status.get("active_governance_version"),
                    "last_sync_time": self._governance_status.get("last_sync_time"),
                }
            )
            self._persist_phase2_state()
            provider_intelligence_status = await self.refresh_provider_capabilities_once(
                force_refresh=True,
                submit_to_core=True,
                trust_state=trust_state,
            )

            readiness_result = await self._operational_readiness_checker.check_once(trust_state=trust_state)
            if not readiness_result.get("ready"):
                self._last_error = str(readiness_result.get("last_error") or "operational_mqtt_not_ready")
                if hasattr(self._logger, "warning"):
                    self._logger.warning(
                        "[operational-mqtt-readiness-warning] %s",
                        {
                            "node_id": self._node_id,
                            "error": self._last_error,
                            "action": "operational_transition_continues",
                        },
                    )

            self._lifecycle.transition_to(
                NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED,
                {"source": "capability_declaration_runner"},
            )
            self._lifecycle.transition_to(
                NodeLifecycleState.OPERATIONAL,
                {"source": "capability_declaration_runner"},
            )
            await self._emit_status_telemetry(
                trust_state=trust_state,
                lifecycle_state=NodeLifecycleState.OPERATIONAL.value,
                overall_status="operational",
            )
            self._status = "accepted"
            self._persist_phase2_state()
            return {
                "status": "accepted",
                "result": result.payload,
                "accepted_profile": accepted_payload,
                "governance_bundle": governance_payload,
                "provider_capability_report": self._provider_report_payload(),
                "provider_intelligence_status": provider_intelligence_status,
                "operational_mqtt_readiness": readiness_result,
            }

        self._lifecycle.transition_to(
            NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
            {
                "source": "capability_declaration_runner",
                "error": result.error,
                "retryable": result.retryable,
            },
        )
        self._lifecycle.transition_to(
            NodeLifecycleState.DEGRADED,
            {"source": "capability_declaration_runner", "reason": result.error or "capability_submission_failed"},
        )
        self._diag.degraded_recovery(
            {"node_id": self._node_id, "event": "degraded", "source": "capability_submission", "error": result.error}
        )
        self._status = "retry_pending" if result.retryable else "rejected"
        self._last_error = result.error
        return {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "result": result.payload,
        }

    async def refresh_provider_capabilities_once(
        self,
        *,
        force_refresh: bool = False,
        submit_to_core: bool = True,
        trust_state: dict | None = None,
    ) -> dict:
        provider_selection = (
            self._provider_selection_store.load_or_create(openai_enabled=False)
            if self._provider_selection_store is not None and hasattr(self._provider_selection_store, "load_or_create")
            else None
        )
        if self._provider_runtime_manager is not None and hasattr(self._provider_runtime_manager, "refresh"):
            report = await self._provider_runtime_manager.refresh()
            changed = report != (self._provider_capability_report if isinstance(self._provider_capability_report, dict) else None)
        else:
            report, changed = await self._provider_intelligence_service.build_provider_capability_report(
                provider_selection_config=provider_selection,
                force_refresh=force_refresh,
            )
        self._provider_capability_report = report
        self._persist_phase2_state()

        core_submission = {"submitted": False, "reason": None}
        can_submit = submit_to_core and isinstance(self._accepted_profile, dict)
        if can_submit:
            trust = trust_state if isinstance(trust_state, dict) else (self._trust_store.load() if self._trust_store else None)
            if isinstance(trust, dict):
                if changed:
                    result = await self._capability_client.submit_provider_intelligence(
                        core_api_endpoint=str(trust.get("core_api_endpoint") or "").strip(),
                        trust_token=str(trust.get("node_trust_token") or "").strip(),
                        node_id=self._node_id,
                        provider_intelligence_report=report,
                    )
                    core_submission = {
                        "submitted": True,
                        "status": result.status,
                        "retryable": result.retryable,
                        "error": result.error,
                    }
                    self._provider_intelligence_last_submitted_at = datetime.now(timezone.utc).isoformat()
                else:
                    core_submission = {"submitted": False, "reason": "unchanged"}
            else:
                core_submission = {"submitted": False, "reason": "missing_trust_state"}
        else:
            core_submission = {"submitted": False, "reason": "capability_not_accepted"}

        return {
            "status": "refreshed",
            "changed": changed,
            "report": self._provider_report_payload(),
            "core_submission": core_submission,
        }

    async def redeclare_if_needed(self, *, reason: str, force: bool = False) -> dict:
        if self._lifecycle.get_state() in {
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
        }:
            return await self.submit_once()
        if not isinstance(self._accepted_profile, dict):
            return {"status": "skipped", "reason": "capability_not_accepted"}
        trust_state = self._trust_store.load() if self._trust_store is not None else None
        if not isinstance(trust_state, dict):
            return {"status": "skipped", "reason": "missing_trust_state"}
        task_capability_selection = (
            self._task_capability_selection_store.load_or_create()
            if self._task_capability_selection_store is not None
            and hasattr(self._task_capability_selection_store, "load_or_create")
            else None
        )
        selected_task_families = (
            list(task_capability_selection.get("selected_task_families") or [])
            if isinstance(task_capability_selection, dict)
            else None
        )
        manifest = self._build_manifest_payload(trust_state=trust_state, selected_task_families=selected_task_families)
        if not force and isinstance(self._last_manifest_payload, dict) and manifest == self._last_manifest_payload:
            return {"status": "unchanged", "reason": reason}

        result = await self._capability_client.submit_manifest(
            core_api_endpoint=str(trust_state.get("core_api_endpoint") or "").strip(),
            trust_token=str(trust_state.get("node_trust_token") or "").strip(),
            node_id=self._node_id,
            capability_manifest=manifest,
        )
        self._last_submitted_at = datetime.now(timezone.utc).isoformat()
        self._last_manifest_payload = manifest
        self._last_manifest_summary = {
            "task_families": list(manifest.get("declared_task_families") or []),
            "enabled_providers": list(manifest.get("enabled_providers") or []),
            "manifest_version": manifest.get("manifest_version"),
        }
        self._last_declaration_result = {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "payload": result.payload,
            "submitted_at": self._last_submitted_at,
            "reason": reason,
        }
        if result.status == "accepted":
            self._accepted_profile = {
                **(self._accepted_profile or {}),
                "acceptance_timestamp": str(
                    result.payload.get("accepted_at")
                    or result.payload.get("acceptance_timestamp")
                    or datetime.now(timezone.utc).isoformat()
                ).strip(),
                "raw_response": result.payload,
                "submitted_manifest": manifest,
            }
            if self._capability_state_store is not None and hasattr(self._capability_state_store, "save"):
                self._capability_state_store.save(self._accepted_profile)
        self._persist_phase2_state()
        return {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "result": result.payload,
            "reason": reason,
            "manifest_summary": self._last_manifest_summary,
        }

    async def refresh_governance_once(self) -> dict:
        trust_state = self._trust_store.load() if self._trust_store is not None else None
        if not isinstance(trust_state, dict):
            raise ValueError("missing valid trust state for governance refresh")

        governance_result = await self._governance_client.fetch_baseline_governance(
            core_api_endpoint=str(trust_state.get("core_api_endpoint") or "").strip(),
            trust_token=str(trust_state.get("node_trust_token") or "").strip(),
            node_id=self._node_id,
        )
        if governance_result.status == "synced":
            governance_payload = _build_governance_payload(
                governance_payload=governance_result.payload,
                trust_state=trust_state,
            )
            if self._governance_state_store is not None and hasattr(self._governance_state_store, "save"):
                self._governance_state_store.save(governance_payload)
            self._governance_bundle = governance_payload
            self._refresh_governance_status(refresh_state="synced", last_refresh_error=None)
            self._diag.governance_sync(
                {
                    "node_id": self._node_id,
                    "result_status": "synced",
                    "policy_version": governance_payload.get("policy_version"),
                }
            )
            self._diag.governance_freshness(
                {
                    "node_id": self._node_id,
                    "state": self._governance_status.get("state"),
                    "active_governance_version": self._governance_status.get("active_governance_version"),
                    "last_sync_time": self._governance_status.get("last_sync_time"),
                }
            )
            self._persist_phase2_state()
            provider_refresh = await self.refresh_provider_capabilities_once(force_refresh=False, submit_to_core=True)
            return {
                "status": "synced",
                "governance_bundle": governance_payload,
                "governance_status": self._governance_status,
                "provider_capability_refresh": provider_refresh,
            }

        self._refresh_governance_status(
            refresh_state="core_temporarily_unavailable" if governance_result.retryable else "sync_rejected",
            last_refresh_error=governance_result.error,
        )
        self._diag.governance_sync(
            {
                "node_id": self._node_id,
                "result_status": governance_result.status,
                "retryable": governance_result.retryable,
                "error": governance_result.error,
            }
        )
        self._diag.governance_freshness(
            {
                "node_id": self._node_id,
                "state": self._governance_status.get("state"),
                "active_governance_version": self._governance_status.get("active_governance_version"),
                "last_sync_time": self._governance_status.get("last_sync_time"),
            }
        )
        if self._governance_status.get("state") == "stale":
            await self._emit_status_telemetry(
                trust_state=trust_state,
                lifecycle_state=self._lifecycle.get_state().value,
                overall_status="governance_stale",
            )
        return {
            "status": governance_result.status,
            "retryable": governance_result.retryable,
            "error": governance_result.error,
            "result": governance_result.payload,
            "governance_status": self._governance_status,
        }

    def recover_from_degraded(self) -> dict:
        if self._lifecycle.get_state() != NodeLifecycleState.DEGRADED:
            raise ValueError("node is not in degraded state")

        target_state = NodeLifecycleState.CAPABILITY_SETUP_PENDING
        readiness = (
            self._operational_readiness_checker.status_payload()
            if hasattr(self._operational_readiness_checker, "status_payload")
            else {}
        )
        governance_fresh = self._governance_status.get("state") == "fresh"
        operational_ready = bool(readiness.get("ready"))
        if self._accepted_profile and governance_fresh:
            target_state = NodeLifecycleState.OPERATIONAL

        self._lifecycle.transition_to(
            target_state,
            {
                "source": "capability_declaration_runner_recovery",
                "governance_state": self._governance_status.get("state"),
                "operational_mqtt_ready": operational_ready,
            },
        )
        self._diag.degraded_recovery(
            {
                "node_id": self._node_id,
                "event": "recovered",
                "target_state": target_state.value,
                "governance_state": self._governance_status.get("state"),
                "operational_mqtt_ready": operational_ready,
            }
        )
        if target_state == NodeLifecycleState.OPERATIONAL:
            self._status = "accepted"
            self._last_error = None
        else:
            self._status = "idle"
        self._persist_phase2_state()
        return {"status": "recovered", "target_state": target_state.value, "capability_status": self._status}

    async def resume_operational_if_ready(self) -> dict:
        state = self._lifecycle.get_state()
        if state != NodeLifecycleState.CAPABILITY_SETUP_PENDING:
            return {
                "resumed": False,
                "reason": "lifecycle_not_capability_setup_pending",
                "target_state": state.value,
            }
        if not isinstance(self._accepted_profile, dict):
            return {
                "resumed": False,
                "reason": "accepted_capability_missing",
                "target_state": state.value,
            }
        if self._governance_status.get("state") != "fresh":
            return {
                "resumed": False,
                "reason": "governance_not_fresh",
                "target_state": state.value,
            }

        trust_state = self._trust_store.load() if self._trust_store is not None else None
        if not isinstance(trust_state, dict):
            return {
                "resumed": False,
                "reason": "missing_valid_trust_state",
                "target_state": state.value,
            }

        readiness_result = await self._operational_readiness_checker.check_once(trust_state=trust_state)
        if not readiness_result.get("ready"):
            self._last_error = str(readiness_result.get("last_error") or "operational_mqtt_not_ready")

        self._lifecycle.transition_to(
            NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS,
            {"source": "startup_resume"},
        )
        self._lifecycle.transition_to(
            NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED,
            {"source": "startup_resume"},
        )
        self._lifecycle.transition_to(
            NodeLifecycleState.OPERATIONAL,
            {"source": "startup_resume"},
        )
        self._status = "accepted"
        await self._emit_status_telemetry(
            trust_state=trust_state,
            lifecycle_state=NodeLifecycleState.OPERATIONAL.value,
            overall_status="operational",
        )
        self._persist_phase2_state()
        return {
            "resumed": True,
            "reason": "accepted_capability_and_fresh_governance_and_ready_mqtt",
            "target_state": self._lifecycle.get_state().value,
            "operational_mqtt_readiness": readiness_result,
        }

    async def resume_or_refresh_on_startup(self) -> dict:
        resume_result = await self.resume_operational_if_ready()
        if resume_result.get("resumed"):
            return resume_result
        if resume_result.get("reason") != "governance_not_fresh":
            return resume_result
        if not isinstance(self._accepted_profile, dict):
            return resume_result

        governance_refresh = await self.refresh_governance_once()
        if governance_refresh.get("status") != "synced":
            return {
                "resumed": False,
                "reason": "governance_refresh_failed",
                "target_state": self._lifecycle.get_state().value,
                "resume_result": resume_result,
                "governance_refresh": governance_refresh,
            }

        resumed_after_refresh = await self.resume_operational_if_ready()
        if resumed_after_refresh.get("resumed"):
            return {
                **resumed_after_refresh,
                "reason": "governance_refreshed_on_startup",
                "initial_resume_result": resume_result,
                "governance_refresh": governance_refresh,
            }
        return {
            "resumed": False,
            "reason": "governance_refreshed_but_resume_blocked",
            "target_state": self._lifecycle.get_state().value,
            "initial_resume_result": resume_result,
            "governance_refresh": governance_refresh,
            "resume_result": resumed_after_refresh,
        }

    def _persist_phase2_state(self) -> None:
        if self._phase2_state_store is None or not hasattr(self._phase2_state_store, "save"):
            return
        provider_selection = (
            self._provider_selection_store.load_or_create(openai_enabled=False)
            if self._provider_selection_store is not None and hasattr(self._provider_selection_store, "load_or_create")
            else {}
        )
        payload = {
            "schema_version": "1.0",
            "enabled_provider_selection": provider_selection if isinstance(provider_selection, dict) else {},
            "accepted_capability": self._accepted_profile if isinstance(self._accepted_profile, dict) else None,
            "active_governance": self._governance_bundle if isinstance(self._governance_bundle, dict) else None,
            "provider_capability_report": (
                self._provider_report_payload()
                if isinstance(self._provider_capability_report, dict)
                else None
            ),
            "last_manifest_payload": self._last_manifest_payload if isinstance(self._last_manifest_payload, dict) else None,
            "last_declaration_result": self._last_declaration_result if isinstance(self._last_declaration_result, dict) else None,
            "timestamps": {
                "capability_declaration_timestamp": (
                    self._accepted_profile.get("acceptance_timestamp") if isinstance(self._accepted_profile, dict) else None
                ),
                "governance_sync_timestamp": (
                    self._governance_bundle.get("synced_at") if isinstance(self._governance_bundle, dict) else None
                ),
                "provider_capability_refresh_timestamp": (
                    self._provider_capability_report.get("generated_at")
                    if isinstance(self._provider_capability_report, dict)
                    else None
                ),
            },
        }
        self._phase2_state_store.save(payload)

    async def _emit_status_telemetry(
        self,
        *,
        trust_state: dict,
        lifecycle_state: str,
        overall_status: str,
        extra_payload: dict | None = None,
    ) -> dict | None:
        if self._telemetry_publisher is None or not hasattr(self._telemetry_publisher, "publish_status"):
            return None
        payload = {
            "lifecycle_state": lifecycle_state,
            "overall_status": overall_status,
            "trusted": True,
            "capability_state": self._status,
            "governance_state": self._governance_status.get("state"),
            "governance_version": self._governance_status.get("active_governance_version"),
            "operational_mqtt_ready": (
                self._operational_readiness_checker.status_payload().get("ready")
                if hasattr(self._operational_readiness_checker, "status_payload")
                else None
            ),
        }
        if isinstance(extra_payload, dict):
            payload.update(extra_payload)
        payload.update(self._prompt_service_summary())
        result = await self._telemetry_publisher.publish_status(
            trust_state=trust_state,
            node_id=self._node_id,
            payload=payload,
        )
        if not result.get("published"):
            self._last_error = str(result.get("last_error") or "telemetry_publish_failed")
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[trusted-status-telemetry-warning] %s",
                    {
                        "node_id": self._node_id,
                        "error": self._last_error,
                        "action": "lifecycle_unchanged",
                    },
                )
        return result

    async def emit_workflow_status_telemetry(self, *, workflow_request: str, workflow_status: str, details: dict | None = None) -> dict | None:
        if self._trust_store is None or not hasattr(self._trust_store, "load"):
            return None
        trust_state = self._trust_store.load()
        if not isinstance(trust_state, dict):
            return None
        normalized_request = str(workflow_request or "").strip()
        normalized_status = str(workflow_status or "").strip().lower()
        if not normalized_request or not normalized_status:
            return None
        return await self._emit_status_telemetry(
            trust_state=trust_state,
            lifecycle_state=self._lifecycle.get_state().value,
            overall_status=f"workflow_{normalized_status}",
            extra_payload={
                "event_type": "workflow_request",
                "workflow_request": normalized_request,
                "workflow_status": normalized_status,
                "workflow_details": details if isinstance(details, dict) else {},
            },
        )


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
