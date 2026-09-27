import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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


class ServiceTokenEnforcementTests(unittest.IsolatedAsyncioTestCase):
    def _state(self, tmp, client):
        return NodeControlState(
            lifecycle=NodeLifecycle(logger=logging.getLogger("test")),
            config_path=str(Path(tmp) / "bootstrap.json"),
            logger=logging.getLogger("test"),
            trust_state_store=_TrustStore(),
            service_token_introspection_client=client,
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

    async def test_missing_bearer_token_is_http_401_when_enforcement_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = create_node_control_app(state=self._state(tmp, _IntrospectionClient()), logger=logging.getLogger("test"))
            with TestClient(app) as http:
                response = http.post("/api/execution/direct", json=self._request().model_dump(mode="json"))

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["detail"], "service_token_required")


if __name__ == "__main__":
    unittest.main()
