"""SVIS extraction pipeline ordering, failure, quality, and cancellation tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date

import pytest

from survey_scribe import pipeline as pipeline_module
from survey_scribe.config import RetryConfig
from survey_scribe.models.svis import DataType, NumericRange, SurveyVariable
from survey_scribe.pipeline import (
    BlockExtraction,
    ExtractedMetadata,
    ExtractedVariable,
    ExtractionPipeline,
    PipelineConfig,
)
from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.testing import DeterministicFakeProvider, FakeRequest, FakeStep
from survey_scribe.results import DiagnosticCode, ResultStatus
from survey_scribe.sources.base import (
    SourceBlock,
    SourceCoverage,
    SourceDiagnostic,
    SourceDocument,
    SourceProvenance,
    SourceTable,
    render_table,
)
from survey_scribe.sources.chunking import chunk_document


def _capabilities() -> ModelCapabilities:
    return ModelCapabilities(
        provider="fake",
        model="pipeline-fake-v1",
        structured_output=True,
        strict_schema=True,
        max_input_tokens=200_000,
        max_output_tokens=8_192,
        supported_generation_settings=frozenset({"temperature", "max_output_tokens", "seed"}),
        evidence=CapabilityEvidence.verified,
        tested_sdk_version="fake-1",
    )


def _document() -> SourceDocument:
    return SourceDocument(
        source_name="survey.txt",
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="block-0",
                order=0,
                kind="text",
                text="Q1. Age",
                provenance=SourceProvenance(source_name="survey.txt", page=1),
            ),
            SourceBlock(
                id="block-1",
                order=1,
                kind="text",
                text="Q2. Employment",
                provenance=SourceProvenance(source_name="survey.txt", page=2),
            ),
        ),
        snapshot_sha256="a" * 64,
    )


def _chunk_id(request: FakeRequest) -> str:
    content = next(message.content for message in request.messages if message.role == "user")
    return content.split("CHUNK_ID: ", maxsplit=1)[1].splitlines()[0]


def _source_block_ids(request: FakeRequest) -> tuple[str, ...]:
    content = next(message.content for message in request.messages if message.role == "user")
    encoded = content.split("SOURCE_BLOCK_IDS: ", maxsplit=1)[1].splitlines()[0]
    return tuple(json.loads(encoded))


@pytest.mark.asyncio
async def test_pipeline_preserves_source_order_and_marks_partial_quality() -> None:
    async def respond(request: FakeRequest) -> object:
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN",
                country_code="TST",
                year=2026,
                survey_name="Synthetic Survey",
            )
        chunk_id = _chunk_id(request)
        block_ids = _source_block_ids(request)
        variables: list[ExtractedVariable] = []
        if "block-0" in block_ids:
            await asyncio.sleep(0.02)
            variables.append(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name="age",
                        question_text="Age",
                        data_type=DataType.numeric,
                        extraction_confidence=0.6,
                    ),
                    source_block_ids=("block-0",),
                )
            )
        if "block-1" in block_ids:
            variables.append(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name="employment",
                        question_text="Employment",
                        data_type=DataType.categorical_single,
                        extraction_confidence=1.0,
                    ),
                    source_block_ids=("block-1",),
                )
            )
        return BlockExtraction(
            block_id=chunk_id,
            variables=tuple(variables),
        )

    provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=respond)
    result = await ExtractionPipeline(
        provider,
        config=PipelineConfig(max_concurrency=2),
        extraction_date=date(2026, 9, 3),
    ).extract(_document())

    assert result.status is ResultStatus.success
    assert result.output is not None
    assert [variable.raw_name for variable in result.output.variables] == [
        "age",
        "employment",
    ]
    assert [variable.source_page for variable in result.output.variables] == [0, 1]
    assert all(variable.needs_review for variable in result.output.variables)
    assert provider.peak_concurrency <= 2
    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert DiagnosticCode.quality_low_confidence in codes
    assert DiagnosticCode.quality_missing_categories in codes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cell", "overlap_tokens", "provider_limit"),
    [("x" * 997, 0, 200_000), ('"\\\t\n\u00e9"' * 100, 200, 10_000)],
)
async def test_pipeline_packs_tables_within_the_complete_request_budget(
    cell: str, overlap_tokens: int, provider_limit: int
) -> None:
    blocks: list[SourceBlock] = []
    for index in range(11):
        provenance = SourceProvenance(source_name="survey.pdf", page=index + 1)
        rows = ((f"{index}: " + (cell if index < 10 else "L" * 8_000),), ("Shared row",))
        table = SourceTable(id=f"table-{index:06d}", rows=rows, provenance=provenance)
        blocks.extend(
            (
                SourceBlock(
                    id=f"question-{index:06d}",
                    order=2 * index,
                    kind="text",
                    text=f"Question {index}",
                    provenance=provenance,
                ),
                SourceBlock(
                    id=table.id,
                    order=2 * index + 1,
                    kind="table",
                    text=render_table(rows),
                    provenance=provenance,
                    table=table,
                ),
            )
        )
    document = SourceDocument(
        source_name="survey.pdf", media_type="application/pdf", blocks=tuple(blocks)
    )
    table_ids = tuple(table.id for table in document.tables)
    requests: list[FakeRequest] = []

    async def respond(request: FakeRequest) -> object:
        requests.append(request)
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN", country_code="TST", year=2026, survey_name="Survey"
            )
        return BlockExtraction(
            block_id=_chunk_id(request),
            variables=tuple(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name=block_id, data_type=DataType.text, extraction_confidence=1.0
                    ),
                    source_block_ids=(block_id,),
                )
                for block_id in _source_block_ids(request)
                if block_id in table_ids
            ),
        )

    provider = DeterministicFakeProvider(
        capabilities=replace(_capabilities(), max_input_tokens=provider_limit), responder=respond
    )
    config = PipelineConfig(max_request_tokens=11_460, overlap_tokens=overlap_tokens)
    pipeline = ExtractionPipeline(provider, config=config)
    result = await pipeline.extract(document)

    assert result.status is ResultStatus.success
    assert result.output is not None
    assert [variable.raw_name for variable in result.output.variables] == list(table_ids)
    assert [variable.source_page for variable in result.output.variables] == list(range(11))
    assert result.failed_blocks == ()
    assert all(
        provider.estimate_tokens(request.messages) <= min(config.max_request_tokens, provider_limit)
        for request in requests
    )
    table_batches = [
        set(_source_block_ids(request)).intersection(table_ids)
        for request in requests
        if request.response_model is BlockExtraction
    ]
    assert len(table_batches) > 1
    assert any(len(batch) > 1 for batch in table_batches)
    chunked = pipeline._chunk_document(document)
    assert (
        tuple(
            part.table
            for chunk in chunked.chunks
            for part in chunk.parts
            if part.id in chunk.new_part_ids and part.table is not None
        )
        == document.tables
    )
    assert any(chunk.overlap_part_ids for chunk in chunked.chunks) is bool(overlap_tokens)


@pytest.mark.asyncio
async def test_pipeline_splits_escaped_text_without_losing_source_part_provenance() -> None:
    text = '"\\\t\n\u00e9"' * 300
    document = _document().model_copy(
        update={"blocks": (_document().blocks[0].model_copy(update={"text": text}),)}
    )
    requests: list[FakeRequest] = []

    async def respond(request: FakeRequest) -> object:
        requests.append(request)
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN", country_code="TST", year=2026, survey_name="Survey"
            )
        return BlockExtraction(
            block_id=_chunk_id(request),
            variables=(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name="age", data_type=DataType.text, extraction_confidence=1.0
                    ),
                    source_block_ids=("block-0",),
                ),
            ),
        )

    provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=respond)
    pipeline = ExtractionPipeline(
        provider, config=PipelineConfig(max_request_tokens=2_200, overlap_tokens=200)
    )
    result = await pipeline.extract(document)

    assert result.status is ResultStatus.success
    assert result.output is not None
    assert result.failed_blocks == ()
    assert all(provider.estimate_tokens(request.messages) <= 2_200 for request in requests)
    chunked = pipeline._chunk_document(document)
    new_parts = [
        part for chunk in chunked.chunks for part in chunk.parts if part.id in chunk.new_part_ids
    ]
    assert "".join(part.text for part in new_parts) == text
    assert [part.part_index for part in new_parts] == list(range(1, len(new_parts) + 1))
    assert {part.part_count for part in new_parts} == {len(new_parts)}
    assert all(part.provenance == document.blocks[0].provenance for part in new_parts)


@pytest.mark.asyncio
async def test_pipeline_rejects_a_table_that_cannot_fit_the_serialized_request() -> None:
    provenance = SourceProvenance(source_name="survey.pdf", page=1)
    rows = (("\u00e9" * 250,),)
    table = SourceTable(id="table-1", rows=rows, provenance=provenance)
    document = SourceDocument(
        source_name="survey.pdf",
        media_type="application/pdf",
        blocks=(
            SourceBlock(
                id="table-1",
                order=0,
                kind="table",
                text=render_table(rows),
                provenance=provenance,
                table=table,
            ),
        ),
    )
    provider = DeterministicFakeProvider(capabilities=_capabilities())
    result = await ExtractionPipeline(
        provider, config=PipelineConfig(max_request_tokens=2_200, overlap_tokens=0)
    ).extract(document)

    assert result.status is ResultStatus.failed
    assert result.output is None
    assert provider.call_count == 0
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["SOURCE_LIMIT_EXCEEDED"]


@pytest.mark.asyncio
async def test_pipeline_uses_metadata_fallback_and_accounts_for_unreadable_units() -> None:
    document = _document().model_copy(
        update={
            "coverage": SourceCoverage(
                unit="page",
                total_units=3,
                converted_units=(1, 2),
                failed_units=(3,),
            ),
            "diagnostics": (
                SourceDiagnostic(
                    code="SOURCE_PAGE_UNREADABLE",
                    message="One page was unreadable.",
                    unit="page",
                    unit_index=3,
                ),
            ),
        }
    )

    async def respond(request: FakeRequest) -> object:
        if request.response_model is ExtractedMetadata:
            raise TimeoutError("private source text")
        chunk_id = _chunk_id(request)
        block_ids = _source_block_ids(request)
        return BlockExtraction(
            block_id=chunk_id,
            variables=tuple(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name=block_id,
                        data_type=DataType.text,
                        extraction_confidence=1.0,
                    ),
                    source_block_ids=(block_id,),
                )
                for block_id in block_ids
            ),
        )

    provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=respond)
    result = await ExtractionPipeline(
        provider,
        config=PipelineConfig(max_concurrency=2),
        extraction_date=date(2026, 9, 3),
    ).extract(document)

    assert result.status is ResultStatus.partial
    assert result.output is not None
    assert result.output.survey_id == "UNK_2026_SURVEY"
    assert result.failed_blocks[0].block_id == "source-page-3"
    assert {diagnostic.code for diagnostic in result.diagnostics}.issuperset(
        {DiagnosticCode.metadata_incomplete, DiagnosticCode.source_unreadable}
    )
    assert "private source text" not in repr(result)


@pytest.mark.asyncio
async def test_pipeline_returns_failed_when_all_blocks_fail_and_propagates_cancellation() -> None:
    async def fail_blocks(request: FakeRequest) -> object:
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN",
                country_code="TST",
                year=2026,
                survey_name="Synthetic Survey",
            )
        raise TimeoutError("private source")

    failed_provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=fail_blocks)
    failed = await ExtractionPipeline(
        failed_provider,
        config=PipelineConfig(max_concurrency=2),
        extraction_date=date(2026, 9, 3),
    ).extract(_document())
    assert failed.status is ResultStatus.failed
    assert failed.output is None
    assert [block.block_id for block in failed.failed_blocks] == ["chunk-000001"]

    async def cancel(_request: FakeRequest) -> object:
        raise asyncio.CancelledError

    cancelled_provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=cancel)
    with pytest.raises(asyncio.CancelledError):
        await ExtractionPipeline(
            cancelled_provider,
            extraction_date=date(2026, 9, 3),
        ).extract(_document())


@pytest.mark.asyncio
async def test_pipeline_retries_invalid_ranges_and_reports_truncation() -> None:
    block_calls = 0

    async def retry_range(request: FakeRequest) -> object:
        nonlocal block_calls
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN",
                country_code="TST",
                year=2026,
                survey_name="Synthetic Survey",
            )
        block_calls += 1
        minimum, maximum = (10, 1) if block_calls == 1 else (1, 10)
        return {
            "block_id": _chunk_id(request),
            "variables": [
                {
                    "variable": {
                        "raw_name": "age",
                        "data_type": "numeric",
                        "numeric_range": {
                            "min_value": minimum,
                            "max_value": maximum,
                        },
                        "extraction_confidence": 1.0,
                    },
                    "source_block_ids": ["block-0"],
                }
            ],
        }

    provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=retry_range)
    result = await ExtractionPipeline(
        provider,
        config=PipelineConfig(retry=RetryConfig(initial_delay_seconds=0.0)),
        extraction_date=date(2026, 9, 3),
    ).extract(_document())
    assert result.output is not None
    assert result.output.variables[0].numeric_range == NumericRange(
        min_value=1,
        max_value=10,
    )
    assert block_calls == 2

    truncated = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(
            FakeStep.output(
                ExtractedMetadata(
                    survey_id="TST_2026_SYN",
                    country_code="TST",
                    year=2026,
                    survey_name="Synthetic Survey",
                )
            ),
            FakeStep.output(
                BlockExtraction(block_id="chunk-000001", variables=()),
                finish_reason="length",
            ),
        ),
    )
    truncated_result = await ExtractionPipeline(
        truncated,
        extraction_date=date(2026, 9, 3),
    ).extract(_document())
    assert truncated_result.status is ResultStatus.failed
    assert DiagnosticCode.provider_truncated in {
        diagnostic.code for diagnostic in truncated_result.diagnostics
    }

    async def invalid_range(request: FakeRequest) -> object:
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN",
                country_code="TST",
                year=2026,
                survey_name="Synthetic Survey",
            )
        return {
            "block_id": _chunk_id(request),
            "variables": [
                {
                    "variable": {
                        "raw_name": "age",
                        "data_type": "numeric",
                        "numeric_range": {"min_value": 10, "max_value": 1},
                        "extraction_confidence": 1.0,
                    },
                    "source_block_ids": ["block-0"],
                }
            ],
        }

    exhausted = DeterministicFakeProvider(
        capabilities=_capabilities(),
        responder=invalid_range,
    )
    exhausted_result = await ExtractionPipeline(
        exhausted,
        config=PipelineConfig(
            retry=RetryConfig(
                max_attempts=2,
                initial_delay_seconds=0.0,
                max_delay_seconds=0.0,
            )
        ),
        extraction_date=date(2026, 9, 3),
    ).extract(_document())
    assert exhausted_result.status is ResultStatus.failed
    assert [block.block_id for block in exhausted_result.failed_blocks] == ["chunk-000001"]
    assert [diagnostic.code for diagnostic in exhausted_result.diagnostics].count(
        DiagnosticCode.validation_failed
    ) == 1


@pytest.mark.asyncio
async def test_pipeline_cancels_siblings_and_keeps_overlap_repeated_row_provenance() -> None:
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def cancel_one() -> int:
        await entered.wait()
        raise asyncio.CancelledError

    async def wait_forever() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    with pytest.raises(asyncio.CancelledError):
        await pipeline_module._gather_cancel_on_control((wait_forever(), cancel_one()))
    assert entered.is_set()
    assert cleaned.is_set()


@pytest.mark.asyncio
async def test_pipeline_carries_overlap_proof_into_exact_deduplication() -> None:
    document = SourceDocument(
        source_name="survey.txt",
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="first",
                order=0,
                kind="text",
                text="Q1 Age " + "a" * 40,
                provenance=SourceProvenance(source_name="survey.txt"),
            ),
            SourceBlock(
                id="second",
                order=1,
                kind="text",
                text="Q2 Other " + "b" * 500,
                provenance=SourceProvenance(source_name="survey.txt"),
            ),
        ),
        snapshot_sha256="d" * 64,
    )

    async def respond(request: FakeRequest) -> object:
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN",
                country_code="TST",
                year=2026,
                survey_name="Synthetic Survey",
            )
        block_ids = _source_block_ids(request)
        variables = (
            (
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name="age",
                        question_text="Age",
                        data_type=DataType.numeric,
                        extraction_confidence=1.0,
                    ),
                    source_block_ids=("first",),
                ),
            )
            if "first" in block_ids
            else ()
        )
        return BlockExtraction(block_id=_chunk_id(request), variables=variables)

    provider = DeterministicFakeProvider(capabilities=_capabilities(), responder=respond)
    result = await ExtractionPipeline(
        provider,
        # 1,630: the same 188-token content budget the test was written with (the 1.1.0
        # variable prompt is ~600 tokens longer than 1.0.0's); the chunking is unchanged
        config=PipelineConfig(max_request_tokens=1_630, overlap_tokens=100),
        extraction_date=date(2026, 9, 3),
    ).extract(document)
    assert result.output is not None
    assert [variable.raw_name for variable in result.output.variables] == ["age"]
    assert DiagnosticCode.quality_overlap_deduped in {
        diagnostic.code for diagnostic in result.diagnostics
    }

    provenance = SourceProvenance(
        source_name="survey.csv",
        section_path=("Roster",),
        row_start=1,
        row_end=2,
    )
    table = SourceTable(
        id="table-1",
        rows=(("Q1", "Age"), ("Q1", "Age")),
        provenance=provenance,
    )
    table_document = SourceDocument(
        source_name="survey.csv",
        media_type="text/csv",
        blocks=(
            SourceBlock(
                id="table-block",
                order=0,
                kind="table",
                text="Q1 | Age\nQ1 | Age",
                provenance=provenance,
                table=table,
            ),
        ),
        snapshot_sha256="c" * 64,
    )
    requests: list[str] = []

    async def capture(request: FakeRequest) -> object:
        content = next(message.content for message in request.messages if message.role == "user")
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN",
                country_code="TST",
                year=2026,
                survey_name="Synthetic Survey",
            )
        requests.append(content)
        return BlockExtraction(
            block_id=_chunk_id(request),
            variables=(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name="age",
                        data_type=DataType.numeric,
                        module="Wrong",
                        extraction_confidence=1.0,
                    ),
                    source_block_ids=("table-block",),
                ),
            ),
        )

    captured = DeterministicFakeProvider(capabilities=_capabilities(), responder=capture)
    table_result = await ExtractionPipeline(
        captured,
        extraction_date=date(2026, 9, 3),
    ).extract(table_document)
    assert table_result.output is not None
    assert table_result.output.variables[0].module == "Roster"
    assert '"count":2' in requests[0]
    assert table_result.artifact_provenance is not None
    assert [item.pass_kind for item in table_result.artifact_provenance.prompt_versions] == [
        "metadata",
        "extraction",
    ]


@pytest.mark.asyncio
async def test_pipeline_rejects_bad_identities_limits_and_conflicting_metadata() -> None:
    with pytest.raises(ValueError, match="unique"):
        ExtractedVariable(
            variable=SurveyVariable(
                raw_name="age",
                data_type=DataType.numeric,
                extraction_confidence=1.0,
            ),
            source_block_ids=("block-0", "block-0"),
        )
    with pytest.raises(ValueError, match="minimum"):
        BlockExtraction(
            block_id="chunk",
            variables=(
                ExtractedVariable(
                    variable=SurveyVariable(
                        raw_name="age",
                        data_type=DataType.numeric,
                        numeric_range=NumericRange(min_value=10, max_value=1),
                        extraction_confidence=1.0,
                    ),
                    source_block_ids=("block-0",),
                ),
            ),
        )

    tiny = replace(_capabilities(), max_input_tokens=1)
    failed_limit = await ExtractionPipeline(
        DeterministicFakeProvider(capabilities=tiny),
        config=PipelineConfig(max_request_tokens=1_024),
    ).extract(_document())
    assert failed_limit.status is ResultStatus.failed

    calls = 0

    async def conflict(request: FakeRequest) -> object:
        nonlocal calls
        calls += 1
        if request.response_model is ExtractedMetadata:
            return ExtractedMetadata(
                survey_id="TST_2026_SYN",
                country_code="TST",
                year=2026,
                survey_name=f"Survey {calls}",
            )
        return BlockExtraction(block_id="wrong", variables=())

    long_document = SourceDocument(
        source_name="survey.txt",
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="one",
                order=0,
                kind="text",
                text="a" * 300,
                provenance=SourceProvenance(source_name="survey.txt"),
            ),
            SourceBlock(
                id="two",
                order=1,
                kind="text",
                text="b" * 300,
                provenance=SourceProvenance(source_name="survey.txt"),
            ),
        ),
    )
    conflicting = await ExtractionPipeline(
        DeterministicFakeProvider(capabilities=_capabilities(), responder=conflict),
        config=PipelineConfig(max_request_tokens=1_630, overlap_tokens=0),  # as above
    ).extract(long_document)
    assert DiagnosticCode.metadata_incomplete in {
        diagnostic.code for diagnostic in conflicting.diagnostics
    }
    assert conflicting.artifact_provenance is None

    table_provenance = SourceProvenance(
        source_name="survey.csv",
        row_start=1,
        row_end=2,
    )
    repeated_table = SourceTable(
        id="table-coverage",
        rows=(("Q1", "Age"), ("Q1", "Age")),
        provenance=table_provenance,
    )
    repeated_document = SourceDocument(
        source_name="survey.csv",
        media_type="text/csv",
        blocks=(
            SourceBlock(
                id="table-coverage-block",
                order=0,
                kind="table",
                text="Q1 | Age\nQ1 | Age",
                provenance=table_provenance,
                table=repeated_table,
            ),
        ),
    )
    chunked = chunk_document(repeated_document, max_tokens=100_000)
    oversized_inventory = pipeline_module._repeated_row_inventory(
        chunked.model_copy(update={"repeated_rows": chunked.repeated_rows * 100}),
        chunked.chunks[0],
    )
    assert '"sha256"' in oversized_inventory
