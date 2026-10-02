from dataclasses import dataclass
from datetime import datetime, timezone

from ai_node.family_memory.models import FamilyAuthorizationContext, MemoryAction, MemoryVisibility


@dataclass(frozen=True)
class FamilyMemoryPolicyDecision:
    allowed: bool
    reason: str
    authorization_id: str | None = None
    allowed_person_ids: tuple[str, ...] = ()
    allowed_visibility: tuple[MemoryVisibility, ...] = ()


def _deny(reason: str, context: FamilyAuthorizationContext | None = None) -> FamilyMemoryPolicyDecision:
    return FamilyMemoryPolicyDecision(
        allowed=False,
        reason=reason,
        authorization_id=context.authorization_id if context is not None else None,
    )


def evaluate_family_memory_access(
    *,
    authorization: FamilyAuthorizationContext | None,
    action: MemoryAction,
    visibility: MemoryVisibility,
    subject_person_ids: list[str],
    expected_core_id: str,
    expected_household_id: str,
    expected_room_id: str | None = None,
    now: datetime | None = None,
) -> FamilyMemoryPolicyDecision:
    if authorization is None:
        return _deny("identity_required")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        return _deny("authorization_expired", authorization)
    if current_time < authorization.issued_at or current_time >= authorization.expires_at:
        return _deny("authorization_expired", authorization)
    if authorization.core_id != expected_core_id:
        return _deny("wrong_core", authorization)
    if authorization.household_id != expected_household_id:
        return _deny("wrong_household", authorization)
    if expected_room_id is not None and authorization.context.room_id != expected_room_id:
        return _deny("wrong_room", authorization)
    if authorization.decision.effect != "allow":
        return _deny("operation_denied", authorization)
    if authorization.operation.kind != action or action not in authorization.decision.allowed_actions:
        return _deny("operation_denied", authorization)
    if visibility not in authorization.operation.requested_visibility:
        return _deny("visibility_denied", authorization)
    if visibility not in authorization.decision.allowed_visibility:
        return _deny("visibility_denied", authorization)

    normalized_subjects = tuple(dict.fromkeys(str(item or "").strip() for item in subject_person_ids if str(item or "").strip()))
    if not normalized_subjects:
        return _deny("identity_required", authorization)
    if not set(normalized_subjects).issubset(set(authorization.decision.allowed_person_ids)):
        return _deny("visibility_denied", authorization)
    if not authorization.decision.consent_ids:
        return _deny("consent_required", authorization)

    identity_states = {participant.identity_state for participant in authorization.participants}
    participant_ids = {
        participant.person_id for participant in authorization.participants if participant.person_id is not None
    }
    if identity_states & {"unknown", "conflicted"}:
        if visibility in {"private", "explicit", "guardian_managed"}:
            return _deny("identity_uncertain", authorization)
    if "probable" in identity_states:
        if visibility in {"private", "explicit", "guardian_managed"} or authorization.operation.risk == "personal_sensitive":
            return _deny("identity_uncertain", authorization)

    if authorization.requester.platform_role == "guest":
        if action != "memory.read" or visibility in {"private", "guardian_managed"}:
            return _deny("operation_denied", authorization)

    if visibility == "private":
        if len(normalized_subjects) != 1:
            return _deny("visibility_denied", authorization)
        if len(participant_ids) != 1 or participant_ids != set(normalized_subjects):
            return _deny("visibility_denied", authorization)

    if len(participant_ids) > 1 and not participant_ids.issubset(set(authorization.decision.allowed_person_ids)):
        return _deny("visibility_denied", authorization)

    return FamilyMemoryPolicyDecision(
        allowed=True,
        reason="family_memory_allowed",
        authorization_id=authorization.authorization_id,
        allowed_person_ids=normalized_subjects,
        allowed_visibility=(visibility,),
    )
