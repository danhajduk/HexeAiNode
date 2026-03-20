import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NormalizedTaskInputs:
    prompt: str | None
    messages: list[dict]
    system_prompt: str | None
    max_tokens: int | None = None
    temperature: float | None = None
    metadata: dict = field(default_factory=dict)


def _normalized_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalized_messages(value: object) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("invalid_input")
    normalized: list[dict] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("invalid_input")
        role = _normalized_optional_string(entry.get("role"))
        content = _normalized_optional_string(entry.get("content"))
        if role is None or content is None:
            raise ValueError("invalid_input")
        item = {"role": role, "content": content}
        if _normalized_optional_string(entry.get("name")) is not None:
            item["name"] = _normalized_optional_string(entry.get("name"))
        normalized.append(item)
    return normalized


def _normalized_temperature(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ValueError("invalid_input")
    normalized = float(value)
    if normalized < 0.0 or normalized > 2.0:
        raise ValueError("invalid_input")
    return normalized


def _normalized_max_tokens(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError("invalid_input")
    if value <= 0:
        raise ValueError("invalid_input")
    return int(value)


def _prompt_from_text_like_inputs(inputs: dict) -> str | None:
    for key in ("prompt", "text", "content", "body", "input_text"):
        prompt = _normalized_optional_string(inputs.get(key))
        if prompt is not None:
            return prompt
    return None


def _prompt_from_email_inputs(inputs: dict) -> tuple[str | None, dict]:
    subject = _normalized_optional_string(inputs.get("subject"))
    body = _normalized_optional_string(inputs.get("body")) or _normalized_optional_string(inputs.get("content"))
    if subject is None and body is None:
        return None, {}
    parts: list[str] = []
    if subject is not None:
        parts.append(f"Subject: {subject}")
    if body is not None:
        parts.append(body)
    return "\n\n".join(parts), {"email_subject": subject}


def _prompt_from_event_inputs(inputs: dict) -> str | None:
    event_payload = inputs.get("event")
    if isinstance(event_payload, dict) and event_payload:
        return json.dumps(event_payload, sort_keys=True)
    return None


def _prompt_from_image_inputs(inputs: dict) -> tuple[str | None, dict]:
    image_url = _normalized_optional_string(inputs.get("image_url"))
    image_base64 = _normalized_optional_string(inputs.get("image_base64"))
    images = inputs.get("images") if isinstance(inputs.get("images"), list) else []
    image_count = len(images)
    if image_url is None and image_base64 is None and image_count == 0:
        return None, {}
    metadata = {
        "image_url": image_url,
        "image_base64_present": bool(image_base64),
        "image_count": image_count,
    }
    prompt = _normalized_optional_string(inputs.get("instruction")) or "Classify the provided image input."
    return prompt, metadata


def validate_and_normalize_task_inputs(*, task_family: str, inputs: dict | None) -> NormalizedTaskInputs:
    payload = inputs if isinstance(inputs, dict) else {}
    normalized_family = str(task_family or "").strip().lower()
    system_prompt = _normalized_optional_string(payload.get("system_prompt"))
    messages = _normalized_messages(payload.get("messages"))
    max_tokens = _normalized_max_tokens(payload.get("max_tokens"))
    temperature = _normalized_temperature(payload.get("temperature"))

    prompt = None
    metadata: dict = {}

    if normalized_family.endswith(".email"):
        prompt, metadata = _prompt_from_email_inputs(payload)
    elif normalized_family == "task.summarization.event":
        prompt = _prompt_from_event_inputs(payload)
    elif normalized_family.endswith(".image"):
        prompt, metadata = _prompt_from_image_inputs(payload)

    if prompt is None:
        prompt = _prompt_from_text_like_inputs(payload)

    if prompt is None and not messages:
        raise ValueError("invalid_input")

    return NormalizedTaskInputs(
        prompt=prompt,
        messages=messages,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        metadata=metadata,
    )
