import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from ai_node.execution.task_models import TaskExecutionRequest
from ai_node.lifecycle.node_lifecycle import NodeLifecycle
from ai_node.runtime.node_control_api import NodeControlState, create_node_control_app


class _TrustStore:
    def load(self):
        return {
            "node_id": "node-provider",
            "core_api_endpoint": "http://core.local:9001",
            "node_trust_token": "provider-trust",
        }


class _IntrospectionClient:
    def __init__(self, *, claims=None, active=True, error_code=None):
        self.claims = claims or {
            "sub": "node-caller",
            "aud": "node-service:node-provider:openai",
            "scp": ["service.execute:task.classification"],
            "provider_node_id": "node-provider",
        }
        self.active = active
        self.error_code = error_code
        self.calls = []

    async def introspect(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(active=self.active, claims=self.claims if self.active else None, error_code=self.error_code)


class _TaskChatOnlyIntrospectionClient(_IntrospectionClient):
    async def introspect(self, **kwargs):
        self.calls.append(kwargs)
        allowed = kwargs["required_scopes"] == ["service.execute:task.chat"]
        return SimpleNamespace(
            active=allowed,
            claims={
                "sub": "node-caller",
                "aud": "node-service:node-provider:local",
                "scp": ["service.execute:task.chat"],
                "provider_node_id": "node-provider",
            }
            if allowed
            else None,
            error_code=None if allowed else "token_scope_insufficient",
        )


class _PromptStore:
    def __init__(self):
        self.payload = {
            "schema_version": "1.0",
            "prompt_services": [],
            "probation": {"active_prompt_ids": [], "reasons": {}, "updated_at": None},
            "updated_at": None,
        }

    def load_or_create(self):
        return self.payload

    def save(self, payload):
        self.payload = payload


class ServiceTokenEnforcementTests(unittest.IsolatedAsyncioTestCase):
    def _state(self, tmp, client, **kwargs):
        return NodeControlState(
            lifecycle=NodeLifecycle(logger=logging.getLogger("test")),
            config_path=str(Path(tmp) / "bootstrap.json"),
            logger=logging.getLogger("test"),
            trust_state_store=_TrustStore(),
            service_token_introspection_client=client,
            **kwargs,
        )

    @staticmethod
    def _request(**overrides):
        payload = {
            "task_id": "task-1",
            "task_family": "task.classification",
            "requested_by": "node-caller",
            "requested_provider": "openai",
            "inputs": {},
            "trace_id": "trace-1",
        }
        payload.update(overrides)
        return TaskExecutionRequest(**payload)

    async def test_verified_claims_bind_subject_audience_provider_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            introspection = _IntrospectionClient()
            state = self._state(tmp, introspection)
            request = self._request()

            claims = await state.authorize_service_execution(service_token="issued-jwt", request=request)

            self.assertEqual(claims["sub"], "node-caller")
            self.assertEqual(request.requested_provider, "openai")
            self.assertEqual(
                introspection.calls[0]["required_scopes"],
                ["service.execute:task.classification"],
            )

    async def test_subject_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            introspection = _IntrospectionClient(
                claims={
                    "sub": "different-caller",
                    "aud": "node-service:node-provider:openai",
                    "scp": ["service.execute:task.classification"],
                    "provider_node_id": "node-provider",
                }
            )
            state = self._state(tmp, introspection)

            with self.assertRaisesRegex(ValueError, "service_token_subject_mismatch"):
                await state.authorize_service_execution(service_token="issued-jwt", request=self._request())

    async def test_provider_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, _IntrospectionClient())

            with self.assertRaisesRegex(ValueError, "service_token_provider_mismatch"):
                await state.authorize_service_execution(
                    service_token="issued-jwt",
                    request=self._request(requested_provider="local"),
                )

    async def test_service_identity_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, _IntrospectionClient())

            with self.assertRaisesRegex(ValueError, "service_token_service_mismatch"):
                await state.authorize_service_execution(
                    service_token="issued-jwt",
                    request=self._request(service_id="impersonated-service"),
                )

    async def test_missing_bearer_token_is_http_401_when_enforcement_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_node_control_app(state=self._state(tmp, _IntrospectionClient()), logger=logging.getLogger("test"))
            with TestClient(app) as http:
                response = http.post("/api/execution/direct", json=self._request().model_dump(mode="json"))

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"], "service_token_required")

    async def test_prompt_catalog_requires_scope_and_filters_by_verified_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            introspection = _IntrospectionClient()
            state = self._state(tmp, introspection, prompt_service_state_store=_PromptStore())
            state.register_prompt_service(
                prompt_id="prompt.owned",
                service_id="node-caller",
                owner_service="node-caller",
                owner_client_id="node-caller",
                task_family="task.classification",
            )
            state.register_prompt_service(
                prompt_id="prompt.foreign",
                service_id="other-node",
                owner_service="other-node",
                owner_client_id="other-node",
                task_family="task.classification",
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("test"))
            with TestClient(app) as http:
                anonymous = http.get("/api/prompts/services")
                authorized = http.get(
                    "/api/prompts/services",
                    headers={"Authorization": "Bearer issued-jwt"},
                )

            self.assertEqual(anonymous.status_code, 401)
            self.assertEqual(authorized.status_code, 200)
            prompts = authorized.json()["state"]["prompt_services"]
            self.assertEqual([prompt["prompt_id"] for prompt in prompts], ["prompt.owned"])
            self.assertEqual(introspection.calls[-1]["required_scopes"], ["ai.prompts.read"])

    async def test_assistant_prompt_lookup_accepts_task_chat_execution_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            introspection = _TaskChatOnlyIntrospectionClient()
            state = self._state(tmp, introspection, prompt_service_state_store=_PromptStore())
            state.register_prompt_service(
                prompt_id="prompt.hexeinteraction.assistant",
                service_id="node-caller",
                owner_service="node-caller",
                owner_client_id="node-caller",
                task_family="task.chat",
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("test"))
            with TestClient(app) as http:
                response = http.get(
                    "/api/prompts/services/prompt.hexeinteraction.assistant",
                    headers={"Authorization": "Bearer issued-jwt"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [call["required_scopes"] for call in introspection.calls],
                [["ai.prompts.read"], ["service.execute:task.chat"]],
            )

    async def test_openapi_declares_core_service_bearer_and_operation_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_node_control_app(
                state=self._state(tmp, _IntrospectionClient()),
                logger=logging.getLogger("test"),
            )
            schema = app.openapi()

            self.assertEqual(
                schema["components"]["securitySchemes"]["CoreServiceBearer"]["scheme"],
                "bearer",
            )
            operation = schema["paths"]["/api/prompts/services"]["get"]
            self.assertEqual(operation["security"], [{"CoreServiceBearer": []}])
            self.assertEqual(operation["x-hexe-required-scopes"], ["ai.prompts.read"])
            assistant_operation = schema["paths"]["/api/prompts/services/{prompt_id}"]["get"]
            self.assertEqual(
                assistant_operation["x-hexe-scope-alternatives"],
                {"prompt.hexeinteraction.assistant": ["service.execute:task.chat"]},
            )

    async def test_job_polling_rejects_a_different_verified_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._state(tmp, _IntrospectionClient())
            state.execution_job_status = AsyncMock(
                return_value={
                    "status": "queued",
                    "job_id": "job-1",
                    "client_id": "other-node",
                    "request": {"requested_by": "other-node"},
                }
            )
            app = create_node_control_app(state=state, logger=logging.getLogger("test"))
            with TestClient(app) as http:
                response = http.get(
                    "/api/execution/jobs/job-1",
                    headers={"Authorization": "Bearer issued-jwt"},
                )

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["detail"], "job_owner_mismatch")


if __name__ == "__main__":
    unittest.main()
