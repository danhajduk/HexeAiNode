import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.openai_catalog import OpenAIPricingCatalogService


FIXTURE_DIR = Path(__file__).parent / "providers" / "fixtures"


class _FixtureFetcher:
    def __init__(self, html: str):
        self._html = html

    async def fetch_first_available(self, *, urls: list[str]) -> tuple[str, str]:
        return urls[0], self._html


class PricingExtractionGoldenTests(unittest.IsolatedAsyncioTestCase):
    async def test_golden_pricing_extraction_fixture(self):
        html = (FIXTURE_DIR / "pricing_page_snapshot.html").read_text(encoding="utf-8")
        extraction_output = (FIXTURE_DIR / "pricing_extraction_ai_output.json").read_text(encoding="utf-8")
        expected = json.loads((FIXTURE_DIR / "pricing_extraction_expected.json").read_text(encoding="utf-8"))

        captured = {"prompt": ""}

        async def fake_execute(_model: str, _system_prompt: str, user_prompt: str) -> str:
            captured["prompt"] = user_prompt
            return extraction_output

        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("pricing-golden-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                text_cache_path=str(Path(tmp) / "pricing_page_text_cache.json"),
                overrides_path=str(Path(tmp) / "provider_model_pricing_overrides.json"),
                fetcher=_FixtureFetcher(html),
            )
            result = await service.refresh(
                force=True,
                model_ids=[
                    "gpt-5-mini",
                    "gpt-image-1.5",
                    "sora-2",
                    "whisper-1",
                    "tts-1",
                    "text-embedding-3-small",
                    "omni-moderation-stable",
                    "gpt-realtime-mini",
                    "gpt-5-chat-latest",
                ],
                execute_batch=fake_execute,
            )

            self.assertEqual(result["status"], "refreshed")
            self.assertIn("- gpt-5-mini", captured["prompt"])
            self.assertNotIn("- gpt-5-chat-latest", captured["prompt"])

            snapshot = service.load_snapshot()
            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.extraction_source, "ai_extraction")

            actual = [
                {
                    "model_id": entry.model_id,
                    "family": entry.family,
                    "pricing_basis": entry.pricing_basis,
                    "input_price": entry.input_price,
                    "cached_input_price": entry.cached_input_price,
                    "output_price": entry.output_price,
                    "normalized_price": entry.normalized_price,
                    "normalized_unit": entry.normalized_unit,
                }
                for entry in snapshot.entries
            ]
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
