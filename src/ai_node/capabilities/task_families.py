import re
from typing import Optional, Tuple


TASK_CLASSIFICATION = "task.classification"
TASK_CLASSIFICATION_TEXT = "task.classification.text"
TASK_CLASSIFICATION_EMAIL = "task.classification.email"
TASK_CLASSIFICATION_IMAGE = "task.classification.image"

TASK_SUMMARIZATION_TEXT = "task.summarization.text"
TASK_SUMMARIZATION_EMAIL = "task.summarization.email"
TASK_SUMMARIZATION_EVENT = "task.summarization.event"

TASK_GENERATION_TEXT = "task.generation.text"
TASK_GENERATION_IMAGE = "task.generation.image"

LEGACY_TASK_FAMILY_ALIASES = {
    TASK_CLASSIFICATION_TEXT: TASK_CLASSIFICATION,
}

CANONICAL_TASK_FAMILIES = (
    TASK_CLASSIFICATION,
    TASK_CLASSIFICATION_EMAIL,
    TASK_CLASSIFICATION_IMAGE,
    TASK_SUMMARIZATION_TEXT,
    TASK_SUMMARIZATION_EMAIL,
    TASK_SUMMARIZATION_EVENT,
    TASK_GENERATION_TEXT,
    TASK_GENERATION_IMAGE,
    "task.chat",
    "task.summarization",
    "task.reasoning",
    "task.information_extraction",
    "task.structured_extraction",
    "task.translation",
    "task.sentiment_analysis",
    "task.task_planning",
    "task.workflow_reasoning",
    "task.tool_usage",
    "task.automation_command",
    "task.environment_control",
    "task.coding",
    "task.vision_analysis",
    "task.object_detection",
    "task.image_description",
    "task.document_ocr",
    "task.image_generation",
    "task.image_editing",
    "task.image_variation",
    "task.speech_to_text",
    "task.text_to_speech",
    "task.voice_conversation",
    "task.audio_analysis",
    "task.realtime_voice",
    "task.streaming_response",
    "task.low_latency_interaction",
    "task.embedding_generation",
    "task.semantic_search",
    "task.document_indexing",
    "task.knowledge_retrieval",
    "task.moderation",
    "task.policy_check",
)

_TASK_FAMILY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{1,127}$")


def canonicalize_task_family(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return LEGACY_TASK_FAMILY_ALIASES.get(normalized, normalized)


def is_legacy_task_family_alias(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in LEGACY_TASK_FAMILY_ALIASES


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        canonical = canonicalize_task_family(str(item or ""))
        if canonical:
            normalized.append(canonical)
    return sorted(set(normalized))


def create_declared_task_family_capabilities(task_families: list[str] | None = None) -> list[str]:
    declared = _normalize_string_list(task_families) if isinstance(task_families, list) else list(CANONICAL_TASK_FAMILIES)
    is_valid, error = validate_task_family_capabilities(declared)
    if not is_valid:
        raise ValueError(f"invalid task family declaration: {error}")
    return declared


def validate_task_family_capabilities(task_families: object) -> Tuple[bool, Optional[str]]:
    if not isinstance(task_families, list):
        return False, "invalid_task_families"
    normalized = _normalize_string_list(task_families)
    if not normalized:
        return True, None
    invalid = [family for family in normalized if not _TASK_FAMILY_ID_RE.match(family)]
    if invalid:
        return False, f"invalid_task_family:{invalid[0]}"
    unknown = [family for family in normalized if family not in set(CANONICAL_TASK_FAMILIES)]
    if unknown:
        return False, f"unsupported_task_family:{unknown[0]}"
    return True, None
