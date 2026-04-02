import asyncio
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from ai_node.lifecycle.node_lifecycle import NodeLifecycle, NodeLifecycleState
from ai_node.registration.registration_client import RegistrationClient
from ai_node.trust.trust_activation_parser import parse_trust_activation_payload
from ai_node.trust.trust_store import TrustStateStore


def _is_loopback_host(value: object) -> bool:
    host = str(value or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


class HttpxJsonAdapter:
    async def post_json(self, url: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
        return _parse_json_response(response)

    async def get_json(self, url: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
        return _parse_json_response(response)


def _parse_json_response(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {"detail": response.text.strip() or "invalid_json_response"}

    if response.status_code >= 400:
        detail = payload.get("detail") or payload.get("error") or f"request failed ({response.status_code})"
        raise RuntimeError(str(detail))
    if not isinstance(payload, dict):
        raise RuntimeError("response must be a JSON object")
    return payload


class OnboardingRuntime:
    def __init__(
        self,
        *,
        lifecycle: NodeLifecycle,
        logger,
        node_id: str,
        node_software_version: str = "0.1.0",
        protocol_version: str = "1.0",
        hostname: Optional[str] = None,
        ui_endpoint: Optional[str] = None,
        api_base_url: Optional[str] = None,
        trust_state_path: str = ".run/trust_state.json",
        finalize_poll_interval_seconds: float = 2.0,
    ) -> None:
        self._lifecycle = lifecycle
        self._logger = logger
        self._node_id = str(node_id).strip()
        if not self._node_id:
            raise ValueError("onboarding runtime requires node_id")
        self._node_software_version = node_software_version
        self._protocol_version = protocol_version
        self._hostname = hostname
        self._ui_endpoint = ui_endpoint
        self._api_base_url = api_base_url
        self._finalize_poll_interval_seconds = finalize_poll_interval_seconds
        self._http_adapter = HttpxJsonAdapter()
        self._registration_client = RegistrationClient(
            lifecycle=lifecycle,
            http_adapter=self._http_adapter,
            logger=logger,
        )
        self._trust_store = TrustStateStore(path=trust_state_path, logger=logger)
        self._lock = threading.Lock()
        self._inflight = False
        self._run_id = 0
        self._pending_approval_url = None
        self._pending_session_id = None
        self._pending_node_nonce = None

    def on_core_discovered(self, bootstrap_payload: dict, node_name: str) -> None:
        with self._lock:
            if self._inflight:
                return
            if self._lifecycle.get_state() != NodeLifecycleState.CORE_DISCOVERED:
                return
            self._inflight = True
            self._run_id += 1
            run_id = self._run_id

        worker = threading.Thread(
            target=self._run_registration,
            args=(bootstrap_payload, node_name, run_id),
            daemon=True,
        )
        worker.start()

    def get_status_context(self) -> dict:
        with self._lock:
            return {
                "pending_approval_url": self._pending_approval_url,
                "pending_session_id": self._pending_session_id,
                "pending_node_nonce": self._pending_node_nonce,
            }

    def cancel(self) -> None:
        with self._lock:
            self._run_id += 1
            self._inflight = False
            self._pending_approval_url = None
            self._pending_session_id = None
            self._pending_node_nonce = None

    def _is_run_active(self, run_id: int) -> bool:
        with self._lock:
            return run_id == self._run_id

    def _run_registration(self, bootstrap_payload: dict, node_name: str, run_id: int) -> None:
        try:
            asyncio.run(self._run_registration_async(bootstrap_payload, node_name, run_id))
        except Exception as exc:
            if not self._is_run_active(run_id):
                return
            error_message = str(exc).strip() or repr(exc)
            if hasattr(self._logger, "error"):
                self._logger.error(
                    "[registration-failed] %s",
                    {"error_type": type(exc).__name__, "message": error_message},
                )
            current = self._lifecycle.get_state()
            if current in {
                NodeLifecycleState.CORE_DISCOVERED,
                NodeLifecycleState.REGISTRATION_PENDING,
                NodeLifecycleState.PENDING_APPROVAL,
            }:
                self._lifecycle.transition_to(
                    NodeLifecycleState.DEGRADED,
                    {
                        "stage": "registration",
                        "error_type": type(exc).__name__,
                        "error": error_message,
                    },
                )
        finally:
            with self._lock:
                if run_id == self._run_id:
                    self._inflight = False

    async def _run_registration_async(self, bootstrap_payload: dict, node_name: str, run_id: int) -> None:
        if not self._is_run_active(run_id):
            return
        node_nonce = str(uuid.uuid4())
        response = await self._registration_client.register(
            bootstrap_payload=bootstrap_payload,
            node_id=self._node_id,
            node_name=node_name,
            node_software_version=self._node_software_version,
            protocol_version=self._protocol_version,
            node_nonce=node_nonce,
            hostname=self._hostname,
            ui_endpoint=self._ui_endpoint,
            api_base_url=self._api_base_url,
        )
        status = (
            response.get("status")
            or response.get("onboarding_status")
            or response.get("session", {}).get("onboarding_status")
        )
        if hasattr(self._logger, "info"):
            self._logger.info("[registration-response] %s", {"status": status})

        session = response.get("session") if isinstance(response.get("session"), dict) else {}
        session_id = session.get("session_id")
        finalize_path = session.get("finalize", {}).get("path")
        approval_url = session.get("approval_url")
        if status not in {"pending", "pending_approval"} or not session_id or not finalize_path:
            raise RuntimeError(f"unexpected onboarding session response: {response}")

        if not self._is_run_active(run_id):
            return
        self._lifecycle.transition_to(NodeLifecycleState.PENDING_APPROVAL)
        with self._lock:
            if run_id == self._run_id:
                self._pending_approval_url = approval_url
                self._pending_session_id = session_id
                self._pending_node_nonce = node_nonce
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[pending-approval] %s",
                {
                    "session_id": session_id,
                    "approval_url": approval_url,
                    "node_id": self._node_id,
                    "node_nonce": node_nonce,
                },
            )

        api_base = str(bootstrap_payload.get("api_base", "")).strip()
        if not api_base:
            raise RuntimeError("bootstrap payload missing api_base")

        finalize_url = self._build_finalize_url(api_base=api_base, finalize_path=str(finalize_path), node_nonce=node_nonce)
        await self._wait_for_finalize(
            finalize_url=finalize_url,
            bootstrap_payload=bootstrap_payload,
            node_name=node_name,
            run_id=run_id,
            node_nonce=node_nonce,
        )

    @staticmethod
    def _build_finalize_url(*, api_base: str, finalize_path: str, node_nonce: str) -> str:
        parsed = urlparse(api_base)
        base = f"{api_base.rstrip('/')}/"
        relative = finalize_path[1:] if finalize_path.startswith("/") else finalize_path
        base_path = parsed.path.strip("/")
        if base_path and (relative == base_path or relative.startswith(f"{base_path}/")):
            relative = relative[len(base_path) :].lstrip("/")
        url = urljoin(base, relative)
        query = urlencode({"node_nonce": node_nonce})
        return f"{url}?{query}"

    async def _wait_for_finalize(
        self,
        *,
        finalize_url: str,
        bootstrap_payload: dict,
        node_name: str,
        run_id: int,
        node_nonce: str,
    ) -> None:
        consecutive_poll_errors = 0
        max_consecutive_poll_errors = 30
        while True:
            if not self._is_run_active(run_id):
                return
            try:
                decision = await self._http_adapter.get_json(finalize_url)
                consecutive_poll_errors = 0
            except Exception as exc:
                consecutive_poll_errors += 1
                error_message = str(exc).strip() or repr(exc)
                if hasattr(self._logger, "warning"):
                    self._logger.warning(
                        "[finalize-poll-error] %s",
                        {
                            "error_type": type(exc).__name__,
                            "message": error_message,
                            "attempt": consecutive_poll_errors,
                            "max_attempts": max_consecutive_poll_errors,
                        },
                    )
                if consecutive_poll_errors >= max_consecutive_poll_errors:
                    raise RuntimeError(
                        f"finalize polling failed after {max_consecutive_poll_errors} attempts: "
                        f"{type(exc).__name__}: {error_message}"
                    ) from exc
                backoff_seconds = min(
                    self._finalize_poll_interval_seconds * max(consecutive_poll_errors, 1),
                    10.0,
                )
                await asyncio.sleep(backoff_seconds)
                continue
            onboarding_status = str(decision.get("onboarding_status") or decision.get("status") or "").strip()
            if onboarding_status in {"pending", "pending_approval"}:
                await asyncio.sleep(self._finalize_poll_interval_seconds)
                continue
            if onboarding_status == "approved":
                self._finalize_approved(
                    decision=decision,
                    bootstrap_payload=bootstrap_payload,
                    node_name=node_name,
                    node_nonce=node_nonce,
                )
                return
            if onboarding_status in {"rejected", "expired", "consumed", "invalid"}:
                raise RuntimeError(f"onboarding finalize returned {onboarding_status}")
            raise RuntimeError(f"unexpected finalize response: {decision}")

    def _finalize_approved(
        self,
        *,
        decision: dict,
        bootstrap_payload: dict,
        node_name: str,
        node_nonce: str | None,
    ) -> None:
        activation_payload = decision.get("activation") if isinstance(decision.get("activation"), dict) else decision
        activation_envelope = {"status": "approved", **activation_payload}
        ok, parsed = parse_trust_activation_payload(activation_envelope)
        if not ok:
            raise RuntimeError(f"invalid trust activation payload: {parsed}")
        if parsed["node_id"] != self._node_id:
            raise RuntimeError(
                f"node_id mismatch between identity ({self._node_id}) and activation payload ({parsed['node_id']})"
            )

        bootstrap_mqtt_host = str(bootstrap_payload.get("mqtt_host") or bootstrap_payload.get("bootstrap_host") or "").strip()
        activation_mqtt_host = str(parsed["operational_mqtt_host"]).strip()
        effective_operational_mqtt_host = activation_mqtt_host
        if _is_loopback_host(activation_mqtt_host) and bootstrap_mqtt_host and not _is_loopback_host(bootstrap_mqtt_host):
            effective_operational_mqtt_host = bootstrap_mqtt_host
            if hasattr(self._logger, "warning"):
                self._logger.warning(
                    "[operational-mqtt-host-corrected] %s",
                    {
                        "activation_operational_mqtt_host": activation_mqtt_host,
                        "bootstrap_mqtt_host": bootstrap_mqtt_host,
                        "effective_operational_mqtt_host": effective_operational_mqtt_host,
                    },
                )
        elif hasattr(self._logger, "info"):
            self._logger.info(
                "[operational-mqtt-host-selected] %s",
                {
                    "activation_operational_mqtt_host": activation_mqtt_host,
                    "bootstrap_mqtt_host": bootstrap_mqtt_host,
                    "effective_operational_mqtt_host": effective_operational_mqtt_host,
                },
            )

        trust_state = {
            "node_id": parsed["node_id"],
            "node_name": node_name,
            "node_type": parsed.get("node_type", "ai-node"),
            "paired_core_id": parsed["paired_core_id"],
            "core_api_endpoint": str(bootstrap_payload.get("api_base", "")).strip(),
            "node_trust_token": parsed["node_trust_token"],
            "initial_baseline_policy": parsed["initial_baseline_policy"],
            "baseline_policy_version": activation_payload.get("baseline_policy_version", "1.0"),
            "operational_mqtt_identity": parsed["operational_mqtt_identity"],
            "operational_mqtt_token": parsed["operational_mqtt_token"],
            "operational_mqtt_host": effective_operational_mqtt_host,
            "operational_mqtt_port": parsed["operational_mqtt_port"],
            "bootstrap_mqtt_host": bootstrap_mqtt_host,
            "registration_timestamp": datetime.now().astimezone().isoformat(),
        }
        self._trust_store.save(trust_state)
        self._lifecycle.transition_to(NodeLifecycleState.TRUSTED)
        self._lifecycle.transition_to(
            NodeLifecycleState.CAPABILITY_SETUP_PENDING,
            {"source": "onboarding_finalize_approved"},
        )
        with self._lock:
            self._pending_approval_url = None
            self._pending_session_id = None
            self._pending_node_nonce = None
        if hasattr(self._logger, "info"):
            self._logger.info(
                "[onboarding-finalized] %s",
                {
                    "status": "approved",
                    "node_id": parsed["node_id"],
                    "node_nonce": node_nonce,
                },
            )
