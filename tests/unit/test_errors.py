"""Typed error rendering and recursive redaction tests."""

from __future__ import annotations

import pytest

from survey_scribe.errors import (
    REDACTED,
    ArtifactWriteError,
    redact_data,
    redact_exception,
)


def test_recursive_redaction_preserves_container_types_and_non_sensitive_data() -> None:
    payload = {
        "api_key": "mapping-secret",
        "nested": [
            ("access_token=tuple-secret", ValueError("password=exception-secret")),
            {"url": "https://example.test/path?sig=query-secret"},
        ],
        7: "credential=numeric-key-secret",
    }

    redacted = redact_data(payload)

    assert redacted == {
        "api_key": REDACTED,
        "nested": [
            ("access_token=[REDACTED]", "ValueError: password=[REDACTED]"),
            {"url": "https://example.test/path?sig=[REDACTED]"},
        ],
        7: "credential=[REDACTED]",
    }
    assert isinstance(redacted["nested"], list)
    assert isinstance(redacted["nested"][0], tuple)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (("api_key=tuple-secret", 1), ("api_key=[REDACTED]", 1)),
        (["access_token=list-secret", 2], ["access_token=[REDACTED]", 2]),
        ({"password=set-secret", 3}, {"password=[REDACTED]", 3}),
        (42, 42),
    ],
)
def test_redact_data_handles_each_recursive_value_type(value: object, expected: object) -> None:
    assert redact_data(value) == expected


def test_exception_redaction_stops_at_cycles_and_applies_caller_values() -> None:
    private_text = "private questionnaire text"
    error = RuntimeError(f"failed for {private_text}")
    error.__cause__ = error

    rendered = redact_exception(error, sensitive_values=(private_text, ""))

    assert rendered == "RuntimeError: failed for [REDACTED]"


def test_artifact_write_error_records_stage_and_redacts_its_message() -> None:
    error = ArtifactWriteError("commit", "api_key=stage-secret")

    assert error.stage == "commit"
    assert error.code == "ARTIFACT_WRITE_FAILED"
    assert str(error) == "Artifact commit stage failed: api_key=[REDACTED]"
