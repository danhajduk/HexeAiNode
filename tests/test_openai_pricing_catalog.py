import json
import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.providers.models import ModelCapability
from ai_node.providers.openai_catalog import (
    OpenAIPricingCatalogService,
    OpenAIPricingEntry,
    OpenAIPricingPageParser,
    OpenAIPricingSnapshot,
    _build_family_pricing_extraction_prompt,
    _normalize_extracted_payload,
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

    def test_parser_extracts_entries_from_compact_rows(self):
        parser = OpenAIPricingPageParser()
        html = """
        <section>
          <p>gpt-5.4-pro $3.00 $0.30 $15.00 --- --- ---</p>
          <p>text-embedding-3-small $0.10</p>
        </section>
        """
        entries = parser.parse(
            html=html,
            source_url="https://developers.openai.com/api/docs/pricing",
            scraped_at="2026-03-13T00:00:00Z",
        )
        self.assertEqual([entry.model_id for entry in entries], ["gpt-5.4-pro", "text-embedding-3-small"])
        self.assertEqual(entries[0].pricing_basis, "per_1m_tokens")
        self.assertEqual(entries[0].input_price, 3.0)
        self.assertEqual(entries[0].output_price, 15.0)

    def test_pricing_source_normalization_removes_wrapper_noise(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        normalized = service._normalize_pricing_source_text(
            page_text="""
            import { x } from "y";
            <style>.foo { color: red; }</style>
            <script>console.log("noise")</script>
            <div class="wrapper">
            GPT-5.4
            Input: $1.25 / 1M tokens
            </div>
            className="layout-shell"
            export const page = {};
            """
        )
        self.assertNotIn("import { x }", normalized)
        self.assertNotIn("console.log", normalized)
        self.assertNotIn("<div", normalized)
        self.assertNotIn("className=", normalized)
        self.assertIn("GPT-5.4", normalized)
        self.assertIn("Input: $1.25 / 1M tokens", normalized)

    def test_pricing_source_section_splitter_extracts_canonical_sections(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        sections = service._split_pricing_source_sections(
            normalized_text="""
            ## Text tokens
            gpt-5-mini
            Input: $0.25 / 1M

            ## Image generation
            gpt-image-1.5
            $0.19 per image

            ## Moderation
            omni-moderation-2024-09-26
            Free of charge
            """
        )
        self.assertIn("gpt-5-mini", sections["text_tokens"])
        self.assertIn("gpt-image-1.5", sections["image_generation"])
        self.assertIn("omni-moderation-2024-09-26", sections["moderation"])
        self.assertEqual(sections["audio_tokens"], "")

    def test_section_splitter_keeps_sections_empty_when_only_headings_present(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        sections = service._split_pricing_source_sections(
            normalized_text="""
            ## Text tokens

            ## Image generation
            """
        )
        self.assertEqual(sections["text_tokens"], "")
        self.assertEqual(sections["image_generation"], "")

    def test_extract_text_token_pricing_rows_filters_headings_and_empty_blocks(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        extracted = service._extract_text_token_pricing_rows(
            section_text="""
            ## Text tokens
            Model | Input | Output

            gpt-5-mini
            Input: $0.25 / 1M
            Output: $2.00 / 1M

            gpt-5.4-pro
            Input: $3.00 / 1M
            Output: $15.00 / 1M

            gpt-5.4

            gpt-4.1-mini
            Input: $0.80 / 1M
            Output: $3.20 / 1M
            """,
            target_model_ids=["gpt-5-mini", "gpt-5.4", "gpt-5.4-pro"],
        )
        self.assertIn("gpt-5-mini", extracted)
        self.assertIn("gpt-5.4-pro", extracted)
        self.assertNotIn("Model | Input | Output", extracted)
        self.assertNotIn("gpt-5.4\n", extracted)
        self.assertNotIn("gpt-4.1-mini", extracted)

    def test_extractors_ignore_heading_only_boilerplate_sections(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        self.assertEqual(
            service._extract_text_token_pricing_rows(
                section_text="## Text tokens\nModel | Input | Output",
                target_model_ids=["gpt-5-mini"],
            ),
            "",
        )
        self.assertEqual(
            service._extract_embeddings_pricing_rows(
                section_text="## Embeddings\nModel | Price",
                target_model_ids=["text-embedding-3-small"],
            ),
            "",
        )

    def test_extract_audio_realtime_rows_reads_audio_and_transcription_sections(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        extracted = service._extract_audio_realtime_pricing_rows(
            audio_tokens_section="""
            ## Audio tokens
            gpt-realtime-1.5
            Input: $4.00 / 1M
            Output: $16.00 / 1M
            """,
            transcription_section="""
            ## Transcription and speech generation
            gpt-realtime-mini
            Input: $0.60 / 1M
            Output: $2.40 / 1M
            """,
            target_model_ids=["gpt-realtime-1.5", "gpt-realtime-mini"],
        )
        self.assertIn("gpt-realtime-1.5", extracted)
        self.assertIn("$4.00", extracted)
        self.assertIn("gpt-realtime-mini", extracted)
        self.assertIn("$2.40", extracted)

    def test_extract_image_generation_rows_prefers_medium_1024x1536(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        extracted = service._extract_image_generation_pricing_rows(
            section_text="""
            ## Image generation
            gpt-image-1.5
            low 1024x1024: $0.04
            medium 1024x1536: $0.19
            high 1536x1536: $0.40
            """,
            target_model_ids=["gpt-image-1.5", "gpt-image-1-mini"],
        )
        self.assertIn("gpt-image-1.5", extracted)
        self.assertIn("medium 1024x1536: $0.19", extracted)
        self.assertNotIn("low 1024x1024: $0.04", extracted)

    def test_extract_video_rows_preserves_standard_and_batch_rates(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        extracted = service._extract_video_pricing_rows(
            section_text="""
            ## Video
            sora-2
            standard: $0.12 per second
            batch: $0.06 per second
            1080p output
            """,
            target_model_ids=["sora-2"],
        )
        self.assertIn("sora-2", extracted)
        self.assertIn("standard: $0.12 per second", extracted)
        self.assertIn("batch: $0.06 per second", extracted)
        self.assertIn("1080p output", extracted)

    def test_extract_stt_tts_other_rows_preserves_official_units(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        extracted = service._extract_stt_tts_other_pricing_rows(
            other_models_section="""
            ## Other models
            whisper-1
            $0.006 per minute
            tts-1-hd
            $30 per 1M characters
            """,
            transcription_section="""
            ## Transcription and speech generation
            tts-1
            $15 per 1M characters
            """,
            target_model_ids=["whisper-1", "tts-1", "tts-1-hd"],
        )
        self.assertIn("whisper-1", extracted)
        self.assertIn("$0.006 per minute", extracted)
        self.assertIn("tts-1", extracted)
        self.assertIn("$15 per 1M characters", extracted)
        self.assertIn("tts-1-hd", extracted)
        self.assertIn("$30 per 1M characters", extracted)

    def test_extract_embeddings_rows_includes_token_pricing_content(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        extracted = service._extract_embeddings_pricing_rows(
            section_text="""
            ## Embeddings
            text-embedding-3-small
            $0.10 / 1M tokens
            """,
            target_model_ids=["text-embedding-3-small"],
        )
        self.assertIn("text-embedding-3-small", extracted)
        self.assertIn("$0.10 / 1M tokens", extracted)

    def test_extract_moderation_rows_supports_free_status(self):
        service = OpenAIPricingCatalogService(
            logger=logging.getLogger("openai-pricing-test"),
        )
        extracted = service._extract_moderation_pricing_rows(
            section_text="""
            ## Moderation
            omni-moderation-2024-09-26
            Free of charge
            """,
            target_model_ids=["omni-moderation-2024-09-26"],
        )
        self.assertIn("omni-moderation-2024-09-26", extracted)
        self.assertIn("Free of charge", extracted)

    def test_normalize_extracted_payload_uses_null_for_non_applicable_zero_fields(self):
        entries = _normalize_extracted_payload(
            payload={
                "models": [
                    {
                        "model_id": "whisper-1",
                        "family": "speech_to_text",
                        "pricing_basis": "per_minute",
                        "input_price": 0.0,
                        "cached_input_price": 0.0,
                        "output_price": 0.0,
                        "normalized_price": 0.006,
                        "normalized_unit": "per_minute",
                    },
                    {
                        "model_id": "tts-1-hd",
                        "family": "text_to_speech",
                        "pricing_basis": "per_1m_characters",
                        "input_price": 0.0,
                        "cached_input_price": 0.0,
                        "output_price": 0.0,
                        "normalized_price": 30.0,
                        "normalized_unit": "per_1m_characters",
                    },
                ]
            },
            allowed_models={
                "whisper-1": "speech_to_text",
                "tts-1-hd": "text_to_speech",
            },
            source_url="https://developers.openai.com/api/docs/pricing",
            extracted_at="2026-03-14T00:00:00Z",
        )
        by_id = {entry.model_id: entry for entry in entries}
        self.assertIsNone(by_id["whisper-1"].input_price)
        self.assertIsNone(by_id["whisper-1"].cached_input_price)
        self.assertIsNone(by_id["whisper-1"].output_price)
        self.assertEqual(by_id["whisper-1"].normalized_price, 0.006)
        self.assertIsNone(by_id["tts-1-hd"].input_price)
        self.assertIsNone(by_id["tts-1-hd"].cached_input_price)
        self.assertIsNone(by_id["tts-1-hd"].output_price)
        self.assertEqual(by_id["tts-1-hd"].normalized_price, 30.0)

    def test_normalize_extracted_payload_applies_family_rules(self):
        entries = _normalize_extracted_payload(
            payload={
                "models": [
                    {
                        "model_id": "gpt-image-1.5",
                        "family": "image_generation",
                        "pricing_basis": "per_1m_tokens",
                        "input_price": 0.0,
                        "output_price": 0.19,
                        "normalized_price": None,
                        "normalized_unit": "per_1m_tokens",
                    },
                    {
                        "model_id": "omni-moderation-2024-09-26",
                        "family": "moderation",
                        "pricing_basis": "per_1m_tokens",
                        "input_price": None,
                        "cached_input_price": None,
                        "output_price": None,
                        "normalized_price": None,
                        "normalized_unit": "per_1m_tokens",
                        "notes": ["free of charge"],
                    },
                ]
            },
            allowed_models={
                "gpt-image-1.5": "image_generation",
                "omni-moderation-2024-09-26": "moderation",
            },
            source_url="https://developers.openai.com/api/docs/pricing",
            extracted_at="2026-03-14T00:00:00Z",
        )
        by_id = {entry.model_id: entry for entry in entries}
        self.assertEqual(by_id["gpt-image-1.5"].pricing_basis, "per_image")
        self.assertEqual(by_id["gpt-image-1.5"].normalized_unit, "medium_1024x1536_per_image")
        self.assertEqual(by_id["gpt-image-1.5"].normalized_price, 0.19)
        self.assertEqual(by_id["omni-moderation-2024-09-26"].normalized_price, 0.0)
        self.assertIn("status:free", by_id["omni-moderation-2024-09-26"].notes)

    async def test_refresh_runs_ai_extraction_for_filtered_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            debug_path = Path(tmp) / "response.json"
            normalized_cache_path = Path(tmp) / "pricing_page_text_normalized_cache.json"
            sections_cache_path = Path(tmp) / "pricing_page_sections_cache.json"
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                fetcher=_FakeFetcher(html="<section><p>gpt-5-mini Input $0.25 Output $2.00</p></section>"),
                debug_response_path=str(debug_path),
                normalized_text_cache_path=str(normalized_cache_path),
                sections_cache_path=str(sections_cache_path),
            )

            seen_prompt_families: list[str] = []

            async def fake_execute(_model: str, system_prompt: str, user_prompt: str) -> str:
                self.assertIn("return json only", system_prompt.lower())
                self.assertIn("You are extracting OpenAI pricing from official pricing page text.", user_prompt)
                self.assertNotIn("- gpt-5-chat-latest", user_prompt)
                if "Prompt Family: llm_pricing_extraction_prompt" in user_prompt:
                    seen_prompt_families.append("llm")
                    self.assertIn("- gpt-5-mini", user_prompt)
                    self.assertIn("- gpt-4.1", user_prompt)
                    self.assertNotIn("- omni-moderation-2024-09-26", user_prompt)
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-5-mini",
                                    "family": "llm",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.25,
                                    "cached_input_price": 0.025,
                                    "output_price": 2.0,
                                    "batch_input_price": 0.125,
                                    "batch_output_price": 1.0,
                                    "normalized_price": 2.0,
                                    "normalized_unit": "per_1m_tokens",
                                    "notes": ["ai_extracted"],
                                }
                            ]
                        }
                    )
                if "Prompt Family: embeddings_moderation_pricing_extraction_prompt" in user_prompt:
                    seen_prompt_families.append("embeddings_moderation")
                    self.assertIn("- omni-moderation-2024-09-26", user_prompt)
                    self.assertNotIn("- gpt-5-mini", user_prompt)
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "omni-moderation-2024-09-26",
                                    "family": "moderation",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.1,
                                    "cached_input_price": 0.01,
                                    "output_price": 0.4,
                                    "normalized_price": 0.4,
                                    "normalized_unit": "per_1m_tokens",
                                    "notes": ["ai_extracted"],
                                },
                            ]
                        }
                    )
                self.fail(f"Unexpected prompt family in user_prompt: {user_prompt[:120]}")
                return json.dumps({"models": []})

            refresh = await service.refresh(
                force=True,
                model_ids=["gpt-5-mini", "gpt-4.1", "omni-moderation-2024-09-26", "gpt-5-chat-latest"],
                execute_batch=fake_execute,
            )
            self.assertEqual(refresh["status"], "refreshed")
            snapshot = service.load_snapshot()
            self.assertIsNotNone(snapshot)
            by_id = {entry.model_id: entry for entry in snapshot.entries}
            self.assertEqual(by_id["gpt-5-mini"].pricing_basis, "per_1m_tokens")
            self.assertIn("batch_prices_ignored", by_id["gpt-5-mini"].notes)
            self.assertEqual(by_id["omni-moderation-2024-09-26"].family, "moderation")
            self.assertEqual(snapshot.extraction_source, "ai_extraction_family_prompts")
            self.assertEqual(sorted(seen_prompt_families), ["embeddings_moderation", "llm"])
            self.assertTrue(debug_path.exists())
            debug_payload = json.loads(debug_path.read_text(encoding="utf-8"))
            self.assertIn("raw_response", debug_payload)
            self.assertIn("parsed_response", debug_payload)
            self.assertTrue(normalized_cache_path.exists())
            normalized_payload = json.loads(normalized_cache_path.read_text(encoding="utf-8"))
            self.assertIn("gpt-5-mini Input $0.25 Output $2.00", normalized_payload["text"])
            self.assertTrue(sections_cache_path.exists())
            sections_payload = json.loads(sections_cache_path.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(sections_payload["sections"].keys()),
                sorted(
                    [
                        "text_tokens",
                        "image_tokens",
                        "audio_tokens",
                        "video",
                        "transcription_and_speech_generation",
                        "other_models",
                        "image_generation",
                        "embeddings",
                        "moderation",
                    ]
                ),
            )
            self.assertIn("extracted_sections", sections_payload)
            self.assertIn("text_tokens_target_rows", sections_payload["extracted_sections"])
            self.assertIn("audio_realtime_target_rows", sections_payload["extracted_sections"])
            self.assertIn("image_generation_target_rows", sections_payload["extracted_sections"])
            self.assertIn("video_generation_target_rows", sections_payload["extracted_sections"])
            self.assertIn("stt_tts_other_target_rows", sections_payload["extracted_sections"])
            self.assertIn("embeddings_target_rows", sections_payload["extracted_sections"])
            self.assertIn("moderation_target_rows", sections_payload["extracted_sections"])
            self.assertIn("family_diagnostics", sections_payload)
            llm_diag = sections_payload["family_diagnostics"]["llm_pricing_extraction_prompt"]
            self.assertIn("target_models", llm_diag)
            self.assertIn("source_section_name", llm_diag)
            self.assertIn("normalized_source_snippet", llm_diag)
            self.assertIn("extraction_prompt_used", llm_diag)
            self.assertIn("raw_extraction_result", llm_diag)
            self.assertIn("validation_result", llm_diag)
            self.assertEqual(
                debug_payload["allowed_model_ids"],
                ["gpt-4.1", "gpt-5-mini", "omni-moderation-2024-09-26"],
            )
            self.assertTrue(Path(tmp, "provider_model_pricing.json").exists())

    async def test_refresh_preserves_last_known_good_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                fetcher=_FakeFetcher(html="<section><p>gpt-5-mini Input $0.25 Output $2.00</p></section>"),
            )
            service.save_manual_pricing(
                model_id="gpt-5-mini",
                input_price_per_1m=0.25,
                output_price_per_1m=2.0,
            )

            async def bad_execute(_model: str, _system_prompt: str, _user_prompt: str) -> str:
                return "{invalid_json"

            refresh = await service.refresh(
                force=True,
                model_ids=["gpt-5-mini"],
                execute_batch=bad_execute,
            )
            self.assertEqual(refresh["status"], "refreshed")
            pricing = get_openai_model_pricing("gpt-5-mini", pricing_service=service)
            self.assertEqual(pricing["input_per_1m_tokens"], 0.25)
            diagnostics = service.diagnostics_payload()
            self.assertEqual(diagnostics["refresh_state"], "ok")

    async def test_refresh_rejects_malformed_family_without_failing_successful_families(self):
        with tempfile.TemporaryDirectory() as tmp:
            debug_path = Path(tmp) / "response.json"
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                fetcher=_FakeFetcher(html="<section><p>gpt-5-mini Input $0.25 Output $2.00</p></section>"),
                debug_response_path=str(debug_path),
            )

            async def mixed_execute(_model: str, _system_prompt: str, user_prompt: str) -> str:
                if "Prompt Family: llm_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-5-mini",
                                    "family": "llm",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.25,
                                    "output_price": 2.0,
                                    "normalized_price": 2.0,
                                    "normalized_unit": "per_1m_tokens",
                                }
                            ]
                        }
                    )
                if "Prompt Family: embeddings_moderation_pricing_extraction_prompt" in user_prompt:
                    return "{invalid_json"
                return json.dumps({"models": []})

            refresh = await service.refresh(
                force=True,
                model_ids=["gpt-5-mini", "omni-moderation-2024-09-26"],
                execute_batch=mixed_execute,
            )
            self.assertEqual(refresh["status"], "refreshed")
            snapshot = service.load_snapshot()
            self.assertIsNotNone(snapshot)
            by_id = {entry.model_id: entry for entry in snapshot.entries}
            self.assertIn("gpt-5-mini", by_id)
            self.assertNotIn("omni-moderation-2024-09-26", by_id)
            self.assertEqual(snapshot.extraction_source, "ai_extraction_family_prompts_partial")
            debug_payload = json.loads(debug_path.read_text(encoding="utf-8"))
            self.assertEqual(
                debug_payload["family_validation_results"]["embeddings_moderation_pricing_extraction_prompt"]["status"],
                "failed",
            )

    async def test_refresh_uses_last_known_good_family_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                fetcher=_FakeFetcher(html="<section><p>gpt-5-mini Input $0.25 Output $2.00</p></section>"),
            )

            async def first_execute(_model: str, _system_prompt: str, user_prompt: str) -> str:
                if "Prompt Family: llm_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-5-mini",
                                    "family": "llm",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.25,
                                    "output_price": 2.0,
                                    "normalized_price": 2.0,
                                    "normalized_unit": "per_1m_tokens",
                                }
                            ]
                        }
                    )
                if "Prompt Family: embeddings_moderation_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "omni-moderation-2024-09-26",
                                    "family": "moderation",
                                    "pricing_basis": "per_1m_tokens",
                                    "normalized_price": 0.0,
                                    "normalized_unit": "per_1m_tokens",
                                    "notes": ["free of charge"],
                                }
                            ]
                        }
                    )
                return json.dumps({"models": []})

            first = await service.refresh(
                force=True,
                model_ids=["gpt-5-mini", "omni-moderation-2024-09-26"],
                execute_batch=first_execute,
            )
            self.assertEqual(first["status"], "refreshed")

            async def second_execute(_model: str, _system_prompt: str, user_prompt: str) -> str:
                if "Prompt Family: llm_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-5-mini",
                                    "family": "llm",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.30,
                                    "output_price": 2.2,
                                    "normalized_price": 2.2,
                                    "normalized_unit": "per_1m_tokens",
                                }
                            ]
                        }
                    )
                if "Prompt Family: embeddings_moderation_pricing_extraction_prompt" in user_prompt:
                    return "{invalid_json"
                return json.dumps({"models": []})

            second = await service.refresh(
                force=True,
                model_ids=["gpt-5-mini", "omni-moderation-2024-09-26"],
                execute_batch=second_execute,
            )
            self.assertEqual(second["status"], "refreshed")
            snapshot = service.load_snapshot()
            self.assertIsNotNone(snapshot)
            by_id = {entry.model_id: entry for entry in snapshot.entries}
            self.assertEqual(by_id["gpt-5-mini"].output_price, 2.2)
            self.assertIn("omni-moderation-2024-09-26", by_id)
            self.assertEqual(by_id["omni-moderation-2024-09-26"].extraction_status, "fallback_used")
            self.assertTrue(
                any(note == "family_status:moderation=fallback_used" for note in (snapshot.notes or []))
            )

    async def test_integration_end_to_end_family_refresh_pipeline(self):
        fixtures_root = Path(__file__).parent / "providers" / "fixtures" / "pricing_sections"
        index_payload = json.loads((fixtures_root / "index.json").read_text(encoding="utf-8"))
        combined_source = "\n\n".join(
            (fixtures_root / index_payload[name]).read_text(encoding="utf-8")
            for name in [
                "text_tokens",
                "audio_tokens",
                "image_generation",
                "video",
                "other_models",
                "embeddings",
                "moderation",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                fetcher=_FakeFetcher(html=combined_source),
            )

            async def integration_execute(_model: str, _system_prompt: str, user_prompt: str) -> str:
                if "Prompt Family: llm_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-5-mini",
                                    "family": "llm",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.25,
                                    "cached_input_price": 0.025,
                                    "output_price": 2.0,
                                    "normalized_price": 2.0,
                                    "normalized_unit": "per_1m_tokens",
                                }
                            ]
                        }
                    )
                if "Prompt Family: realtime_audio_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-realtime-mini",
                                    "family": "realtime_voice",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.60,
                                    "output_price": 2.40,
                                    "normalized_price": 2.40,
                                    "normalized_unit": "per_1m_tokens",
                                }
                            ]
                        }
                    )
                if "Prompt Family: image_generation_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-image-1.5",
                                    "family": "image_generation",
                                    "pricing_basis": "per_image",
                                    "output_price": 0.19,
                                    "normalized_price": 0.19,
                                    "normalized_unit": "medium_1024x1536_per_image",
                                }
                            ]
                        }
                    )
                if "Prompt Family: video_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "sora-2",
                                    "family": "video_generation",
                                    "pricing_basis": "per_second",
                                    "output_price": 0.12,
                                    "normalized_price": 0.12,
                                    "normalized_unit": "per_second",
                                }
                            ]
                        }
                    )
                if "Prompt Family: stt_tts_other_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "whisper-1",
                                    "family": "speech_to_text",
                                    "pricing_basis": "per_minute",
                                    "normalized_price": 0.006,
                                    "normalized_unit": "per_minute",
                                },
                                {
                                    "model_id": "tts-1",
                                    "family": "text_to_speech",
                                    "pricing_basis": "per_1m_characters",
                                    "normalized_price": 15.0,
                                    "normalized_unit": "per_1m_characters",
                                },
                            ]
                        }
                    )
                if "Prompt Family: embeddings_moderation_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "text-embedding-3-small",
                                    "family": "embeddings",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.10,
                                    "normalized_price": 0.10,
                                    "normalized_unit": "per_1m_tokens",
                                },
                                {
                                    "model_id": "omni-moderation-2024-09-26",
                                    "family": "moderation",
                                    "pricing_basis": "per_1m_tokens",
                                    "normalized_price": 0.0,
                                    "normalized_unit": "per_1m_tokens",
                                    "notes": ["free of charge"],
                                },
                            ]
                        }
                    )
                return json.dumps({"models": []})

            refresh = await service.refresh(
                force=True,
                model_ids=[
                    "gpt-5-mini",
                    "gpt-realtime-mini",
                    "gpt-image-1.5",
                    "sora-2",
                    "whisper-1",
                    "tts-1",
                    "text-embedding-3-small",
                    "omni-moderation-2024-09-26",
                ],
                execute_batch=integration_execute,
            )
            self.assertEqual(refresh["status"], "refreshed")
            snapshot = service.load_snapshot()
            self.assertIsNotNone(snapshot)
            by_id = {entry.model_id: entry for entry in snapshot.entries}
            self.assertEqual(by_id["gpt-5-mini"].pricing_basis, "per_1m_tokens")
            self.assertEqual(by_id["gpt-realtime-mini"].pricing_basis, "per_1m_tokens")
            self.assertEqual(by_id["gpt-image-1.5"].pricing_basis, "per_image")
            self.assertEqual(by_id["sora-2"].pricing_basis, "per_second")
            self.assertEqual(by_id["whisper-1"].pricing_basis, "per_minute")
            self.assertEqual(by_id["tts-1"].pricing_basis, "per_1m_characters")
            self.assertEqual(by_id["text-embedding-3-small"].pricing_basis, "per_1m_tokens")
            self.assertIn("status:free", by_id["omni-moderation-2024-09-26"].notes)

    async def test_manual_pricing_and_merge_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
            )
            payload = service.save_manual_pricing(
                model_id="gpt-5.4-pro-2026-03-05",
                input_price_per_1m=3.0,
                output_price_per_1m=15.0,
            )
            self.assertEqual(payload["status"], "manual_saved")
            pricing = get_openai_model_pricing("gpt-5.4-pro", pricing_service=service)
            self.assertEqual(pricing["pricing_status"], "manual")
            self.assertEqual(pricing["input_per_1m_tokens"], 3.0)

            merged_models, unknown_models = service.merge_model_capabilities(
                [
                    ModelCapability(
                        model_id="gpt-5.4-pro-2026-03-05",
                        display_name="gpt-5.4-pro-2026-03-05",
                    )
                ]
            )
            self.assertEqual(unknown_models, [])
            self.assertEqual(merged_models[0].base_model_id, "gpt-5.4-pro")
            self.assertEqual(merged_models[0].pricing_input, 3.0)
            self.assertEqual(merged_models[0].pricing_output, 15.0)

    async def test_builtin_fallback_pricing_for_current_gpt_54_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
            )

            mini_pricing = get_openai_model_pricing("gpt-5.4-mini-2026-03-17", pricing_service=service)
            pricing = get_openai_model_pricing("gpt-5.4-nano-2026-03-17", pricing_service=service)

            self.assertEqual(mini_pricing["pricing_status"], "manual")
            self.assertEqual(mini_pricing["input_per_1m_tokens"], 0.75)
            self.assertEqual(mini_pricing["cached_input_per_1m_tokens"], 0.075)
            self.assertEqual(mini_pricing["output_per_1m_tokens"], 4.5)
            self.assertEqual(pricing["pricing_status"], "manual")
            self.assertEqual(pricing["input_per_1m_tokens"], 0.20)
            self.assertEqual(pricing["cached_input_per_1m_tokens"], 0.02)
            self.assertEqual(pricing["output_per_1m_tokens"], 1.25)

    async def test_merge_keeps_free_moderation_model_available_when_fallback_pricing_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
            )
            service._store.save(  # noqa: SLF001
                OpenAIPricingSnapshot(
                    refresh_state="ok",
                    stale=False,
                    source_urls=["https://developers.openai.com/api/docs/pricing.md"],
                    source_url_used="https://developers.openai.com/api/docs/pricing.md",
                    scraped_at="2026-04-04T12:00:00+00:00",
                    extraction_source="ai_extraction_family_prompts_partial",
                    entries=[
                        OpenAIPricingEntry(
                            model_id="omni-moderation-2024-09-26",
                            family="moderation",
                            pricing_basis="per_1m_tokens",
                            input_price=0.0,
                            output_price=0.0,
                            cached_input_price=0.0,
                            normalized_price=0.0,
                            normalized_unit="per_1m_tokens",
                            source_url="https://developers.openai.com/api/docs/pricing.md",
                            extracted_at="2026-04-04T12:00:00+00:00",
                            extraction_status="fallback_used",
                            notes=["status:free"],
                        )
                    ],
                )
            )

            merged_models, unknown_models = service.merge_model_capabilities(
                [
                    ModelCapability(
                        model_id="omni-moderation-2024-09-26",
                        display_name="omni-moderation-2024-09-26",
                        status="available",
                    )
                ]
            )

            self.assertEqual(unknown_models, [])
            self.assertEqual(merged_models[0].status, "available")
            self.assertEqual(merged_models[0].pricing_input, 0.0)
            self.assertEqual(merged_models[0].pricing_output, 0.0)

    async def test_manual_pricing_persists_across_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                overrides_path=str(Path(tmp) / "provider_model_pricing_overrides.json"),
                manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
                fetcher=_FakeFetcher(html="<section><p>gpt-5-mini Input $0.50 Output $4.00</p></section>"),
            )
            service.save_manual_pricing(
                model_id="gpt-5-mini",
                input_price_per_1m=0.25,
                output_price_per_1m=2.0,
            )

            async def execute(_model: str, _system_prompt: str, user_prompt: str) -> str:
                if "Prompt Family: llm_pricing_extraction_prompt" in user_prompt:
                    return json.dumps(
                        {
                            "models": [
                                {
                                    "model_id": "gpt-5-mini",
                                    "family": "llm",
                                    "pricing_basis": "per_1m_tokens",
                                    "input_price": 0.50,
                                    "output_price": 4.0,
                                    "normalized_price": 4.0,
                                    "normalized_unit": "per_1m_tokens",
                                }
                            ]
                        }
                    )
                return json.dumps({"models": []})

            refresh = await service.refresh(force=True, model_ids=["gpt-5-mini"], execute_batch=execute)

            self.assertEqual(refresh["status"], "refreshed")
            pricing = get_openai_model_pricing("gpt-5-mini", pricing_service=service)
            self.assertEqual(pricing["input_per_1m_tokens"], 0.25)
            self.assertEqual(pricing["output_per_1m_tokens"], 2.0)
            overrides_payload = json.loads(Path(tmp, "provider_model_pricing_overrides.json").read_text(encoding="utf-8"))
            self.assertEqual(overrides_payload["models"][0]["model_id"], "gpt-5-mini")

    def test_manual_pricing_yaml_is_scaffolded_from_known_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "provider_model_classifications.json").write_text(
                json.dumps(
                    {
                        "entries": [
                            {"model_id": "gpt-5.4-mini"},
                            {"model_id": "gpt-realtime-mini"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                overrides_path=str(Path(tmp) / "provider_model_pricing_overrides.json"),
                manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
            )

            manual_yaml = Path(tmp, "openai-pricing.yaml").read_text(encoding="utf-8")

            self.assertIsNotNone(service)
            self.assertIn("models:", manual_yaml)
            self.assertIn("  gpt-5.4-mini:", manual_yaml)
            self.assertIn("  gpt-realtime-mini:", manual_yaml)

    def test_manual_pricing_yaml_overrides_catalog_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "provider_model_pricing.json").write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "parser_version": "2.0",
                        "refresh_state": "ok",
                        "stale": False,
                        "entries": [
                            {
                                "model_id": "gpt-5.4-mini",
                                "family": "llm",
                                "pricing_basis": "per_1m_tokens",
                                "input_price": 0.375,
                                "cached_input_price": None,
                                "output_price": 2.25,
                                "normalized_price": 2.25,
                                "normalized_unit": "per_1m_tokens",
                                "notes": [],
                                "source_url": "manual://local_override",
                                "extracted_at": "2026-04-04T00:00:00+00:00",
                                "extraction_status": "manual",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            Path(tmp, "openai-pricing.yaml").write_text(
                "\n".join(
                    [
                        "version: 1",
                        "models:",
                        "  gpt-5.4-mini:",
                        "    Input: 0.75",
                        "    Cached input: 0.075",
                        "    Output: 4.5",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            service = OpenAIPricingCatalogService(
                logger=logging.getLogger("openai-pricing-test"),
                catalog_path=str(Path(tmp) / "provider_model_pricing.json"),
                overrides_path=str(Path(tmp) / "provider_model_pricing_overrides.json"),
                manual_config_path=str(Path(tmp) / "openai-pricing.yaml"),
            )

            pricing = get_openai_model_pricing("gpt-5.4-mini", pricing_service=service)

            self.assertEqual(pricing["input_per_1m_tokens"], 0.75)
            self.assertEqual(pricing["cached_input_per_1m_tokens"], 0.075)
            self.assertEqual(pricing["output_per_1m_tokens"], 4.5)
            self.assertEqual(pricing["source_url"], "manual://yaml_override")

    def test_validation_rejects_empty_entry_sets(self):
        is_valid, error = validate_openai_pricing_entries([])
        self.assertFalse(is_valid)
        self.assertEqual(error, "pricing_entries_empty")

    def test_snapshot_model_validation_round_trip(self):
        snapshot = OpenAIPricingSnapshot(
            source_urls=["https://developers.openai.com/api/docs/pricing"],
            source_url_used="https://developers.openai.com/api/docs/pricing",
            scraped_at="2026-03-13T00:00:00Z",
            refresh_state="ok",
            stale=False,
            entries=[],
        )
        self.assertEqual(snapshot.refresh_state, "ok")

    def test_section_fixture_files_exist_with_representative_rows(self):
        fixtures_root = Path(__file__).parent / "providers" / "fixtures" / "pricing_sections"
        index_payload = json.loads((fixtures_root / "index.json").read_text(encoding="utf-8"))
        expected_sections = {
            "text_tokens",
            "audio_tokens",
            "image_generation",
            "video",
            "other_models",
            "embeddings",
            "moderation",
        }
        self.assertEqual(set(index_payload.keys()), expected_sections)
        representative_checks = {
            "text_tokens": "gpt-5.4-pro",
            "audio_tokens": "gpt-realtime-mini",
            "image_generation": "gpt-image-1.5",
            "video": "sora-2",
            "other_models": "whisper-1",
            "embeddings": "text-embedding-3-small",
            "moderation": "omni-moderation-2024-09-26",
        }
        for section_name, expected_row in representative_checks.items():
            fixture_path = fixtures_root / index_payload[section_name]
            self.assertTrue(fixture_path.exists(), f"Missing fixture file for {section_name}")
            text = fixture_path.read_text(encoding="utf-8")
            self.assertIn(expected_row, text)

    def test_family_prompt_builders_include_schema_and_target_models(self):
        prompt_names = [
            "llm_pricing_extraction_prompt",
            "realtime_audio_pricing_extraction_prompt",
            "image_generation_pricing_extraction_prompt",
            "video_pricing_extraction_prompt",
            "stt_tts_other_pricing_extraction_prompt",
            "embeddings_moderation_pricing_extraction_prompt",
        ]
        for prompt_name in prompt_names:
            system_prompt, user_prompt = _build_family_pricing_extraction_prompt(
                prompt_name=prompt_name,
                model_ids=["gpt-5-mini"],
                section_text="gpt-5-mini Input: $0.25 / 1M tokens",
            )
            self.assertIn("Return JSON only", system_prompt)
            self.assertIn("Prompt Family:", user_prompt)
            self.assertIn('"models"', user_prompt)
            self.assertIn('"model_id"', user_prompt)
            self.assertIn("- gpt-5-mini", user_prompt)

    def test_normalize_extracted_payload_omits_models_not_returned_by_prompt(self):
        entries = _normalize_extracted_payload(
            payload={
                "models": [
                    {
                        "model_id": "gpt-5-mini",
                        "family": "llm",
                        "pricing_basis": "per_1m_tokens",
                        "input_price": 0.25,
                        "output_price": 2.0,
                        "normalized_price": 2.0,
                        "normalized_unit": "per_1m_tokens",
                    }
                ]
            },
            allowed_models={"gpt-5-mini": "llm", "gpt-5.4": "llm"},
            source_url="https://developers.openai.com/api/docs/pricing",
            extracted_at="2026-03-14T00:00:00Z",
        )
        self.assertEqual([entry.model_id for entry in entries], ["gpt-5-mini"])

    def test_normalize_extracted_payload_converts_non_applicable_zero_to_null(self):
        entries = _normalize_extracted_payload(
            payload={
                "models": [
                    {
                        "model_id": "tts-1",
                        "family": "text_to_speech",
                        "pricing_basis": "per_1m_characters",
                        "input_price": 0.0,
                        "cached_input_price": 0.0,
                        "output_price": 0.0,
                        "normalized_price": 15.0,
                        "normalized_unit": "per_1m_characters",
                    }
                ]
            },
            allowed_models={"tts-1": "text_to_speech"},
            source_url="https://developers.openai.com/api/docs/pricing",
            extracted_at="2026-03-14T00:00:00Z",
        )
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].input_price)
        self.assertIsNone(entries[0].cached_input_price)
        self.assertIsNone(entries[0].output_price)
        self.assertEqual(entries[0].normalized_price, 15.0)


if __name__ == "__main__":
    unittest.main()
