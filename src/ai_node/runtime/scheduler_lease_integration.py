from dataclasses import dataclass

from ai_node.core_api.scheduler_lease_client import SchedulerLeaseClient


@dataclass(frozen=True)
class NodeLeaseBinding:
    node_id: str
    worker_id: str
    capabilities: list[str]


class SchedulerLeaseIntegration:
    def __init__(self, *, scheduler_client: SchedulerLeaseClient, logger, node_id_provider, capability_provider) -> None:
        self._scheduler_client = scheduler_client
        self._logger = logger
        self._node_id_provider = node_id_provider
        self._capability_provider = capability_provider

    def node_binding(self) -> NodeLeaseBinding:
        node_id = str(self._node_id_provider() or "").strip()
        capabilities = self._capability_provider() if callable(self._capability_provider) else []
        normalized_capabilities = [str(item).strip() for item in capabilities if str(item).strip()]
        if not node_id:
            raise ValueError("node_id_required")
        return NodeLeaseBinding(node_id=node_id, worker_id=node_id, capabilities=normalized_capabilities)

    async def request_lease(self, *, core_api_endpoint: str, trust_token: str | None = None, max_units: int = 1):
        binding = self.node_binding()
        return await self._scheduler_client.request_lease(
            core_api_endpoint=core_api_endpoint,
            worker_id=binding.worker_id,
            capabilities=binding.capabilities,
            max_units=max_units,
            trust_token=trust_token,
            node_id=binding.node_id,
        )

    async def heartbeat(self, *, core_api_endpoint: str, lease_id: str, trust_token: str | None = None):
        binding = self.node_binding()
        return await self._scheduler_client.heartbeat(
            core_api_endpoint=core_api_endpoint,
            lease_id=lease_id,
            worker_id=binding.worker_id,
            trust_token=trust_token,
            node_id=binding.node_id,
        )

    async def report_progress(
        self,
        *,
        core_api_endpoint: str,
        lease_id: str,
        progress: float,
        metrics: dict | None = None,
        message: str | None = None,
        trust_token: str | None = None,
    ):
        binding = self.node_binding()
        return await self._scheduler_client.report_progress(
            core_api_endpoint=core_api_endpoint,
            lease_id=lease_id,
            worker_id=binding.worker_id,
            progress=progress,
            metrics=metrics,
            message=message,
            trust_token=trust_token,
            node_id=binding.node_id,
        )

    async def complete(
        self,
        *,
        core_api_endpoint: str,
        lease_id: str,
        status: str,
        result: dict | None = None,
        error: str | None = None,
        trust_token: str | None = None,
    ):
        binding = self.node_binding()
        return await self._scheduler_client.complete(
            core_api_endpoint=core_api_endpoint,
            lease_id=lease_id,
            worker_id=binding.worker_id,
            status=status,
            result=result,
            error=error,
            trust_token=trust_token,
            node_id=binding.node_id,
        )

    @staticmethod
    def bind_lease_to_task_request(*, request, lease_id: str):
        return request.model_copy(update={"lease_id": str(lease_id or "").strip() or None})
