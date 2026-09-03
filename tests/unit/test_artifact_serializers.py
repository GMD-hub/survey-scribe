"""Typed artifact serializer boundary tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from survey_scribe.errors import ArtifactWriteError
from survey_scribe.models import DataType, SurveySVIS, SurveyVariable
from survey_scribe.results import ArtifactKind, ExtractionResult
from survey_scribe.serialization.artifacts import JsonArtifactSerializer


class GenericOutput(BaseModel):
    survey_id: str
    values: list[int]


class ExtendedSurveySVIS(SurveySVIS):
    extension: str


def _survey(survey_id: str = "TST_2024_SYNTH") -> SurveySVIS:
    return SurveySVIS(
        survey_id=survey_id,
        country_code="TST",
        year=2024,
        survey_name="Synthetic Survey",
        variables=[
            SurveyVariable(
                raw_name="q1",
                data_type=DataType.text,
                extraction_confidence=1.0,
            )
        ],
        source_file="questionnaire.pdf",
        source_format="pdf",
        extraction_date=date(2024, 6, 1),
    )


def test_generic_typed_serializer_uses_non_svis_names(tmp_path: Path) -> None:
    output = GenericOutput(survey_id="GENERIC_1", values=[1, 2])
    serializer = JsonArtifactSerializer(GenericOutput, filename_suffix="_data.json")

    written = ExtractionResult(output=output).write(tmp_path, serializer=serializer)

    main = next(reference for reference in written.artifacts if reference.kind == ArtifactKind.main)
    projection = next(
        reference for reference in written.artifacts if reference.kind == ArtifactKind.projection
    )
    assert main.path.name == "GENERIC_1_data.json"
    assert projection.path == tmp_path / "GENERIC_1_data.json"
    assert json.loads(main.path.read_text(encoding="utf-8")) == output.model_dump(mode="json")
    assert not (tmp_path / "GENERIC_1_svis.json").exists()


def test_default_serializer_treats_svis_subclass_as_generic(tmp_path: Path) -> None:
    extended = ExtendedSurveySVIS(**_survey().model_dump(), extension="routing")

    written = ExtractionResult(output=extended).write(tmp_path)

    main = next(reference for reference in written.artifacts if reference.kind == ArtifactKind.main)
    assert main.path.name == "TST_2024_SYNTH_result.json"
    assert not (tmp_path / "TST_2024_SYNTH_svis.json").exists()


def test_default_generic_serializer_accepts_output_without_embedded_identity(
    tmp_path: Path,
) -> None:
    result = ExtractionResult[dict[str, int]](
        output={"value": 1},
        survey_id="GENERIC_MAP",
    )

    written = result.write(tmp_path)

    projection = next(
        reference for reference in written.artifacts if reference.kind == ArtifactKind.projection
    )
    assert projection.path.name == "GENERIC_MAP_result.json"
    assert json.loads(projection.path.read_text(encoding="utf-8")) == {"value": 1}


def test_exact_svis_write_revalidates_detached_identity_before_setup(tmp_path: Path) -> None:
    output = _survey()
    result = ExtractionResult(output=output)
    output.survey_id = "CHANGED_AFTER_RESULT_CREATION"

    with pytest.raises(ArtifactWriteError, match="survey_id"):
        result.write(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_typed_serializer_rejects_the_wrong_runtime_output_type(tmp_path: Path) -> None:
    serializer = JsonArtifactSerializer(GenericOutput, filename_suffix="_data.json")

    with pytest.raises(ArtifactWriteError, match="output type"):
        ExtractionResult[Any](output={"survey_id": "GENERIC_1"}, survey_id="GENERIC_1").write(
            tmp_path,
            serializer=serializer,
        )

    assert list(tmp_path.iterdir()) == []


def test_serializer_rejects_unsafe_artifact_filename_suffix(tmp_path: Path) -> None:
    output = GenericOutput(survey_id="GENERIC_1", values=[])
    serializer = JsonArtifactSerializer(GenericOutput, filename_suffix="/../../escape.json")

    with pytest.raises(ArtifactWriteError, match="filename"):
        ExtractionResult(output=output).write(tmp_path, serializer=serializer)

    assert list(tmp_path.iterdir()) == []
