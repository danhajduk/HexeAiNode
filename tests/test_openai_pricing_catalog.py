import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.models import ModelCapability
from ai_node.providers.openai_catalog import (
    OpenAIPricingCatalogService,
    OpenAIPricingPageParser,
    OpenAIPricingSnapshot,
    get_openai_model_pricing,
    is_openai_date_versioned_model_id,
    is_regular_openai_model_id,
    normalize_openai_display_name,
    resolve_openai_base_model_id,
    validate_openai_pricing_entries,
)


class _FakeFetcher:
    def __init__(self, *, html: str | None = None, error: str | None = None):
        self._html = html
        self._error = error

    async def fetch_first_available(self, *, urls: list[str]) -> tuple[str, str]:
        if self._error:
            raise RuntimeError(self._error)
        return urls[0], self._html or ""


class OpenAIPricingCatalogTests(unittest.IsolatedAsyncioTestCase):
    def test_normalization_helpers(self):
        self.assertEqual(normalize_openai_display_name("GPT-5 Mini"), "gpt-5-mini")
        self.assertEqual(resolve_openai_base_model_id("gpt-5-mini-2026-03-01"), "gpt-5-mini")
        self.assertEqual(resolve_openai_base_model_id("gpt-5-chat-latest"), "gpt-5-chat")
        self.assertTrue(is_openai_date_versioned_model_id("gpt-5-mini-2026-03-01"))
        self.assertTrue(is_openai_date_versioned_model_id("gpt-4-0613"))
        self.assertFalse(is_openai_date_versioned_model_id("gpt-5.4-pro"))
        self.assertTrue(is_regular_openai_model_id("gpt-5.4-pro"))
        self.assertFalse(is_regular_openai_model_id("gpt-5.3-chat-latest"))
        self.assertFalse(is_regular_openai_model_id("gpt-4o-realtime-preview"))
        self.assertFalse(is_regular_openai_model_id("gpt-4-0613"))

    def test_parser_extracts_prices_from_simple_html(self):
        parser = OpenAIPricingPageParser()
        html = """
        <section>
          <h2>GPT-5 mini</h2>
          <p>Input $0.25 / 1M tokens</p>
          <p>Cached input $0.025 / 1M tokens</p>
          <p>Output $2.00 / 1M tokens</p>
          <p>Batch input $0.125 / 1M tokens</p>
          <p>Batch output $1.00 / 1M tokens</p>
        </section>
        """
        entries = parser.parse(html=html, source_url="https://openai.com/api/pricing/", scraped_at="2026-03-13T00:00:00Z")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].model_id, "gpt-5-mini")
        self.assertEqual(entries[0].input_price_per_1m, 0.25)
        self.assertEqual(entries[0].cached_input_price_per_1m, 0.025)
        self.assertEqual(entries[0].output_price_per_1m, 2.0)
        self.assertEqual(entries[0].batch_input_price_per_1m, 0.125)
        self.assertEqual(entries[0].batch_output_price_per_1m, 1.0)

    def test_parser_extracts_compact_docs_table_rows(self):
        parser = OpenAIPricingPageParser()
        html = """
        <section>
          <h2>Standard</h2>
          <p>gpt-5.4-pro $3.00 $0.30 $15.00 --- --- ---</p>
          <h2>Batch</h2>
          <p>gpt-5.4-pro $1.50 $0.15 $7.50 --- --- ---</p>
        </section>
        """
        entries = parser.parse(
            html=html,
            source_url="https://developers.openai.com/api/docs/pricing",
            scraped_at="2026-03-13T00:00:00Z",
        )
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].model_id, "gpt-5.4-pro")
        self.assertEqual(entries[0].input_price_per_1m, 3.0)
        self.assertEqual(entries[0].cached_input_price_per_1m, 0.3)
        self.assertEqual(entries[0].output_price_per_1m, 15.0)
        self.assertEqual(entries[0].batch_input_price_per_1m, 1.5)
        self.assertEqual(entries[0].batch_output_price_per_1m, 7.5)

    async def test_refresh_keeps_manual_only_snapshot_and_cost_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "openai_pricing_catalog.json"),
            )
            service.save_manual_pricing(
                model_id="gpt-5-mini",
                input_price_per_1m=0.25,
                output_price_per_1m=2.0,
            )
            refresh = await service.refresh(force=True)
            self.assertEqual(refresh["status"], "manual_only")
            self.assertTrue(Path(tmp, "openai_pricing_catalog.json").exists())

            merged_models, unknown_models = service.merge_model_capabilities(
                [
                    ModelCapability(
                        model_id="gpt-5-mini-2026-03-01",
                        display_name="gpt-5-mini-2026-03-01",
                    )
                ]
            )
            self.assertEqual(unknown_models, [])
            self.assertEqual(merged_models[0].base_model_id, "gpt-5-mini")
            self.assertEqual(merged_models[0].pricing_input, 0.25)
            self.assertEqual(merged_models[0].pricing_output, 2.0)
            self.assertEqual(merged_models[0].pricing_status, "manual")

            pricing = get_openai_model_pricing("gpt-5-mini-2026-03-01", pricing_service=service)
            self.assertEqual(pricing["input_per_1m_tokens"], 0.25)
            self.assertEqual(pricing["output_per_1m_tokens"], 2.0)

    async def test_refresh_without_snapshot_reports_manual_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "openai_pricing_catalog.json"),
            )
            refresh = await service.refresh(force=True)
            self.assertEqual(refresh["status"], "manual_only")
            self.assertIsNone(refresh["snapshot"])
            diagnostics = service.diagnostics_payload()
            self.assertTrue(diagnostics["stale"])
            self.assertIn("live_pricing_scrape_disabled", diagnostics["notes"])

    def test_validation_rejects_empty_entry_sets(self):
        is_valid, error = validate_openai_pricing_entries([])
        self.assertFalse(is_valid)
        self.assertEqual(error, "pricing_entries_empty")

    def test_snapshot_model_validation_round_trip(self):
        snapshot = OpenAIPricingSnapshot(
            source_urls=["https://openai.com/api/pricing/"],
            source_url_used="https://openai.com/api/pricing/",
            scraped_at="2026-03-13T00:00:00Z",
            refresh_state="ok",
            stale=False,
            entries=[],
        )
        self.assertEqual(snapshot.refresh_state, "ok")

    def test_manual_pricing_creates_local_override_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "openai_pricing_catalog.json"),
            )
            payload = service.save_manual_pricing(
                model_id="gpt-5.4-pro-2026-03-05",
                display_name="GPT-5.4 Pro",
                input_price_per_1m=3.0,
                output_price_per_1m=15.0,
            )
            self.assertEqual(payload["status"], "manual_saved")
            diagnostics = service.diagnostics_payload()
            self.assertEqual(diagnostics["refresh_state"], "manual")
            pricing = get_openai_model_pricing("gpt-5.4-pro", pricing_service=service)
            self.assertEqual(pricing["pricing_status"], "manual")
            self.assertEqual(pricing["input_per_1m_tokens"], 3.0)


if __name__ == "__main__":
    unittest.main()
