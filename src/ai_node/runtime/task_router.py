from collections.abc import Awaitable, Callable


TaskExecutionHandler = Callable[..., Awaitable]


class TaskRouter:
    def __init__(self, *, default_handler: TaskExecutionHandler | None = None, routable_task_families_provider=None) -> None:
        self._default_handler = default_handler
        self._routable_task_families_provider = routable_task_families_provider or (lambda: [])
        self._handlers: dict[str, TaskExecutionHandler] = {}

    def register_handler(self, *, task_families: list[str], handler: TaskExecutionHandler) -> None:
        if not callable(handler):
            raise ValueError("handler_required")
        for task_family in task_families:
            normalized = str(task_family or "").strip()
            if not normalized:
                continue
            self._handlers[normalized] = handler

    def resolve_handler(self, *, task_family: str) -> TaskExecutionHandler:
        normalized = str(task_family or "").strip()
        if normalized in self._handlers:
            return self._handlers[normalized]
        if self._default_handler is not None:
            routable = self._routable_task_families_provider() if callable(self._routable_task_families_provider) else []
            if not routable or normalized in set(str(item or "").strip() for item in routable):
                return self._default_handler
        raise ValueError("task_family_not_routable")

    async def dispatch(self, *, task_family: str, **kwargs):
        handler = self.resolve_handler(task_family=task_family)
        return await handler(**kwargs)
