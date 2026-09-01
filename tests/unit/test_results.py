"""Result envelope and status tests."""

from __future__ import annotations

from math import inf, nan
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from survey_scribe.results import (
    ArtifactReference,
    Diagnostic,
    DiagnosticCode,
    DiagnosticSeverity,
    ExtractionResult,
    FailedBlock,
    ResultStatus,
)
from survey_scribe.serialization.legacy import legacy_payload


class MutableOutput(BaseModel):
    survey_id: str
    values: list[int]


class NestedMappingOutput(BaseModel):
    values: dict[Any, str]


def test_result_collections_and_outer_envelope_are_frozen() -> None:
    result = ExtractionResult[MutableOutput].model_validate(
        {
            "output": MutableOutput(survey_id="TST_2024_SYNTH", values=[1]),
            "diagnostics": [
                Diagnostic(code=DiagnosticCode.quality_low_confidence, message="review")
            ],
            "failed_blocks": [FailedBlock(block_id="2", message="unreadable")],
            "artifacts": [
                ArtifactReference(
                    kind="main",
                    path=Path("main.json"),
                    generation_id="generation",
                    sha256="0" * 64,
                )
            ],
        }
    )

    assert isinstance(result.diagnostics, tuple)
    assert isinstance(result.failed_blocks, tuple)
    assert isinstance(result.artifacts, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        result.output = None
    with pytest.raises(AttributeError):
        cast(Any, result.diagnostics).append(Diagnostic(code="OTHER", message="not possible"))


def test_caller_owned_output_can_remain_mutable_and_snapshot_is_detached() -> None:
    output = MutableOutput(survey_id="TST_2024_SYNTH", values=[1])
    result = ExtractionResult(output=output)
    snapshot = result.serialization_snapshot()

    output.values.append(2)

    assert result.output is output
    assert output.values == [1, 2]
    assert snapshot["output"]["values"] == [1]


def test_diagnostic_details_are_detached_finite_json_and_recursively_immutable() -> None:
    source: dict[str, Any] = {"nested": {"values": [1, 2.5, True, None, "text"]}}

    diagnostic = Diagnostic(code="TEST", message="safe", details=source)
    source["nested"]["values"].append("changed")

    assert diagnostic.details == {"nested": {"values": (1, 2.5, True, None, "text")}}
    assert diagnostic.model_dump(mode="json")["details"] == {
        "nested": {"values": [1, 2.5, True, None, "text"]}
    }
    with pytest.raises(TypeError, match="immutable"):
        diagnostic.details["new"] = "value"
    with pytest.raises(TypeError, match="immutable"):
        diagnostic.details["nested"]["values"] += (3,)


@pytest.mark.parametrize(
    "details",
    [
        {1: "non-string key"},
        {"value": nan},
        {"value": inf},
        {"value": {"not", "json"}},
        {"value": object()},
    ],
)
def test_diagnostic_details_reject_non_json_or_nonfinite_values(details: object) -> None:
    with pytest.raises(ValidationError):
        Diagnostic.model_validate({"code": "TEST", "message": "safe", "details": details})


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            ExtractionResult(output=MutableOutput(survey_id="SUCCESS", values=[])),
            ResultStatus.success,
        ),
        (
            ExtractionResult(
                output=MutableOutput(survey_id="PARTIAL", values=[]),
                failed_blocks=(FailedBlock(block_id="1", message="failed"),),
            ),
            ResultStatus.partial,
        ),
        (
            ExtractionResult(
                output=MutableOutput(survey_id="PARTIAL_DIAGNOSTIC", values=[]),
                diagnostics=(
                    Diagnostic(
                        code=DiagnosticCode.metadata_incomplete,
                        message="metadata missing",
                        severity=DiagnosticSeverity.error,
                    ),
                ),
            ),
            ResultStatus.partial,
        ),
        (
            ExtractionResult[MutableOutput](
                output=None,
                diagnostics=(Diagnostic(code="PROVIDER_FAILED", message="provider failed"),),
            ),
            ResultStatus.failed,
        ),
    ],
)
def test_status_is_derived_from_output_and_failures(
    result: ExtractionResult[MutableOutput], expected: ResultStatus
) -> None:
    assert result.status is expected


def test_quality_warning_does_not_make_a_complete_result_partial() -> None:
    result = ExtractionResult(
        output=MutableOutput(survey_id="TST_2024_SYNTH", values=[]),
        diagnostics=(
            Diagnostic(
                code=DiagnosticCode.quality_low_confidence,
                message="review required",
                severity=DiagnosticSeverity.warning,
            ),
        ),
    )

    assert result.status is ResultStatus.success


def test_provider_failure_with_usable_output_is_partial() -> None:
    result = ExtractionResult(
        output=MutableOutput(survey_id="TST_2024_SYNTH", values=[]),
        diagnostics=(Diagnostic(code=DiagnosticCode.provider_failed, message="provider failed"),),
    )

    assert result.status is ResultStatus.partial


def test_legacy_payload_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(TypeError, match="string keys"):
        legacy_payload({1: "integer", "1": "string"})


def test_legacy_payload_rejects_non_string_keys_in_nested_models() -> None:
    nested = NestedMappingOutput(values={1: "integer", "1": "string"})

    with pytest.raises(TypeError, match="string keys"):
        legacy_payload({"nested": nested})


def test_result_creation_has_no_write_side_effect(tmp_path: Path) -> None:
    ExtractionResult(output=MutableOutput(survey_id="TST_2024_SYNTH", values=[]))

    assert list(tmp_path.iterdir()) == []


def test_diagnostic_codes_are_stable_strings() -> None:
    assert DiagnosticCode.quality_low_confidence.value == "QUALITY_LOW_CONFIDENCE"
    assert DiagnosticCode.metadata_incomplete.value == "METADATA_INCOMPLETE"
    assert ResultStatus.partial.value == "partial"
