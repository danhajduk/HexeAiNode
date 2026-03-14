import unittest

from ai_node.providers.model_feature_schema import MODEL_FEATURE_KEYS, create_default_feature_flags, normalize_feature_flags


class ModelFeatureSchemaTests(unittest.TestCase):
    def test_default_feature_flags_include_full_schema(self):
        flags = create_default_feature_flags()
        self.assertEqual(set(flags.keys()), set(MODEL_FEATURE_KEYS))
        self.assertTrue(all(value is False for value in flags.values()))

    def test_normalize_feature_flags_accepts_partial_updates(self):
        flags = normalize_feature_flags(feature_flags={"chat": True, "moderation": True})
        self.assertTrue(flags["chat"])
        self.assertTrue(flags["moderation"])
        self.assertFalse(flags["reasoning"])

    def test_normalize_feature_flags_rejects_unknown_features(self):
        with self.assertRaisesRegex(ValueError, "classification_feature_unknown"):
            normalize_feature_flags(feature_flags={"unknown_feature": True})

    def test_normalize_feature_flags_rejects_non_boolean_values(self):
        with self.assertRaisesRegex(ValueError, "classification_feature_value_invalid"):
            normalize_feature_flags(feature_flags={"chat": "yes"})


if __name__ == "__main__":
    unittest.main()
