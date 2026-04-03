import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.client_usage_store import (
    ClientUsageStore,
    aggregate_provider_execution_log,
    aggregate_provider_execution_log_by_model,
    aggregate_provider_metrics,
    aggregate_provider_metrics_by_model,
)


class ClientUsageStoreTests(unittest.TestCase):
    def test_record_execution_updates_lifetime_and_monthly_rollups(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ClientUsageStore(path=str(Path(tmp) / "client_usage.db"), logger=logging.getLogger("client-usage-test"))

            store.record_execution(
                client_id="node-email",
                prompt_id="prompt.email.classifier",
                model_id="gpt-5.4-nano",
                customer_id="local-user",
                prompt_tokens=400,
                completion_tokens=50,
                total_tokens=450,
                cost_usd=0.00014,
                used_at="2026-04-03T09:05:02.880000-07:00",
            )

            payload = store.summary_payload(month_key="2026-04")

            self.assertTrue(payload["configured"])
            self.assertEqual(payload["current_month"], "2026-04")
            self.assertEqual(payload["clients"][0]["client_id"], "node-email")
            self.assertEqual(payload["clients"][0]["lifetime"]["calls"], 1)
            self.assertEqual(payload["clients"][0]["current_month"]["total_tokens"], 450)
            self.assertAlmostEqual(payload["clients"][0]["lifetime"]["cost_usd"], 0.00014, places=10)
            self.assertEqual(payload["clients"][0]["prompts"][0]["prompt_id"], "prompt.email.classifier")
            self.assertEqual(payload["clients"][0]["prompts"][0]["models"][0]["model_id"], "gpt-5.4-nano")

    def test_aggregate_provider_metrics_sums_successful_model_usage(self):
        totals = aggregate_provider_metrics(
            {
                "providers": {
                    "openai": {
                        "models": {
                            "gpt-5.4": {
                                "successful_requests": 1,
                                "prompt_tokens": 69,
                                "completion_tokens": 41,
                                "total_tokens": 110,
                                "estimated_cost": 0.0,
                            },
                            "gpt-5.4-nano": {
                                "successful_requests": 501,
                                "prompt_tokens": 206769,
                                "completion_tokens": 22338,
                                "total_tokens": 229107,
                                "estimated_cost": 0.0672463,
                            },
                        }
                    }
                }
            }
        )

        self.assertEqual(totals["calls"], 502)
        self.assertEqual(totals["total_tokens"], 229217)
        self.assertAlmostEqual(totals["cost_usd"], 0.0672463, places=10)

    def test_aggregate_provider_metrics_by_model_sums_each_model(self):
        totals = aggregate_provider_metrics_by_model(
            {
                "providers": {
                    "openai": {
                        "models": {
                            "gpt-5.4": {
                                "successful_requests": 1,
                                "prompt_tokens": 69,
                                "completion_tokens": 41,
                                "total_tokens": 110,
                                "estimated_cost": 0.0,
                            },
                            "gpt-5.4-nano": {
                                "successful_requests": 501,
                                "prompt_tokens": 206769,
                                "completion_tokens": 22338,
                                "total_tokens": 229107,
                                "estimated_cost": 0.0672463,
                            },
                        }
                    }
                }
            }
        )

        self.assertEqual(totals["gpt-5.4"]["calls"], 1)
        self.assertEqual(totals["gpt-5.4-nano"]["total_tokens"], 229107)
        self.assertAlmostEqual(totals["gpt-5.4-nano"]["cost_usd"], 0.0672463, places=10)

    def test_aggregate_provider_execution_log_reads_provider_execution_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backend.log"
            path.write_text(
                "\n".join(
                    [
                        "2026-04-03 08:48:30,187 INFO ai_node.main: [provider-execution] {'provider_id': 'openai', 'model_id': 'gpt-5.4-nano', 'latency_ms': 1258.389, 'prompt_tokens': 427, 'completion_tokens': 52, 'estimated_cost': 0.0001504, 'success': True}",
                        "2026-04-03 08:48:31,797 INFO ai_node.main: [provider-execution] {'provider_id': 'openai', 'model_id': 'gpt-5.4-nano', 'latency_ms': 1052.654, 'prompt_tokens': 384, 'completion_tokens': 41, 'estimated_cost': 0.00012805, 'success': True}",
                    ]
                ),
                encoding="utf-8",
            )

            totals = aggregate_provider_execution_log(str(path))

            self.assertEqual(totals["calls"], 2)
            self.assertEqual(totals["total_tokens"], 904)
            self.assertAlmostEqual(totals["cost_usd"], 0.00027845, places=10)
            self.assertEqual(totals["last_used_at"], "2026-04-03T08:48:31.797")

    def test_aggregate_provider_execution_log_by_model_reads_each_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backend.log"
            path.write_text(
                "\n".join(
                    [
                        "2026-04-03 08:48:30,187 INFO ai_node.main: [provider-execution] {'provider_id': 'openai', 'model_id': 'gpt-5.4-nano', 'latency_ms': 1258.389, 'prompt_tokens': 427, 'completion_tokens': 52, 'estimated_cost': 0.0001504, 'success': True}",
                        "2026-04-03 08:48:31,797 INFO ai_node.main: [provider-execution] {'provider_id': 'openai', 'model_id': 'gpt-5.4', 'latency_ms': 1052.654, 'prompt_tokens': 384, 'completion_tokens': 41, 'estimated_cost': 0.00012805, 'success': True}",
                    ]
                ),
                encoding="utf-8",
            )

            totals = aggregate_provider_execution_log_by_model(str(path))

            self.assertEqual(totals["gpt-5.4-nano"]["calls"], 1)
            self.assertEqual(totals["gpt-5.4"]["total_tokens"], 425)
            self.assertEqual(totals["gpt-5.4"]["last_used_at"], "2026-04-03T08:48:31.797")


if __name__ == "__main__":
    unittest.main()
