import argparse
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.bootstrap_mqtt_runner import BootstrapMqttRunner
from ai_node.runtime.bootstrap_timeout import BootstrapConnectTimeoutMonitor
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app


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
) -> int:
    configure_logging(log_file)
    LOGGER.info("starting ai-node backend")
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
    bootstrap_runner = BootstrapMqttRunner(lifecycle=lifecycle, logger=LOGGER)
    control_state = NodeControlState(
        lifecycle=lifecycle,
        config_path=bootstrap_config_path,
        logger=LOGGER,
        bootstrap_runner=bootstrap_runner,
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
    )


if __name__ == "__main__":
    sys.exit(main())
