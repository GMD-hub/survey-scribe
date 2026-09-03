"""Routed artifact v2 publication, recovery, and privacy contracts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest

from survey_scribe.config import RoutingConfig, SurveyScribeConfig
from survey_scribe.errors import ArtifactCollisionError, ArtifactWriteError
from survey_scribe.models import (
    DataType,
    QuestionnaireRoutingGraph,
    RoutedAnswerCategory,
    RoutedNumericRange,
    RoutedSurveySVIS,
    RoutedSurveyVariable,
    RoutingAudit,
    RoutingNode,
    RoutingSourceBinding,
    StudyType,
    SurveySVIS,
    SurveyVariable,
    UnitLevel,
)
from survey_scribe.results import (
    ArtifactKind,
    ArtifactProvenance,
    Diagnostic,
    ExtractionResult,
    FailedBlock,
    PromptArtifactProvenance,
)
from survey_scribe.routing import Containment, EvidenceOrigin, NodeKind
from survey_scribe.serialization import artifacts
from survey_scribe.serialization import routing as routing_serialization
from survey_scribe.serialization.legacy import legacy_json_bytes
from survey_scribe.serialization.routing import (
    ArtifactManifestV1,
    ArtifactManifestV2,
    RoutedSurveySVISArtifactSerializer,
    parse_artifact_manifest,
)

SURVEY_ID = "TST_2026_ROUTE"
SOURCE_SHA256 = "a" * 64
RESPONSE_SHA256 = "b" * 64
PROMPT_SHA256 = "c" * 64

_PRIVATE_VALUES = (
    "Private synthetic survey prose",
    "Private variable label",
    "What is the private response?",
    "Only private respondents",
    "If private response, continue",
    "Private module",
    "Private variable notes",
    "Private category label",
    "Private numeric notes",
    "Private extraction notes",
    "Private graph label",
    "Private reviewer response",
    "Private failed chunk",
    "Private native expression",
    "Private adapter failure",
    "Private nested exception",
)


def _routed_survey(*, graph_version: str = "1.0") -> RoutedSurveySVIS:
    binding = RoutingSourceBinding(
        survey_id=SURVEY_ID,
        source_name="private-questionnaire.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        snapshot_sha256=SOURCE_SHA256,
        source_conversion_schema_version="1.0",
    )
    audit = RoutingAudit(
        source_binding=binding,
        inventory=(),
        source_spans=(),
        evidence=(),
        candidate_edges=(),
        discrepancies=(),
        review_decisions=(),
    )
    node = RoutingNode(
        node_id="entry:start",
        kind=NodeKind.entry,
        source_item_id=None,
        raw_name=None,
        label=_PRIVATE_VALUES[10],
        terminal_kind=None,
        activation_condition=None,
        repeat_spec=None,
        containment=Containment(
            parent_node_id=None,
            child_node_ids=(),
            entry_child_node_id=None,
        ),
        next_node_ids=(),
        previous_node_ids=(),
        outgoing_edge_ids=(),
        incoming_edge_ids=(),
    )
    graph_values = {
        "schema_version": graph_version,
        "entry_node_ids": ("entry:start",),
        "nodes": (node,),
        "edges": (),
        "loops": (),
        "diagnostics": (),
        "routing_audit": audit,
    }
    graph = (
        QuestionnaireRoutingGraph(**graph_values)  # type: ignore[arg-type]
        if graph_version == "1.0"
        else QuestionnaireRoutingGraph.model_construct(**graph_values)
    )
    return RoutedSurveySVIS(
        survey_id=SURVEY_ID,
        country_code="TST",
        year=2026,
        survey_name=_PRIVATE_VALUES[0],
        study_type=StudyType.lsms,
        data_collection_mode="CAPI",
        language="en",
        variables=(
            RoutedSurveyVariable(
                raw_name="private_q1",
                label=_PRIVATE_VALUES[1],
                question_text=_PRIVATE_VALUES[2],
                data_type=DataType.categorical_single,
                categories=(
                    RoutedAnswerCategory(
                        code="private-code",
                        label=_PRIVATE_VALUES[7],
                        is_missing=False,
                    ),
                ),
                numeric_range=RoutedNumericRange(
                    min_value=0.0,
                    max_value=9.0,
                    notes=_PRIVATE_VALUES[8],
                ),
                universe=_PRIVATE_VALUES[3],
                skip_condition_raw=_PRIVATE_VALUES[4],
                module=_PRIVATE_VALUES[5],
                unit_of_analysis=UnitLevel.household,
                source_page=0,
                extraction_confidence=1.0,
                needs_review=False,
                notes=_PRIVATE_VALUES[6],
                routing_node_id=None,
            ),
        ),
        source_file="private-questionnaire.xlsx",
        source_format="xlsx",
        extraction_date=date(2026, 9, 1),
        extraction_notes=_PRIVATE_VALUES[9],
        routing_schema_version="1.0",
        routing_graph=graph,
    )


def _provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        source_sha256=(SOURCE_SHA256,),
        model_response_sha256=(RESPONSE_SHA256,),
        prompt_versions=(
            PromptArtifactProvenance(
                pass_kind="forward",
                version="1.0.0",
                prompt_sha256=PROMPT_SHA256,
            ),
        ),
    )


def _routed_result(
    run_id: str = "run-routed",
    *,
    adversarial_operational_prose: bool = False,
) -> ExtractionResult[RoutedSurveySVIS]:
    diagnostics: tuple[Diagnostic, ...] = ()
    failed_blocks: tuple[FailedBlock, ...] = ()
    if adversarial_operational_prose:
        diagnostics = (
            Diagnostic(
                code="ROUTING_REVIEW_FAILED",
                message=f"{_PRIVATE_VALUES[11]} {_PRIVATE_VALUES[13]}",
                details={"native": _PRIVATE_VALUES[12]},
            ),
        )
        failed_blocks = (FailedBlock(block_id="private-block", message=_PRIVATE_VALUES[11]),)
    return ExtractionResult(
        output=_routed_survey(),
        run_id=run_id,
        diagnostics=diagnostics,
        failed_blocks=failed_blocks,
        artifact_provenance=_provenance(),
    )


def _active_pointer(output_dir: Path) -> Path:
    pointers = list((output_dir / ".survey-scribe" / "surveys").glob("*/active.json"))
    assert len(pointers) == 1
    return pointers[0]


def _active_generation(output_dir: Path) -> tuple[dict[str, object], Path]:
    pointer_path = _active_pointer(output_dir)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    return pointer, pointer_path.parent / str(pointer["path"])


def test_routed_write_round_trips_main_exact_projection_sidecar_and_manifest_v2(
    tmp_path: Path,
) -> None:
    original = _routed_result()

    written = original.write(tmp_path)

    pointer, generation = _active_generation(tmp_path)
    routed_main = generation / f"{SURVEY_ID}_routed_svis.json"
    generation_projection = generation / f"{SURVEY_ID}_svis.json"
    stable_projection = tmp_path / f"{SURVEY_ID}_svis.json"
    sidecar = generation / f"{SURVEY_ID}_sidecar.json"
    manifest = parse_artifact_manifest((generation / "manifest.json").read_bytes())

    assert isinstance(manifest, ArtifactManifestV2)
    assert RoutedSurveySVIS.model_validate_json(routed_main.read_bytes()) == original.output
    assert original.output is not None
    expected_projection = original.output.to_survey_svis()
    assert SurveySVIS.model_validate_json(generation_projection.read_bytes()) == expected_projection
    assert generation_projection.read_bytes() == legacy_json_bytes(expected_projection)
    assert stable_projection.read_bytes() == generation_projection.read_bytes()
    assert manifest.routing_schema_version == "1.0"
    assert manifest.graph_schema_version == "1.0"
    assert manifest.routed_main_sha256 == hashlib.sha256(routed_main.read_bytes()).hexdigest()
    assert (
        manifest.legacy_projection_sha256
        == hashlib.sha256(generation_projection.read_bytes()).hexdigest()
    )
    assert manifest.source_sha256 == (SOURCE_SHA256,)
    assert manifest.model_response_sha256 == (RESPONSE_SHA256,)
    assert manifest.prompt_versions[0].version == "1.0.0"
    assert manifest.prompt_versions[0].prompt_sha256 == PROMPT_SHA256
    assert (
        pointer["manifest_sha256"]
        == hashlib.sha256((generation / "manifest.json").read_bytes()).hexdigest()
    )
    assert {reference.kind for reference in written.artifacts} >= {
        ArtifactKind.main,
        ArtifactKind.projection,
        ArtifactKind.legacy,
        ArtifactKind.sidecar,
        ArtifactKind.manifest,
        ArtifactKind.active_pointer,
    }

    sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar_payload["schema_version"] == 2
    assert sidecar_payload["routing_schema_version"] == "1.0"
    assert sidecar_payload["graph_schema_version"] == "1.0"
    assert sidecar_payload["source_sha256"] == [SOURCE_SHA256]
    assert sidecar_payload["model_response_sha256"] == [RESPONSE_SHA256]
    assert "diagnostics" not in sidecar_payload
    assert "failed_blocks" not in sidecar_payload


def test_routed_projection_preserves_exact_v1_keys_types_defaults_enums_and_order() -> None:
    routed = _routed_survey()
    projection = routed.to_survey_svis()
    payload = json.loads(legacy_json_bytes(projection), object_pairs_hook=dict)

    assert list(payload) == list(SurveySVIS.model_fields)
    assert list(payload["variables"][0]) == list(SurveyVariable.model_fields)
    assert payload["study_type"] == "lsms"
    assert payload["variables"][0]["unit_of_analysis"] == "household"
    assert payload["variables"][0]["needs_review"] is False
    assert payload["variables"][0]["source_page"] == 0
    assert isinstance(payload["variables"][0]["extraction_confidence"], float)
    assert "routing_node_id" not in payload["variables"][0]
    assert "routing_schema_version" not in payload
    assert "routing_graph" not in payload


def test_legacy_write_bytes_and_manifest_v1_parser_remain_unchanged(tmp_path: Path) -> None:
    projection = _routed_survey().to_survey_svis()

    written = ExtractionResult(output=projection, run_id="legacy-run").write(tmp_path)

    _, generation = _active_generation(tmp_path)
    main = generation / f"{SURVEY_ID}_svis.json"
    manifest = parse_artifact_manifest((generation / "manifest.json").read_bytes())
    assert isinstance(manifest, ArtifactManifestV1)
    assert main.read_bytes() == legacy_json_bytes(projection)
    assert (tmp_path / f"{SURVEY_ID}_svis.json").read_bytes() == main.read_bytes()
    assert manifest.schema_version == 1
    assert not hasattr(manifest, "routing_schema_version")
    assert next(item for item in written.artifacts if item.kind == ArtifactKind.main).path == main


def test_manifest_parser_rejects_unknown_versions_mismatch_and_prose_with_safe_error(
    tmp_path: Path,
) -> None:
    _routed_result().write(tmp_path)
    _, generation = _active_generation(tmp_path)
    payload = json.loads((generation / "manifest.json").read_text(encoding="utf-8"))

    variants = []
    unknown = dict(payload)
    unknown["schema_version"] = 3
    variants.append(unknown)
    mismatch = dict(payload)
    mismatch["graph_schema_version"] = "2.0"
    variants.append(mismatch)
    prose = dict(payload)
    prose["reviewer_response"] = _PRIVATE_VALUES[11]
    variants.append(prose)

    for invalid in variants:
        with pytest.raises(ArtifactWriteError, match="Artifact manifest is invalid") as error:
            parse_artifact_manifest(json.dumps(invalid))
        assert _PRIVATE_VALUES[11] not in str(error.value)


def test_routed_serializer_revalidates_a_detached_frozen_graph_with_fixed_safe_error() -> None:
    valid = _routed_survey()
    invalid_graph = QuestionnaireRoutingGraph.model_construct(
        **{
            **valid.routing_graph.__dict__,
            "schema_version": "2.0",
        }
    )
    invalid = RoutedSurveySVIS.model_construct(
        **{
            **valid.__dict__,
            "routing_graph": invalid_graph,
        }
    )

    with pytest.raises(ArtifactWriteError, match="Routed artifact validation failed") as error:
        RoutedSurveySVISArtifactSerializer(provenance=_provenance()).build_plan(
            invalid,
            survey_id=SURVEY_ID,
        )

    rendered = str(error.value)
    assert _PRIVATE_VALUES[0] not in rendered
    assert _PRIVATE_VALUES[10] not in rendered


def test_routed_serializer_rejects_wrong_type_identity_and_encoding_with_safe_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serializer = RoutedSurveySVISArtifactSerializer(provenance=_provenance())
    with pytest.raises(ArtifactWriteError, match="exact routed output type"):
        serializer.build_plan(cast(RoutedSurveySVIS, object()), survey_id=SURVEY_ID)
    with pytest.raises(ArtifactWriteError, match="identity"):
        serializer.build_plan(_routed_survey(), survey_id="OTHER_SURVEY")

    def reject_encoding(_value: object) -> bytes:
        raise ValueError(_PRIVATE_VALUES[14])

    monkeypatch.setattr(routing_serialization, "legacy_json_bytes", reject_encoding)
    with pytest.raises(ArtifactWriteError, match="serialization failed") as error:
        serializer.build_plan(_routed_survey(), survey_id=SURVEY_ID)
    assert _PRIVATE_VALUES[14] not in str(error.value)


def test_native_routed_serializer_derives_source_only_provenance() -> None:
    plan = RoutedSurveySVISArtifactSerializer().build_plan(
        _routed_survey(),
        survey_id=SURVEY_ID,
    )

    assert plan.routed_metadata is not None
    assert plan.routed_metadata.source_sha256 == (SOURCE_SHA256,)
    assert plan.routed_metadata.model_response_sha256 == ()
    assert plan.routed_metadata.prompt_versions == ()


def test_routed_serializer_fails_closed_for_missing_or_mismatched_model_provenance() -> None:
    model_record = SimpleNamespace(
        observation=SimpleNamespace(origin=EvidenceOrigin.forward_extraction)
    )
    audit = SimpleNamespace(
        source_binding=SimpleNamespace(snapshot_sha256=SOURCE_SHA256),
        evidence=(model_record,),
        review_decisions=(),
    )
    snapshot = cast(
        RoutedSurveySVIS,
        SimpleNamespace(routing_graph=SimpleNamespace(routing_audit=audit)),
    )

    with pytest.raises(ArtifactWriteError, match="provenance is required"):
        RoutedSurveySVISArtifactSerializer()._validated_provenance(snapshot)
    with pytest.raises(ArtifactWriteError, match="incomplete"):
        RoutedSurveySVISArtifactSerializer(
            provenance=ArtifactProvenance(
                source_sha256=(SOURCE_SHA256,),
                model_response_sha256=(),
                prompt_versions=(),
            )
        )._validated_provenance(snapshot)
    with pytest.raises(ArtifactWriteError, match="source provenance"):
        RoutedSurveySVISArtifactSerializer(
            provenance=ArtifactProvenance(
                source_sha256=("d" * 64,),
                model_response_sha256=(RESPONSE_SHA256,),
                prompt_versions=_provenance().prompt_versions,
            )
        ).build_plan(_routed_survey(), survey_id=SURVEY_ID)
    invalid = ArtifactProvenance.model_construct(
        source_sha256=(_PRIVATE_VALUES[11],),
        model_response_sha256=(),
        prompt_versions=(),
    )
    with pytest.raises(ArtifactWriteError, match="provenance is invalid") as error:
        RoutedSurveySVISArtifactSerializer(provenance=invalid).build_plan(
            _routed_survey(),
            survey_id=SURVEY_ID,
        )
    assert _PRIVATE_VALUES[11] not in str(error.value)


def test_routed_serializer_validates_reviewer_prompt_and_response_digests() -> None:
    decision = SimpleNamespace(
        prompt_version="1.0.0",
        prompt_sha256=PROMPT_SHA256,
        provider_response_sha256=RESPONSE_SHA256,
    )
    audit = SimpleNamespace(
        source_binding=SimpleNamespace(snapshot_sha256=SOURCE_SHA256),
        evidence=(),
        review_decisions=(decision,),
    )
    snapshot = cast(
        RoutedSurveySVIS,
        SimpleNamespace(routing_graph=SimpleNamespace(routing_audit=audit)),
    )
    mismatched = _provenance()
    with pytest.raises(ArtifactWriteError, match="review provenance"):
        RoutedSurveySVISArtifactSerializer(provenance=mismatched)._validated_provenance(snapshot)

    reviewer = ArtifactProvenance(
        source_sha256=(SOURCE_SHA256,),
        model_response_sha256=(RESPONSE_SHA256,),
        prompt_versions=(
            PromptArtifactProvenance(
                pass_kind="reviewer",
                version="1.0.0",
                prompt_sha256=PROMPT_SHA256,
            ),
        ),
    )
    assert (
        RoutedSurveySVISArtifactSerializer(provenance=reviewer)._validated_provenance(snapshot)
        == reviewer
    )


def test_routed_sidecar_manifest_and_errors_exclude_all_adversarial_prose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = _routed_result(adversarial_operational_prose=True).write(tmp_path)
    _, generation = _active_generation(tmp_path)
    operational = (generation / f"{SURVEY_ID}_sidecar.json").read_text(encoding="utf-8") + (
        generation / "manifest.json"
    ).read_text(encoding="utf-8")
    for private in _PRIVATE_VALUES:
        assert private not in operational

    original_atomic_write = artifacts._atomic_write_bytes
    failed = False

    def fail_projection(path: Path, content: bytes) -> None:
        nonlocal failed
        if path == tmp_path / f"{SURVEY_ID}_svis.json" and not failed:
            failed = True
            try:
                raise ValueError(_PRIVATE_VALUES[14])
            except ValueError as cause:
                raise RuntimeError(
                    f"{_PRIVATE_VALUES[0]} {_PRIVATE_VALUES[11]} {_PRIVATE_VALUES[12]}"
                ) from cause
        original_atomic_write(path, content)

    monkeypatch.setattr(artifacts, "_atomic_write_bytes", fail_projection)
    with pytest.raises(ArtifactWriteError) as error:
        _routed_result(run_id="replacement").write(tmp_path, overwrite=True)
    for private in _PRIVATE_VALUES:
        assert private not in str(error.value)
    assert written.output is not None


def test_routed_collision_overwrite_and_concurrent_same_survey_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _routed_result(run_id="first").write(tmp_path)
    with pytest.raises(ArtifactCollisionError):
        _routed_result(run_id="collision").write(tmp_path)
    second = _routed_result(run_id="second").write(tmp_path, overwrite=True)
    assert first.artifacts != second.artifacts

    other = tmp_path / "concurrent"
    entered = Event()
    release = Event()
    original_write_generation = artifacts._write_generation

    def slow_write_generation(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(timeout=10)
        return original_write_generation(*args, **kwargs)

    monkeypatch.setattr(artifacts, "_write_generation", slow_write_generation)
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(_routed_result(run_id="owner").write, other)
        assert entered.wait(timeout=10)
        contender = executor.submit(_routed_result(run_id="contender").write, other)
        with pytest.raises(ArtifactCollisionError):
            contender.result(timeout=10)
        release.set()
        assert owner.result(timeout=10).artifacts


_ROUTED_CHILD_PROGRAM = r"""
import os
import sys
from datetime import date
from pathlib import Path

from survey_scribe.models import (
    DataType,
    QuestionnaireRoutingGraph,
    RoutedSurveySVIS,
    RoutedSurveyVariable,
    RoutingAudit,
    RoutingNode,
    RoutingSourceBinding,
)
from survey_scribe.results import (
    ArtifactProvenance,
    ExtractionResult,
    PromptArtifactProvenance,
)
from survey_scribe.routing import Containment, NodeKind
from survey_scribe.serialization import artifacts

output_dir = Path(sys.argv[1])
run_id = sys.argv[2]
checkpoint = sys.argv[3]
survey_id = "TST_2026_ROUTE"
binding = RoutingSourceBinding(
    survey_id=survey_id,
    source_name="source.txt",
    media_type="text/plain",
    snapshot_sha256="a" * 64,
    source_conversion_schema_version="1.0",
)
audit = RoutingAudit(
    source_binding=binding,
    inventory=(),
    source_spans=(),
    evidence=(),
    candidate_edges=(),
    discrepancies=(),
    review_decisions=(),
)
node = RoutingNode(
    node_id="entry:start",
    kind=NodeKind.entry,
    source_item_id=None,
    raw_name=None,
    label="Entry",
    terminal_kind=None,
    activation_condition=None,
    repeat_spec=None,
    containment=Containment(
        parent_node_id=None,
        child_node_ids=(),
        entry_child_node_id=None,
    ),
    next_node_ids=(),
    previous_node_ids=(),
    outgoing_edge_ids=(),
    incoming_edge_ids=(),
)
graph = QuestionnaireRoutingGraph(
    schema_version="1.0",
    entry_node_ids=("entry:start",),
    nodes=(node,),
    edges=(),
    loops=(),
    diagnostics=(),
    routing_audit=audit,
)
survey = RoutedSurveySVIS(
    survey_id=survey_id,
    country_code="TST",
    year=2026,
    survey_name=f"Synthetic {run_id}",
    variables=(
        RoutedSurveyVariable(
            raw_name="q1",
            data_type=DataType.text,
            extraction_confidence=1.0,
            routing_node_id=None,
        ),
    ),
    source_file="source.txt",
    source_format="txt",
    extraction_date=date(2026, 9, 1),
    routing_schema_version="1.0",
    routing_graph=graph,
)
provenance = ArtifactProvenance(
    source_sha256=("a" * 64,),
    model_response_sha256=("b" * 64,),
    prompt_versions=(
        PromptArtifactProvenance(
            pass_kind="forward",
            version="1.0.0",
            prompt_sha256="c" * 64,
        ),
    ),
)

def stop_at(stage):
    if stage == checkpoint:
        os._exit(86)

artifacts._publication_checkpoint = stop_at
ExtractionResult(
    output=survey,
    run_id=run_id,
    artifact_provenance=provenance,
).write(output_dir, overwrite=True)
"""


@pytest.mark.parametrize(
    ("checkpoint", "expected_run_id"),
    [
        ("after_generation_commit", "prior"),
        ("after_projection", "replacement"),
        ("after_pointer", "replacement"),
    ],
)
def test_routed_hard_exit_recovers_main_projection_and_pointer_consistently(
    tmp_path: Path,
    checkpoint: str,
    expected_run_id: str,
) -> None:
    _routed_result(run_id="prior").write(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _ROUTED_CHILD_PROGRAM,
            str(tmp_path),
            "replacement",
            checkpoint,
        ],
        check=False,
        text=True,
    )
    assert completed.returncode == 86

    with pytest.raises(ArtifactCollisionError):
        _routed_result(run_id="recovery-probe").write(tmp_path)
    pointer, generation = _active_generation(tmp_path)
    manifest = parse_artifact_manifest((generation / "manifest.json").read_bytes())
    assert isinstance(manifest, ArtifactManifestV2)
    projection = generation / f"{SURVEY_ID}_svis.json"
    assert (tmp_path / f"{SURVEY_ID}_svis.json").read_bytes() == projection.read_bytes()
    assert (
        RoutedSurveySVIS.model_validate_json(
            (generation / f"{SURVEY_ID}_routed_svis.json").read_bytes()
        ).routing_schema_version
        == "1.0"
    )
    assert pointer["run_id"] == expected_run_id
    assert not (_active_pointer(tmp_path).parent / "transaction").exists()


def test_routing_configuration_is_nested_strict_and_has_no_provider_or_credentials() -> None:
    config = SurveyScribeConfig(
        routing={
            "max_request_tokens": 8_000,
            "max_inventory_items_per_call": 100,
            "low_confidence_threshold": 0.8,
        }
    )

    assert isinstance(config.routing, RoutingConfig)
    assert config.routing.max_request_tokens == 8_000
    assert config.routing.max_inventory_items_per_call == 100
    assert config.routing.low_confidence_threshold == 0.8
    assert config.routing.max_source_quote_chars == 2_000
    assert set(RoutingConfig.model_fields).isdisjoint(
        {"provider", "model", "api_key", "bearer_token", "token_callback"}
    )
    assert "api_key" not in config.routing.model_dump(mode="json")


@pytest.mark.parametrize(
    "value",
    [
        {"max_request_tokens": "8000"},
        {"max_condition_depth": 7},
        {"low_confidence_threshold": float("nan")},
        {"provider": "implicit-provider"},
        {"api_key": "private-key"},
    ],
)
def test_nested_routing_configuration_rejects_invalid_or_provider_values(
    value: dict[str, object],
) -> None:
    with pytest.raises(Exception) as error:
        SurveyScribeConfig(routing=value)
    assert "private-key" not in str(error.value)
    assert "implicit-provider" not in str(error.value)


def test_import_and_help_need_no_optional_sdk_or_credentials(repository_root: Path) -> None:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.endswith(("_API_KEY", "_TOKEN")) or name.startswith("AZURE_OPENAI_"):
            environment.pop(name, None)
    program = """
import sys
import survey_scribe
from survey_scribe.cli import main
from survey_scribe.routing import QuestionnaireRouter
assert QuestionnaireRouter is survey_scribe.QuestionnaireRouter
assert set(sys.modules).isdisjoint({'openai', 'instructor', 'anthropic', 'docling', 'openpyxl'})
try:
    main(['--help'])
except SystemExit as error:
    assert error.code == 0
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "survey-scribe" in completed.stdout
