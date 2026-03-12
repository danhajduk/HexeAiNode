import argparse
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
from ai_node.config.provider_selection_config import ProviderSelectionConfigStore
from ai_node.runtime.bootstrap_mqtt_runner import BootstrapMqttRunner
from ai_node.runtime.bootstrap_timeout import BootstrapConnectTimeoutMonitor
from ai_node.runtime.capability_declaration_runner import CapabilityDeclarationRunner
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app
from ai_node.runtime.onboarding_runtime import OnboardingRuntime
from ai_node.persistence.capability_state_store import CapabilityStateStore
from ai_node.persistence.governance_state_store import GovernanceStateStore
from ai_node.persistence.phase2_state_store import Phase2StateStore
from ai_node.trust.trust_store import TrustStateStore


LOGGER = logging.getLogger("ai_node.main")
SHOULD_STOP = False


def _handle_signal(signum, _frame):
    global SHOULD_STOP
    LOGGER.info("received signal %s, stopping", signum)
    SHOULD_STOP = True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synthia AI Node backend entrypoint")
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
        default=os.environ.get("SYNTHIA_NODE_HOSTNAME", socket.gethostname()),
        help="Hostname sent during registration",
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
    trust_state_path: str = ".run/trust_state.json",
    node_identity_path: str = ".run/node_identity.json",
    provider_selection_config_path: str = ".run/provider_selection_config.json",
    capability_state_path: str = ".run/capability_state.json",
    governance_state_path: str = ".run/governance_state.json",
    phase2_state_path: str = ".run/phase2_state.json",
    finalize_poll_interval_seconds: float = 2.0,
) -> int:
    configure_logging(log_file)
    LOGGER.info("starting ai-node backend")
    phase2_diag = Phase2DiagnosticsLogger(LOGGER)
    trust_state_store = TrustStateStore(path=trust_state_path, logger=LOGGER)
    trust_state = trust_state_store.load()
    migration_node_id = None
    if isinstance(trust_state, dict):
        migration_node_id = str(trust_state.get("node_id") or "").strip() or None

    node_identity_store = NodeIdentityStore(path=node_identity_path, logger=LOGGER)
    node_identity = node_identity_store.load_or_create(migration_node_id=migration_node_id)
    provider_selection_store = ProviderSelectionConfigStore(
        path=provider_selection_config_path,
        logger=LOGGER,
    )
    capability_state_store = CapabilityStateStore(path=capability_state_path, logger=LOGGER)
    governance_state_store = GovernanceStateStore(path=governance_state_path, logger=LOGGER)
    phase2_state_store = Phase2StateStore(path=phase2_state_path, logger=LOGGER)
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
        hostname=node_hostname,
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
        node_id=node_identity["node_id"],
        capability_state_store=capability_state_store,
        governance_state_store=governance_state_store,
        phase2_state_store=phase2_state_store,
    )
    control_state = NodeControlState(
        lifecycle=lifecycle,
        config_path=bootstrap_config_path,
        logger=LOGGER,
        bootstrap_runner=bootstrap_runner,
        onboarding_runtime=onboarding_runtime,
        capability_runner=capability_runner,
        node_identity_store=node_identity_store,
        provider_selection_store=provider_selection_store,
        startup_mode=startup_mode,
        trusted_runtime_context=trusted_runtime_context,
    )
    app = create_node_control_app(state=control_state, logger=LOGGER)
    LOGGER.info("phase1 modules loaded; control API active")

    if once:
        bootstrap_runner.stop()
        timeout_monitor.stop()
        LOGGER.info("run-once mode complete")
        return 0

    try:
        uvicorn.run(app, host=api_host, port=api_port, log_level="info", log_config=None)
    finally:
        bootstrap_runner.stop()
        timeout_monitor.stop()
    LOGGER.info("backend stopped cleanly")
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
        trust_state_path=args.trust_state_path,
        node_identity_path=args.node_identity_path,
        provider_selection_config_path=args.provider_selection_config_path,
        capability_state_path=args.capability_state_path,
        governance_state_path=args.governance_state_path,
        phase2_state_path=args.phase2_state_path,
        finalize_poll_interval_seconds=args.finalize_poll_interval_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
