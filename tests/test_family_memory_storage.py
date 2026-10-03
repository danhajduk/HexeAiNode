import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_node.family_memory.models import FamilyAuthorizationContext, FamilyMemoryRecord
from ai_node.family_memory.retrieval import AuthorizedFamilyMemoryRetriever
from ai_node.family_memory.storage import EncryptedFamilyMemoryStore, FamilyMemoryStoreError


class _FailIfReadStore:
    def load_partition(self, **_kwargs):
        raise AssertionError("storage must not be read before authorization")


class FamilyMemoryStorageTests(unittest.TestCase):
    def _record(self, *, memory_id="memory_1", person_id="person_1", **overrides):
        now = datetime.now(timezone.utc)
        payload = {
            "memory_id": memory_id,
            "core_id": "core_1",
            "household_id": "household_1",
            "subject_person_ids": [person_id],
            "visibility": "private",
            "summary": f"Private preference for {person_id}",
            "sensitivity": "personal",
            "consent_ids": ["consent_1"],
            "source_interaction_id": "interaction_1",
            "created_at": now,
            "updated_at": now,
        }
        payload.update(overrides)
        return FamilyMemoryRecord.model_validate(payload)

    def _authorization(self, *, person_id="person_1", participants=None, **overrides):
        now = datetime.now(timezone.utc)
        payload = {
            "contract_version": "hexe.family-identity-authorization.v1",
            "authorization_id": "authz_1",
            "core_id": "core_1",
            "household_id": "household_1",
            "requester": {
                "user_id": "user_1",
                "person_id": person_id,
                "platform_role": "member",
                "session_id": "session_1",
                "device_id": "device_1",
            },
            "participants": participants
            or [{"person_id": person_id, "identity_state": "authenticated", "evidence_id": "evidence_1"}],
            "context": {"room_id": "room_1", "endpoint_id": "endpoint_1", "audience_mode": "private"},
            "operation": {"kind": "memory.read", "risk": "personal", "requested_visibility": ["private"]},
            "decision": {
                "effect": "allow",
                "allowed_person_ids": [person_id],
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

    def test_store_encrypts_content_and_scope_identifiers_at_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EncryptedFamilyMemoryStore(root=Path(tmp), master_key=b"a" * 32)
            record = self._record()
            store.upsert(record)

            files = list(Path(tmp).rglob("*.json.enc"))
            self.assertEqual(len(files), 1)
            raw = files[0].read_text(encoding="utf-8")
            self.assertNotIn(record.summary, raw)
            self.assertNotIn("person_1", str(files[0]))
            self.assertNotIn("person_1", raw)
            self.assertEqual(os.stat(files[0]).st_mode & 0o777, 0o600)
            self.assertEqual(store.load_partition(core_id="core_1", household_id="household_1", person_id="person_1"), [record])

    def test_wrong_key_and_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = EncryptedFamilyMemoryStore(root=root, master_key=b"a" * 32)
            store.upsert(self._record())

            wrong_key_store = EncryptedFamilyMemoryStore(root=root, master_key=b"b" * 32)
            with self.assertRaisesRegex(FamilyMemoryStoreError, "decryption_failed"):
                wrong_key_store.load_partition(core_id="core_1", household_id="household_1", person_id="person_1")

            path = next(root.rglob("*.json.enc"))
            envelope = json.loads(path.read_text(encoding="utf-8"))
            envelope["ciphertext"] = envelope["ciphertext"][:-4] + "AAAA"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(FamilyMemoryStoreError, "decryption_failed"):
                store.load_partition(core_id="core_1", household_id="household_1", person_id="person_1")

    def test_retrieval_is_authorization_first(self):
        retriever = AuthorizedFamilyMemoryRetriever(store=_FailIfReadStore())

        decision, records = retriever.retrieve(
            authorization=None,
            visibility="private",
            subject_person_ids=["person_1"],
            expected_core_id="core_1",
            expected_household_id="household_1",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "identity_required")
        self.assertEqual(records, [])

    def test_authorized_retrieval_isolated_by_person_and_filters_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EncryptedFamilyMemoryStore(root=Path(tmp), master_key=b"a" * 32)
            now = datetime.now(timezone.utc)
            store.upsert(self._record(memory_id="active_1", person_id="person_1"))
            store.upsert(self._record(memory_id="other_1", person_id="person_2"))
            store.upsert(
                self._record(
                    memory_id="expired_1",
                    created_at=now - timedelta(minutes=5),
                    updated_at=now - timedelta(minutes=5),
                    expires_at=now - timedelta(seconds=1),
                )
            )
            store.upsert(self._record(memory_id="deleted_1", status="deleted"))
            retriever = AuthorizedFamilyMemoryRetriever(store=store)

            decision, records = retriever.retrieve(
                authorization=self._authorization(),
                visibility="private",
                subject_person_ids=["person_1"],
                expected_core_id="core_1",
                expected_household_id="household_1",
                expected_room_id="room_1",
                now=now,
            )

            self.assertTrue(decision.allowed)
            self.assertEqual([record.memory_id for record in records], ["active_1"])

    def test_unknown_participant_cannot_reach_private_partition(self):
        retriever = AuthorizedFamilyMemoryRetriever(store=_FailIfReadStore())
        authorization = self._authorization(
            participants=[
                {"person_id": "person_1", "identity_state": "authenticated", "evidence_id": "evidence_1"},
                {"identity_state": "unknown"},
            ]
        )

        decision, records = retriever.retrieve(
            authorization=authorization,
            visibility="private",
            subject_person_ids=["person_1"],
            expected_core_id="core_1",
            expected_household_id="household_1",
            expected_room_id="room_1",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "identity_uncertain")
        self.assertEqual(records, [])

    def test_unauthorized_subject_cannot_probe_another_partition(self):
        retriever = AuthorizedFamilyMemoryRetriever(store=_FailIfReadStore())

        decision, records = retriever.retrieve(
            authorization=self._authorization(),
            visibility="private",
            subject_person_ids=["person_2"],
            expected_core_id="core_1",
            expected_household_id="household_1",
            expected_room_id="room_1",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "visibility_denied")
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
