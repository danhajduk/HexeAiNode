import unittest

from ai_node.runtime.task_router import TaskRouter


class TaskRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_uses_registered_handler_for_exact_task_family(self):
        async def handler(**kwargs):
            return {"handler": "specific", "task_id": kwargs["request"].task_id}

        router = TaskRouter()
        router.register_handler(task_families=["task.classification.text"], handler=handler)

        result = await router.dispatch(
            task_family="task.classification.text",
            request=type("Request", (), {"task_id": "task-001"})(),
            resolution=None,
        )

        self.assertEqual(result["handler"], "specific")
        self.assertEqual(result["task_id"], "task-001")

    async def test_dispatch_falls_back_to_default_handler_when_family_is_routable(self):
        async def default_handler(**kwargs):
            return {"handler": "default", "task_family": kwargs["request"].task_family}

        router = TaskRouter(
            default_handler=default_handler,
            routable_task_families_provider=lambda: ["task.classification.text"],
        )

        request = type("Request", (), {"task_id": "task-001", "task_family": "task.classification.text"})()
        result = await router.dispatch(task_family="task.classification.text", request=request, resolution=None)

        self.assertEqual(result["handler"], "default")

    async def test_dispatch_rejects_non_routable_family_without_handler(self):
        router = TaskRouter(
            default_handler=lambda **_kwargs: None,
            routable_task_families_provider=lambda: ["task.classification.text"],
        )

        with self.assertRaises(ValueError) as context:
            await router.dispatch(
                task_family="task.translation",
                request=type("Request", (), {"task_id": "task-001", "task_family": "task.translation"})(),
                resolution=None,
            )

        self.assertEqual(str(context.exception), "task_family_not_routable")


if __name__ == "__main__":
    unittest.main()
