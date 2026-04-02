import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.identity.node_identity_store import NodeIdentityStore, create_node_identity, validate_node_identity


class NodeIdentityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("node-identity-store-test")

    def test_create_node_identity_returns_valid_payload(self):
        identity = create_node_identity()
        is_valid, error = validate_node_identity(identity)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_node_identity_rejects_invalid_uuid(self):
        is_valid, error = validate_node_identity(
            {
                "node_id": "not-a-uuid",
                "created_at": "2026-03-11T12:00:00Z",
            }
        )
        self.assertFalse(is_valid)
        self.assertEqual(error, "invalid_node_id")

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "node_identity.json"
            store = NodeIdentityStore(path=str(path), logger=self.logger)
            identity = create_node_identity()
            store.save(identity)
            loaded = store.load()
            self.assertEqual(loaded, identity)
            self.assertTrue(loaded["node_id"].startswith("node-"))

    def test_load_returns_none_for_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "node_identity.json"
            path.write_text("{not-json", encoding="utf-8")
            store = NodeIdentityStore(path=str(path), logger=self.logger)
            loaded = store.load()
            self.assertIsNone(loaded)

    def test_load_returns_none_for_invalid_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "node_identity.json"
            path.write_text(
                json.dumps(
                    {
                        "node_id": "bad",
                        "created_at": "2026-03-11T12:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            store = NodeIdentityStore(path=str(path), logger=self.logger)
            loaded = store.load()
            self.assertIsNone(loaded)

    def test_load_or_create_returns_existing_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "node_identity.json"
            store = NodeIdentityStore(path=str(path), logger=self.logger)
            first = store.load_or_create()
            second = store.load_or_create()
            self.assertEqual(first, second)

    def test_load_or_create_backfills_from_migration_node_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "node_identity.json"
            store = NodeIdentityStore(path=str(path), logger=self.logger)
            identity = store.load_or_create(migration_node_id="123e4567-e89b-42d3-a456-426614174000")
            self.assertEqual(identity["node_id"], "node-123e4567-e89b-42d3-a456-426614174000")
            self.assertEqual(identity["id_format"], "uuidv4")

    def test_validate_node_identity_accepts_node_uuid_format(self):
        is_valid, error = validate_node_identity(
            {
                "node_id": "node-123e4567-e89b-42d3-a456-426614174000",
                "created_at": "2026-03-11T12:00:00Z",
                "id_format": "uuidv4",
            }
        )
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_load_normalizes_plain_uuid_to_node_uuid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "node_identity.json"
            path.write_text(
                json.dumps(
                    {
                        "node_id": "123e4567-e89b-42d3-a456-426614174000",
                        "created_at": "2026-03-11T12:00:00Z",
                        "id_format": "uuidv4",
                    }
                ),
                encoding="utf-8",
            )
            store = NodeIdentityStore(path=str(path), logger=self.logger)
            loaded = store.load()
            self.assertEqual(loaded["node_id"], "node-123e4567-e89b-42d3-a456-426614174000")


if __name__ == "__main__":
    unittest.main()
