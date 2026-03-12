from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionAuthorizationResult:
    allowed: bool
    reason: str
    prompt_id: str
    task_family: str


class ExecutionGateway:
    def authorize(self, *, prompt_id: str, task_family: str, prompt_services_state: dict | None) -> ExecutionAuthorizationResult:
        prompt = str(prompt_id or "").strip()
        task = str(task_family or "").strip()
        if not prompt:
            return ExecutionAuthorizationResult(False, "missing_prompt_id", prompt, task)
        if not task:
            return ExecutionAuthorizationResult(False, "missing_task_family", prompt, task)

        entries = []
        if isinstance(prompt_services_state, dict) and isinstance(prompt_services_state.get("prompt_services"), list):
            entries = prompt_services_state.get("prompt_services") or []
        matched = None
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("prompt_id") or "").strip() == prompt:
                matched = entry
                break
        if not isinstance(matched, dict):
            return ExecutionAuthorizationResult(False, "prompt_not_registered", prompt, task)

        if str(matched.get("task_family") or "").strip() != task:
            return ExecutionAuthorizationResult(False, "task_family_mismatch", prompt, task)

        status = str(matched.get("status") or "").strip().lower()
        if status == "probation":
            return ExecutionAuthorizationResult(False, "prompt_in_probation", prompt, task)

        if status != "registered":
            return ExecutionAuthorizationResult(False, "invalid_prompt_status", prompt, task)

        return ExecutionAuthorizationResult(True, "authorized", prompt, task)
