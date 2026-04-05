import logging
import tempfile
import unittest
from pathlib import Path

from ai_node.persistence.prompt_service_state_store import (
    PromptServiceStateStore,
    create_prompt_service_state,
    normalize_prompt_service_state,
    validate_prompt_service_state,
)


class PromptServiceStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("prompt-service-state-store-test")

    def test_create_default_state_is_valid(self):
        payload = create_prompt_service_state()
        is_valid, error = validate_prompt_service_state(payload)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt_service_state.json"
            store = PromptServiceStateStore(path=str(path), logger=self.logger)
            payload = create_prompt_service_state()
            payload["prompt_services"] = [
                {
                    "prompt_id": "prompt.alpha",
                    "prompt_name": "Prompt Alpha",
                    "service_id": "svc-alpha",
                    "owner_service": "svc-alpha",
                    "owner_client_id": "svc-alpha",
                    "task_family": "task.classification",
                    "status": "active",
                    "privacy_class": "internal",
                    "access_scope": "service",
                    "allowed_services": [],
                    "allowed_clients": [],
                    "allowed_customers": [],
                    "execution_policy": {"allow_direct_execution": True, "allow_version_pinning": True},
                    "provider_preferences": {"preferred_providers": ["openai"], "preferred_models": ["gpt-5-mini"]},
                    "constraints": {"max_timeout_s": 30, "structured_output_required": False, "allowed_model_overrides": []},
                    "metadata": {},
                    "current_version": "v1",
                    "versions": [
                        {
                            "version": "v1",
                            "definition": {"system_prompt": "You are a classifier.", "prompt_template": None, "template_variables": [], "default_inputs": {}},
                            "metadata": {},
                            "created_at": payload["updated_at"],
                        }
                    ],
                    "lifecycle_history": [{"state": "active", "reason": "created", "changed_at": payload["updated_at"]}],
                    "usage": {"execution_count": 0, "success_count": 0, "failure_count": 0, "denial_count": 0},
                    "registered_at": payload["updated_at"],
                    "updated_at": payload["updated_at"],
                    "last_reviewed_at": payload["updated_at"],
                    "reviewed_by": "svc-alpha",
                    "review_reason": "created",
                }
            ]
            store.save(payload)
            loaded = store.load()
            self.assertEqual(loaded["schema_version"], "2.0")
            self.assertEqual(loaded["prompt_services"][0]["prompt_id"], "prompt.alpha")
            self.assertEqual(loaded["prompt_services"][0]["current_version"], "v1")
            self.assertEqual(loaded["prompt_services"][0]["status"], "active")
            self.assertEqual(loaded["prompt_services"][0]["versions"][0]["definition"]["system_prompt"], "You are a classifier.")

    def test_normalize_legacy_state_migrates_registered_prompt(self):
        payload = normalize_prompt_service_state(
            {
                "schema_version": "1.0",
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "service_id": "svc-alpha",
                        "task_family": "task.classification",
                        "status": "registered",
                        "metadata": {"owner": "ops"},
                        "registered_at": "2026-03-12T00:00:00Z",
                        "updated_at": "2026-03-12T00:00:00Z",
                    }
                ],
                "probation": {"active_prompt_ids": [], "reasons": {}, "updated_at": "2026-03-12T00:00:00Z"},
                "updated_at": "2026-03-12T00:00:00Z",
            }
        )
        self.assertEqual(payload["schema_version"], "2.0")
        self.assertEqual(payload["prompt_services"][0]["status"], "active")
        self.assertEqual(payload["prompt_services"][0]["current_version"], "v1")
        self.assertEqual(payload["prompt_services"][0]["access_scope"], "service")

    def test_load_or_create_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt_service_state.json"
            store = PromptServiceStateStore(path=str(path), logger=self.logger)
            loaded = store.load_or_create()
            self.assertTrue(path.exists())
            self.assertIn("prompt_services", loaded)

    def test_normalize_preserves_review_due_and_access_policy(self):
        payload = normalize_prompt_service_state(
            {
                "schema_version": "2.0",
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "prompt_name": "Prompt Alpha",
                        "service_id": "svc-alpha",
                        "owner_service": "svc-alpha",
                        "owner_client_id": "client.alpha",
                        "task_family": "task.classification",
                        "status": "review_due",
                        "privacy_class": "internal",
                        "access_scope": "shared",
                        "allowed_services": ["svc-beta"],
                        "allowed_clients": ["client.beta"],
                        "allowed_customers": ["customer-1"],
                        "execution_policy": {"allow_direct_execution": True, "allow_version_pinning": True},
                        "provider_preferences": {},
                        "constraints": {},
                        "metadata": {},
                        "current_version": "v1",
                        "versions": [{"version": "v1", "definition": {}, "metadata": {}, "created_at": "2026-03-12T00:00:00Z"}],
                        "lifecycle_history": [{"state": "review_due", "reason": "policy_migration_review_due", "changed_at": "2026-03-12T00:00:00Z"}],
                        "usage": {"execution_count": 1, "success_count": 1, "failure_count": 0, "denial_count": 0},
                        "registered_at": "2026-03-12T00:00:00Z",
                        "updated_at": "2026-03-12T00:00:00Z",
                        "last_reviewed_at": None,
                        "reviewed_by": None,
                        "review_reason": None,
                    }
                ],
                "probation": {"active_prompt_ids": [], "reasons": {}, "updated_at": "2026-03-12T00:00:00Z"},
                "updated_at": "2026-03-12T00:00:00Z",
            }
        )
        prompt = payload["prompt_services"][0]
        self.assertEqual(prompt["status"], "review_due")
        self.assertEqual(prompt["access_scope"], "shared")
        self.assertEqual(prompt["allowed_services"], ["svc-beta"])

    def test_normalize_preserves_draft_status(self):
        payload = normalize_prompt_service_state(
            {
                "schema_version": "2.0",
                "prompt_services": [
                    {
                        "prompt_id": "prompt.alpha",
                        "prompt_name": "Prompt Alpha",
                        "service_id": "svc-alpha",
                        "owner_service": "svc-alpha",
                        "task_family": "task.classification",
                        "status": "draft",
                        "privacy_class": "internal",
                        "access_scope": "service",
                        "execution_policy": {"allow_direct_execution": True, "allow_version_pinning": True},
                        "provider_preferences": {},
                        "constraints": {},
                        "metadata": {},
                        "current_version": "v1",
                        "versions": [{"version": "v1", "definition": {}, "metadata": {}, "created_at": "2026-03-12T00:00:00Z"}],
                        "lifecycle_history": [{"state": "draft", "reason": "created", "changed_at": "2026-03-12T00:00:00Z"}],
                        "usage": {"execution_count": 0, "success_count": 0, "failure_count": 0, "denial_count": 0},
                        "registered_at": "2026-03-12T00:00:00Z",
                        "updated_at": "2026-03-12T00:00:00Z",
                        "last_reviewed_at": None,
                        "reviewed_by": None,
                        "review_reason": None,
                    }
                ],
                "probation": {"active_prompt_ids": [], "reasons": {}, "updated_at": "2026-03-12T00:00:00Z"},
                "updated_at": "2026-03-12T00:00:00Z",
            }
        )
        prompt = payload["prompt_services"][0]
        self.assertEqual(prompt["status"], "draft")


if __name__ == "__main__":
    unittest.main()
