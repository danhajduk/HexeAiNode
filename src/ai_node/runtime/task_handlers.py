from ai_node.execution.input_validation import validate_and_normalize_task_inputs
from ai_node.providers.models import UnifiedExecutionRequest
from ai_node.runtime.prompt_construction import render_prompt_template


CLASSIFICATION_TASK_FAMILIES = (
    "task.classification",
    "task.classification",
    "task.classification.email",
    "task.classification.image",
)

SUMMARIZATION_TASK_FAMILIES = (
    "task.summarization",
    "task.summarization.text",
    "task.summarization.email",
    "task.summarization.event",
)


DEFAULT_CLASSIFICATION_SYSTEM_PROMPT = (
    "Return only a JSON object for the classification result. "
    'Use the shape {"label": string, "confidence": number|null, "reasoning": string}. '
    "Do not include markdown fences or extra prose."
)

STRUCTURED_EXTRACTION_SYSTEM_PROMPT_SUFFIX = (
    " Return exactly one JSON object. "
    "Do not wrap the JSON object in a field named text. "
    "Do not return a JSON string. "
    "Do not include markdown fences. "
    "Do not include explanations, notes, or prose before or after the JSON object. "
    "The top-level response must be the template object itself."
)


def _build_unified_execution_request(*, request, resolution, normalized_inputs) -> UnifiedExecutionRequest:
    resolution_plan = resolution.get("plan") if isinstance(resolution, dict) else resolution
    authorization = resolution.get("authorization") if isinstance(resolution, dict) else None
    request_inputs = request.inputs if isinstance(getattr(request, "inputs", None), dict) else {}
    prompt_definition = authorization.prompt_definition if authorization is not None and isinstance(authorization.prompt_definition, dict) else {}
    rendered_prompt = render_prompt_template(prompt_definition=prompt_definition, request_inputs=request_inputs)
    system_prompt = (
        normalized_inputs.system_prompt
        or prompt_definition.get("system_prompt")
        or (DEFAULT_CLASSIFICATION_SYSTEM_PROMPT if str(request.task_family or "").strip().startswith("task.classification") else None)
    )
    if str(request.task_family or "").strip().lower() == "task.structured_extraction":
        base_prompt = str(system_prompt or "").strip()
        system_prompt = f"{base_prompt}{STRUCTURED_EXTRACTION_SYSTEM_PROMPT_SUFFIX}" if base_prompt else STRUCTURED_EXTRACTION_SYSTEM_PROMPT_SUFFIX.strip()
    structured_output_schema = request_inputs.get("structured_output_schema")
    if not isinstance(structured_output_schema, dict):
        structured_output_schema = request_inputs.get("json_schema")
    return UnifiedExecutionRequest(
        task_family=request.task_family,
        prompt=rendered_prompt or normalized_inputs.prompt,
        system_prompt=system_prompt,
        messages=normalized_inputs.messages,
        requested_provider=resolution_plan.provider_id,
        requested_model=resolution_plan.model_id,
        temperature=normalized_inputs.temperature,
        max_tokens=normalized_inputs.max_tokens,
        metadata={
            "task_id": request.task_id,
            "requested_by": request.requested_by,
            "trace_id": request.trace_id,
            "prompt_id": getattr(request, "prompt_id", None),
            "prompt_version": getattr(request, "prompt_version", None),
            "lease_id": getattr(request, "lease_id", None),
            "structured_output_schema": structured_output_schema if isinstance(structured_output_schema, dict) else None,
            **(normalized_inputs.metadata if isinstance(normalized_inputs.metadata, dict) else {}),
        },
    )


class ClassificationTaskHandler:
    def __init__(self, *, task_executor) -> None:
        self._task_executor = task_executor

    async def __call__(self, *, request, resolution):
        normalized_inputs = validate_and_normalize_task_inputs(task_family=request.task_family, inputs=request.inputs)
        return await self._task_executor.execute_classification(
            _build_unified_execution_request(
                request=request,
                resolution=resolution,
                normalized_inputs=normalized_inputs,
            )
        )


class SummarizationTaskHandler:
    def __init__(self, *, task_executor) -> None:
        self._task_executor = task_executor

    async def __call__(self, *, request, resolution):
        normalized_inputs = validate_and_normalize_task_inputs(task_family=request.task_family, inputs=request.inputs)
        return await self._task_executor.execute_summarization(
            _build_unified_execution_request(
                request=request,
                resolution=resolution,
                normalized_inputs=normalized_inputs,
            )
        )
