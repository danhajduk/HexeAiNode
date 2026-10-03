from datetime import datetime, timezone

from ai_node.family_memory.models import (
    FamilyAuthorizationContext,
    FamilyMemoryRecord,
    MemoryVisibility,
)
from ai_node.family_memory.policy import FamilyMemoryPolicyDecision, evaluate_family_memory_access
from ai_node.family_memory.storage import EncryptedFamilyMemoryStore


class AuthorizedFamilyMemoryRetriever:
    def __init__(self, *, store: EncryptedFamilyMemoryStore) -> None:
        self._store = store

    def retrieve(
        self,
        *,
        authorization: FamilyAuthorizationContext | None,
        visibility: MemoryVisibility,
        subject_person_ids: list[str],
        expected_core_id: str,
        expected_household_id: str,
        expected_room_id: str | None = None,
        now: datetime | None = None,
        limit: int = 20,
    ) -> tuple[FamilyMemoryPolicyDecision, list[FamilyMemoryRecord]]:
        current_time = now or datetime.now(timezone.utc)
        decision = evaluate_family_memory_access(
            authorization=authorization,
            action="memory.read",
            visibility=visibility,
            subject_person_ids=subject_person_ids,
            expected_core_id=expected_core_id,
            expected_household_id=expected_household_id,
            expected_room_id=expected_room_id,
            now=current_time,
        )
        if not decision.allowed:
            return decision, []

        bounded_limit = min(max(int(limit), 0), 100)
        if bounded_limit == 0:
            return decision, []

        allowed_subjects = set(decision.allowed_person_ids)
        by_id: dict[str, FamilyMemoryRecord] = {}
        for person_id in decision.allowed_person_ids:
            records = self._store.load_partition(
                core_id=expected_core_id,
                household_id=expected_household_id,
                person_id=person_id,
            )
            for record in records:
                if record.status != "active":
                    continue
                if record.expires_at is not None and record.expires_at <= current_time:
                    continue
                if record.visibility != visibility:
                    continue
                if not set(record.subject_person_ids).issubset(allowed_subjects):
                    continue
                if visibility == "explicit":
                    participant_ids = {
                        participant.person_id
                        for participant in authorization.participants
                        if participant.person_id is not None
                    }
                    if not participant_ids.issubset(set(record.audience_person_ids)):
                        continue
                by_id[record.memory_id] = record

        records = sorted(
            by_id.values(),
            key=lambda item: (item.updated_at, item.memory_id),
            reverse=True,
        )
        return decision, records[:bounded_limit]
