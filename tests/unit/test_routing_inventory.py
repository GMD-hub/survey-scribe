"""Deterministic logical questionnaire inventory construction tests."""

from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from survey_scribe.models.svis import DataType, SurveySVIS, SurveyVariable
from survey_scribe.routing.contracts import NodeKind
from survey_scribe.routing.inventory import (
    InventoryBuildError,
    InventoryBuildResult,
    InventoryDiagnostic,
    InventoryItemExtraction,
    build_inventory,
)
from survey_scribe.sources.base import (
    SourceBlock,
    SourceDocument,
    SourceProvenance,
    SourceTable,
    render_table,
)


def _variable(raw_name: str, question_text: str) -> SurveyVariable:
    return SurveyVariable(
        raw_name=raw_name,
        question_text=question_text,
        data_type=DataType.numeric,
        extraction_confidence=1.0,
    )


def _svis(*variables: SurveyVariable) -> SurveySVIS:
    return SurveySVIS(
        survey_id="TST_2024_SYNTH",
        country_code="TST",
        year=2024,
        survey_name="Synthetic survey",
        variables=list(variables),
        source_file="questionnaire.txt",
        source_format="txt",
        extraction_date=date(2024, 6, 1),
    )


def _document(*texts: str, digest: str = "a" * 64) -> SourceDocument:
    provenance = SourceProvenance(source_name="questionnaire.txt", page=1)
    return SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=tuple(
            SourceBlock(
                id=f"block-{index}",
                order=index,
                kind="text",
                text=text,
                provenance=provenance,
            )
            for index, text in enumerate(texts)
        ),
        snapshot_sha256=digest,
    )


def _item(
    local_id: str,
    *,
    source_order: int,
    source_text: str,
    kind: NodeKind = NodeKind.question,
    source_item_id: str | None = None,
    raw_reference: str | None = None,
    section_path: tuple[str, ...] = ("Roster",),
    parent_local_id: str | None = None,
    repeat_group_local_id: str | None = None,
    is_entry: bool = False,
    linked_variable_indices: tuple[int, ...] = (),
    suggested_node_id: str | None = None,
) -> InventoryItemExtraction:
    return InventoryItemExtraction(
        local_id=local_id,
        source_item_id=source_item_id,
        raw_reference=raw_reference or source_item_id or local_id,
        section_path=section_path,
        source_order=source_order,
        block_ids=(f"block-{source_order}",),
        kind=kind,
        parent_local_id=parent_local_id,
        repeat_group_local_id=repeat_group_local_id,
        is_entry=is_entry,
        linked_variable_indices=linked_variable_indices,
        source_text=source_text,
        suggested_node_id=suggested_node_id,
    )


def _complete_case() -> tuple[SourceDocument, SurveySVIS, tuple[InventoryItemExtraction, ...]]:
    document = _document(
        "SECTION Roster",
        "REPEAT Household members",
        "Q1. What are the member's given and family names?",
        "Q2. How old is the member?",
    )
    svis = _svis(
        _variable("given_name", "What is the member's given name?"),
        _variable("family_name", "What is the member's family name?"),
        _variable("age", "How old is the member?"),
        _variable("review_note", "Enumerator review note"),
    )
    items = (
        _item(
            "section",
            source_order=0,
            source_text="SECTION Roster",
            kind=NodeKind.section,
            raw_reference="Roster",
        ),
        _item(
            "repeat",
            source_order=1,
            source_text="REPEAT Household members",
            kind=NodeKind.repeat_group,
            raw_reference="Household members",
            parent_local_id="section",
            is_entry=True,
        ),
        _item(
            "q1",
            source_order=2,
            source_text="Q1. What are the member's given and family names?",
            source_item_id="Q1",
            parent_local_id="repeat",
            repeat_group_local_id="repeat",
            is_entry=True,
            linked_variable_indices=(0, 1),
            suggested_node_id="model-final-id-must-be-ignored",
        ),
        _item(
            "q2",
            source_order=3,
            source_text="Q2. How old is the member?",
            source_item_id="Q2",
            parent_local_id="repeat",
            repeat_group_local_id="repeat",
            linked_variable_indices=(2,),
        ),
    )
    return document, svis, items


def test_build_inventory_preserves_complete_logical_records_and_variable_links() -> None:
    document, svis, extracted = _complete_case()

    result = build_inventory(document, svis, extracted)

    assert [item.source_order for item in result.items] == [0, 1, 2, 3]
    assert [item.source_item_id for item in result.items] == [None, None, "Q1", "Q2"]
    assert [item.raw_reference for item in result.items] == [
        "Roster",
        "Household members",
        "Q1",
        "Q2",
    ]
    assert all(item.section_path == ("Roster",) for item in result.items)
    assert [item.block_ids for item in result.items] == [
        ("block-0",),
        ("block-1",),
        ("block-2",),
        ("block-3",),
    ]
    section, repeat, q1, q2 = result.items
    assert repeat.parent_node_id == section.node_id
    assert q1.parent_node_id == repeat.node_id
    assert q2.repeat_group_node_id == repeat.node_id
    assert result.group_entries == (
        (section.node_id, repeat.node_id),
        (repeat.node_id, q1.node_id),
    )
    assert q1.linked_variable_indices == (0, 1)
    assert result.variable_node_ids == (q1.node_id, q1.node_id, q2.node_id, None)
    assert result.partial is True
    assert [(item.code, item.variable_index) for item in result.diagnostics] == [
        ("UNLINKED_VARIABLE", 3)
    ]
    assert all("model-final-id" not in item.node_id for item in result.items)
    assert result.source_binding.snapshot_sha256 == document.snapshot_sha256


def test_build_inventory_is_reproducible_and_scopes_fallbacks_to_source_version() -> None:
    document, svis, extracted = _complete_case()

    first = build_inventory(document, svis, tuple(reversed(extracted)))
    second = build_inventory(document, svis, extracted)
    changed = build_inventory(
        document.model_copy(update={"snapshot_sha256": "b" * 64}),
        svis,
        extracted,
    )

    assert first == second
    assert first.items[2].node_id == changed.items[2].node_id
    assert first.items[0].node_id != changed.items[0].node_id
    assert first.items[1].node_id != changed.items[1].node_id


def test_reordered_normalized_blocks_preserve_logical_order_and_change_fallback_version() -> None:
    document = _document("First unprinted question", "Second unprinted question")
    svis = _svis()
    extracted = (
        _item("first", source_order=0, source_text="First unprinted question"),
        _item("second", source_order=1, source_text="Second unprinted question"),
    )
    original = build_inventory(document, svis, extracted)
    reordered = _document(
        "Second unprinted question",
        "First unprinted question",
        digest="b" * 64,
    )
    reordered_extracted = (
        extracted[0].model_copy(update={"source_order": 1, "block_ids": ("block-1",)}),
        extracted[1].model_copy(update={"source_order": 0, "block_ids": ("block-0",)}),
    )

    changed = build_inventory(reordered, svis, reordered_extracted)

    assert [item.raw_reference for item in changed.items] == ["second", "first"]
    assert tuple(item.node_id for item in changed.items) != tuple(
        item.node_id for item in original.items
    )


def test_repeated_table_inventory_keeps_one_logical_template() -> None:
    provenance = SourceProvenance(
        source_name="questionnaire.txt",
        sheet="Consumption",
        row_start=1,
        row_end=2,
    )
    rows = (
        ("ITEM", "QUESTION"),
        ("F1", "Quantity consumed for [FOOD PRODUCT]"),
    )
    table = SourceTable(id="table-1", rows=rows, provenance=provenance)
    table_text = render_table(rows)
    document = SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="block-0",
                order=0,
                kind="table",
                text=table_text,
                provenance=provenance,
                table=table,
            ),
        ),
        snapshot_sha256="a" * 64,
    )
    svis = _svis(_variable("food_quantity", "Quantity consumed for one food product"))
    extracted = (
        InventoryItemExtraction(
            local_id="repeat",
            source_item_id=None,
            raw_reference="Food products",
            section_path=("Consumption",),
            source_order=0,
            block_ids=("block-0",),
            kind=NodeKind.repeat_group,
            parent_local_id=None,
            repeat_group_local_id=None,
            is_entry=False,
            linked_variable_indices=(),
            source_text="ITEM | QUESTION",
            suggested_node_id=None,
        ),
        InventoryItemExtraction(
            local_id="f1",
            source_item_id="F1",
            raw_reference="F1",
            section_path=("Consumption",),
            source_order=1,
            block_ids=("block-0",),
            kind=NodeKind.question,
            parent_local_id="repeat",
            repeat_group_local_id="repeat",
            is_entry=True,
            linked_variable_indices=(0,),
            source_text="F1 | Quantity consumed for [FOOD PRODUCT]",
            suggested_node_id="ignore-this-id",
        ),
    )

    result = build_inventory(document, svis, extracted)

    assert len(result.items) == 2
    assert result.items[1].node_id == "question:consumption:f1"
    assert result.items[1].repeat_group_node_id == result.items[0].node_id
    assert result.variable_node_ids == (result.items[1].node_id,)
    assert result.partial is False


def test_build_inventory_allows_many_variables_to_one_question_but_not_two_nodes_per_variable() -> (
    None
):
    document, svis, extracted = _complete_case()
    assert build_inventory(document, svis, extracted).items[2].linked_variable_indices == (0, 1)

    conflicting = list(extracted)
    conflicting[3] = conflicting[3].model_copy(update={"linked_variable_indices": (0, 2)})
    with pytest.raises(InventoryBuildError, match="one inventory item"):
        build_inventory(document, svis, conflicting)


def test_internal_inventory_extraction_rejects_duplicate_local_collections() -> None:
    item = _item("q1", source_order=0, source_text="Q1", source_item_id="Q1")
    values = item.model_dump(mode="json")
    values["block_ids"] = ["block-0", "block-0"]
    with pytest.raises(ValidationError, match="block identifiers"):
        InventoryItemExtraction.model_validate(values)
    values = item.model_dump(mode="json")
    values["linked_variable_indices"] = [0, 0]
    with pytest.raises(ValidationError, match="variable indices"):
        InventoryItemExtraction.model_validate(values)


def test_inventory_diagnostics_and_result_projection_fail_closed() -> None:
    with pytest.raises(ValidationError, match="unique"):
        InventoryDiagnostic(
            code="AMBIGUOUS_PRINTED_ID",
            message="Ambiguous.",
            variable_index=None,
            node_ids=("q1", "q1"),
        )
    with pytest.raises(ValidationError, match="variable index"):
        InventoryDiagnostic(
            code="UNLINKED_VARIABLE",
            message="Unlinked.",
            variable_index=None,
            node_ids=(),
        )

    document, svis, extracted = _complete_case()
    valid = build_inventory(document, svis, extracted).model_dump(mode="json")
    corruptions = []
    duplicate_items = json.loads(json.dumps(valid))
    duplicate_items["items"].append(duplicate_items["items"][0])
    corruptions.append(duplicate_items)
    unknown_variable = json.loads(json.dumps(valid))
    unknown_variable["variable_node_ids"][0] = "missing"
    corruptions.append(unknown_variable)
    unknown_entry = json.loads(json.dumps(valid))
    unknown_entry["group_entries"][0][0] = "missing"
    corruptions.append(unknown_entry)
    wrong_partial = json.loads(json.dumps(valid))
    wrong_partial["partial"] = False
    corruptions.append(wrong_partial)
    for corruption in corruptions:
        with pytest.raises(ValidationError):
            InventoryBuildResult.model_validate(corruption)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("invalid_block", "known source block"),
        ("quote_mismatch", "source text"),
        ("unknown_parent", "known local item"),
        ("parent_not_container", "section or repeat group"),
        ("cycle", "acyclic"),
        ("missing_entry", "exactly one entry"),
        ("duplicate_source_order", "source orders"),
        ("variable_out_of_range", "variable index"),
        ("duplicate_local_id", "local identifiers"),
        ("root_entry", "parent container"),
        ("unknown_repeat", "known local item"),
        ("nonrepeat_membership", "repeat group"),
        ("nonancestor_repeat", "ancestor repeat group"),
        ("nonquestion_link", "only question"),
    ],
)
def test_build_inventory_rejects_invalid_source_hierarchy_and_links(
    mutation: str,
    message: str,
) -> None:
    document, svis, original = _complete_case()
    extracted = list(original)
    if mutation == "invalid_block":
        extracted[2] = extracted[2].model_copy(update={"block_ids": ("missing",)})
    elif mutation == "quote_mismatch":
        extracted[2] = extracted[2].model_copy(update={"source_text": "invented question"})
    elif mutation == "unknown_parent":
        extracted[2] = extracted[2].model_copy(update={"parent_local_id": "missing"})
    elif mutation == "parent_not_container":
        extracted[3] = extracted[3].model_copy(update={"parent_local_id": "q1"})
    elif mutation == "cycle":
        extracted[0] = extracted[0].model_copy(update={"parent_local_id": "repeat"})
    elif mutation == "missing_entry":
        extracted[2] = extracted[2].model_copy(update={"is_entry": False})
    elif mutation == "duplicate_source_order":
        extracted[3] = extracted[3].model_copy(update={"source_order": 2})
    elif mutation == "variable_out_of_range":
        extracted[3] = extracted[3].model_copy(update={"linked_variable_indices": (10,)})
    elif mutation == "duplicate_local_id":
        extracted[3] = extracted[3].model_copy(update={"local_id": "q1"})
    elif mutation == "root_entry":
        extracted[0] = extracted[0].model_copy(update={"is_entry": True})
    elif mutation == "unknown_repeat":
        extracted[3] = extracted[3].model_copy(update={"repeat_group_local_id": "missing"})
    elif mutation == "nonrepeat_membership":
        extracted[3] = extracted[3].model_copy(update={"repeat_group_local_id": "section"})
    elif mutation == "nonancestor_repeat":
        extracted[3] = extracted[3].model_copy(
            update={"parent_local_id": "section", "repeat_group_local_id": "repeat"}
        )
    else:
        extracted[0] = extracted[0].model_copy(update={"linked_variable_indices": (0,)})

    with pytest.raises(InventoryBuildError, match=message):
        build_inventory(document, svis, extracted)


def test_inventory_rejects_empty_input_and_identity_digest_failure() -> None:
    document, svis, extracted = _complete_case()
    with pytest.raises(InventoryBuildError, match="at least one"):
        build_inventory(document, svis, ())
    with pytest.raises(InventoryBuildError, match="digest factory"):
        build_inventory(document, svis, extracted, digest_factory=lambda _payload: "invalid")


def test_duplicate_printed_ids_in_one_section_remain_distinct_and_review_visible() -> None:
    document = _document("Q1. First prompt", "Question 1. Second prompt")
    svis = _svis()
    extracted = (
        _item(
            "first",
            source_order=0,
            source_text="Q1. First prompt",
            source_item_id="Q1",
        ),
        _item(
            "second",
            source_order=1,
            source_text="Question 1. Second prompt",
            source_item_id="Question 1",
        ),
    )

    result = build_inventory(document, svis, extracted)

    assert result.items[0].node_id != result.items[1].node_id
    assert result.diagnostics[0].code == "AMBIGUOUS_PRINTED_ID"
    assert result.diagnostics[0].node_ids == tuple(item.node_id for item in result.items)
    assert result.partial is False


def test_expected_mechanics_fixture_is_exact_and_checksummed(repository_root: Path) -> None:
    manifest_path = repository_root / "tests/fixtures/routing_mechanics/manifest.toml"
    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)
    expected_path = repository_root / manifest["output"]["path"]
    payload = expected_path.read_bytes()

    assert manifest["artifact_kind"] == "deterministic-routing-mechanics"
    assert manifest["benchmark_eligible"] is False
    assert hashlib.sha256(payload).hexdigest() == manifest["output"]["sha256"]

    document, svis, extracted = _complete_case()
    actual = build_inventory(document, svis, extracted).model_dump(mode="json")
    assert actual == json.loads(payload)
