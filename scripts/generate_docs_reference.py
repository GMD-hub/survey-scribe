"""Generate deterministic public schemas used by the documentation site."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from survey_scribe import canonical_routing_schema_json
from survey_scribe.config import SurveyScribeConfig
from survey_scribe.models.svis import SurveySVIS

_ROOT = Path(__file__).resolve().parents[1]
_OUTPUT_DIRECTORY = _ROOT / "docs" / "assets" / "generated"


def _json_document(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def generated_artifacts() -> Mapping[Path, str]:
    """Return every generated documentation artifact and its canonical content."""
    return {
        _OUTPUT_DIRECTORY / "survey-scribe-config.schema.json": _json_document(
            SurveyScribeConfig.model_json_schema(mode="serialization")
        ),
        _OUTPUT_DIRECTORY / "svis.schema.json": _json_document(SurveySVIS.model_json_schema()),
        _OUTPUT_DIRECTORY / "questionnaire-routing.schema.json": canonical_routing_schema_json(),
    }


def _check(artifacts: Mapping[Path, str]) -> int:
    drifted = tuple(
        path
        for path, expected in artifacts.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != expected
    )
    if drifted:
        for path in drifted:
            sys.stderr.write(f"generated documentation drift: {path.relative_to(_ROOT)}\n")
        return 1
    sys.stdout.write(f"generated documentation is current: {len(artifacts)} artifacts\n")
    return 0


def _write(artifacts: Mapping[Path, str]) -> int:
    _OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for path, content in artifacts.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    sys.stdout.write(f"generated documentation artifacts: {len(artifacts)}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Generate references, or fail when committed references have drifted."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    action: Callable[[Mapping[Path, str]], int] = _check if args.check else _write
    return action(generated_artifacts())


if __name__ == "__main__":
    raise SystemExit(main())
