"""Portable artifact identity and internal path safety contracts."""

from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest

from survey_scribe.errors import ArtifactWriteError
from survey_scribe.models import DataType, SurveySVIS, SurveyVariable
from survey_scribe.results import ArtifactKind, ExtractionResult


def _result(survey_id: str) -> ExtractionResult[SurveySVIS]:
    return ExtractionResult(
        output=SurveySVIS(
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
        ),
        run_id=f"run-{survey_id}",
    )


@pytest.mark.parametrize(
    "survey_id",
    ["CON", "con", "PRN", "AUX.data", "NUL", "COM1", "LPT9", "TST_2024."],
)
def test_nonportable_and_reserved_survey_ids_are_rejected(tmp_path: Path, survey_id: str) -> None:
    with pytest.raises(ArtifactWriteError, match="portable"):
        _result(survey_id).write(tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_case_alias_cannot_claim_a_second_legacy_filename(tmp_path: Path) -> None:
    first = _result("Case_ID").write(tmp_path)

    with pytest.raises(ArtifactWriteError, match="alias"):
        _result("case_id").write(tmp_path)

    projection = next(
        reference for reference in first.artifacts if reference.kind == ArtifactKind.legacy
    )
    assert projection.path == tmp_path / "Case_ID_svis.json"
    assert "case_id_svis.json" not in {path.name for path in tmp_path.iterdir()}


def _make_directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            pytest.skip(f"Windows junction creation is unavailable: {completed.stderr.strip()}")
    else:
        link.symlink_to(target, target_is_directory=True)


def _remove_directory_link(link: Path) -> None:
    if os.name == "nt":
        os.rmdir(link)
    else:
        link.unlink()


def test_reparse_or_symlinked_generations_directory_cannot_escape(tmp_path: Path) -> None:
    written = _result("TST_2024_SYNTH").write(tmp_path)
    main = next(reference for reference in written.artifacts if reference.kind == ArtifactKind.main)
    generations = main.path.parents[1]
    original_generations = generations.with_name("saved-generations")
    outside = tmp_path / "outside"
    outside.mkdir()
    generations.rename(original_generations)
    _make_directory_link(generations, outside)

    try:
        with pytest.raises(ArtifactWriteError, match="reparse|symlink"):
            _result("TST_2024_SYNTH").write(tmp_path, overwrite=True)
        assert list(outside.iterdir()) == []
    finally:
        if generations.exists():
            _remove_directory_link(generations)
        original_generations.rename(generations)
