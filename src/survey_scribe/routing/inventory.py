"""Complete deterministic logical item inventory construction."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from survey_scribe.models.routing import InventoryItem, RoutingSourceBinding
from survey_scribe.models.svis import SurveySVIS
from survey_scribe.routing.contracts import NodeKind, NonEmptyStr, StrictRoutingModel
from survey_scribe.routing.identity import (
    SOURCE_CONVERSION_SCHEMA_VERSION,
    DigestFactory,
    NodeIdentityInput,
    assign_node_ids,
    create_source_binding,
    printed_identity_key,
)
from survey_scribe.sources.base import SourceDocument

NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
InventoryDiagnosticCode = Literal["AMBIGUOUS_PRINTED_ID", "UNLINKED_VARIABLE"]


class InventoryBuildError(ValueError):
    """The extracted logical items cannot form a complete safe inventory."""


class InventoryItemExtraction(StrictRoutingModel):
    """Internal item-extraction response with preserved printed identity."""

    local_id: NonEmptyStr
    source_item_id: NonEmptyStr | None
    raw_reference: NonEmptyStr
    section_path: tuple[NonEmptyStr, ...]
    source_order: NonNegativeInt
    block_ids: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    kind: NodeKind
    parent_local_id: NonEmptyStr | None
    repeat_group_local_id: NonEmptyStr | None
    is_entry: StrictBool = False
    linked_variable_indices: tuple[NonNegativeInt, ...] = ()
    source_text: NonEmptyStr
    suggested_node_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_local_collections(self) -> InventoryItemExtraction:
        if len(set(self.block_ids)) != len(self.block_ids):
            raise ValueError("inventory extraction block identifiers must be unique")
        if len(set(self.linked_variable_indices)) != len(self.linked_variable_indices):
            raise ValueError("inventory extraction variable indices must be unique")
        return self


class InventoryDiagnostic(StrictRoutingModel):
    """Safe deterministic inventory diagnostic without source-derived prose."""

    code: InventoryDiagnosticCode
    message: NonEmptyStr
    variable_index: NonNegativeInt | None
    node_ids: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_diagnostic_shape(self) -> InventoryDiagnostic:
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("inventory diagnostic node identifiers must be unique")
        if (self.code == "UNLINKED_VARIABLE") != (self.variable_index is not None):
            raise ValueError("only unlinked-variable diagnostics identify a variable index")
        return self


class InventoryBuildResult(StrictRoutingModel):
    """Stable inventory, containment entries, variable projection, and outcome."""

    source_binding: RoutingSourceBinding
    items: tuple[InventoryItem, ...]
    group_entries: tuple[tuple[NonEmptyStr, NonEmptyStr], ...]
    variable_node_ids: tuple[NonEmptyStr | None, ...]
    diagnostics: tuple[InventoryDiagnostic, ...]
    partial: StrictBool

    @model_validator(mode="after")
    def validate_result_projection(self) -> InventoryBuildResult:
        node_ids = {item.node_id for item in self.items}
        if len(node_ids) != len(self.items):
            raise ValueError("inventory result node identifiers must be unique")
        if any(
            node_id is not None and node_id not in node_ids for node_id in self.variable_node_ids
        ):
            raise ValueError("inventory variable projection must reference an inventory item")
        if any(
            parent not in node_ids or child not in node_ids for parent, child in self.group_entries
        ):
            raise ValueError("inventory group entries must reference inventory items")
        expected_partial = any(item.code == "UNLINKED_VARIABLE" for item in self.diagnostics)
        if self.partial is not expected_partial:
            raise ValueError("inventory partial status must match unlinked variable diagnostics")
        return self


def build_inventory(
    document: SourceDocument,
    svis: SurveySVIS,
    extracted_items: Iterable[InventoryItemExtraction],
    *,
    source_conversion_schema_version: str = SOURCE_CONVERSION_SCHEMA_VERSION,
    digest_factory: DigestFactory | None = None,
) -> InventoryBuildResult:
    """Build complete canonical inventory records from one validated source snapshot."""
    detached_svis = SurveySVIS.model_validate(svis.model_dump(mode="json"))
    source_binding = create_source_binding(
        document,
        detached_svis,
        source_conversion_schema_version=source_conversion_schema_version,
    )
    supplied = tuple(extracted_items)
    if not supplied:
        raise InventoryBuildError("logical inventory extraction must contain at least one item")
    ordered = tuple(sorted(supplied, key=lambda item: item.source_order))
    _validate_unique_inputs(ordered)
    _validate_source_references(ordered, document)
    by_local_id = {item.local_id: item for item in ordered}
    _validate_hierarchy(ordered, by_local_id)

    identities = tuple(
        NodeIdentityInput(
            source_item_id=item.source_item_id,
            raw_reference=item.raw_reference,
            section_path=item.section_path,
            logical_ordinal=ordinal,
            normalized_source_text=item.source_text,
            kind=item.kind,
        )
        for ordinal, item in enumerate(ordered, start=1)
    )
    identity_kwargs = {}
    if digest_factory is not None:
        identity_kwargs["digest_factory"] = digest_factory
    try:
        node_ids = assign_node_ids(
            identities,
            survey_id=detached_svis.survey_id,
            source_version_digest=source_binding.snapshot_sha256,
            **identity_kwargs,
        )
    except ValueError as error:
        raise InventoryBuildError(str(error)) from error
    node_id_by_local_id = dict(zip((item.local_id for item in ordered), node_ids, strict=True))

    inventory = tuple(
        InventoryItem(
            node_id=node_id,
            source_item_id=item.source_item_id,
            raw_reference=item.raw_reference,
            section_path=item.section_path,
            source_order=item.source_order,
            block_ids=item.block_ids,
            kind=item.kind,
            repeat_group_node_id=(
                node_id_by_local_id[item.repeat_group_local_id]
                if item.repeat_group_local_id is not None
                else None
            ),
            parent_node_id=(
                node_id_by_local_id[item.parent_local_id]
                if item.parent_local_id is not None
                else None
            ),
            linked_variable_indices=item.linked_variable_indices,
        )
        for item, node_id in zip(ordered, node_ids, strict=True)
    )

    diagnostics = _printed_identity_diagnostics(ordered, inventory)
    variable_node_ids: list[str | None] = [None] * len(detached_svis.variables)
    for item, inventory_item in zip(ordered, inventory, strict=True):
        if item.linked_variable_indices and item.kind is not NodeKind.question:
            raise InventoryBuildError("only question items can link to SVIS variables")
        for variable_index in item.linked_variable_indices:
            if variable_index >= len(variable_node_ids):
                raise InventoryBuildError("inventory variable index is outside the supplied SVIS")
            if variable_node_ids[variable_index] is not None:
                raise InventoryBuildError(
                    "one variable index cannot link to more than one inventory item"
                )
            variable_node_ids[variable_index] = inventory_item.node_id
    for variable_index, node_id in enumerate(variable_node_ids):
        if node_id is None:
            diagnostics.append(
                InventoryDiagnostic(
                    code="UNLINKED_VARIABLE",
                    message="A legacy variable has no exact logical question link.",
                    variable_index=variable_index,
                    node_ids=(),
                )
            )

    group_entries = tuple(
        (
            node_id_by_local_id[item.parent_local_id],
            node_id_by_local_id[item.local_id],
        )
        for item in ordered
        if item.is_entry and item.parent_local_id is not None
    )
    return InventoryBuildResult(
        source_binding=source_binding,
        items=inventory,
        group_entries=group_entries,
        variable_node_ids=tuple(variable_node_ids),
        diagnostics=tuple(diagnostics),
        partial=any(item.code == "UNLINKED_VARIABLE" for item in diagnostics),
    )


def _validate_unique_inputs(items: tuple[InventoryItemExtraction, ...]) -> None:
    if len({item.local_id for item in items}) != len(items):
        raise InventoryBuildError("inventory local identifiers must be unique")
    if len({item.source_order for item in items}) != len(items):
        raise InventoryBuildError("inventory source orders must be unique")


def _validate_source_references(
    items: tuple[InventoryItemExtraction, ...],
    document: SourceDocument,
) -> None:
    blocks = {block.id: block for block in document.blocks}
    for item in items:
        if any(block_id not in blocks for block_id in item.block_ids):
            raise InventoryBuildError("inventory item must name a known source block")
        source = " ".join(blocks[block_id].text for block_id in item.block_ids)
        if _normalize_whitespace(item.source_text) not in _normalize_whitespace(source):
            raise InventoryBuildError("inventory item source text must occur in its source blocks")


def _validate_hierarchy(
    items: tuple[InventoryItemExtraction, ...],
    by_local_id: dict[str, InventoryItemExtraction],
) -> None:
    containers = {NodeKind.section, NodeKind.repeat_group}
    for item in items:
        if item.parent_local_id is not None:
            parent = by_local_id.get(item.parent_local_id)
            if parent is None:
                raise InventoryBuildError("inventory parent must identify a known local item")
            if parent.kind not in containers:
                raise InventoryBuildError("inventory parent must be a section or repeat group")
        elif item.is_entry:
            raise InventoryBuildError("inventory entry must have one parent container")
        if item.repeat_group_local_id is not None:
            repeat = by_local_id.get(item.repeat_group_local_id)
            if repeat is None:
                raise InventoryBuildError("repeat membership must identify a known local item")
            if repeat.kind is not NodeKind.repeat_group:
                raise InventoryBuildError("repeat membership must identify a repeat group")

    for item in items:
        visited: set[str] = set()
        current: InventoryItemExtraction | None = item
        while current is not None:
            if current.local_id in visited:
                raise InventoryBuildError("inventory containment hierarchy must be acyclic")
            visited.add(current.local_id)
            current = (
                by_local_id[current.parent_local_id]
                if current.parent_local_id is not None
                else None
            )

    for item in items:
        if item.repeat_group_local_id is None:
            continue
        ancestors: set[str] = set()
        parent_id = item.parent_local_id
        while parent_id is not None:
            ancestors.add(parent_id)
            parent_id = by_local_id[parent_id].parent_local_id
        if item.repeat_group_local_id not in ancestors:
            raise InventoryBuildError("repeat membership must identify an ancestor repeat group")

    children_by_parent: dict[str, list[InventoryItemExtraction]] = {
        item.local_id: [] for item in items if item.kind in containers
    }
    for item in items:
        if item.parent_local_id is not None:
            children_by_parent[item.parent_local_id].append(item)
    for children in children_by_parent.values():
        if sum(child.is_entry for child in children) != 1:
            raise InventoryBuildError(
                "each section or repeat group must have exactly one entry child"
            )


def _printed_identity_diagnostics(
    extracted: tuple[InventoryItemExtraction, ...],
    inventory: tuple[InventoryItem, ...],
) -> list[InventoryDiagnostic]:
    groups: dict[tuple[tuple[str, ...], NodeKind, str], list[str]] = {}
    first_order: dict[tuple[tuple[str, ...], NodeKind, str], int] = {}
    for source, item in zip(extracted, inventory, strict=True):
        if source.source_item_id is None:
            continue
        key = printed_identity_key(source.source_item_id, source.section_path, source.kind)
        groups.setdefault(key, []).append(item.node_id)
        first_order.setdefault(key, source.source_order)
    duplicate_keys = sorted(
        (key for key, node_ids in groups.items() if len(node_ids) > 1),
        key=lambda key: first_order[key],
    )
    return [
        InventoryDiagnostic(
            code="AMBIGUOUS_PRINTED_ID",
            message="A section namespace contains an ambiguous printed item identifier.",
            variable_index=None,
            node_ids=tuple(groups[key]),
        )
        for key in duplicate_keys
    ]


def _normalize_whitespace(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


__all__ = [
    "InventoryBuildError",
    "InventoryBuildResult",
    "InventoryDiagnostic",
    "InventoryDiagnosticCode",
    "InventoryItemExtraction",
    "build_inventory",
]
