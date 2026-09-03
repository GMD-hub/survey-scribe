"""Deterministic default SVIS quality-policy tests."""

from __future__ import annotations

from survey_scribe.models.svis import DataType, NumericRange, SurveyVariable
from survey_scribe.pipeline import QualityRecord, apply_quality_policy
from survey_scribe.results import DiagnosticCode
from survey_scribe.sources.base import SourceProvenance


def _record(
    raw_name: str,
    question: str,
    *,
    order: int,
    confidence: float = 1.0,
    module: str | None = None,
    data_type: DataType = DataType.text,
    overlap_block_ids: tuple[str, ...] = (),
) -> QualityRecord:
    return QualityRecord(
        variable=SurveyVariable(
            raw_name=raw_name,
            question_text=question,
            data_type=data_type,
            extraction_confidence=confidence,
            module=module,
        ),
        block_id=f"block-{order}",
        source_order=order,
        provenance=SourceProvenance(source_name="survey.txt", page=1, sheet="Roster"),
        source_block_ids=(f"block-{order}",),
        overlap_block_ids=overlap_block_ids,
    )


def test_quality_policy_applies_review_reconciliation_and_overlap_rules() -> None:
    outcome = apply_quality_policy(
        (
            _record("age", "What is your age?", order=0, confidence=0.69, module="Wrong"),
            _record(
                "age",
                "What is your age?",
                order=1,
                module="Wrong",
                overlap_block_ids=("block-0",),
            ),
            _record(
                "status",
                "What is your status?",
                order=2,
                data_type=DataType.categorical_single,
            ),
            _record("employment", "What is your employment status?", order=3),
        ),
        confidence_threshold=0.70,
    )

    assert [variable.raw_name for variable in outcome.variables] == [
        "age",
        "status",
        "employment",
    ]
    assert outcome.variables[0].needs_review is True
    assert outcome.variables[0].module == "Roster"
    assert outcome.variables[1].needs_review is True
    assert outcome.variables[2].needs_review is True
    codes = {diagnostic.code for diagnostic in outcome.diagnostics}
    assert DiagnosticCode.quality_low_confidence in codes
    assert DiagnosticCode.quality_missing_categories in codes
    assert DiagnosticCode.quality_overlap_deduped in codes
    assert DiagnosticCode.quality_module_reconciled in codes
    assert DiagnosticCode.quality_possible_duplicate in codes


def test_distinct_duplicate_raw_names_are_retained_and_flagged() -> None:
    outcome = apply_quality_policy(
        (
            _record("member", "Member name", order=0),
            _record("member", "Member age", order=1),
        ),
        confidence_threshold=0.70,
    )

    assert len(outcome.variables) == 2
    assert all(variable.needs_review for variable in outcome.variables)
    assert DiagnosticCode.quality_duplicate_raw_name in {
        diagnostic.code for diagnostic in outcome.diagnostics
    }


def test_quality_policy_preserves_threshold_and_diagnostic_order() -> None:
    outcome = apply_quality_policy(
        (
            _record(
                "a",
                "Shared employment status for every active household member now",
                order=0,
                confidence=0.70,
            ),
            _record(
                "b",
                "Shared employment status for every active household member then",
                order=1,
                confidence=0.6999,
            ),
            _record(
                "c",
                "Shared employment status for every active household member later",
                order=2,
                confidence=1.0,
            ),
        ),
        confidence_threshold=0.70,
    )

    assert outcome.variables[0].needs_review is True
    assert outcome.variables[1].needs_review is True
    assert [diagnostic.code for diagnostic in outcome.diagnostics] == [
        DiagnosticCode.quality_module_reconciled,
        DiagnosticCode.quality_low_confidence,
        DiagnosticCode.quality_module_reconciled,
        DiagnosticCode.quality_module_reconciled,
        DiagnosticCode.quality_possible_duplicate,
        DiagnosticCode.quality_possible_duplicate,
        DiagnosticCode.quality_possible_duplicate,
    ]


def test_quality_policy_excludes_invalid_ranges_once_per_failed_block() -> None:
    provenance = SourceProvenance(source_name="survey.txt")
    records = tuple(
        QualityRecord(
            variable=SurveyVariable(
                raw_name=f"invalid-{index}",
                data_type=DataType.numeric,
                numeric_range=NumericRange(min_value=10, max_value=1),
                extraction_confidence=1.0,
            ),
            block_id="chunk-1",
            source_order=0,
            provenance=provenance,
            source_block_ids=("block-1",),
        )
        for index in range(2)
    )

    outcome = apply_quality_policy(records, confidence_threshold=0.70)

    assert outcome.variables == ()
    assert len(outcome.failed_records) == 1
    assert [diagnostic.code for diagnostic in outcome.diagnostics] == [
        DiagnosticCode.validation_failed,
        DiagnosticCode.validation_failed,
    ]
