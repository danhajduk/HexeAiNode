import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from ai_node.family_memory.models import (
    FamilyAuthorizationContext,
    FamilyMemoryDeletionReceipt,
    FamilyMemoryExportManifest,
    FamilyMemoryLifecycleRequest,
    FamilyMemoryRecord,
)
from ai_node.family_memory.policy import evaluate_family_memory_access


class FamilyMemoryPolicyTests(unittest.TestCase):
    def _context(self, **overrides) -> FamilyAuthorizationContext:
        now = datetime.now(timezone.utc)
        payload = {
            "contract_version": "hexe.family-identity-authorization.v1",
            "authorization_id": "authz_1",
            "core_id": "core_1",
            "household_id": "household_1",
            "requester": {
                "user_id": "user_1",
                "person_id": "person_1",
                "platform_role": "member",
                "session_id": "session_1",
                "device_id": "device_1",
            },
            "participants": [
                {"person_id": "person_1", "identity_state": "authenticated", "evidence_id": "evidence_1"}
            ],
            "context": {"room_id": "room_1", "endpoint_id": "endpoint_1", "audience_mode": "private"},
            "operation": {
                "kind": "memory.read",
                "risk": "personal_sensitive",
                "requested_visibility": ["private"],
            },
            "decision": {
                "effect": "allow",
                "allowed_person_ids": ["person_1"],
                "allowed_visibility": ["private"],
                "allowed_actions": ["memory.read"],
                "consent_ids": ["consent_1"],
                "policy_version": "v1",
            },
            "issued_at": now - timedelta(seconds=5),
            "expires_at": now + timedelta(seconds=60),
            "jti": "jti_1",
        }
        payload.update(overrides)
        return FamilyAuthorizationContext.model_validate(payload)

    def _evaluate(self, context: FamilyAuthorizationContext | None, **overrides):
        arguments = {
            "authorization": context,
            "action": "memory.read",
            "visibility": "private",
            "subject_person_ids": ["person_1"],
            "expected_core_id": "core_1",
            "expected_household_id": "household_1",
            "expected_room_id": "room_1",
        }
        arguments.update(overrides)
        return evaluate_family_memory_access(**arguments)

    def test_allows_private_read_for_single_authenticated_authorized_participant(self):
        decision = self._evaluate(self._context())

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "family_memory_allowed")
        self.assertEqual(decision.allowed_person_ids, ("person_1",))

    def test_missing_context_denies_private_memory(self):
        decision = self._evaluate(None)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "identity_required")

    def test_expired_context_is_denied(self):
        now = datetime.now(timezone.utc)
        context = self._context(issued_at=now - timedelta(seconds=60), expires_at=now - timedelta(seconds=1))

        decision = self._evaluate(context, now=now)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "authorization_expired")

    def test_wrong_core_household_and_room_have_stable_denials(self):
        context = self._context()

        self.assertEqual(self._evaluate(context, expected_core_id="core_2").reason, "wrong_core")
        self.assertEqual(self._evaluate(context, expected_household_id="household_2").reason, "wrong_household")
        self.assertEqual(self._evaluate(context, expected_room_id="room_2").reason, "wrong_room")

    def test_room_visibility_requires_room_context(self):
        operation = self._context().operation.model_copy(update={"requested_visibility": ["room"]})
        decision = self._context().decision.model_copy(update={"allowed_visibility": ["room"]})
        context = self._context(
            context={"audience_mode": "shared"},
            operation=operation.model_dump(),
            decision=decision.model_dump(),
        )

        result = self._evaluate(context, visibility="room", expected_room_id=None)

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "wrong_room")

    def test_unknown_participant_suppresses_private_retrieval(self):
        context = self._context(
            participants=[
                {"person_id": "person_1", "identity_state": "authenticated", "evidence_id": "evidence_1"},
                {"identity_state": "unknown"},
            ]
        )

        decision = self._evaluate(context)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "identity_uncertain")

    def test_probable_identity_cannot_authorize_sensitive_private_memory(self):
        context = self._context(
            participants=[{"person_id": "person_1", "identity_state": "probable", "evidence_id": "evidence_1"}]
        )

        decision = self._evaluate(context)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "identity_uncertain")

    def test_guest_cannot_read_private_memory_even_when_decision_claims_allow(self):
        requester = self._context().requester.model_copy(update={"platform_role": "guest"})
        context = self._context(requester=requester.model_dump())

        decision = self._evaluate(context)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "operation_denied")

    def test_multiple_participants_cannot_receive_single_subject_private_memory(self):
        decision_payload = self._context().decision.model_copy(
            update={"allowed_person_ids": ["person_1", "person_2"]}
        )
        context = self._context(
            participants=[
                {"person_id": "person_1", "identity_state": "authenticated", "evidence_id": "evidence_1"},
                {"person_id": "person_2", "identity_state": "verified", "evidence_id": "evidence_2"},
            ],
            decision=decision_payload.model_dump(),
        )

        decision = self._evaluate(context)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "visibility_denied")

    def test_missing_consent_is_denied(self):
        decision_payload = self._context().decision.model_copy(update={"consent_ids": []})
        context = self._context(decision=decision_payload.model_dump())

        decision = self._evaluate(context)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "consent_required")

    def test_context_rejects_unknown_person_id_and_excessive_lifetime(self):
        with self.assertRaises(ValidationError):
            self._context(participants=[{"person_id": "person_1", "identity_state": "unknown"}])

        now = datetime.now(timezone.utc)
        with self.assertRaises(ValidationError):
            self._context(issued_at=now, expires_at=now + timedelta(seconds=121))

    def test_memory_record_enforces_private_and_explicit_scope(self):
        now = datetime.now(timezone.utc)
        base = {
            "memory_id": "memory_1",
            "core_id": "core_1",
            "household_id": "household_1",
            "subject_person_ids": ["person_1"],
            "visibility": "private",
            "summary": "Likes concise morning briefings.",
            "sensitivity": "personal",
            "consent_ids": ["consent_1"],
            "source_interaction_id": "interaction_1",
            "created_at": now,
            "updated_at": now,
        }
        record = FamilyMemoryRecord.model_validate(base)
        self.assertEqual(record.visibility, "private")

        with self.assertRaises(ValidationError):
            FamilyMemoryRecord.model_validate({**base, "audience_person_ids": ["person_2"]})
        with self.assertRaises(ValidationError):
            FamilyMemoryRecord.model_validate({**base, "visibility": "explicit"})

    def test_lifecycle_models_require_scoped_requests_and_unambiguous_receipts(self):
        now = datetime.now(timezone.utc)
        request = FamilyMemoryLifecycleRequest.model_validate(
            {
                "request_id": "delete_1",
                "authorization_id": "authz_1",
                "core_id": "core_1",
                "household_id": "household_1",
                "action": "memory.delete",
                "subject_person_ids": ["person_1"],
                "categories": ["family_memory"],
                "requested_at": now,
                "expires_at": now + timedelta(minutes=5),
            }
        )
        self.assertEqual(request.action, "memory.delete")

        receipt_payload = {
            "receipt_id": "receipt_1",
            "request_id": "delete_1",
            "authorization_id": "authz_1",
            "core_id": "core_1",
            "household_id": "household_1",
            "subject_person_ids": ["person_1"],
            "categories_deleted": ["family_memory"],
            "status": "completed",
            "completed_at": now,
        }
        receipt = FamilyMemoryDeletionReceipt.model_validate(receipt_payload)
        self.assertEqual(receipt.status, "completed")

        with self.assertRaises(ValidationError):
            FamilyMemoryDeletionReceipt.model_validate(
                {
                    **receipt_payload,
                    "categories_retained": ["family_memory"],
                    "retention_reason": "legal_hold",
                }
            )

    def test_export_manifest_is_subject_scoped_and_contains_no_memory_payload(self):
        manifest = FamilyMemoryExportManifest.model_validate(
            {
                "export_id": "export_1",
                "request_id": "request_1",
                "authorization_id": "authz_1",
                "core_id": "core_1",
                "household_id": "household_1",
                "subject_person_ids": ["person_1"],
                "categories_exported": ["family_memory"],
                "record_count": 3,
                "generated_at": datetime.now(timezone.utc),
            }
        )

        self.assertEqual(manifest.record_count, 3)
        self.assertNotIn("records", manifest.model_dump())


if __name__ == "__main__":
    unittest.main()
