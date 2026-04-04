import argparse
import asyncio
import logging
import os
import signal
import socket
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from ai_node.diagnostics.phase2_logger import Phase2DiagnosticsLogger
from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.identity.node_identity_store import NodeIdentityStore
from ai_node.config.provider_credentials_config import ProviderCredentialsStore
from ai_node.config.provider_selection_config import ProviderSelectionConfigStore
from ai_node.config.task_capability_selection_config import TaskCapabilitySelectionConfigStore
from ai_node.core_api.trust_status_client import TrustStatusClient
from ai_node.core_api.budget_policy_client import BudgetPolicyClient
from ai_node.runtime.bootstrap_mqtt_runner import BootstrapMqttRunner
from ai_node.runtime.bootstrap_timeout import BootstrapConnectTimeoutMonitor
from ai_node.runtime.budget_manager import BudgetManager
from ai_node.runtime.capability_declaration_runner import CapabilityDeclarationRunner
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app
from ai_node.runtime.onboarding_runtime import OnboardingRuntime
from ai_node.runtime.service_manager import UserSystemdServiceManager
from ai_node.runtime.user_notification_service import UserNotificationService
from ai_node.persistence.capability_state_store import CapabilityStateStore
from ai_node.persistence.governance_state_store import GovernanceStateStore
from ai_node.persistence.phase2_state_store import Phase2StateStore
from ai_node.persistence.prompt_service_state_store import PromptServiceStateStore
from ai_node.persistence.budget_state_store import BudgetStateStore
from ai_node.persistence.client_usage_store import (
    ClientUsageStore,
    aggregate_provider_execution_log,
    aggregate_provider_execution_log_by_model,
    aggregate_provider_metrics,
    aggregate_provider_metrics_by_model,
)
from ai_node.persistence.provider_capability_report_store import ProviderCapabilityReportStore
from ai_node.providers.runtime_manager import ProviderRuntimeManager
from ai_node.trust.trust_store import TrustStateStore


LOGGER = logging.getLogger("ai_node.main")
SHOULD_STOP = False


def _is_loopback_host(value: object) -> bool:
    host = str(value or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _detect_primary_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            detected = str(probe.getsockname()[0] or "").strip()
            if detected and not _is_loopback_host(detected):
                return detected
    except OSError:
        pass
    try:
        detected = str(socket.gethostbyname(socket.gethostname()) or "").strip()
        if detected and not _is_loopback_host(detected):
            return detected
    except OSError:
        pass
    return None


def _default_node_ui_endpoint(*, node_ui_endpoint: str | None, node_ui_port: int) -> str | None:
    configured = str(node_ui_endpoint or "").strip()
    if configured:
        return configured
    detected_ip = _detect_primary_ip()
    if not detected_ip:
        return None
    return f"http://{detected_ip}:{int(node_ui_port)}/"


def _default_node_hostname(node_hostname: str | None) -> str:
    configured = str(node_hostname or "").strip()
    if configured:
        return configured
    detected_ip = _detect_primary_ip()
    if detected_ip:
        return detected_ip
    return socket.gethostname()


def _default_node_api_base_url(*, node_api_base_url: str | None, api_port: int) -> str | None:
    configured = str(node_api_base_url or "").strip()
    if configured:
        return configured
    detected_ip = _detect_primary_ip()
    if not detected_ip:
        return None
    return f"http://{detected_ip}:{int(api_port)}"


def _handle_signal(signum, _frame):
    global SHOULD_STOP
    LOGGER.info("received signal %s, stopping", signum)
    SHOULD_STOP = True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hexe AI Node backend entrypoint")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one startup cycle and exit (for smoke checks)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=5.0,
        help="Heartbeat interval while running",
    )
    parser.add_argument(
        "--api-host",
        default=os.environ.get("SYNTHIA_API_HOST", "127.0.0.1"),
        help="Node control API host",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=int(os.environ.get("SYNTHIA_API_PORT", "9002")),
        help="Node control API port",
    )
    parser.add_argument(
        "--bootstrap-config-path",
        default=os.environ.get("SYNTHIA_BOOTSTRAP_CONFIG_PATH", ".run/bootstrap_config.json"),
        help="Path for persisted bootstrap setup config",
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("SYNTHIA_BACKEND_LOG_PATH", "logs/backend.log"),
        help="Backend log file path",
    )
    parser.add_argument(
        "--bootstrap-connect-timeout-seconds",
        type=float,
        default=float(os.environ.get("SYNTHIA_BOOTSTRAP_CONNECT_TIMEOUT_SECONDS", "30")),
        help="Timeout for waiting in bootstrap_connecting before degraded",
    )
    parser.add_argument(
        "--node-software-version",
        default=os.environ.get("SYNTHIA_NODE_SOFTWARE_VERSION", "0.1.0"),
        help="Node software version used during registration",
    )
    parser.add_argument(
        "--protocol-version",
        default=os.environ.get("SYNTHIA_NODE_PROTOCOL_VERSION", "1.0"),
        help="Onboarding protocol version used during registration",
    )
    parser.add_argument(
        "--node-hostname",
        default=os.environ.get("SYNTHIA_NODE_HOSTNAME", ""),
        help="Hostname sent during registration",
    )
    parser.add_argument(
        "--node-ui-endpoint",
        default=os.environ.get("SYNTHIA_NODE_UI_ENDPOINT", ""),
        help="Optional absolute node UI URL sent during registration",
    )
    parser.add_argument(
        "--node-ui-port",
        type=int,
        default=int(os.environ.get("SYNTHIA_NODE_UI_PORT", "8081")),
        help="Frontend port used when auto-building the node UI endpoint from the detected node IP",
    )
    parser.add_argument(
        "--node-api-base-url",
        default=os.environ.get("SYNTHIA_NODE_API_BASE_URL", ""),
        help="Optional absolute node API base URL sent during registration",
    )
    parser.add_argument(
        "--trust-state-path",
        default=os.environ.get("SYNTHIA_TRUST_STATE_PATH", ".run/trust_state.json"),
        help="Path to persisted trusted state",
    )
    parser.add_argument(
        "--node-identity-path",
        default=os.environ.get("SYNTHIA_NODE_IDENTITY_PATH", ".run/node_identity.json"),
        help="Path to persisted node identity state",
    )
    parser.add_argument(
        "--provider-selection-config-path",
        default=os.environ.get("SYNTHIA_PROVIDER_SELECTION_CONFIG_PATH", ".run/provider_selection_config.json"),
        help="Path to persisted provider selection config state",
    )
    parser.add_argument(
        "--provider-credentials-path",
        default=os.environ.get("SYNTHIA_PROVIDER_CREDENTIALS_PATH", ".run/provider_credentials.json"),
        help="Path to persisted provider credentials state",
    )
    parser.add_argument(
        "--task-capability-selection-config-path",
        default=os.environ.get(
            "SYNTHIA_TASK_CAPABILITY_SELECTION_CONFIG_PATH",
            ".run/task_capability_selection_config.json",
        ),
        help="Path to persisted selected task capability declarations",
    )
    parser.add_argument(
        "--capability-state-path",
        default=os.environ.get("SYNTHIA_CAPABILITY_STATE_PATH", ".run/capability_state.json"),
        help="Path to persisted accepted capability profile state",
    )
    parser.add_argument(
        "--governance-state-path",
        default=os.environ.get("SYNTHIA_GOVERNANCE_STATE_PATH", ".run/governance_state.json"),
        help="Path to persisted governance bundle state",
    )
    parser.add_argument(
        "--phase2-state-path",
        default=os.environ.get("SYNTHIA_PHASE2_STATE_PATH", ".run/phase2_state.json"),
        help="Path to persisted combined phase-2 activation state",
    )
    parser.add_argument(
        "--provider-capability-report-path",
        default=os.environ.get("SYNTHIA_PROVIDER_CAPABILITY_REPORT_PATH", ".run/provider_capability_report.json"),
        help="Path to persisted provider capability report cache",
    )
    parser.add_argument(
        "--prompt-service-state-path",
        default=os.environ.get("SYNTHIA_PROMPT_SERVICE_STATE_PATH", ".run/prompt_service_state.json"),
        help="Path to persisted prompt/service registration and probation state",
    )
    parser.add_argument(
        "--budget-state-path",
        default=os.environ.get("SYNTHIA_BUDGET_STATE_PATH", ".run/budget_state.json"),
        help="Path to persisted budget policy, grant usage, and reservation state",
    )
    parser.add_argument(
        "--provider-capability-refresh-interval-seconds",
        type=int,
        default=int(os.environ.get("SYNTHIA_PROVIDER_CAPABILITY_REFRESH_INTERVAL_SECONDS", "14400")),
        help="Provider capability refresh interval in seconds (recommended: 3600-21600)",
    )
    parser.add_argument(
        "--openai-pricing-catalog-path",
        default=os.environ.get("SYNTHIA_OPENAI_PRICING_CATALOG_PATH", "providers/openai/provider_model_pricing.json"),
        help="Path to persisted OpenAI pricing catalog cache",
    )
    parser.add_argument(
        "--openai-pricing-manual-config-path",
        default=os.environ.get("SYNTHIA_OPENAI_PRICING_MANUAL_CONFIG_PATH", "config/openai-pricing.yaml"),
        help="Path to manual OpenAI pricing YAML overrides",
    )
    parser.add_argument(
        "--openai-pricing-refresh-interval-seconds",
        type=int,
        default=int(os.environ.get("SYNTHIA_OPENAI_PRICING_REFRESH_INTERVAL_SECONDS", "86400")),
        help="OpenAI pricing refresh interval in seconds; 0 disables scheduled refresh",
    )
    parser.add_argument(
        "--openai-pricing-stale-tolerance-seconds",
        type=int,
        default=int(os.environ.get("SYNTHIA_OPENAI_PRICING_STALE_TOLERANCE_SECONDS", "172800")),
        help="Maximum pricing catalog age before cost estimation is disabled",
    )
    parser.add_argument(
        "--finalize-poll-interval-seconds",
        type=float,
        default=float(os.environ.get("SYNTHIA_FINALIZE_POLL_INTERVAL_SECONDS", "2")),
        help="Polling interval for onboarding finalize status",
    )
    return parser


def configure_logging(log_file: str) -> None:
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


def run(
    *,
    once: bool,
    interval_seconds: float,
    api_host: str = "127.0.0.1",
    api_port: int = 9002,
    bootstrap_config_path: str = ".run/bootstrap_config.json",
    log_file: str = "logs/backend.log",
    bootstrap_connect_timeout_seconds: float = 30.0,
    node_software_version: str = "0.1.0",
    protocol_version: str = "1.0",
    node_hostname: str | None = None,
    node_ui_endpoint: str | None = None,
    node_ui_port: int = 8081,
    node_api_base_url: str | None = None,
    trust_state_path: str = ".run/trust_state.json",
    node_identity_path: str = ".run/node_identity.json",
    provider_selection_config_path: str = ".run/provider_selection_config.json",
    provider_credentials_path: str = ".run/provider_credentials.json",
    task_capability_selection_config_path: str = ".run/task_capability_selection_config.json",
    capability_state_path: str = ".run/capability_state.json",
    governance_state_path: str = ".run/governance_state.json",
    phase2_state_path: str = ".run/phase2_state.json",
    provider_capability_report_path: str = ".run/provider_capability_report.json",
    prompt_service_state_path: str = ".run/prompt_service_state.json",
    budget_state_path: str = ".run/budget_state.json",
    client_usage_db_path: str = ".run/client_usage.db",
    provider_capability_refresh_interval_seconds: int = 14400,
    openai_pricing_catalog_path: str = "providers/openai/provider_model_pricing.json",
    openai_pricing_manual_config_path: str = "config/openai-pricing.yaml",
    openai_pricing_refresh_interval_seconds: int = 86400,
    openai_pricing_stale_tolerance_seconds: int = 172800,
    finalize_poll_interval_seconds: float = 2.0,
) -> int:
    configure_logging(log_file)
    LOGGER.info("[Hexe AI Node] starting backend")
    resolved_node_ui_endpoint = _default_node_ui_endpoint(
        node_ui_endpoint=node_ui_endpoint,
        node_ui_port=node_ui_port,
    )
    resolved_node_hostname = _default_node_hostname(node_hostname)
    resolved_node_api_base_url = _default_node_api_base_url(
        node_api_base_url=node_api_base_url,
        api_port=api_port,
    )
    phase2_diag = Phase2DiagnosticsLogger(LOGGER)
    trust_state_store = TrustStateStore(path=trust_state_path, logger=LOGGER)
    trust_state = trust_state_store.load()
    if isinstance(trust_state, dict):
        operational_host = str(trust_state.get("operational_mqtt_host") or "").strip()
        bootstrap_host = str(trust_state.get("bootstrap_mqtt_host") or "").strip()
        if _is_loopback_host(operational_host) and bootstrap_host and not _is_loopback_host(bootstrap_host):
            trust_state["operational_mqtt_host"] = bootstrap_host
            trust_state_store.save(trust_state)
            LOGGER.warning(
                "[trust-state-operational-host-corrected] %s",
                {
                    "from": operational_host,
                    "to": bootstrap_host,
                },
            )
    migration_node_id = None
    if isinstance(trust_state, dict):
        migration_node_id = str(trust_state.get("node_id") or "").strip() or None

    node_identity_store = NodeIdentityStore(path=node_identity_path, logger=LOGGER)
    node_identity = node_identity_store.load_or_create(migration_node_id=migration_node_id)
    provider_selection_store = ProviderSelectionConfigStore(
        path=provider_selection_config_path,
        logger=LOGGER,
    )
    provider_credentials_store = ProviderCredentialsStore(
        path=provider_credentials_path,
        logger=LOGGER,
    )
    task_capability_selection_store = TaskCapabilitySelectionConfigStore(
        path=task_capability_selection_config_path,
        logger=LOGGER,
    )
    capability_state_store = CapabilityStateStore(path=capability_state_path, logger=LOGGER)
    governance_state_store = GovernanceStateStore(path=governance_state_path, logger=LOGGER)
    phase2_state_store = Phase2StateStore(path=phase2_state_path, logger=LOGGER)
    provider_capability_report_store = ProviderCapabilityReportStore(
        path=provider_capability_report_path,
        logger=LOGGER,
    )
    budget_state_store = BudgetStateStore(path=budget_state_path, logger=LOGGER)
    client_usage_store = ClientUsageStore(path=client_usage_db_path, logger=LOGGER)
    provider_runtime_manager = ProviderRuntimeManager(
        logger=LOGGER,
        provider_selection_store=provider_selection_store,
        provider_credentials_store=provider_credentials_store,
        registry_path=os.environ.get("SYNTHIA_PROVIDER_REGISTRY_PATH", "data/provider_registry.json"),
        metrics_path=os.environ.get("SYNTHIA_PROVIDER_METRICS_PATH", "data/provider_metrics.json"),
        pricing_catalog_path=openai_pricing_catalog_path,
        pricing_manual_config_path=openai_pricing_manual_config_path,
        pricing_refresh_interval_seconds=openai_pricing_refresh_interval_seconds,
        pricing_stale_tolerance_seconds=openai_pricing_stale_tolerance_seconds,
    )
    prompt_service_state_store = PromptServiceStateStore(path=prompt_service_state_path, logger=LOGGER)
    needs_usage_seed = (
        not client_usage_store.has_usage_data()
        and client_usage_store.get_metadata(key="historical_seed_completed") != "1"
    )
    needs_model_seed = not client_usage_store.has_model_usage_data()
    if needs_usage_seed or needs_model_seed:
        prompt_state = prompt_service_state_store.load_or_create()
        budget_state = budget_state_store.load_or_create()
        prompt_services = list(prompt_state.get("prompt_services") or []) if isinstance(prompt_state, dict) else []
        primary_prompt = prompt_services[0] if prompt_services else {}
        historical_client_id = str(primary_prompt.get("service_id") or primary_prompt.get("owner_service") or "node-email").strip() or "node-email"
        historical_prompt_id = str(primary_prompt.get("prompt_id") or "prompt.email.classifier").strip() or "prompt.email.classifier"
        customer_candidates = {
            str(entry.get("customer_id") or "").strip()
            for entry in list(budget_state.get("recent_denials") or [])
            if isinstance(entry, dict) and str(entry.get("customer_id") or "").strip()
        } if isinstance(budget_state, dict) else set()
        historical_customer_id = next(iter(customer_candidates)) if len(customer_candidates) == 1 else None
        log_totals = aggregate_provider_execution_log(log_file)
        log_totals_by_model = aggregate_provider_execution_log_by_model(log_file)
        metrics_totals = aggregate_provider_metrics(provider_runtime_manager.metrics_snapshot())
        metrics_totals_by_model = aggregate_provider_metrics_by_model(provider_runtime_manager.metrics_snapshot())
        seed_used_at = str(log_totals.get("last_used_at") or local_now_iso()).strip() or local_now_iso()
        if needs_usage_seed:
            client_usage_store.seed_historical_usage(
                client_id=historical_client_id,
                prompt_id=historical_prompt_id,
                customer_id=historical_customer_id,
                calls=max(int(log_totals.get("calls") or 0), 0),
                prompt_tokens=max(int(log_totals.get("prompt_tokens") or 0), 0),
                completion_tokens=max(int(log_totals.get("completion_tokens") or 0), 0),
                total_tokens=max(int(log_totals.get("total_tokens") or 0), 0),
                cost_usd=max(float(log_totals.get("cost_usd") or 0.0), 0.0),
                used_at=seed_used_at,
            )
            delta_calls = max(int(metrics_totals.get("calls") or 0) - int(log_totals.get("calls") or 0), 0)
            delta_prompt_tokens = max(int(metrics_totals.get("prompt_tokens") or 0) - int(log_totals.get("prompt_tokens") or 0), 0)
            delta_completion_tokens = max(
                int(metrics_totals.get("completion_tokens") or 0) - int(log_totals.get("completion_tokens") or 0),
                0,
            )
            delta_total_tokens = max(int(metrics_totals.get("total_tokens") or 0) - int(log_totals.get("total_tokens") or 0), 0)
            delta_cost_usd = max(float(metrics_totals.get("cost_usd") or 0.0) - float(log_totals.get("cost_usd") or 0.0), 0.0)
            client_usage_store.seed_historical_usage(
                client_id=historical_client_id,
                prompt_id=historical_prompt_id,
                customer_id=historical_customer_id,
                calls=delta_calls,
                prompt_tokens=delta_prompt_tokens,
                completion_tokens=delta_completion_tokens,
                total_tokens=delta_total_tokens,
                cost_usd=delta_cost_usd,
                used_at=seed_used_at,
            )
        historical_model_ids = sorted(set(log_totals_by_model) | set(metrics_totals_by_model))
        if needs_model_seed:
            for model_id in historical_model_ids:
                model_log_totals = log_totals_by_model.get(model_id, {})
                model_metrics_totals = metrics_totals_by_model.get(model_id, {})
                model_seed_used_at = str(model_log_totals.get("last_used_at") or seed_used_at).strip() or seed_used_at
                client_usage_store.seed_historical_usage(
                    client_id=historical_client_id,
                    prompt_id=historical_prompt_id,
                    model_id=model_id,
                    include_aggregate=False,
                    customer_id=historical_customer_id,
                    calls=max(int(model_log_totals.get("calls") or 0), 0),
                    prompt_tokens=max(int(model_log_totals.get("prompt_tokens") or 0), 0),
                    completion_tokens=max(int(model_log_totals.get("completion_tokens") or 0), 0),
                    total_tokens=max(int(model_log_totals.get("total_tokens") or 0), 0),
                    cost_usd=max(float(model_log_totals.get("cost_usd") or 0.0), 0.0),
                    used_at=model_seed_used_at,
                )
                client_usage_store.seed_historical_usage(
                    client_id=historical_client_id,
                    prompt_id=historical_prompt_id,
                    model_id=model_id,
                    include_aggregate=False,
                    customer_id=historical_customer_id,
                    calls=max(int(model_metrics_totals.get("calls") or 0) - int(model_log_totals.get("calls") or 0), 0),
                    prompt_tokens=max(
                        int(model_metrics_totals.get("prompt_tokens") or 0)
                        - int(model_log_totals.get("prompt_tokens") or 0),
                        0,
                    ),
                    completion_tokens=max(
                        int(model_metrics_totals.get("completion_tokens") or 0)
                        - int(model_log_totals.get("completion_tokens") or 0),
                        0,
                    ),
                    total_tokens=max(
                        int(model_metrics_totals.get("total_tokens") or 0) - int(model_log_totals.get("total_tokens") or 0),
                        0,
                    ),
                    cost_usd=max(
                        float(model_metrics_totals.get("cost_usd") or 0.0)
                        - float(model_log_totals.get("cost_usd") or 0.0),
                        0.0,
                    ),
                    used_at=model_seed_used_at,
                )
        if needs_usage_seed:
            client_usage_store.set_metadata(key="historical_seed_completed", value="1")
        LOGGER.info(
            "[client-usage-seeded] %s",
            {
                "client_id": historical_client_id,
                "prompt_id": historical_prompt_id,
                "log_calls": int(log_totals.get("calls") or 0),
                "metrics_calls": int(metrics_totals.get("calls") or 0),
            },
        )
    trust_status_client = TrustStatusClient(logger=LOGGER)
    budget_policy_client = BudgetPolicyClient(logger=LOGGER)
    notification_service = UserNotificationService(
        logger=LOGGER,
        trust_state_provider=lambda: trust_state_store.load() if hasattr(trust_state_store, "load") else {},
    )
    budget_manager = BudgetManager(
        store=budget_state_store,
        logger=LOGGER,
        provider_runtime_manager=provider_runtime_manager,
        budget_policy_client=budget_policy_client,
        notification_service=notification_service,
        trust_state_provider=lambda: trust_state_store.load() if hasattr(trust_state_store, "load") else {},
    )
    LOGGER.info("[node-identity] %s", {"node_id": node_identity["node_id"], "path": node_identity_path})
    if isinstance(trust_state, dict):
        trust_node_id = str(trust_state.get("node_id") or "").strip()
        identity_node_id = str(node_identity.get("node_id") or "").strip()
        if trust_node_id and trust_node_id != identity_node_id:
            LOGGER.error(
                "[node-identity-mismatch] trust_state.node_id=%s does not match identity.node_id=%s",
                trust_node_id,
                identity_node_id,
            )
            return 1
    startup_mode = "bootstrap_onboarding"
    trusted_runtime_context = {}
    if isinstance(trust_state, dict):
        startup_mode = "trusted_resume"
        trusted_runtime_context = {
            "node_id": str(trust_state.get("node_id") or "").strip(),
            "paired_core_id": str(trust_state.get("paired_core_id") or "").strip(),
            "core_api_endpoint": str(trust_state.get("core_api_endpoint") or "").strip(),
            "operational_mqtt_host": str(trust_state.get("operational_mqtt_host") or "").strip(),
            "operational_mqtt_port": trust_state.get("operational_mqtt_port"),
            "pairing_timestamp": str(trust_state.get("registration_timestamp") or "").strip(),
        }

    monitor_ref = {"monitor": None}

    def _on_transition(transition):
        monitor = monitor_ref.get("monitor")
        if monitor is not None:
            monitor.on_transition(transition)

    lifecycle = NodeLifecycle(logger=LOGGER, on_transition=_on_transition)
    timeout_monitor = BootstrapConnectTimeoutMonitor(
        lifecycle=lifecycle,
        logger=LOGGER,
        timeout_seconds=bootstrap_connect_timeout_seconds,
    )
    monitor_ref["monitor"] = timeout_monitor
    timeout_monitor.start()
    if startup_mode == "trusted_resume":
        lifecycle.transition_to(
            NodeLifecycleState.TRUSTED,
            {"startup_mode": "trusted_resume"},
        )
        lifecycle.transition_to(
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            {"startup_mode": "trusted_resume"},
        )
        LOGGER.info(
            "[startup-path] %s",
            {
                "mode": "trusted_resume",
                "state": NodeLifecycleState.CAPABILITY_SETUP_PENDING.value,
                "paired_core_id": trusted_runtime_context.get("paired_core_id"),
            },
        )
        phase2_diag.post_trust_activation(
            {
                "mode": "trusted_resume",
                "state": NodeLifecycleState.CAPABILITY_SETUP_PENDING.value,
                "paired_core_id": trusted_runtime_context.get("paired_core_id"),
                "core_api_endpoint": trusted_runtime_context.get("core_api_endpoint"),
                "operational_mqtt_host": trusted_runtime_context.get("operational_mqtt_host"),
                "operational_mqtt_port": trusted_runtime_context.get("operational_mqtt_port"),
            }
        )
    onboarding_runtime = OnboardingRuntime(
        lifecycle=lifecycle,
        logger=LOGGER,
        node_id=node_identity["node_id"],
        node_software_version=node_software_version,
        protocol_version=protocol_version,
        hostname=resolved_node_hostname,
        ui_endpoint=resolved_node_ui_endpoint,
        api_base_url=resolved_node_api_base_url,
        trust_state_path=trust_state_path,
        finalize_poll_interval_seconds=finalize_poll_interval_seconds,
    )
    bootstrap_runner = BootstrapMqttRunner(
        lifecycle=lifecycle,
        logger=LOGGER,
        on_core_discovered=onboarding_runtime.on_core_discovered,
    )
    capability_runner = CapabilityDeclarationRunner(
        lifecycle=lifecycle,
        logger=LOGGER,
        trust_store=trust_state_store,
        provider_selection_store=provider_selection_store,
        provider_credentials_store=provider_credentials_store,
        task_capability_selection_store=task_capability_selection_store,
        node_id=node_identity["node_id"],
        node_software_version=node_software_version,
        capability_state_store=capability_state_store,
        governance_state_store=governance_state_store,
        phase2_state_store=phase2_state_store,
        provider_capability_report_store=provider_capability_report_store,
        prompt_service_state_store=prompt_service_state_store,
        provider_runtime_manager=provider_runtime_manager,
        provider_capability_refresh_interval_seconds=provider_capability_refresh_interval_seconds,
        notification_service=notification_service,
    )
    if startup_mode == "trusted_resume":
        try:
            resume_result = asyncio.run(capability_runner.resume_or_refresh_on_startup())
            LOGGER.info("[startup-resume] %s", resume_result)
        except Exception:
            LOGGER.exception("[startup-resume] failed to evaluate trusted startup resume")
    service_manager = UserSystemdServiceManager(logger=LOGGER)
    control_state = NodeControlState(
        lifecycle=lifecycle,
        config_path=bootstrap_config_path,
        logger=LOGGER,
        bootstrap_runner=bootstrap_runner,
        onboarding_runtime=onboarding_runtime,
        capability_runner=capability_runner,
        node_identity_store=node_identity_store,
        provider_selection_store=provider_selection_store,
        provider_credentials_store=provider_credentials_store,
        task_capability_selection_store=task_capability_selection_store,
        trust_state_store=trust_state_store,
        governance_state_store=governance_state_store,
        prompt_service_state_store=prompt_service_state_store,
        budget_state_store=budget_state_store,
        client_usage_store=client_usage_store,
        trust_status_client=trust_status_client,
        provider_runtime_manager=provider_runtime_manager,
        budget_manager=budget_manager,
        notification_service=notification_service,
        service_manager=service_manager,
        provider_refresh_interval_seconds=provider_capability_refresh_interval_seconds,
        startup_mode=startup_mode,
        trusted_runtime_context=trusted_runtime_context,
    )
    app = create_node_control_app(state=control_state, logger=LOGGER)
    LOGGER.info("[Hexe AI Node] phase1 modules loaded; control API active")

    if once:
        bootstrap_runner.stop()
        timeout_monitor.stop()
        LOGGER.info("[Hexe AI Node] run-once mode complete")
        return 0

    try:
        uvicorn.run(app, host=api_host, port=api_port, log_level="info", log_config=None)
    finally:
        bootstrap_runner.stop()
        timeout_monitor.stop()
    LOGGER.info("[Hexe AI Node] backend stopped cleanly")
    return 0


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    args = build_parser().parse_args()
    return run(
        once=args.once,
        interval_seconds=args.interval_seconds,
        api_host=args.api_host,
        api_port=args.api_port,
        bootstrap_config_path=args.bootstrap_config_path,
        log_file=args.log_file,
        bootstrap_connect_timeout_seconds=args.bootstrap_connect_timeout_seconds,
        node_software_version=args.node_software_version,
        protocol_version=args.protocol_version,
        node_hostname=args.node_hostname,
        node_ui_endpoint=args.node_ui_endpoint,
        node_ui_port=args.node_ui_port,
        node_api_base_url=args.node_api_base_url,
        trust_state_path=args.trust_state_path,
        node_identity_path=args.node_identity_path,
        provider_selection_config_path=args.provider_selection_config_path,
        provider_credentials_path=args.provider_credentials_path,
        task_capability_selection_config_path=args.task_capability_selection_config_path,
        capability_state_path=args.capability_state_path,
        governance_state_path=args.governance_state_path,
        phase2_state_path=args.phase2_state_path,
        provider_capability_report_path=args.provider_capability_report_path,
        prompt_service_state_path=args.prompt_service_state_path,
        budget_state_path=args.budget_state_path,
        client_usage_db_path=os.environ.get("SYNTHIA_CLIENT_USAGE_DB_PATH", ".run/client_usage.db"),
        provider_capability_refresh_interval_seconds=args.provider_capability_refresh_interval_seconds,
        openai_pricing_catalog_path=args.openai_pricing_catalog_path,
        openai_pricing_manual_config_path=args.openai_pricing_manual_config_path,
        openai_pricing_refresh_interval_seconds=args.openai_pricing_refresh_interval_seconds,
        openai_pricing_stale_tolerance_seconds=args.openai_pricing_stale_tolerance_seconds,
        finalize_poll_interval_seconds=args.finalize_poll_interval_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
