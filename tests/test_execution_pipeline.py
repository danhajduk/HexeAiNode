import unittest

from ai_node.execution.pipeline import HANDLER_PIPELINE_STAGES


class ExecutionPipelineTests(unittest.TestCase):
    def test_handler_pipeline_matches_phase3_contract(self):
        self.assertEqual(
            HANDLER_PIPELINE_STAGES,
            (
                "normalize_input",
                "validate_task",
                "validate_inputs",
                "resolve_provider_model",
                "execute_handler",
                "normalize_output",
                "emit_telemetry",
                "return_result",
            ),
        )


if __name__ == "__main__":
    unittest.main()
