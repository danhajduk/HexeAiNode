import pytest

from ai_node.prompts.versioning import normalize_prompt_version
from ai_node.prompts.registration import create_prompt_service_registration, update_prompt_service_definition


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("v1", "v1.0"),
        ("v10", "v10.0"),
        ("v2.0", "v2.0"),
        ("v3.4.5", "v3.4.5"),
    ],
)
def test_normalize_prompt_version_accepts_canonical_and_major_shorthand(value, expected):
    assert normalize_prompt_version(value) == expected


@pytest.mark.parametrize("value", ["", "v0", "v01", "v1.01", "v1.", "V1.0", "release-1"])
def test_normalize_prompt_version_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="invalid_prompt_version"):
        normalize_prompt_version(value)


def test_historical_date_prefixed_version_is_execution_compatibility_only():
    value = "2026-05-01.v2"
    assert normalize_prompt_version(value, allow_legacy_stored=True) == value
    with pytest.raises(ValueError, match="invalid_prompt_version"):
        normalize_prompt_version(value)


def test_registration_and_update_persist_canonical_versions():
    entry = create_prompt_service_registration(
        prompt_id="prompt.version-test",
        service_id="service.test",
        task_family="task.classification",
        version="v10",
    )
    assert entry["current_version"] == "v10.0"
    assert entry["versions"][0]["version"] == "v10.0"

    updated = update_prompt_service_definition(entry, definition={"system_prompt": "Updated"})
    assert updated["current_version"] == "v11.0"


def test_registration_rejects_historical_compatibility_version():
    with pytest.raises(ValueError, match="invalid_prompt_version"):
        create_prompt_service_registration(
            prompt_id="prompt.version-test",
            service_id="service.test",
            task_family="task.classification",
            version="2026-05-01.v2",
        )
