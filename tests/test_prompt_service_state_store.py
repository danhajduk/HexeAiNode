import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.prompt_service_state_store import (
    PromptServiceStateStore,
    create_prompt_service_state,
    validate_prompt_service_state,
)


class PromptServiceStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("prompt-service-state-store-test")

    def test_create_default_state_is_valid(self):
        payload = create_prompt_service_state()
        is_valid, error = validate_prompt_service_state(payload)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt_service_state.json"
            store = PromptServiceStateStore(path=str(path), logger=self.logger)
            payload = create_prompt_service_state()
            payload["prompt_services"] = [
                {
                    "prompt_id": "prompt.alpha",
                    "service_id": "svc-alpha",
                    "task_family": "task.classification.text",
                    "status": "registered",
                    "metadata": {},
                    "registered_at": payload["updated_at"],
                    "updated_at": payload["updated_at"],
                }
            ]
            store.save(payload)
            loaded = store.load()
            self.assertEqual(loaded, payload)

    def test_load_or_create_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt_service_state.json"
            store = PromptServiceStateStore(path=str(path), logger=self.logger)
            loaded = store.load_or_create()
            self.assertTrue(path.exists())
            self.assertIn("prompt_services", loaded)


if __name__ == "__main__":
    unittest.main()
