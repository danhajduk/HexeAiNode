import unittest

from ai_node.capabilities.task_families import CANONICAL_TASK_FAMILIES
from ai_node.execution.task_families import (
    PHASE3_TASK_FAMILY_V1,
    canonicalize_phase3_task_family,
    validate_execution_task_family,
)


class Phase3TaskFamilyVocabularyTests(unittest.TestCase):
    def test_phase3_v1_reuses_existing_extended_task_family_vocabulary(self):
        self.assertEqual(PHASE3_TASK_FAMILY_V1, tuple(CANONICAL_TASK_FAMILIES))

    def test_canonicalize_keeps_existing_extended_family_values(self):
        self.assertEqual(canonicalize_phase3_task_family("task.classification.text"), "task.classification.text")
        self.assertEqual(canonicalize_phase3_task_family("task.chat"), "task.chat")
        self.assertEqual(canonicalize_phase3_task_family("task.structured_extraction"), "task.structured_extraction")

    def test_validate_allows_family_when_declared_and_accepted(self):
        result = validate_execution_task_family(
            task_family="task.classification.text",
            declared_task_families=["task.classification.text", "task.chat"],
            accepted_capability_profile={"declared_task_families": ["task.classification.text", "task.chat"]},
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "task_family_allowed")
        self.assertEqual(result.canonical_task_family, "task.classification.text")

    def test_validate_rejects_non_canonical_family(self):
        result = validate_execution_task_family(
            task_family="task.chat_response",
            declared_task_families=["task.chat"],
            accepted_capability_profile={"declared_task_families": ["task.chat"]},
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "unsupported_task_family")

    def test_validate_rejects_family_not_declared(self):
        result = validate_execution_task_family(
            task_family="task.translation",
            declared_task_families=["task.classification.text"],
            accepted_capability_profile={"declared_task_families": ["task.translation"]},
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "task_family_not_declared")

    def test_validate_rejects_family_not_accepted(self):
        result = validate_execution_task_family(
            task_family="task.translation",
            declared_task_families=["task.translation"],
            accepted_capability_profile={"declared_task_families": ["task.classification.text"]},
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "task_family_not_accepted")


if __name__ == "__main__":
    unittest.main()
