"""Typed error rendering and recursive redaction tests."""

from __future__ import annotations

import pytest

from survey_scribe.errors import (
    REDACTED,
    ArtifactWriteError,
    is_sensitive_key,
    is_sensitive_query_key,
    redact_data,
    redact_exception,
    redact_text,
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


@pytest.mark.parametrize(
    "key",
    [
        "subscription-key",
        "Subscription_Key",
        "ocp-apim-subscription-key",
        "OCP_APIM_SUBSCRIPTION_KEY",
    ],
)
def test_subscription_key_mapping_and_query_names_are_sensitive(key: str) -> None:
    marker = "synthetic-mapping-value"

    assert redact_data({key: marker, "subscription-name": "public-label"}) == {
        key: REDACTED,
        "subscription-name": "public-label",
    }
    assert is_sensitive_key(key) is True
    assert is_sensitive_query_key(key) is True


@pytest.mark.parametrize(
    ("value", "secret"),
    [
        ("subscription-key=synthetic-assigned-secret", "synthetic-assigned-secret"),
        (
            "Ocp-Apim-Subscription-Key: synthetic secret,with;delimiters",
            "synthetic secret,with;delimiters",
        ),
        ('{"subscription_key":"synthetic-quoted-secret"}', "synthetic-quoted-secret"),
        (
            r"{\"ocp-apim-subscription-key\":\"synthetic-escaped-secret\"}",
            "synthetic-escaped-secret",
        ),
        (
            "https://example.test/path?OCP_APIM_SUBSCRIPTION_KEY=synthetic-query-secret",
            "synthetic-query-secret",
        ),
        (
            "https://example.test/path?OcpApimSubscriptionKey=synthetic-compact-secret",
            "synthetic-compact-secret",
        ),
        (
            "https://example.test/path?Ocp%2DApim%2DSubscription%2DKey=synthetic-encoded-secret",
            "synthetic-encoded-secret",
        ),
    ],
)
def test_subscription_key_text_forms_redact_complete_values(value: str, secret: str) -> None:
    rendered = redact_text(value)

    assert secret not in rendered
    assert REDACTED in rendered


def test_subscription_key_redaction_covers_nested_exceptions_but_not_nearby_metadata() -> None:
    try:
        try:
            raise ValueError("subscription-key=synthetic-cause-secret")
        except ValueError as cause:
            raise RuntimeError("ocp_apim_subscription_key=synthetic-error-secret") from cause
    except RuntimeError as error:
        rendered = redact_exception(error)

    assert "synthetic-cause-secret" not in rendered
    assert "synthetic-error-secret" not in rendered
    assert redact_text("subscription-name=public-label") == "subscription-name=public-label"
