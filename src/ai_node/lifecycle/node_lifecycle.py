from enum import Enum
from typing import Callable, Dict, Optional, Set


class NodeLifecycleState(str, Enum):
    UNCONFIGURED = "unconfigured"
    BOOTSTRAP_CONNECTING = "bootstrap_connecting"
    BOOTSTRAP_CONNECTED = "bootstrap_connected"
    CORE_DISCOVERED = "core_discovered"
    REGISTRATION_PENDING = "registration_pending"
    PENDING_APPROVAL = "pending_approval"
    TRUSTED = "trusted"
    CAPABILITY_SETUP_PENDING = "capability_setup_pending"
    OPERATIONAL = "operational"
    DEGRADED = "degraded"


ALLOWED_TRANSITIONS: Dict[NodeLifecycleState, Set[NodeLifecycleState]] = {
    NodeLifecycleState.UNCONFIGURED: {NodeLifecycleState.BOOTSTRAP_CONNECTING},
    NodeLifecycleState.BOOTSTRAP_CONNECTING: {NodeLifecycleState.BOOTSTRAP_CONNECTED},
    NodeLifecycleState.BOOTSTRAP_CONNECTED: {NodeLifecycleState.CORE_DISCOVERED},
    NodeLifecycleState.CORE_DISCOVERED: {NodeLifecycleState.REGISTRATION_PENDING},
    NodeLifecycleState.REGISTRATION_PENDING: {NodeLifecycleState.PENDING_APPROVAL},
    NodeLifecycleState.PENDING_APPROVAL: {NodeLifecycleState.TRUSTED},
    NodeLifecycleState.TRUSTED: {NodeLifecycleState.CAPABILITY_SETUP_PENDING},
    NodeLifecycleState.CAPABILITY_SETUP_PENDING: {NodeLifecycleState.OPERATIONAL},
    NodeLifecycleState.OPERATIONAL: set(),
    NodeLifecycleState.DEGRADED: {NodeLifecycleState.OPERATIONAL},
}

DEGRADABLE_STATES: Set[NodeLifecycleState] = {
    NodeLifecycleState.BOOTSTRAP_CONNECTING,
    NodeLifecycleState.BOOTSTRAP_CONNECTED,
    NodeLifecycleState.CORE_DISCOVERED,
    NodeLifecycleState.REGISTRATION_PENDING,
    NodeLifecycleState.PENDING_APPROVAL,
    NodeLifecycleState.TRUSTED,
    NodeLifecycleState.CAPABILITY_SETUP_PENDING,
    NodeLifecycleState.OPERATIONAL,
}


class NodeLifecycle:
    def __init__(
        self,
        logger,
        on_transition: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._state = NodeLifecycleState.UNCONFIGURED
        self._logger = logger
        self._on_transition = on_transition or (lambda _: None)

    def get_state(self) -> NodeLifecycleState:
        return self._state

    def can_transition_to(self, next_state: NodeLifecycleState) -> bool:
        return _can_transition(self._state, next_state)

    def transition_to(self, next_state: NodeLifecycleState, meta: Optional[dict] = None) -> NodeLifecycleState:
        if not isinstance(next_state, NodeLifecycleState):
            raise ValueError(f"unknown lifecycle state: {next_state}")
        if not _can_transition(self._state, next_state):
            raise ValueError(f"invalid state transition: {self._state.value} -> {next_state.value}")

        previous = self._state
        self._state = next_state
        payload = {"from": previous.value, "to": next_state.value, **(meta or {})}
        if hasattr(self._logger, "info"):
            self._logger.info("[state-transition] %s", payload)
        self._on_transition({"from": previous, "to": next_state, "meta": meta or {}})
        return self._state


def _can_transition(from_state: NodeLifecycleState, to_state: NodeLifecycleState) -> bool:
    if to_state == NodeLifecycleState.DEGRADED and from_state in DEGRADABLE_STATES:
        return True
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())
