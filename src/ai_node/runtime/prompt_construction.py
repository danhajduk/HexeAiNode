import json
import re


_TEMPLATE_VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def _stringify_template_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float, list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=isinstance(value, dict))
    return str(value)


def merge_prompt_inputs(*, request_inputs: dict | None, prompt_definition: dict | None) -> dict:
    merged: dict = {}
    if isinstance(prompt_definition, dict):
        default_inputs = prompt_definition.get("default_inputs")
        if isinstance(default_inputs, dict):
            merged.update(default_inputs)
    if isinstance(request_inputs, dict):
        merged.update(request_inputs)
    return merged


def render_prompt_template(*, prompt_definition: dict | None, request_inputs: dict | None) -> str | None:
    if not isinstance(prompt_definition, dict):
        return None
    prompt_template = str(prompt_definition.get("prompt_template") or "")
    if not prompt_template.strip():
        return None

    merged_inputs = merge_prompt_inputs(request_inputs=request_inputs, prompt_definition=prompt_definition)
    rendered = prompt_template
    for variable_name in sorted(set(_TEMPLATE_VARIABLE_PATTERN.findall(prompt_template))):
        value = _stringify_template_value(merged_inputs.get(variable_name))
        rendered = rendered.replace("{{" + variable_name + "}}", value)
        rendered = rendered.replace("{{ " + variable_name + " }}", value)
    return rendered
