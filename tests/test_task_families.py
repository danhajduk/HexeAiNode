import unittest

from ai_node.capabilities.task_families import (
    CANONICAL_TASK_FAMILIES,
    TASK_CLASSIFICATION,
    create_declared_task_family_capabilities,
    validate_task_family_capabilities,
)


class TaskFamilyCapabilityTests(unittest.TestCase):
    def test_default_declared_task_families_match_canonical(self):
        declared = create_declared_task_family_capabilities()
        self.assertEqual(declared, list(CANONICAL_TASK_FAMILIES))

    def test_validate_rejects_invalid_task_family(self):
        is_valid, error = validate_task_family_capabilities(["task.classification", "BAD FAMILY"])
        self.assertFalse(is_valid)
        self.assertEqual(error, "invalid_task_family:bad family")

    def test_create_rejects_invalid_task_family(self):
        with self.assertRaises(ValueError):
            create_declared_task_family_capabilities(["task.summarization.text", "BAD FAMILY"])

    def test_legacy_classification_alias_is_canonicalized(self):
        declared = create_declared_task_family_capabilities(["task.classification.text"])
        self.assertEqual(declared, [TASK_CLASSIFICATION])


if __name__ == "__main__":
    unittest.main()
