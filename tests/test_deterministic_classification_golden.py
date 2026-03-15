import json
import unittest
from pathlib import Path

from ai_node.providers.model_capability_catalog import build_deterministic_entries
from ai_node.providers.openai_model_catalog import OpenAIProviderModelCatalogEntry


FIXTURE_DIR = Path(__file__).parent / "providers" / "fixtures"


class DeterministicClassificationGoldenTests(unittest.TestCase):
    def test_golden_deterministic_classification_fixture(self):
        source = json.loads((FIXTURE_DIR / "deterministic_classification_models.json").read_text(encoding="utf-8"))
        expected = json.loads((FIXTURE_DIR / "deterministic_classification_expected.json").read_text(encoding="utf-8"))

        models = [
            OpenAIProviderModelCatalogEntry(
                model_id=item["model_id"],
                family=item["family"],
                discovered_at=source["discovered_at"],
            )
            for item in source["models"]
        ]

        actual = [entry.model_dump() for entry in build_deterministic_entries(models=models)]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
