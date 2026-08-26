"""Characterize the selected legacy root pipeline behavior with safe stubs."""

from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from survey_scribe.models.svis import DataType, SurveySVIS, SurveyVariable


class StubInstructorError(Exception):
    """Safe stand-in for the legacy Instructor exception."""


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _load_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    process_pdf: Any,
    extract_metadata: Any,
    extract_variables: Any,
) -> ModuleType:
    instructor = _module("instructor")
    instructor_v2 = _module("instructor.v2")
    instructor_core = _module("instructor.v2.core")
    instructor_errors = _module("instructor.v2.core.errors", InstructorError=StubInstructorError)
    agent = _module(
        "agents.svis_agent",
        extract_survey_metadata=extract_metadata,
        extract_variables_from_chunk=extract_variables,
    )
    extractor = _module("extractors.docling_pdf", process_pdf=process_pdf)

    for name, module in {
        "instructor": instructor,
        "instructor.v2": instructor_v2,
        "instructor.v2.core": instructor_core,
        "instructor.v2.core.errors": instructor_errors,
        "agents.svis_agent": agent,
        "extractors.docling_pdf": extractor,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "docling_pipeline", raising=False)
    return importlib.import_module("docling_pipeline")


def _metadata() -> SurveySVIS:
    return SurveySVIS(
        survey_id="TST_2024_SYNTH",
        country_code="TST",
        year=2024,
        survey_name="Synthetic Questionnaire 2024",
        variables=[],
        source_file="questionnaire.pdf",
        source_format="pdf",
        extraction_date=date(2024, 6, 1),
    )


def test_run_returns_none_and_replaces_named_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chunk = SimpleNamespace(module_name="Roster", text="# Roster\nQuestion", chunk_index=0)
    output = tmp_path / "output"
    output.mkdir()
    target = output / "TST_2024_SYNTH_svis.json"
    target.write_text("old", encoding="utf-8")
    pipeline = _load_pipeline(
        monkeypatch,
        process_pdf=lambda _path: (False, [chunk]),
        extract_metadata=lambda **_kwargs: _metadata(),
        extract_variables=lambda _chunk: [
            SurveyVariable(raw_name="q1", data_type=DataType.text, extraction_confidence=1.0)
        ],
    )

    result = pipeline.run(tmp_path / "questionnaire.pdf", output)

    assert result is None
    written = SurveySVIS.model_validate_json(target.read_text(encoding="utf-8"))
    assert [variable.raw_name for variable in written.variables] == ["q1"]


@pytest.mark.parametrize("source_result", [(True, []), (False, [])])
def test_scan_and_no_content_return_none_without_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_result: tuple[bool, list[Any]],
) -> None:
    pipeline = _load_pipeline(
        monkeypatch,
        process_pdf=lambda _path: source_result,
        extract_metadata=lambda **_kwargs: pytest.fail("metadata should not run"),
        extract_variables=lambda _chunk: pytest.fail("variables should not run"),
    )
    output = tmp_path / "output"

    assert pipeline.run(tmp_path / "questionnaire.pdf", output) is None
    assert not output.exists()


def test_failed_chunk_is_omitted_and_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chunks = [
        SimpleNamespace(module_name="Good", text="good", chunk_index=0),
        SimpleNamespace(module_name="Bad", text="bad", chunk_index=1),
    ]

    def extract(chunk: Any) -> list[SurveyVariable]:
        if chunk.module_name == "Bad":
            raise StubInstructorError("invalid structured response")
        return [SurveyVariable(raw_name="q1", data_type=DataType.text, extraction_confidence=1.0)]

    pipeline = _load_pipeline(
        monkeypatch,
        process_pdf=lambda _path: (False, chunks),
        extract_metadata=lambda **_kwargs: _metadata(),
        extract_variables=extract,
    )
    output = tmp_path / "output"

    pipeline.run(tmp_path / "questionnaire.pdf", output)

    written = SurveySVIS.model_validate_json(
        (output / "TST_2024_SYNTH_svis.json").read_text(encoding="utf-8")
    )
    assert [variable.raw_name for variable in written.variables] == ["q1"]
    assert written.extraction_notes == "Sections that failed extraction after retries: ['Bad']"


def test_metadata_failure_writes_placeholder_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chunk = SimpleNamespace(module_name="Roster", text="question", chunk_index=0)

    def fail_metadata(**_kwargs: Any) -> SurveySVIS:
        raise StubInstructorError("invalid metadata")

    pipeline = _load_pipeline(
        monkeypatch,
        process_pdf=lambda _path: (False, [chunk]),
        extract_metadata=fail_metadata,
        extract_variables=lambda _chunk: [],
    )
    output = tmp_path / "output"

    assert pipeline.run(tmp_path / "questionnaire.pdf", output) is None
    written = SurveySVIS.model_validate_json(
        (output / "questionnaire_svis.json").read_text(encoding="utf-8")
    )
    assert written.country_code == "UNK"
    assert written.year == 0
    assert written.extraction_notes == "Metadata extraction failed — fill in manually."


def test_all_failed_chunks_still_write_empty_legacy_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    chunks = [
        SimpleNamespace(module_name="One", text="one", chunk_index=0),
        SimpleNamespace(module_name="Two", text="two", chunk_index=1),
    ]

    def fail_variables(_chunk: Any) -> list[SurveyVariable]:
        raise StubInstructorError("invalid variables")

    pipeline = _load_pipeline(
        monkeypatch,
        process_pdf=lambda _path: (False, chunks),
        extract_metadata=lambda **_kwargs: _metadata(),
        extract_variables=fail_variables,
    )
    output = tmp_path / "output"

    pipeline.run(tmp_path / "questionnaire.pdf", output)

    written = SurveySVIS.model_validate_json(
        (output / "TST_2024_SYNTH_svis.json").read_text(encoding="utf-8")
    )
    assert written.variables == []
    assert (
        written.extraction_notes == "Sections that failed extraction after retries: ['One', 'Two']"
    )


def test_root_cli_shape_and_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pipeline = _load_pipeline(
        monkeypatch,
        process_pdf=lambda _path: (False, []),
        extract_metadata=lambda **_kwargs: _metadata(),
        extract_variables=lambda _chunk: [],
    )
    missing = tmp_path / "missing.pdf"
    monkeypatch.setattr(sys, "argv", ["docling_pipeline.py", str(missing)])
    with pytest.raises(SystemExit, match="1"):
        pipeline.main()

    text_file = tmp_path / "questionnaire.txt"
    text_file.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["docling_pipeline.py", str(text_file)])
    with pytest.raises(SystemExit, match="1"):
        pipeline.main()


def test_root_cli_forwards_explicit_output_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pipeline = _load_pipeline(
        monkeypatch,
        process_pdf=lambda _path: (False, []),
        extract_metadata=lambda **_kwargs: _metadata(),
        extract_variables=lambda _chunk: [],
    )
    source = tmp_path / "questionnaire.pdf"
    source.write_bytes(b"synthetic")
    output = tmp_path / "custom-output"
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(pipeline, "run", lambda path, directory: calls.append((path, directory)))
    monkeypatch.setattr(
        sys,
        "argv",
        ["docling_pipeline.py", str(source), "--output-dir", str(output)],
    )

    pipeline.main()

    assert calls == [(source, output)]
