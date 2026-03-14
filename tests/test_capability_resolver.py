import json
import tempfile
import unittest
from pathlib import Path

from ai_node.runtime.capability_resolver import (
    build_feature_union,
    load_task_graph,
    resolve_node_capabilities,
    resolve_task_capabilities,
)


class CapabilityResolverTests(unittest.TestCase):
    def test_load_task_graph_reads_valid_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task_graph.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "capability_graph_version": "1.0",
                        "tasks": {"task.reasoning": {"all_of": ["reasoning"]}},
                    }
                ),
                encoding="utf-8",
            )
            payload = load_task_graph(path=str(path))
            self.assertIn("tasks", payload)
            self.assertIn("task.reasoning", payload["tasks"])

    def test_build_feature_union_only_uses_enabled_models(self):
        feature_union = build_feature_union(
            model_feature_entries=[
                {"model_id": "gpt-5-mini", "features": {"reasoning": True, "chat": True}},
                {"model_id": "whisper-1", "features": {"speech_to_text": True}},
            ],
            enabled_models=["gpt-5-mini"],
        )
        self.assertTrue(feature_union["reasoning"])
        self.assertTrue(feature_union["chat"])
        self.assertFalse(feature_union["speech_to_text"])

    def test_resolve_task_capabilities_evaluates_rules(self):
        feature_union = {
            "reasoning": True,
            "chat": True,
            "planning": False,
        }
        task_graph = {
            "tasks": {
                "task.reasoning": {"all_of": ["reasoning"]},
                "task.chat": {"all_of": ["chat"]},
                "task.task_planning": {"all_of": ["planning"]},
            }
        }
        resolved = resolve_task_capabilities(feature_union=feature_union, task_graph=task_graph)
        self.assertEqual(resolved, ["task.chat", "task.reasoning"])

    def test_resolve_node_capabilities_returns_union_and_tasks(self):
        payload = resolve_node_capabilities(
            enabled_models=["gpt-5-mini", "whisper-1"],
            model_feature_catalog={
                "entries": [
                    {"model_id": "gpt-5-mini", "features": {"reasoning": True, "chat": True}},
                    {"model_id": "whisper-1", "features": {"speech_to_text": True}},
                ]
            },
            task_graph={
                "capability_graph_version": "1.0",
                "tasks": {
                    "task.reasoning": {"all_of": ["reasoning"]},
                    "task.chat": {"all_of": ["chat"]},
                    "task.speech_to_text": {"all_of": ["speech_to_text"]},
                },
            },
        )
        self.assertEqual(payload["enabled_models"], ["gpt-5-mini", "whisper-1"])
        self.assertTrue(payload["feature_union"]["speech_to_text"])
        self.assertEqual(payload["resolved_tasks"], ["task.chat", "task.reasoning", "task.speech_to_text"])


if __name__ == "__main__":
    unittest.main()
