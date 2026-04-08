import asyncio
import json
import os
import socket
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from ai_node.config.bootstrap_config import BOOTSTRAP_PORT, BOOTSTRAP_TOPIC, create_bootstrap_config
from ai_node.execution.gateway import ExecutionGateway
from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.config.provider_credentials_config import summarize_provider_credentials
from ai_node.core_api.budget_declaration_client import BudgetDeclarationClient
from ai_node.core_api.trust_status_client import TrustStatusClient
from ai_node.providers.openai_model_catalog import select_representative_openai_model_ids
from ai_node.prompts import PromptRegistry
from ai_node.config.task_capability_selection_config import DECLARABLE_TASK_FAMILIES, create_task_capability_selection_config
from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.runtime.provider_resolver import ProviderResolver
from ai_node.runtime.internal_scheduler import InternalScheduler
from ai_node.runtime.service_manager import NullServiceManager
from ai_node.runtime.capability_resolver import load_task_graph
from ai_node.runtime.execution_telemetry import ExecutionTelemetryPublisher
from ai_node.runtime.task_execution_service import TaskExecutionService
from ai_node.runtime.capability_declaration_runner import (
    STATUS_HEARTBEAT_INTERVAL_SECONDS,
    STATUS_TELEMETRY_INTERVAL_SECONDS,
)
from ai_node.supervisor import SupervisorApiClient
from ai_node.time_utils import local_now, local_now_iso


class CapabilityDeclarationPrerequisiteError(ValueError):
    def __init__(self, *, payload: dict) -> None:
        self.payload = payload
        super().__init__(str(payload.get("message") or "capability declaration prerequisites are not satisfied"))


def _mask_grant_name(value: object) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if len(normalized) <= 10:
        return normalized[:2] + ("*" * max(len(normalized) - 4, 0)) + normalized[-2:]
    return normalized[:6] + ("*" * max(len(normalized) - 10, 1)) + normalized[-4:]


def _short_grant_name(value: object, *, scope_kind: object = None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    parts = [part for part in normalized.split(":") if part]
    scope = str(scope_kind or (parts[-1] if parts else "")).strip().lower() or "grant"
    candidate = parts[-2] if len(parts) >= 2 else normalized
    candidate_alnum = "".join(ch for ch in str(candidate) if ch.isalnum())
    suffix = candidate_alnum[-4:] if len(candidate_alnum) >= 4 else candidate_alnum
    if suffix:
        return f"{scope} {suffix}".strip()
    return scope


class NodeRuntimeMetrics:
    def __init__(self, *, window_s: float = 60.0, max_samples: int = 4000) -> None:
        self._window_s = float(window_s)
        self._max_samples = max(100, int(max_samples))
        self._samples: deque[tuple[float, float, bool]] = deque()
        self._lock = Lock()
        self._last_cpu_sample: tuple[float, float] | None = None

    def record_request(self, *, duration_ms: float, status_code: int) -> None:
        now = time.monotonic()
        is_error = int(status_code) >= 400
        with self._lock:
            self._samples.append((now, float(duration_ms), is_error))
            self._prune_locked(now)
            if len(self._samples) > self._max_samples:
                while len(self._samples) > self._max_samples:
                    self._samples.popleft()

    def snapshot(self) -> dict[str, float]:
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            durations = [item[1] for item in self._samples]
            count = len(durations)
            errors = sum(1 for item in self._samples if item[2])
            rps = (count / self._window_s) if self._window_s > 0 else 0.0
            p95 = self._p95_ms(durations)
            error_rate = (errors / count) if count else 0.0
            cpu_percent = self._cpu_percent_locked()
        mem_percent = self._mem_percent()
        payload: dict[str, float] = {
            "rps": round(rps, 2),
            "error_rate": round(error_rate, 3),
        }
        if p95 is not None:
            payload["latency_ms_p95"] = round(p95, 2)
        if cpu_percent is not None:
            payload["cpu_percent"] = round(cpu_percent, 2)
        if mem_percent is not None:
            payload["mem_percent"] = round(mem_percent, 2)
        return payload

    def _prune_locked(self, now: float) -> None:
        while self._samples and (now - self._samples[0][0]) > self._window_s:
            self._samples.popleft()

    def _p95_ms(self, durations: list[float]) -> float | None:
        if not durations:
            return None
        sorted_vals = sorted(durations)
        idx = max(0, int(round(0.95 * len(sorted_vals) + 0.5)) - 1)
        idx = min(idx, len(sorted_vals) - 1)
        return float(sorted_vals[idx])

    def _cpu_percent_locked(self) -> float | None:
        sample = self._read_cpu_times()
        if sample is None:
            return None
        total, idle = sample
        if self._last_cpu_sample is None:
            self._last_cpu_sample = (total, idle)
            return None
        last_total, last_idle = self._last_cpu_sample
        self._last_cpu_sample = (total, idle)
        delta_total = total - last_total
        if delta_total <= 0:
            return None
        delta_idle = idle - last_idle
        usage = (delta_total - delta_idle) / delta_total
        return max(0.0, min(100.0, usage * 100.0))

    @staticmethod
    def _read_cpu_times() -> tuple[float, float] | None:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as handle:
                first = handle.readline()
        except OSError:
            return None
        if not first.startswith("cpu "):
            return None
        parts = first.strip().split()
        if len(parts) < 5:
            return None
        try:
            values = [float(item) for item in parts[1:]]
        except ValueError:
            return None
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0.0)
        return total, idle

    @staticmethod
    def _mem_percent() -> float | None:
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                raw = handle.readlines()
        except OSError:
            return None
        total = None
        available = None
        for line in raw:
            if line.startswith("MemTotal:"):
                total = float(line.split()[1]) * 1024.0
            elif line.startswith("MemAvailable:"):
                available = float(line.split()[1]) * 1024.0
            if total is not None and available is not None:
                break
        if total is None or available is None or total <= 0:
            return None
        used = max(total - available, 0.0)
        return max(0.0, min(100.0, (used / total) * 100.0))


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
        budget_state_store=None,
        client_usage_store=None,
        trust_status_client=None,
        budget_declaration_client=None,
        execution_gateway=None,
        provider_runtime_manager=None,
        budget_manager=None,
        notification_service=None,
        service_manager=None,
        task_execution_service=None,
        internal_scheduler=None,
        supervisor_client=None,
        node_hostname: str | None = None,
        node_api_base_url: str | None = None,
        node_ui_endpoint: str | None = None,
        node_software_version: str | None = None,
        protocol_version: str | None = None,
        provider_refresh_interval_seconds: int = 900,
        mqtt_recovery_store=None,
        operational_mqtt_health_check_interval_seconds: int = 10,
        operational_mqtt_health_normal_interval_seconds: int = 300,
        operational_mqtt_health_fast_window_seconds: int = 300,
        operational_mqtt_restart_delay_seconds: int = 10,
        operational_mqtt_restart_max_attempts: int = 3,
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
        self._prompt_registry = None
        self._budget_state_store = budget_state_store
        self._client_usage_store = client_usage_store
        self._trust_status_client = trust_status_client or TrustStatusClient(logger=logger)
        self._budget_declaration_client = budget_declaration_client or BudgetDeclarationClient(logger=logger)
        self._execution_gateway = execution_gateway or ExecutionGateway()
        self._provider_runtime_manager = provider_runtime_manager
        self._budget_manager = budget_manager
        self._notification_service = notification_service
        self._service_manager = service_manager or NullServiceManager()
        self._task_execution_service = task_execution_service
        self._internal_scheduler = internal_scheduler or InternalScheduler(logger=logger)
        self._supervisor_client = supervisor_client or SupervisorApiClient()
        self._node_hostname = node_hostname
        self._node_api_base_url = node_api_base_url
        self._node_ui_endpoint = node_ui_endpoint
        self._node_software_version = node_software_version
        self._protocol_version = protocol_version
        self._provider_refresh_interval_seconds = max(int(provider_refresh_interval_seconds), 60)
        self._mqtt_recovery_store = mqtt_recovery_store
        self._operational_mqtt_health_check_interval_seconds = max(int(operational_mqtt_health_check_interval_seconds), 5)
        self._operational_mqtt_health_normal_interval_seconds = max(
            int(operational_mqtt_health_normal_interval_seconds), 60
        )
        self._operational_mqtt_health_fast_window_seconds = max(
            int(operational_mqtt_health_fast_window_seconds), 0
        )
        self._operational_mqtt_restart_delay_seconds = max(int(operational_mqtt_restart_delay_seconds), 1)
        self._operational_mqtt_restart_max_attempts = max(int(operational_mqtt_restart_max_attempts), 1)
        self._startup_mode = startup_mode
        self._trusted_runtime_context = trusted_runtime_context or {}
        self._runtime_metrics = NodeRuntimeMetrics()
        self._operational_mqtt_fast_until = local_now() + timedelta(
            seconds=self._operational_mqtt_health_fast_window_seconds
        )
        self._phase2_diag = Phase2DiagnosticsLogger(logger)
        self._bootstrap_config = None
        self._provider_selection_config = None
        self._provider_credentials_summary = None
        self._task_capability_selection_config = None
        self._prompt_service_state = None
        self._node_id = None
        self._identity_state = "unknown"
        self._supervisor_registered = False
        self._supervisor_last_error = None
        self._supervisor_last_seen = None
        self._load_identity()
        self._rehydrate_trusted_state()
        self._load_provider_selection_config()
        self._load_provider_credentials_summary()
        self._load_task_capability_selection_config()
        self._load_prompt_service_state()
        self._load_existing_config()
        self._register_background_scheduler_tasks()

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
        canonical = set(DECLARABLE_TASK_FAMILIES)
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
        provider_budget_limits = {}
        supported_providers = {"cloud": [], "local": [], "future": []}
        selected_task_families = []
        budget_status = self.budget_state_payload()
        if isinstance(provider_config, dict):
            providers = provider_config.get("providers") if isinstance(provider_config.get("providers"), dict) else {}
            enabled_providers = list(providers.get("enabled") or [])
            provider_budget_limits = dict(providers.get("budget_limits") or {})
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
                "budget_limits": provider_budget_limits,
                "supported": supported_providers,
            },
            "task_capability_selection": {
                "configured": task_capability_config is not None,
                "selected_count": len(selected_task_families),
                "selected": selected_task_families,
                "available": list(DECLARABLE_TASK_FAMILIES),
            },
            "budget_policy": budget_status,
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

    def _rehydrate_trusted_state(self) -> None:
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        if not isinstance(trust_state, dict):
            return

        trust_node_id = str(trust_state.get("node_id") or "").strip()
        if (
            not self._is_non_empty_string(self._node_id)
            and trust_node_id
            and self._node_identity_store is not None
            and hasattr(self._node_identity_store, "load_or_create")
        ):
            try:
                payload = self._node_identity_store.load_or_create(migration_node_id=trust_node_id)
            except TypeError:
                payload = self._node_identity_store.load_or_create()
            if isinstance(payload, dict) and self._is_non_empty_string(payload.get("node_id")):
                self._node_id = str(payload.get("node_id")).strip()
                self._identity_state = "valid"

        if not self._is_non_empty_string(self._node_id) and trust_node_id:
            self._node_id = trust_node_id
            self._identity_state = "valid"

        if not isinstance(self._trusted_runtime_context, dict):
            self._trusted_runtime_context = {}
        if not self._trusted_runtime_context and trust_node_id:
            self._trusted_runtime_context = {
                "node_id": trust_node_id,
                "paired_core_id": str(trust_state.get("paired_core_id") or "").strip(),
                "core_api_endpoint": str(trust_state.get("core_api_endpoint") or "").strip(),
                "operational_mqtt_host": str(trust_state.get("operational_mqtt_host") or "").strip(),
                "operational_mqtt_port": trust_state.get("operational_mqtt_port"),
                "pairing_timestamp": str(trust_state.get("registration_timestamp") or "").strip(),
            }
        if (
            trust_node_id
            and self._startup_mode == "bootstrap_onboarding"
            and self._is_non_empty_string(self._trusted_runtime_context.get("paired_core_id"))
        ):
            self._startup_mode = "trusted_resume"

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
            self._prompt_registry = None
            return
        self._prompt_registry = PromptRegistry(store=self._prompt_service_state_store, logger=self._logger)
        self._prompt_service_state = self._prompt_registry.snapshot()

    @staticmethod
    def _now_iso() -> str:
        return local_now_iso()

    def status_payload(self) -> dict:
        self._rehydrate_trusted_state()
        self._sync_core_support_status()
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
            "api_metrics": self._resource_usage_payload(),
            "provider_selection_configured": self._provider_selection_config is not None,
            "provider_credentials": self.provider_credentials_payload(provider_id="openai"),
            "task_capability_selection_configured": self._task_capability_selection_config is not None,
            "capability_setup": capability_setup_contract,
            "capability_declaration": capability_context,
            "operational_mqtt_recovery": self.operational_mqtt_recovery_payload(),
            "internal_scheduler": self.internal_scheduler_payload(),
            "prompt_service_state": self.prompt_service_state_payload(),
            "services": self.service_status_payload().get("services"),
        }

    def internal_scheduler_payload(self) -> dict:
        if self._internal_scheduler is None or not hasattr(self._internal_scheduler, "snapshot"):
            return {"configured": False, "scheduler_status": "unavailable", "tasks": {}}
        snapshot = self._internal_scheduler.snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {})}

    def operational_mqtt_recovery_payload(self) -> dict:
        if self._mqtt_recovery_store is None or not hasattr(self._mqtt_recovery_store, "snapshot"):
            return {
                "configured": False,
                "active": False,
                "attempt_count": 0,
                "max_attempts": self._operational_mqtt_restart_max_attempts,
                "last_error": None,
                "last_checked_at": None,
                "last_restart_requested_at": None,
                "next_restart_not_before": None,
                "exhausted": False,
            }
        snapshot = self._mqtt_recovery_store.snapshot()
        return {"configured": True, **(snapshot if isinstance(snapshot, dict) else {})}

    def _sync_core_support_status(self) -> None:
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        if not isinstance(trust_state, dict):
            return
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        trust_token = str(trust_state.get("node_trust_token") or "").strip()
        core_api_endpoint = str(trust_state.get("core_api_endpoint") or "").strip()
        if not node_id or not trust_token or not core_api_endpoint:
            return
        state = self._lifecycle.get_state()
        if state in {
            NodeLifecycleState.UNCONFIGURED,
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            NodeLifecycleState.BOOTSTRAP_CONNECTED,
            NodeLifecycleState.CORE_DISCOVERED,
            NodeLifecycleState.REGISTRATION_PENDING,
            NodeLifecycleState.PENDING_APPROVAL,
        }:
            return
        if self._trust_status_client is None or not hasattr(self._trust_status_client, "fetch"):
            return
        try:
            support_result = self._trust_status_client.fetch(
                core_api_endpoint=core_api_endpoint,
                trust_token=trust_token,
                node_id=node_id,
            )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[trust-status-check-failed] %s", {"node_id": node_id, "error": str(exc)})
            return
        if support_result.status == "removed":
            self._reset_for_core_removal(payload=support_result.payload)

    @staticmethod
    def _delete_store_file(store) -> None:
        path = getattr(store, "_path", None)
        if isinstance(path, Path) and path.exists():
            path.unlink()

    @classmethod
    def _clear_persisted_store(cls, store) -> None:
        if store is None:
            return
        if hasattr(store, "clear") and callable(getattr(store, "clear")):
            store.clear()
            return
        cls._delete_store_file(store)

    def _reset_for_core_removal(self, *, payload: dict) -> None:
        if hasattr(self._logger, "warning"):
            self._logger.warning(
                "[core-node-removed] %s",
                {
                    "node_id": payload.get("node_id") or self._node_id,
                    "support_state": payload.get("support_state"),
                    "message": payload.get("message"),
                },
            )
        if self._bootstrap_runner is not None and hasattr(self._bootstrap_runner, "stop"):
            self._bootstrap_runner.stop()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "cancel"):
            self._onboarding_runtime.cancel()
        self._bootstrap_config = None
        if self._config_path.exists():
            self._config_path.unlink()
        self._delete_store_file(self._trust_state_store)
        self._delete_store_file(self._node_identity_store)
        self._delete_store_file(self._governance_state_store)
        self._delete_store_file(self._prompt_service_state_store)
        if self._capability_runner is not None and hasattr(self._capability_runner, "clear_local_state_for_reonboarding"):
            self._capability_runner.clear_local_state_for_reonboarding()
        self._trusted_runtime_context = {}
        self._node_id = None
        self._identity_state = "unknown"
        self._startup_mode = "bootstrap_onboarding"
        self._lifecycle.reset_to_unconfigured({"source": "core_node_removed"})

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
        if self._prompt_registry is not None:
            self._prompt_service_state = self._prompt_registry.snapshot()
        if not isinstance(self._prompt_service_state, dict):
            return {"configured": False, "state": None}
        prompts = self._prompt_service_state.get("prompt_services")
        prompt_list = prompts if isinstance(prompts, list) else []
        return {
            "configured": True,
            "state": self._prompt_service_state,
            "summary": {
                "prompt_count": len(prompt_list),
                "review_due_count": len(
                    [
                        item
                        for item in prompt_list
                        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "review_due"
                    ]
                ),
                "active_count": len(
                    [
                        item
                        for item in prompt_list
                        if isinstance(item, dict) and str(item.get("status") or "").strip().lower() == "active"
                    ]
                ),
            },
        }

    def budget_state_payload(self) -> dict:
        if self._budget_manager is None:
            return {"configured": False, "policy_status": "unconfigured", "grant_count": 0, "grants": []}
        return self._budget_manager.status_payload()

    def client_usage_payload(self) -> dict:
        if self._client_usage_store is None or not hasattr(self._client_usage_store, "summary_payload"):
            return {"configured": False, "current_month": local_now_iso()[:7], "clients": []}
        payload = self._client_usage_store.summary_payload()
        return self._attach_client_grants(payload=payload)

    def _attach_client_grants(self, *, payload: dict) -> dict:
        clients = list(payload.get("clients") or []) if isinstance(payload, dict) else []
        budget_state = self.budget_state_payload()
        grants = list(budget_state.get("grants") or []) if isinstance(budget_state, dict) else []
        if not grants:
            governance_bundle = self._governance_bundle_payload()
            governance_budget_policy = {}
            if isinstance(governance_bundle.get("budget_policy"), dict):
                governance_budget_policy = governance_bundle.get("budget_policy") or {}
            elif isinstance(governance_bundle.get("raw_response"), dict):
                raw_response = governance_bundle.get("raw_response") or {}
                nested_bundle = raw_response.get("governance_bundle") if isinstance(raw_response.get("governance_bundle"), dict) else {}
                governance_budget_policy = nested_bundle.get("budget_policy") if isinstance(nested_bundle.get("budget_policy"), dict) else {}
            grants = list(governance_budget_policy.get("grants") or []) if isinstance(governance_budget_policy, dict) else []
        enriched_clients = []
        for client in clients:
            client_payload = dict(client) if isinstance(client, dict) else {}
            customer_id = str(client_payload.get("customer_id") or "").strip()
            client_id = str(client_payload.get("client_id") or "").strip()
            client_payload["grant"] = self._select_client_grant(
                grants=grants,
                customer_id=customer_id or None,
                client_id=client_id or None,
            )
            enriched_clients.append(client_payload)
        return {**(payload if isinstance(payload, dict) else {}), "clients": enriched_clients}

    @staticmethod
    def _select_client_grant(*, grants: list[dict], customer_id: str | None, client_id: str | None) -> dict | None:
        customer_key = str(customer_id or "").strip()
        client_key = str(client_id or "").strip()
        matched = None
        node_scope_grants: list[dict] = []
        for grant in grants:
            if not isinstance(grant, dict):
                continue
            scope_kind = str(grant.get("scope_kind") or "").strip().lower()
            subject_id = str(grant.get("subject_id") or "").strip()
            if scope_kind == "customer" and customer_key and subject_id == customer_key:
                matched = grant
                break
            if scope_kind == "service" and client_key and subject_id == client_key:
                matched = grant
                break
            if scope_kind == "node" and str(grant.get("status") or "").strip().lower() == "active":
                node_scope_grants.append(grant)
        if matched is None:
            matched = node_scope_grants[0] if len(node_scope_grants) == 1 else None
        if matched is None:
            return None
        return {
            "grant_display_name": _short_grant_name(matched.get("grant_id"), scope_kind=matched.get("scope_kind")),
            "grant_name": _mask_grant_name(matched.get("grant_id")),
            "grant_id": matched.get("grant_id"),
            "scope_kind": matched.get("scope_kind"),
            "subject_id": matched.get("subject_id"),
            "valid_from": matched.get("period_start"),
            "valid_to": matched.get("period_end"),
            "status": matched.get("status"),
            "budget_cents": ((matched.get("limits") or {}).get("max_cost_cents") if isinstance(matched.get("limits"), dict) else None),
        }

    def register_prompt_service(
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
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.create_prompt(
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
        return self.prompt_service_state_payload()

    def update_prompt_service(
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
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.update_prompt(
            prompt_id=prompt_id,
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
        return self.prompt_service_state_payload()

    def get_prompt_service(self, *, prompt_id: str) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        return {"configured": True, "prompt": self._prompt_registry.get_prompt(prompt_id=prompt_id)}

    def transition_prompt_service(self, *, prompt_id: str, state: str, reason: str | None = None) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.transition_prompt(prompt_id=prompt_id, state=state, reason=reason)
        return self.prompt_service_state_payload()

    def update_prompt_probation(self, *, prompt_id: str, action: str, reason: str | None = None) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.update_probation(prompt_id=prompt_id, action=action, reason=reason)
        return self.prompt_service_state_payload()

    def review_prompt_service(
        self,
        *,
        prompt_id: str,
        reviewed_by: str | None = None,
        review_reason: str | None = None,
        state: str | None = "active",
    ) -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        self._prompt_service_state = self._prompt_registry.review_prompt(
            prompt_id=prompt_id,
            reviewed_by=reviewed_by,
            review_reason=review_reason,
            state=state,
        )
        return self.prompt_service_state_payload()

    def migrate_prompt_services_to_review_due(self, *, reason: str = "policy_migration_review_due") -> dict:
        if self._prompt_registry is None:
            raise ValueError("prompt service state store is not configured")
        migrated = self._prompt_registry.migrate_all_to_review_due(reason=reason)
        self._prompt_service_state = {
            key: value for key, value in migrated.items() if key != "migration"
        }
        payload = self.prompt_service_state_payload()
        payload["migration"] = migrated.get("migration") if isinstance(migrated, dict) else None
        return payload

    def authorize_execution(
        self,
        *,
        prompt_id: str,
        task_family: str,
        prompt_version: str | None = None,
        requested_by: str | None = None,
        service_id: str | None = None,
        customer_id: str | None = None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        inputs: dict | None = None,
    ) -> dict:
        if self._prompt_registry is not None:
            self._prompt_service_state = self._prompt_registry.snapshot()
        state = self._prompt_service_state if isinstance(self._prompt_service_state, dict) else None
        result = self._execution_gateway.authorize(
            prompt_id=prompt_id,
            task_family=task_family,
            prompt_services_state=state,
            prompt_version=prompt_version,
            requested_by=requested_by,
            service_id=service_id,
            customer_id=customer_id,
            requested_provider=requested_provider,
            requested_model=requested_model,
            inputs=inputs,
        )
        if self._prompt_registry is not None and prompt_id:
            self._prompt_registry.record_authorization(
                prompt_id=prompt_id,
                allowed=result.allowed,
                reason=result.reason,
                used_at=self._now_iso(),
            )
            self._prompt_service_state = self._prompt_registry.snapshot()
        return {
            "allowed": result.allowed,
            "reason": result.reason,
            "prompt_id": result.prompt_id,
            "task_family": result.task_family,
            "prompt_version": result.prompt_version,
            "prompt_state": result.prompt_state,
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

    def record_request_metrics(self, *, duration_ms: float, status_code: int) -> None:
        if self._runtime_metrics is None:
            return
        self._runtime_metrics.record_request(duration_ms=duration_ms, status_code=status_code)

    def _resource_usage_payload(self) -> dict:
        if self._runtime_metrics is None:
            return {}
        return dict(self._runtime_metrics.snapshot())

    def _supervisor_runtime_state_payload(self) -> dict:
        state = self._lifecycle.get_state()
        runtime_state = "starting"
        lifecycle_state = state.value
        health_status = "unknown"
        running = True
        if state == NodeLifecycleState.OPERATIONAL:
            runtime_state = "running"
            lifecycle_state = "running"
            health_status = "healthy"
        elif state == NodeLifecycleState.DEGRADED:
            runtime_state = "running"
            lifecycle_state = "degraded"
            health_status = "unhealthy"
        elif state == NodeLifecycleState.UNCONFIGURED:
            runtime_state = "stopped"
            lifecycle_state = "stopped"
            health_status = "unknown"
            running = False
        return {
            "runtime_state": runtime_state,
            "lifecycle_state": lifecycle_state,
            "health_status": health_status,
            "running": running,
            "desired_state": "running",
        }

    def _supervisor_runtime_payload(self) -> dict:
        trust_state = self._trust_state_payload()
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        node_name = str(trust_state.get("node_name") or node_id or "Hexe AI Node").strip()
        node_type = str(trust_state.get("node_type") or "ai-node").strip() or "ai-node"
        host_id = socket.gethostname()
        state_payload = self._supervisor_runtime_state_payload()
        runtime_metadata = {
            "node_software_version": self._node_software_version,
            "protocol_version": self._protocol_version,
            "startup_mode": self._startup_mode,
            "paired_core_id": str(trust_state.get("paired_core_id") or "").strip() or None,
            "core_api_endpoint": str(trust_state.get("core_api_endpoint") or "").strip() or None,
        }
        return {
            "node_id": node_id,
            "node_name": node_name,
            "node_type": node_type,
            "host_id": host_id,
            "hostname": self._node_hostname or host_id,
            "api_base_url": self._node_api_base_url,
            "ui_base_url": self._node_ui_endpoint,
            **state_payload,
            "resource_usage": self._resource_usage_payload(),
            "runtime_metadata": runtime_metadata,
        }

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
            budget_manager=self._budget_manager,
            client_usage_store=self._client_usage_store,
            execution_gateway=self._execution_gateway,
            prompt_registry=self._prompt_registry,
            prompt_services_state_provider=lambda: (
                self._prompt_registry.snapshot() if self._prompt_registry is not None else {}
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

    async def refresh_budget_policy(self) -> dict:
        if self._budget_manager is None:
            raise ValueError("budget manager is not configured")
        return await self._budget_manager.refresh_policy_from_core(
            trust_state=self._trust_state_payload(),
            governance_bundle=self._governance_bundle_payload(),
        )

    @staticmethod
    def _build_budget_declaration_available_models(report: dict | None, provider_id: str) -> list[dict]:
        if not isinstance(report, dict):
            return []
        normalized_provider_id = str(provider_id or "").strip().lower()
        providers = report.get("providers") if isinstance(report.get("providers"), list) else []
        for provider_entry in providers:
            if not isinstance(provider_entry, dict):
                continue
            entry_provider_id = str(provider_entry.get("provider") or provider_entry.get("provider_id") or "").strip().lower()
            if entry_provider_id != normalized_provider_id:
                continue
            available_models = []
            for model_entry in provider_entry.get("models") or []:
                if not isinstance(model_entry, dict):
                    continue
                model_id = str(model_entry.get("id") or model_entry.get("model_id") or "").strip()
                if not model_id:
                    continue
                status = str(model_entry.get("status") or "available").strip().lower()
                if status not in {"available", "degraded"}:
                    continue
                payload = {"model_id": model_id}
                pricing = model_entry.get("pricing")
                if isinstance(pricing, dict):
                    payload["pricing"] = pricing
                latency_metrics = model_entry.get("latency_metrics")
                if isinstance(latency_metrics, dict):
                    payload["latency_metrics"] = latency_metrics
                available_models.append(payload)
            return available_models
        return []

    def _provider_capability_report_payload(self) -> dict:
        capability_payload = (
            self._capability_runner.status_payload()
            if self._capability_runner is not None and hasattr(self._capability_runner, "status_payload")
            else {}
        )
        report = capability_payload.get("provider_capability_report") if isinstance(capability_payload, dict) else {}
        return report if isinstance(report, dict) else {}

    def _build_budget_declaration_payload(self, *, provider_id: str) -> dict:
        provider_payload = self.provider_selection_payload()
        providers = provider_payload.get("config", {}).get("providers") if isinstance(provider_payload, dict) else {}
        enabled_providers = providers.get("enabled") if isinstance(providers, dict) else []
        budget_limits = providers.get("budget_limits") if isinstance(providers, dict) else {}
        normalized_provider_id = str(provider_id or "").strip().lower()
        if normalized_provider_id not in [str(item).strip().lower() for item in (enabled_providers or [])]:
            raise ValueError(f"{normalized_provider_id} must be enabled before declaring budget")
        provider_budget = budget_limits.get(normalized_provider_id) if isinstance(budget_limits, dict) else None
        if not isinstance(provider_budget, dict):
            raise ValueError(f"{normalized_provider_id} budget must be saved before declaring to Core")
        max_cost_cents = provider_budget.get("max_cost_cents")
        if not isinstance(max_cost_cents, int) or max_cost_cents <= 0:
            raise ValueError(f"{normalized_provider_id} budget must be a positive whole number of cents")
        period = str(provider_budget.get("period") or "monthly").strip().lower()
        if period not in {"weekly", "monthly"}:
            raise ValueError("provider budget period must be weekly or monthly")
        report = self._provider_capability_report_payload()
        return {
            "service_capacity": {
                "service": "ai.inference",
                "period": period,
                "limits": {"max_cost_cents": max_cost_cents},
            },
            "provider_intelligence": [
                {
                    "provider": normalized_provider_id,
                    "capacity": {
                        "period": period,
                        "limits": {"max_cost_cents": max_cost_cents},
                    },
                    "available_models": self._build_budget_declaration_available_models(report, normalized_provider_id),
                }
            ],
            "node_available": True,
            "observed_at": str(report.get("generated_at") or local_now_iso()).strip(),
        }

    async def declare_budget_to_core(self, *, provider_id: str = "openai") -> dict:
        trust_state = self._trust_state_payload()
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        trust_token = str(trust_state.get("node_trust_token") or "").strip()
        core_api_endpoint = str(trust_state.get("core_api_endpoint") or "").strip()
        if not node_id or not trust_token or not core_api_endpoint:
            raise ValueError("trusted Core connection is required before declaring budget")
        declaration_payload = self._build_budget_declaration_payload(provider_id=provider_id)
        result = await self._budget_declaration_client.submit_declaration(
            core_api_endpoint=core_api_endpoint,
            trust_token=trust_token,
            node_id=node_id,
            declaration_payload=declaration_payload,
        )
        return {
            "status": result.status,
            "retryable": result.retryable,
            "error": result.error,
            "provider_id": str(provider_id or "").strip().lower(),
            "declaration_payload": declaration_payload,
            "result": result.payload,
        }

    def restart_service(self, *, target: str) -> dict:
        if self._service_manager is None or not hasattr(self._service_manager, "restart"):
            raise ValueError("service manager is not configured")
        result = self._service_manager.restart(target=target)
        return {"status": "ok", **result, "services": self._service_manager.get_status()}

    def update_provider_selection(self, *, openai_enabled: bool, provider_budget_limits: dict | None = None) -> dict:
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
        normalized_budget_limits: dict[str, dict[str, int | str]] = {}
        if isinstance(provider_budget_limits, dict):
            supported = providers.get("supported") if isinstance(providers.get("supported"), dict) else {}
            supported_ids = {
                str(item).strip().lower()
                for group in ("cloud", "local", "future")
                for item in list(supported.get(group) or [])
                if str(item).strip()
            }
            for provider_id, limit_payload in provider_budget_limits.items():
                normalized_provider_id = str(provider_id or "").strip().lower()
                if normalized_provider_id not in supported_ids or not isinstance(limit_payload, dict):
                    continue
                max_cost_cents = limit_payload.get("max_cost_cents")
                if max_cost_cents in (None, ""):
                    continue
                period = str(limit_payload.get("period") or "monthly").strip().lower()
                if period not in {"weekly", "monthly"}:
                    raise ValueError("provider budget period must be weekly or monthly")
                normalized_budget_limits[normalized_provider_id] = {
                    "max_cost_cents": max(int(max_cost_cents), 0),
                    "period": period,
                }
        providers["budget_limits"] = normalized_budget_limits
        self._provider_selection_store.save(payload)
        self._provider_selection_config = payload
        self._phase2_diag.provider_selection(
            {
                "source": "node_control_api",
                "enabled_providers": providers["enabled"],
                "provider_budget_limits": normalized_budget_limits,
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
                "generated_at": local_now_iso(),
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
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
        }

    def openai_provider_model_capabilities_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_capabilities_payload"):
            return {
                "provider_id": "openai",
                "classification_model": None,
                "entries": [],
                "generated_at": local_now_iso(),
                "source": "provider_model_capabilities",
            }
        payload = self._provider_runtime_manager.openai_model_capabilities_payload()
        entries = payload.get("entries") if isinstance(payload, dict) and isinstance(payload.get("entries"), list) else []
        return {
            "provider_id": "openai",
            "classification_model": payload.get("classification_model") if isinstance(payload, dict) else None,
            "entries": entries,
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
            "source": str(payload.get("source") or "provider_model_capabilities").strip()
            if isinstance(payload, dict)
            else "provider_model_capabilities",
        }

    def openai_model_features_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_model_features_payload"):
            return {
                "schema_version": "1.0",
                "generated_at": local_now_iso(),
                "entries": [],
                "source": "provider_model_features",
            }
        payload = self._provider_runtime_manager.openai_model_features_payload()
        if not isinstance(payload, dict):
            return {
                "schema_version": "1.0",
                "generated_at": local_now_iso(),
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
                "generated_at": local_now_iso(),
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
                "generated_at": local_now_iso(),
                "source": "node_capabilities",
            }
        return payload

    def openai_enabled_models_payload(self) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "openai_enabled_models_payload"):
            return {
                "provider_id": "openai",
                "models": [],
                "generated_at": local_now_iso(),
                "source": "provider_enabled_models",
            }
        payload = self._provider_runtime_manager.openai_enabled_models_payload()
        models = payload.get("models") if isinstance(payload, dict) and isinstance(payload.get("models"), list) else []
        return {
            "provider_id": "openai",
            "models": models,
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
            "source": str(payload.get("source") or "provider_enabled_models").strip()
            if isinstance(payload, dict)
            else "provider_enabled_models",
        }

    @staticmethod
    def _resolved_task_families_from_capability_payload(payload: dict | None) -> list[str]:
        if not isinstance(payload, dict):
            return []
        resolved = payload.get("enabled_task_capabilities") or payload.get("resolved_tasks") or []
        if not isinstance(resolved, list):
            return []
        normalized = sorted({str(item).strip() for item in resolved if str(item).strip()})
        return normalized

    def save_openai_enabled_models(self, *, model_ids: list[str]) -> dict:
        if self._provider_runtime_manager is None or not hasattr(self._provider_runtime_manager, "save_openai_enabled_models"):
            raise ValueError("openai enabled model persistence is not configured")
        payload = self._provider_runtime_manager.save_openai_enabled_models(model_ids=model_ids)
        return {
            "provider_id": "openai",
            **(payload if isinstance(payload, dict) else {}),
        }

    async def update_openai_enabled_models_with_redeclaration(self, *, model_ids: list[str]) -> dict:
        before_payload = self.node_capabilities_payload()
        before_tasks = self._resolved_task_families_from_capability_payload(before_payload)
        response = self.save_openai_enabled_models(model_ids=model_ids)
        after_payload = self.node_capabilities_payload()
        after_tasks = self._resolved_task_families_from_capability_payload(after_payload)
        task_surface_changed = before_tasks != after_tasks
        declaration: dict
        if task_surface_changed:
            declaration = await self.redeclare_capabilities(reason="enabled_models_changed", force=False)
        else:
            declaration = {"status": "unchanged", "reason": "enabled_models_no_task_change"}
        return {
            **response,
            "task_surface_changed": task_surface_changed,
            "previous_resolved_tasks": before_tasks,
            "resolved_tasks": after_tasks,
            "declaration": declaration,
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
            "generated_at": str(payload.get("generated_at") or local_now_iso()).strip()
            if isinstance(payload, dict)
            else local_now_iso(),
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
            "internal_scheduler": self.internal_scheduler_payload(),
            "classification_model": resolved.get("classification_model"),
            "last_declaration_payload": capability_status.get("last_manifest_payload"),
            "last_declaration_result": capability_status.get("last_declaration_result"),
        }

    def _register_background_scheduler_tasks(self) -> None:
        if self._internal_scheduler is None or not hasattr(self._internal_scheduler, "register_interval_task"):
            return
        self._internal_scheduler.register_interval_task(
            task_id="provider_capability_refresh",
            display_name="Provider Capability Refresh",
            interval_seconds=self._provider_refresh_interval_seconds,
            schedule_name="4_times_a_day",
            task_kind="provider_specific_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="heartbeat",
            display_name="HB",
            interval_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            schedule_name="heartbeat_5_seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="supervisor_heartbeat",
            display_name="Supervisor HB",
            interval_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            schedule_name="heartbeat_5_seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._internal_scheduler.register_interval_task(
            task_id="telemetry",
            display_name="Telemetry",
            interval_seconds=STATUS_TELEMETRY_INTERVAL_SECONDS,
            schedule_name="telemetry_60_seconds",
            task_kind="local_recurring",
            readiness_critical=False,
        )
        self._sync_operational_mqtt_health_schedule()

    def _operational_mqtt_health_schedule_definition(self) -> dict:
        lifecycle_state = self._lifecycle.get_state()
        recovery_snapshot = self.operational_mqtt_recovery_payload()
        within_fast_window = local_now() < self._operational_mqtt_fast_until
        fast_states = {
            NodeLifecycleState.TRUSTED,
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_FAILED_RETRY_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_IN_PROGRESS,
            NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED,
            NodeLifecycleState.DEGRADED,
        }
        fast_mode = (
            lifecycle_state in fast_states
            or bool(recovery_snapshot.get("active"))
            or bool(recovery_snapshot.get("exhausted"))
            or (lifecycle_state == NodeLifecycleState.OPERATIONAL and within_fast_window)
        )
        if fast_mode:
            interval_seconds = self._operational_mqtt_health_check_interval_seconds
            if interval_seconds == 10:
                return {
                    "interval_seconds": interval_seconds,
                    "schedule_name": "every_10_seconds",
                    "schedule_detail": "Every 10 seconds",
                }
            return {
                "interval_seconds": interval_seconds,
                "schedule_name": "interval_seconds",
                "schedule_detail": f"Every {interval_seconds} seconds",
            }
        interval_seconds = self._operational_mqtt_health_normal_interval_seconds
        if interval_seconds == 300:
            return {
                "interval_seconds": interval_seconds,
                "schedule_name": "every_5_minutes",
                "schedule_detail": "00:05, 00:10, 00:15, ...",
            }
        return {
            "interval_seconds": interval_seconds,
            "schedule_name": "interval_seconds",
            "schedule_detail": f"Every {interval_seconds} seconds",
        }

    def _sync_operational_mqtt_health_schedule(self) -> None:
        if self._internal_scheduler is None or not hasattr(self._internal_scheduler, "register_interval_task"):
            return
        schedule = self._operational_mqtt_health_schedule_definition()
        self._internal_scheduler.register_interval_task(
            task_id="operational_mqtt_health",
            display_name="Operational MQTT Health",
            interval_seconds=int(schedule["interval_seconds"]),
            schedule_name=str(schedule["schedule_name"]),
            schedule_detail=schedule.get("schedule_detail"),
            task_kind="local_recurring",
            readiness_critical=False,
        )

    def _extend_operational_mqtt_fast_window(self) -> None:
        self._operational_mqtt_fast_until = local_now() + timedelta(
            seconds=self._operational_mqtt_health_fast_window_seconds
        )

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
        self._start_bootstrap_listener_if_available()
        try:
            result = await self.refresh_provider_capabilities(force_refresh=False)
            if hasattr(self._logger, "info"):
                self._logger.info(
                    "[provider-intelligence-refresh-startup] %s",
                    {
                        "status": result.get("status"),
                        "changed": result.get("changed"),
                        "core_submission": result.get("core_submission"),
                    },
                )
        except Exception as exc:
            if hasattr(self._logger, "warning"):
                self._logger.warning("[provider-intelligence-refresh-startup-error] %s", {"error": str(exc)})
        self._notify_back_online()
        if self._internal_scheduler is not None and hasattr(self._internal_scheduler, "start_interval_task"):
            self._internal_scheduler.start_interval_task(
                task_id="provider_capability_refresh",
                coroutine_factory=self._provider_refresh_job_once,
                initial_delay_seconds=self._provider_refresh_interval_seconds,
            )
            self._internal_scheduler.start_interval_task(
                task_id="heartbeat",
                coroutine_factory=self._heartbeat_job_once,
                initial_delay_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            )
            self._internal_scheduler.start_interval_task(
                task_id="supervisor_heartbeat",
                coroutine_factory=self._supervisor_heartbeat_job_once,
                initial_delay_seconds=STATUS_HEARTBEAT_INTERVAL_SECONDS,
            )
            self._internal_scheduler.start_interval_task(
                task_id="telemetry",
                coroutine_factory=self._status_telemetry_job_once,
                initial_delay_seconds=STATUS_TELEMETRY_INTERVAL_SECONDS,
            )
            self._internal_scheduler.start_interval_task(
                task_id="operational_mqtt_health",
                coroutine_factory=self._operational_mqtt_health_job_once,
                initial_delay_seconds=0,
            )

    def _notify_back_online(self) -> None:
        if self._notification_service is None or not hasattr(self._notification_service, "notify"):
            return
        trust_state = self._trust_state_payload()
        node_id = str(trust_state.get("node_id") or self._node_id or "").strip()
        node_name = str(trust_state.get("node_name") or "").strip() or node_id
        if not node_id:
            return
        self._notification_service.notify(
            title=f"{node_name} is back online",
            message=f"{node_name} {node_id} is back online.",
            kind="event",
            severity="success",
            priority="high",
            urgency="notification",
            component="node_control_api",
            label="Hexe AI Node",
            event_type="node_back_online",
            dedupe_key=f"node-back-online:{node_id}",
            data={"node_id": node_id, "node_name": node_name},
            trust_state=trust_state,
        )

    async def stop_background_jobs(self) -> None:
        if self._internal_scheduler is not None and hasattr(self._internal_scheduler, "stop_all"):
            await self._internal_scheduler.stop_all()

    async def _provider_refresh_job_once(self) -> dict:
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
        return result

    async def _status_telemetry_job_once(self) -> dict | None:
        if self._capability_runner is None or not hasattr(self._capability_runner, "emit_periodic_status_telemetry"):
            return {"status": "skipped", "reason": "capability_runner_not_configured"}
        result = await self._capability_runner.emit_periodic_status_telemetry()
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[status-telemetry-job] %s",
                {"published": bool((result or {}).get("published")), "result": result},
            )
        return result

    async def _heartbeat_job_once(self) -> dict | None:
        if self._capability_runner is None or not hasattr(self._capability_runner, "emit_periodic_heartbeat"):
            return {"status": "skipped", "reason": "capability_runner_not_configured"}
        result = await self._capability_runner.emit_periodic_heartbeat()
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[heartbeat-job] %s",
                {"published": bool((result or {}).get("published")), "result": result},
            )
        return result

    async def _supervisor_heartbeat_job_once(self) -> dict | None:
        if self._supervisor_client is None:
            return {"status": "skipped", "reason": "supervisor_client_not_configured"}
        payload = self._supervisor_runtime_payload()
        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            return {"status": "skipped", "reason": "missing_node_id"}
        health = await asyncio.to_thread(self._supervisor_client.health)
        if not isinstance(health, dict):
            self._supervisor_registered = False
            self._supervisor_last_error = "supervisor_unreachable"
            return {"status": "skipped", "reason": "supervisor_unreachable"}
        status = str(health.get("status") or "").strip().lower()
        ready = health.get("ready")
        if status not in {"ok", "healthy"} or (ready is not None and not bool(ready)):
            self._supervisor_registered = False
            self._supervisor_last_error = "supervisor_not_ready"
            return {"status": "skipped", "reason": "supervisor_not_ready"}
        if not self._supervisor_registered:
            registered = await asyncio.to_thread(self._supervisor_client.register_runtime, payload)
            if not isinstance(registered, dict):
                self._supervisor_last_error = "supervisor_register_failed"
                return {"status": "error", "reason": "supervisor_register_failed"}
            self._supervisor_registered = True
        heartbeat_payload = {
            "node_id": payload.get("node_id"),
            "host_id": payload.get("host_id"),
            "hostname": payload.get("hostname"),
            "api_base_url": payload.get("api_base_url"),
            "ui_base_url": payload.get("ui_base_url"),
            "runtime_state": payload.get("runtime_state"),
            "lifecycle_state": payload.get("lifecycle_state"),
            "health_status": payload.get("health_status"),
            "running": payload.get("running"),
            "resource_usage": payload.get("resource_usage", {}),
            "runtime_metadata": payload.get("runtime_metadata", {}),
        }
        heartbeat = await asyncio.to_thread(self._supervisor_client.heartbeat_runtime, heartbeat_payload)
        if not isinstance(heartbeat, dict):
            self._supervisor_registered = False
            self._supervisor_last_error = "supervisor_heartbeat_failed"
            return {"status": "error", "reason": "supervisor_heartbeat_failed"}
        self._supervisor_last_error = None
        self._supervisor_last_seen = local_now_iso()
        return {"status": "ok", "supervisor": {"last_seen_at": self._supervisor_last_seen}}

    async def _operational_mqtt_health_job_once(self) -> dict | None:
        result = await self.check_operational_mqtt_health_once()
        if hasattr(self._logger, "info") and result is not None:
            self._logger.info("[operational-mqtt-health-job] %s", result)
        return result

    async def check_operational_mqtt_health_once(self) -> dict | None:
        lifecycle_state = self._lifecycle.get_state()
        self._sync_operational_mqtt_health_schedule()
        monitorable_states = {
            NodeLifecycleState.TRUSTED,
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            NodeLifecycleState.CAPABILITY_DECLARATION_ACCEPTED,
            NodeLifecycleState.OPERATIONAL,
            NodeLifecycleState.DEGRADED,
        }
        recovery_snapshot = self.operational_mqtt_recovery_payload()
        if lifecycle_state not in monitorable_states:
            if recovery_snapshot.get("configured") and recovery_snapshot.get("active"):
                self._mqtt_recovery_store.clear()
            return {
                "status": "skipped",
                "reason": "lifecycle_not_monitorable",
                "lifecycle_state": lifecycle_state.value,
            }
        if self._capability_runner is None or not hasattr(self._capability_runner, "check_operational_mqtt_health_once"):
            return {
                "status": "skipped",
                "reason": "capability_runner_not_configured",
                "lifecycle_state": lifecycle_state.value,
            }

        health = await self._capability_runner.check_operational_mqtt_health_once()
        if not isinstance(health, dict):
            return {
                "status": "skipped",
                "reason": "trust_state_unavailable",
                "lifecycle_state": lifecycle_state.value,
            }
        if health.get("healthy"):
            if recovery_snapshot.get("active") or recovery_snapshot.get("exhausted"):
                if self._mqtt_recovery_store is not None and hasattr(self._mqtt_recovery_store, "clear"):
                    self._mqtt_recovery_store.clear()
                if (
                    lifecycle_state == NodeLifecycleState.DEGRADED
                    and self._capability_runner is not None
                    and hasattr(self._capability_runner, "recover_from_degraded")
                ):
                    try:
                        recovery = self._capability_runner.recover_from_degraded()
                    except ValueError:
                        recovery = {"status": "skipped", "reason": "degraded_recovery_unavailable"}
                    if self._lifecycle.get_state() == NodeLifecycleState.OPERATIONAL:
                        self._extend_operational_mqtt_fast_window()
                    self._sync_operational_mqtt_health_schedule()
                    return {
                        "status": "healthy",
                        "lifecycle_state": self._lifecycle.get_state().value,
                        "health": health,
                        "recovery": recovery,
                    }
            self._sync_operational_mqtt_health_schedule()
            return {"status": "healthy", "lifecycle_state": lifecycle_state.value, "health": health}

        error = str(health.get("last_error") or "operational_mqtt_not_ready")
        if (
            lifecycle_state != NodeLifecycleState.DEGRADED
            and self._lifecycle.can_transition_to(NodeLifecycleState.DEGRADED)
        ):
            self._lifecycle.transition_to(
                NodeLifecycleState.DEGRADED,
                {"source": "operational_mqtt_health_monitor", "reason": error},
            )
        if self._capability_runner is not None and hasattr(self._capability_runner, "mark_operational_mqtt_unhealthy"):
            self._capability_runner.mark_operational_mqtt_unhealthy(error=error)
        self._sync_operational_mqtt_health_schedule()

        if self._mqtt_recovery_store is None or not hasattr(self._mqtt_recovery_store, "record_restart_requested"):
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "reason": "mqtt_recovery_store_not_configured",
            }

        active_snapshot = self._mqtt_recovery_store.note_unhealthy(
            error=error,
            max_attempts=self._operational_mqtt_restart_max_attempts,
        )
        if int(active_snapshot.get("attempt_count") or 0) >= int(active_snapshot.get("max_attempts") or 0):
            exhausted = self._mqtt_recovery_store.mark_exhausted(
                error=error,
                max_attempts=self._operational_mqtt_restart_max_attempts,
            )
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "recovery": exhausted,
                "reason": "restart_attempts_exhausted",
            }

        if self._service_manager is None or not hasattr(self._service_manager, "schedule_restart"):
            exhausted = self._mqtt_recovery_store.mark_exhausted(
                error=error,
                max_attempts=self._operational_mqtt_restart_max_attempts,
            )
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "recovery": exhausted,
                "reason": "service_manager_cannot_schedule_restart",
            }
        try:
            scheduled_restart = self._service_manager.schedule_restart(
                target="backend",
                delay_seconds=self._operational_mqtt_restart_delay_seconds,
            )
        except Exception as exc:
            exhausted = self._mqtt_recovery_store.mark_exhausted(
                error=f"{error}; restart_schedule_failed: {exc}",
                max_attempts=self._operational_mqtt_restart_max_attempts,
            )
            return {
                "status": "unhealthy",
                "lifecycle_state": self._lifecycle.get_state().value,
                "health": health,
                "restart_scheduled": False,
                "recovery": exhausted,
                "reason": "restart_schedule_failed",
            }

        recovery = self._mqtt_recovery_store.record_restart_requested(
            error=error,
            delay_seconds=self._operational_mqtt_restart_delay_seconds,
            max_attempts=self._operational_mqtt_restart_max_attempts,
        )
        await asyncio.sleep(self._operational_mqtt_restart_delay_seconds + 1)
        return {
            "status": "unhealthy",
            "lifecycle_state": self._lifecycle.get_state().value,
            "health": health,
            "restart_scheduled": True,
            "scheduled_restart": scheduled_restart,
            "recovery": recovery,
        }

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

    def _start_bootstrap_listener_if_available(self) -> None:
        if self._bootstrap_runner is None:
            return
        if self._bootstrap_config is not None:
            self._start_bootstrap_runner_if_available()
            return
        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        if not isinstance(trust_state, dict):
            return
        bootstrap_host = str(
            trust_state.get("bootstrap_mqtt_host") or trust_state.get("operational_mqtt_host") or ""
        ).strip()
        node_name = str(trust_state.get("node_name") or "").strip()
        if not bootstrap_host or not node_name:
            return
        self._bootstrap_runner.start(
            bootstrap_host=bootstrap_host,
            port=BOOTSTRAP_PORT,
            topic=BOOTSTRAP_TOPIC,
            node_name=node_name,
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

    def handle_node_identity_change(self, node_id: str) -> None:
        normalized = str(node_id or "").strip()
        if not normalized:
            raise ValueError("node_id is required")
        self._node_id = normalized
        self._identity_state = "valid"
        if self._capability_runner is not None and hasattr(self._capability_runner, "update_node_id"):
            self._capability_runner.update_node_id(normalized)

    def rerequest_trust(self) -> dict:
        current_state = self._lifecycle.get_state()
        if current_state in {
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            NodeLifecycleState.BOOTSTRAP_CONNECTED,
            NodeLifecycleState.CORE_DISCOVERED,
            NodeLifecycleState.REGISTRATION_PENDING,
            NodeLifecycleState.PENDING_APPROVAL,
        }:
            raise ValueError("trust re-request is unavailable while onboarding is already in progress")

        trust_state = (
            self._trust_state_store.load()
            if self._trust_state_store is not None and hasattr(self._trust_state_store, "load")
            else None
        )
        bootstrap_host = ""
        node_name = ""
        if isinstance(trust_state, dict):
            bootstrap_host = str(
                trust_state.get("bootstrap_mqtt_host") or trust_state.get("operational_mqtt_host") or ""
            ).strip()
            node_name = str(trust_state.get("node_name") or "").strip()
        if not bootstrap_host and self._bootstrap_config is not None:
            bootstrap_host = str(self._bootstrap_config.bootstrap_host or "").strip()
        if not node_name and self._bootstrap_config is not None:
            node_name = str(self._bootstrap_config.node_name or "").strip()
        if not bootstrap_host:
            raise ValueError("bootstrap host is unavailable for trust re-request")
        if not node_name:
            raise ValueError("node name is unavailable for trust re-request")

        if self._bootstrap_runner is not None and hasattr(self._bootstrap_runner, "stop"):
            self._bootstrap_runner.stop()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "cancel"):
            self._onboarding_runtime.cancel()
        if self._onboarding_runtime is not None and hasattr(self._onboarding_runtime, "prepare_retrust"):
            self._onboarding_runtime.prepare_retrust(allow_identity_reset_on_duplicate=True)

        self._bootstrap_config = create_bootstrap_config(
            {
                "bootstrap_host": bootstrap_host,
                "node_name": node_name,
            }
        )
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(
                {
                    "bootstrap_host": self._bootstrap_config.bootstrap_host,
                    "node_name": self._bootstrap_config.node_name,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self._clear_persisted_store(self._trust_state_store)
        self._clear_persisted_store(self._governance_state_store)
        if self._capability_runner is not None and hasattr(self._capability_runner, "clear_local_state_for_reonboarding"):
            self._capability_runner.clear_local_state_for_reonboarding()
        self._trusted_runtime_context = {}
        self._startup_mode = "bootstrap_onboarding"
        self._lifecycle.reset_to_unconfigured({"source": "trust_rerequest"})
        self._lifecycle.transition_to(
            NodeLifecycleState.BOOTSTRAP_CONNECTING,
            {"source": "trust_rerequest"},
        )
        self._start_bootstrap_runner_if_available()
        return {
            "status": "started",
            "flow": "trust_rerequest",
            "lifecycle_state": self._lifecycle.get_state().value,
            "bootstrap_host": self._bootstrap_config.bootstrap_host,
            "node_name": self._bootstrap_config.node_name,
            "node_id": self._node_id,
        }


class OnboardingInitiateRequest(BaseModel):
    mqtt_host: str
    node_name: str


class ProviderSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openai_enabled: bool
    provider_budget_limits: dict[str, dict[str, int | str | None]] | None = None


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


class BudgetDeclarationRequest(BaseModel):
    provider_id: str = "openai"


class RefreshTriggerRequest(BaseModel):
    force_refresh: bool = True


class PromptServiceRegisterRequest(BaseModel):
    prompt_id: str
    service_id: str
    task_family: str
    prompt_name: str | None = None
    owner_service: str | None = None
    owner_client_id: str | None = None
    privacy_class: str = "internal"
    access_scope: str = "service"
    allowed_services: list[str] | None = None
    allowed_clients: list[str] | None = None
    allowed_customers: list[str] | None = None
    execution_policy: dict | None = None
    provider_preferences: dict | None = None
    constraints: dict | None = None
    definition: dict | None = None
    version: str | None = None
    status: str = "active"
    metadata: dict | None = None


class PromptServiceUpdateRequest(BaseModel):
    prompt_name: str | None = None
    owner_service: str | None = None
    owner_client_id: str | None = None
    task_family: str | None = None
    privacy_class: str | None = None
    access_scope: str | None = None
    allowed_services: list[str] | None = None
    allowed_clients: list[str] | None = None
    allowed_customers: list[str] | None = None
    execution_policy: dict | None = None
    provider_preferences: dict | None = None
    constraints: dict | None = None
    definition: dict | None = None
    version: str | None = None
    metadata: dict | None = None


class PromptProbationRequest(BaseModel):
    action: str
    reason: str | None = None


class PromptLifecycleRequest(BaseModel):
    state: str
    reason: str | None = None


class PromptReviewRequest(BaseModel):
    reviewed_by: str | None = None
    review_reason: str | None = None
    state: str | None = "active"


class PromptReviewDueMigrationRequest(BaseModel):
    reason: str | None = "policy_migration_review_due"


class ExecutionAuthorizeRequest(BaseModel):
    prompt_id: str
    task_family: str
    prompt_version: str | None = None
    requested_by: str | None = None
    service_id: str | None = None
    customer_id: str | None = None
    requested_provider: str | None = None
    requested_model: str | None = None
    inputs: dict | None = None


def create_node_control_app(*, state: NodeControlState, logger) -> FastAPI:
    app = FastAPI(title="Hexe AI Node Control API", version="0.1.0")
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

    @app.middleware("http")
    async def _metrics_middleware(request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            if hasattr(state, "record_request_metrics"):
                state.record_request_metrics(duration_ms=duration_ms, status_code=status_code)

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
                "/api/budgets/state",
                "/api/budgets/declare",
                "/api/budgets/refresh",
                "/api/capabilities/providers/refresh",
                "/api/node/retrust",
                "/api/node/recover",
                "/api/prompts/services",
                "/api/prompts/services/{prompt_id}",
                "/api/prompts/services/{prompt_id}/lifecycle",
                "/api/prompts/services/{prompt_id}/probation",
                "/api/execution/authorize",
                "/api/services/status",
                "/api/services/restart",
                "/debug/providers",
                "/debug/providers/models",
                "/debug/providers/metrics",
                "/debug/prompts",
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
            response = state.update_provider_selection(
                openai_enabled=payload.openai_enabled,
                provider_budget_limits=payload.provider_budget_limits,
            )
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
            response = await state.update_openai_enabled_models_with_redeclaration(model_ids=payload.model_ids)
            await state.notify_workflow_request(
                workflow_request="openai_enabled_models_update",
                workflow_status="done",
                details={
                    "model_count": len(response.get("models") or []),
                    "task_surface_changed": bool(response.get("task_surface_changed")),
                    "resolved_task_count": len(response.get("resolved_tasks") or []),
                    "declaration_status": (response.get("declaration") or {}).get("status"),
                    "declaration_reason": (response.get("declaration") or {}).get("reason"),
                },
            )
            return response
        except ValueError as exc:
            await state.notify_workflow_request(
                workflow_request="openai_enabled_models_update",
                workflow_status="stopped",
                details={"error": str(exc)},
            )
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
    async def post_openai_model_capabilities_refresh(
        x_admin_token: str | None = Header(default=None, alias="X-Synthia-Admin-Token")
    ):
        try:
            require_admin(x_admin_token)
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
    async def post_capability_rebuild(
        x_admin_token: str | None = Header(default=None, alias="X-Synthia-Admin-Token")
    ):
        try:
            require_admin(x_admin_token)
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
        x_admin_token: str | None = Header(default=None, alias="X-Synthia-Admin-Token"),
    ):
        try:
            require_admin(x_admin_token)
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

    @app.get("/api/budgets/state")
    def get_budget_state():
        return state.budget_state_payload()

    @app.get("/api/usage/clients")
    def get_client_usage():
        return state.client_usage_payload()

    @app.post("/api/budgets/declare")
    async def post_budget_declare(payload: BudgetDeclarationRequest):
        try:
            return await state.declare_budget_to_core(provider_id=payload.provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/budgets/refresh")
    async def post_budget_refresh():
        try:
            return await state.refresh_budget_policy()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/capabilities/providers/refresh")
    async def post_provider_capability_refresh(
        payload: ProviderCapabilityRefreshRequest,
        x_admin_token: str | None = Header(default=None, alias="X-Synthia-Admin-Token"),
    ):
        try:
            require_admin(x_admin_token)
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

    @app.post("/api/node/retrust")
    def post_node_retrust():
        try:
            return state.rerequest_trust()
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
                prompt_name=payload.prompt_name,
                owner_service=payload.owner_service,
                owner_client_id=payload.owner_client_id,
                privacy_class=payload.privacy_class,
                access_scope=payload.access_scope,
                allowed_services=payload.allowed_services,
                allowed_clients=payload.allowed_clients,
                allowed_customers=payload.allowed_customers,
                execution_policy=payload.execution_policy,
                provider_preferences=payload.provider_preferences,
                constraints=payload.constraints,
                definition=payload.definition,
                version=payload.version,
                status=payload.status,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/prompts/services/{prompt_id}")
    def get_prompt_service(prompt_id: str):
        try:
            return state.get_prompt_service(prompt_id=prompt_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/prompts/services/{prompt_id}")
    def put_prompt_service(prompt_id: str, payload: PromptServiceUpdateRequest):
        try:
            return state.update_prompt_service(
                prompt_id=prompt_id,
                prompt_name=payload.prompt_name,
                owner_service=payload.owner_service,
                owner_client_id=payload.owner_client_id,
                task_family=payload.task_family,
                privacy_class=payload.privacy_class,
                access_scope=payload.access_scope,
                allowed_services=payload.allowed_services,
                allowed_clients=payload.allowed_clients,
                allowed_customers=payload.allowed_customers,
                execution_policy=payload.execution_policy,
                provider_preferences=payload.provider_preferences,
                constraints=payload.constraints,
                metadata=payload.metadata,
                definition=payload.definition,
                version=payload.version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/services/{prompt_id}/lifecycle")
    def post_prompt_lifecycle(prompt_id: str, payload: PromptLifecycleRequest):
        try:
            return state.transition_prompt_service(prompt_id=prompt_id, state=payload.state, reason=payload.reason)
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

    @app.post("/api/prompts/services/{prompt_id}/review")
    def post_prompt_review(prompt_id: str, payload: PromptReviewRequest):
        try:
            return state.review_prompt_service(
                prompt_id=prompt_id,
                reviewed_by=payload.reviewed_by,
                review_reason=payload.review_reason,
                state=payload.state,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/prompts/services/migrations/review-due")
    def post_prompt_review_due_migration(payload: PromptReviewDueMigrationRequest):
        try:
            return state.migrate_prompt_services_to_review_due(reason=payload.reason or "policy_migration_review_due")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/execution/authorize")
    def post_execution_authorize(payload: ExecutionAuthorizeRequest):
        return state.authorize_execution(
            prompt_id=payload.prompt_id,
            task_family=payload.task_family,
            prompt_version=payload.prompt_version,
            requested_by=payload.requested_by,
            service_id=payload.service_id,
            customer_id=payload.customer_id,
            requested_provider=payload.requested_provider,
            requested_model=payload.requested_model,
            inputs=payload.inputs,
        )

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

    @app.get("/debug/prompts")
    def get_debug_prompts():
        return state.prompt_service_state_payload()

    @app.get("/debug/budgets")
    def get_debug_budgets():
        return state.budget_state_payload()

    @app.get("/debug/execution")
    def get_debug_execution():
        return state.execution_observability_payload()

    @app.get("/api/capabilities/diagnostics")
    def get_capability_diagnostics(x_admin_token: str | None = Header(default=None, alias="X-Synthia-Admin-Token")):
        require_admin(x_admin_token)
        return state.capability_diagnostics_payload()

    if hasattr(logger, "info"):
        logger.info("[node-control-api] FastAPI app initialized")
    return app
