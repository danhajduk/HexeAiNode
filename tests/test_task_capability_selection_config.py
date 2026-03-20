import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.config.task_capability_selection_config import (
    TaskCapabilitySelectionConfigStore,
    create_task_capability_selection_config,
    validate_task_capability_selection_config,
)


class TaskCapabilitySelectionConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("task-capability-selection-config-test")

    def test_create_defaults_include_canonical_task_families(self):
        config = create_task_capability_selection_config()
        self.assertTrue(config["selected_task_families"])
        self.assertEqual(config["schema_version"], "1.0")

    def test_validate_rejects_unknown_task_family(self):
        is_valid, error = validate_task_capability_selection_config(
            {"schema_version": "1.0", "selected_task_families": ["task.classification", "task.unknown"]}
        )
        self.assertFalse(is_valid)
        self.assertEqual(error, "unsupported_task_family:task.unknown")

    def test_create_canonicalizes_legacy_classification_alias(self):
        config = create_task_capability_selection_config(
            {"selected_task_families": ["task.classification.text", "task.summarization.text"]}
        )
        self.assertEqual(
            config["selected_task_families"],
            ["task.classification", "task.summarization.text"],
        )

    def test_store_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task_capability_selection.json"
            store = TaskCapabilitySelectionConfigStore(path=str(path), logger=self.logger)
            config = create_task_capability_selection_config(
                {
                    "selected_task_families": [
                        "task.classification",
                        "task.summarization.text",
                    ]
                }
            )
            store.save(config)
            loaded = store.load()
            self.assertEqual(loaded, config)

    def test_store_load_or_create_creates_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task_capability_selection.json"
            store = TaskCapabilitySelectionConfigStore(path=str(path), logger=self.logger)
            config = store.load_or_create()
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), config)


if __name__ == "__main__":
    unittest.main()
