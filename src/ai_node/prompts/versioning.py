import re


CANONICAL_PROMPT_VERSION_PATTERN = r"^v[1-9][0-9]*\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?$"
LEGACY_MAJOR_ONLY_PROMPT_VERSION_PATTERN = r"^v[1-9][0-9]*$"
LEGACY_STORED_PROMPT_VERSION_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.v[1-9][0-9]*$"

_CANONICAL_PROMPT_VERSION_RE = re.compile(CANONICAL_PROMPT_VERSION_PATTERN)
_LEGACY_MAJOR_ONLY_PROMPT_VERSION_RE = re.compile(LEGACY_MAJOR_ONLY_PROMPT_VERSION_PATTERN)
_LEGACY_STORED_PROMPT_VERSION_RE = re.compile(LEGACY_STORED_PROMPT_VERSION_PATTERN)


def normalize_prompt_version(value: object, *, allow_legacy_stored: bool = False) -> str:
    version = str(value or "").strip()
    if _LEGACY_MAJOR_ONLY_PROMPT_VERSION_RE.fullmatch(version):
        return f"{version}.0"
    if _CANONICAL_PROMPT_VERSION_RE.fullmatch(version):
        return version
    if allow_legacy_stored and _LEGACY_STORED_PROMPT_VERSION_RE.fullmatch(version):
        return version
    raise ValueError("invalid_prompt_version")


def prompt_version_major(value: object) -> int | None:
    try:
        normalized = normalize_prompt_version(value)
    except ValueError:
        return None
    return int(normalized[1:].split(".", 1)[0])
