"""Bounded core XLSForm adapter with versioned native-routing support."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from survey_scribe.models.routing import RepeatKind, TerminalKind
from survey_scribe.routing.contracts import (
    ConditionOperator,
    ExtractedRoutingCondition,
    ItemReference,
    NodeKind,
    SourceSpan,
    TransitionKind,
)
from survey_scribe.routing.native import (
    NativeActivation,
    NativeRoutingDiagnostic,
    NativeRoutingItem,
    NativeRoutingSemantics,
    NativeSourceExpression,
    NativeSourceRecord,
    NativeTransition,
)
from survey_scribe.sources.base import (
    ResolvedSource,
    SourceDocument,
    SourceFormatError,
    SourceLimitError,
    SourceLimits,
    SourceSecurityError,
    SourceTable,
    render_table,
)
from survey_scribe.sources.tabular import CsvAdapter, XlsxAdapter

XLSFORM_SUPPORT_MATRIX_VERSION = "1.0"
XLSFORM_SUPPORT_MATRIX: Mapping[str, str] = MappingProxyType(
    {
        "survey_choices_settings": "preserved",
        "multilingual_labels": "preserved",
        "groups": "logical_containment",
        "repeats": "logical_template",
        "reference_comparisons": "exact",
        "selected": "exact",
        "boolean_and_or_not": "exact",
        "functions_other_than_selected": "opaque",
        "arithmetic": "opaque",
        "constraints": "preserved_not_flow",
        "calculations": "preserved_not_flow",
        "choice_filters": "preserved_not_flow",
        "excel_formulas_macros_external_links": "rejected",
        "external_choices": "confined_bundle_only",
    }
)

_REFERENCE = re.compile(r"\$\{([^{}]+)\}")
_COMPARISON = re.compile(r"^\$\{([^{}]+)\}\s*(>=|<=|!=|=|>|<)\s*(.+)$", re.DOTALL)
_SELECTED = re.compile(
    r"^selected\s*\(\s*\$\{([^{}]+)\}\s*,\s*(.+)\s*\)$",
    re.IGNORECASE | re.DOTALL,
)
_INTEGER = re.compile(r"^[+-]?[0-9]+$")
_FLOAT = re.compile(r"^[+-]?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+)$")
_REMOTE_REFERENCE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


class XlsFormAdapter:
    """Preserve XLSX normalization and add native semantics for XLSForm workbooks."""

    def __init__(self, *, xlsx_adapter: XlsxAdapter | None = None) -> None:
        self._xlsx = xlsx_adapter or XlsxAdapter()

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        """Return the unchanged normalized XLSX document contract."""
        return self._xlsx.convert(source, limits=limits)

    def convert_native(
        self,
        source: ResolvedSource,
        document: SourceDocument,
        *,
        limits: SourceLimits,
    ) -> NativeRoutingSemantics | None:
        """Parse an XLSForm when a case-insensitive ``survey`` sheet is present."""
        tables = {
            table.provenance.sheet.casefold(): table
            for table in document.tables
            if table.provenance.sheet
        }
        survey = tables.get("survey")
        if survey is None:
            return None
        return _parse_xlsform(source, document, survey, tables, limits)


def _parse_xlsform(
    source: ResolvedSource,
    document: SourceDocument,
    survey: SourceTable,
    tables: Mapping[str, SourceTable],
    limits: SourceLimits,
) -> NativeRoutingSemantics:
    survey_headers, survey_rows = _table_records(survey, required=("type", "name"))
    records = list(_preserved_records("survey", survey_headers, survey_rows))
    diagnostics: list[NativeRoutingDiagnostic] = []

    choices_by_list: dict[str, set[str]] = {}
    choices = tables.get("choices")
    if choices is not None:
        choice_headers, choice_rows = _table_records(
            choices,
            required=("list_name", "name"),
        )
        records.extend(_preserved_records("choices", choice_headers, choice_rows))
        for _row, values in choice_rows:
            list_name = values.get("list_name", "").strip()
            name = values.get("name", "").strip()
            if list_name and name:
                choices_by_list.setdefault(list_name, set()).add(name)

    settings = tables.get("settings")
    if settings is not None:
        setting_headers, setting_rows = _table_records(settings, required=())
        records.extend(_preserved_records("settings", setting_headers, setting_rows))

    referenced_external: list[str] = []
    referenced_lists: list[str] = []
    parsed_rows: list[tuple[tuple[str, ...], dict[str, str], str]] = []
    for row, values in survey_rows:
        row_type = values.get("type", "").strip()
        parsed_rows.append((row, values, row_type))
        choice_reference = _choice_reference(row_type)
        first_type_part = row_type.split(maxsplit=1)[0].casefold() if row_type else ""
        if choice_reference is None and first_type_part in {
            "select_one_from_file",
            "select_multiple_from_file",
        }:
            raise SourceFormatError("XLSForm external-choice reference is missing")
        if choice_reference is not None:
            kind, value = choice_reference
            if kind == "external":
                referenced_external.append(value)
            else:
                referenced_lists.append(value)

    for list_name in dict.fromkeys(referenced_lists):
        if list_name not in choices_by_list:
            diagnostics.append(NativeRoutingDiagnostic(code="XLSFORM_CHOICE_LIST_MISSING"))
    for filename in dict.fromkeys(referenced_external):
        records.extend(_external_choice_records(source, filename, limits))

    items, relevant_by_local, row_by_local = _native_items(
        document,
        survey,
        parsed_rows,
        diagnostics,
    )
    references = {
        item.source_item_id: item
        for item in items
        if item.source_item_id is not None and item.kind is NodeKind.question
    }
    activations = tuple(
        NativeActivation(
            local_id=f"xlsform:activation:{position:06d}",
            item_local_id=local_id,
            expression=_parse_expression(expression, references),
            source_span=_source_span(document, survey, row_by_local[local_id], position),
        )
        for position, (local_id, expression) in enumerate(relevant_by_local, start=1)
    )
    transitions = _native_transitions(document, survey, items, row_by_local)
    cell_count = sum(len(record.values) for record in records)
    if cell_count > limits.max_cells:
        raise SourceLimitError("max_cells", "XLSForm exceeds the configured cell limit")
    return NativeRoutingSemantics(
        schema_version="1.0",
        adapter=f"survey-scribe/xlsform/{XLSFORM_SUPPORT_MATRIX_VERSION}",
        complete=True,
        items=items,
        transitions=transitions,
        activations=activations,
        records=tuple(records),
        diagnostics=tuple(diagnostics),
    )


def _native_items(
    document: SourceDocument,
    survey: SourceTable,
    parsed_rows: list[tuple[tuple[str, ...], dict[str, str], str]],
    diagnostics: list[NativeRoutingDiagnostic],
) -> tuple[
    tuple[NativeRoutingItem, ...],
    tuple[tuple[str, str], ...],
    dict[str, tuple[str, ...]],
]:
    block_id = _table_block_id(document, survey)
    header_row = survey.rows[0]
    items: list[NativeRoutingItem] = [
        NativeRoutingItem(
            local_id="xlsform:entry",
            source_item_id=None,
            raw_reference="XLSForm entry",
            label="Survey entry",
            section_path=(),
            source_order=0,
            block_ids=(block_id,),
            kind=NodeKind.entry,
            parent_local_id=None,
            repeat_group_local_id=None,
            is_entry=False,
            linked_variable_names=(),
            source_text=render_table((header_row,)),
            terminal_kind=None,
            repeat_kind=None,
        )
    ]
    stack: list[str] = []
    repeat_stack: list[str] = []
    names: set[str] = set()
    children_seen: set[str] = set()
    relevant: list[tuple[str, str]] = []
    row_by_local: dict[str, tuple[str, ...]] = {"xlsform:entry": header_row}
    item_by_local: dict[str, NativeRoutingItem] = {items[0].local_id: items[0]}

    for row, values, row_type in parsed_rows:
        normalized_type = " ".join(row_type.casefold().split())
        if normalized_type in {"end group", "end_group", "end repeat", "end_repeat"}:
            if not stack:
                raise SourceFormatError("XLSForm group or repeat endings are unbalanced")
            closing = stack.pop()
            if item_by_local[closing].kind is NodeKind.repeat_group:
                repeat_stack.pop()
            continue
        if not row_type and not any(value.strip() for value in values.values()):
            continue
        name = values.get("name", "").strip()
        is_container = normalized_type in {
            "begin group",
            "begin_group",
            "begin repeat",
            "begin_repeat",
        }
        if not name:
            if is_container or normalized_type:
                raise SourceFormatError("XLSForm survey rows require names except for end rows")
            continue
        if name in names:
            raise SourceFormatError("XLSForm survey item names must be unique")
        names.add(name)
        if normalized_type == "calculate":
            continue
        local_id = f"xlsform:item:{len(items):06d}"
        parent = stack[-1] if stack else None
        kind = (
            NodeKind.repeat_group
            if normalized_type in {"begin repeat", "begin_repeat"}
            else NodeKind.section
            if normalized_type in {"begin group", "begin_group"}
            else NodeKind.question
        )
        label = _preferred_label(values) or name
        section_path = tuple(item_by_local[item_id].raw_reference for item_id in stack)
        item = NativeRoutingItem(
            local_id=local_id,
            source_item_id=name,
            raw_reference=name,
            label=label,
            section_path=section_path,
            source_order=len(items),
            block_ids=(block_id,),
            kind=kind,
            parent_local_id=parent,
            repeat_group_local_id=repeat_stack[-1] if repeat_stack else None,
            is_entry=parent is not None and parent not in children_seen,
            linked_variable_names=((name,) if kind is NodeKind.question else ()),
            source_text=render_table((row,)),
            terminal_kind=None,
            repeat_kind=(RepeatKind.other if kind is NodeKind.repeat_group else None),
        )
        if parent is not None:
            children_seen.add(parent)
        items.append(item)
        item_by_local[local_id] = item
        row_by_local[local_id] = row
        expression = values.get("relevant", "").strip() or values.get("bind::relevant", "").strip()
        if expression:
            relevant.append((local_id, expression))
        if is_container:
            stack.append(local_id)
            if kind is NodeKind.repeat_group:
                repeat_stack.append(local_id)
        elif not _supported_question_type(normalized_type):
            diagnostics.append(NativeRoutingDiagnostic(code="XLSFORM_TYPE_UNSUPPORTED"))

    if stack:
        raise SourceFormatError("XLSForm group or repeat endings are unbalanced")
    containers = {
        item.local_id for item in items if item.kind in {NodeKind.section, NodeKind.repeat_group}
    }
    if any(container not in children_seen for container in containers):
        raise SourceFormatError("XLSForm groups and repeats must contain at least one logical item")
    terminal_row = survey.rows[-1]
    terminal = NativeRoutingItem(
        local_id="xlsform:terminal",
        source_item_id=None,
        raw_reference="XLSForm complete",
        label="Survey complete",
        section_path=(),
        source_order=len(items),
        block_ids=(block_id,),
        kind=NodeKind.terminal,
        parent_local_id=None,
        repeat_group_local_id=None,
        is_entry=False,
        linked_variable_names=(),
        source_text=render_table((terminal_row,)),
        terminal_kind=TerminalKind.survey_complete,
        repeat_kind=None,
    )
    items.append(terminal)
    row_by_local[terminal.local_id] = terminal_row
    return tuple(items), tuple(relevant), row_by_local


def _native_transitions(
    document: SourceDocument,
    survey: SourceTable,
    items: tuple[NativeRoutingItem, ...],
    row_by_local: Mapping[str, tuple[str, ...]],
) -> tuple[NativeTransition, ...]:
    by_local = {item.local_id: item for item in items}
    children: dict[str | None, list[str]] = {}
    for item in items:
        if item.kind in {NodeKind.entry, NodeKind.terminal}:
            continue
        children.setdefault(item.parent_local_id, []).append(item.local_id)
    terminal_id = next(item.local_id for item in items if item.kind is NodeKind.terminal)
    transitions: list[tuple[str, str, TransitionKind]] = []
    root = children.get(None, [])
    transitions.append(
        ("xlsform:entry", root[0] if root else terminal_id, TransitionKind.sequential)
    )
    for item in items:
        nested = children.get(item.local_id, [])
        if item.kind in {NodeKind.section, NodeKind.repeat_group}:
            transitions.append((item.local_id, nested[0], TransitionKind.unconditional))
            continue
        if item.kind in {NodeKind.entry, NodeKind.terminal}:
            continue
        transitions.append(
            (
                item.local_id,
                _next_logical(item, by_local, children, terminal_id),
                TransitionKind.sequential,
            )
        )
    return tuple(
        NativeTransition(
            local_id=f"xlsform:transition:{position:06d}",
            source_local_id=source_id,
            target_local_id=target_id,
            transition_kind=kind,
            expression=None,
            source_span=_source_span(document, survey, row_by_local[source_id], position),
            explicitly_stated=True,
            priority=None,
        )
        for position, (source_id, target_id, kind) in enumerate(transitions, start=1)
    )


def _next_logical(
    item: NativeRoutingItem,
    by_local: Mapping[str, NativeRoutingItem],
    children: Mapping[str | None, list[str]],
    terminal_id: str,
) -> str:
    current = item
    while True:
        siblings = children.get(current.parent_local_id, [])
        position = siblings.index(current.local_id)
        if position + 1 < len(siblings):
            return siblings[position + 1]
        if current.parent_local_id is None:
            return terminal_id
        current = by_local[current.parent_local_id]


def _parse_expression(
    exact_expression: str,
    known_items: Mapping[str, NativeRoutingItem],
) -> NativeSourceExpression:
    reference_names = tuple(dict.fromkeys(_REFERENCE.findall(exact_expression)))
    references = tuple(
        ItemReference(
            raw_reference=name,
            source_item_id=name,
            canonical_hint=None,
            section_path=(known_items[name].section_path if name in known_items else ()),
            node_kind=NodeKind.question,
        )
        for name in reference_names
    )
    projection = _project_expression(exact_expression, known_items)
    return NativeSourceExpression(
        language="xlsform-xpath",
        version=XLSFORM_SUPPORT_MATRIX_VERSION,
        exact_expression=exact_expression,
        references=references,
        projection=projection,
    )


def _project_expression(
    expression: str,
    known_items: Mapping[str, NativeRoutingItem],
) -> ExtractedRoutingCondition:
    value = _strip_outer_parentheses(expression.strip())
    for keyword, operator in (("or", ConditionOperator.any), ("and", ConditionOperator.all)):
        parts = _split_top_level(value, keyword)
        if len(parts) >= 2:
            children = tuple(_project_expression(part, known_items) for part in parts)
            if any(child.operator is ConditionOperator.opaque for child in children):
                return _opaque(expression)
            return ExtractedRoutingCondition(
                operator=operator,
                item_reference=None,
                value=None,
                values=None,
                children=children,
                raw_text=expression,
            )
    not_match = re.fullmatch(r"not\s*\((.*)\)", value, re.IGNORECASE | re.DOTALL)
    if not_match is not None:
        child_text = not_match.group(1)
        child = _project_expression(child_text, known_items)
        if child.operator is ConditionOperator.selected:
            return child.model_copy(
                update={"operator": ConditionOperator.not_selected, "raw_text": expression}
            )
        if child.operator is ConditionOperator.opaque:
            return _opaque(expression)
        return ExtractedRoutingCondition(
            operator=ConditionOperator.not_,
            item_reference=None,
            value=None,
            values=None,
            children=(child,),
            raw_text=expression,
        )
    selected = _SELECTED.fullmatch(value)
    if selected is not None:
        name, scalar_text = selected.groups()
        scalar = _scalar(scalar_text)
        if scalar is _UNSUPPORTED or name not in known_items:
            return _opaque(expression)
        return _leaf(
            ConditionOperator.selected,
            known_items[name],
            expression,
            value=scalar,
        )
    comparison = _COMPARISON.fullmatch(value)
    if comparison is not None:
        name, symbol, scalar_text = comparison.groups()
        scalar = _scalar(scalar_text)
        if scalar is _UNSUPPORTED or name not in known_items:
            return _opaque(expression)
        if scalar == "" and symbol in {"=", "!="}:
            return _leaf(
                ConditionOperator.not_answered if symbol == "=" else ConditionOperator.answered,
                known_items[name],
                expression,
            )
        operator = {
            "=": ConditionOperator.equals,
            "!=": ConditionOperator.not_equals,
            ">": ConditionOperator.greater_than,
            ">=": ConditionOperator.greater_than_or_equal,
            "<": ConditionOperator.less_than,
            "<=": ConditionOperator.less_than_or_equal,
        }[symbol]
        return _leaf(operator, known_items[name], expression, value=scalar)
    return _opaque(expression)


def _leaf(
    operator: ConditionOperator,
    item: NativeRoutingItem,
    raw_text: str,
    *,
    value: object = None,
) -> ExtractedRoutingCondition:
    return ExtractedRoutingCondition(
        operator=operator,
        item_reference=ItemReference(
            raw_reference=item.raw_reference,
            source_item_id=item.source_item_id,
            canonical_hint=None,
            section_path=item.section_path,
            node_kind=NodeKind.question,
        ),
        value=value,  # type: ignore[arg-type]
        values=None,
        children=None,
        raw_text=raw_text,
    )


def _opaque(raw_text: str) -> ExtractedRoutingCondition:
    return ExtractedRoutingCondition(
        operator=ConditionOperator.opaque,
        item_reference=None,
        value=None,
        values=None,
        children=None,
        raw_text=raw_text,
    )


_UNSUPPORTED = object()


def _scalar(value: str) -> str | int | float | bool | object:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    if _INTEGER.fullmatch(stripped):
        return int(stripped)
    if _FLOAT.fullmatch(stripped):
        return float(stripped)
    if stripped.casefold() == "true()":
        return True
    if stripped.casefold() == "false()":
        return False
    return _UNSUPPORTED


def _split_top_level(value: str, keyword: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    index = 0
    while index < len(value):
        character = value[index]
        if quote is not None:
            if character == quote and (index == 0 or value[index - 1] != "\\"):
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return (value,)
        elif depth == 0 and value[index : index + len(keyword)].casefold() == keyword:
            before = value[index - 1] if index else " "
            after_index = index + len(keyword)
            after = value[after_index] if after_index < len(value) else " "
            if before.isspace() and after.isspace():
                parts.append(value[start:index].strip())
                start = after_index
                index = after_index
                continue
        index += 1
    if not parts:
        return (value,)
    parts.append(value[start:].strip())
    return tuple(parts) if all(parts) else (value,)


def _strip_outer_parentheses(value: str) -> str:
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        quote: str | None = None
        closes_at_end = False
        for index, character in enumerate(value):
            if quote is not None:
                if character == quote and (index == 0 or value[index - 1] != "\\"):
                    quote = None
                continue
            if character in {"'", '"'}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    closes_at_end = index == len(value) - 1
                    break
        if not closes_at_end:
            break
        value = value[1:-1].strip()
    return value


def _table_records(
    table: SourceTable,
    *,
    required: tuple[str, ...],
) -> tuple[tuple[str, ...], list[tuple[tuple[str, ...], dict[str, str]]]]:
    if not table.rows:
        raise SourceFormatError("XLSForm sheets must contain one header row")
    headers = tuple(_normalize_header(value) for value in table.rows[0])
    nonempty = tuple(header for header in headers if header)
    if len(set(nonempty)) != len(nonempty):
        raise SourceFormatError("XLSForm sheet headers must be unique")
    if any(name not in headers for name in required):
        raise SourceFormatError("XLSForm sheet is missing a required header")
    rows: list[tuple[tuple[str, ...], dict[str, str]]] = []
    for row in table.rows[1:]:
        values = {
            header: row[index] if index < len(row) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(value.strip() for value in values.values()):
            rows.append((row, values))
    return headers, rows


def _preserved_records(
    collection: str,
    headers: tuple[str, ...],
    rows: list[tuple[tuple[str, ...], dict[str, str]]],
) -> tuple[NativeSourceRecord, ...]:
    return tuple(
        NativeSourceRecord(
            collection=collection,  # type: ignore[arg-type]
            source_order=position,
            values=tuple((header, values.get(header, "")) for header in headers if header),
        )
        for position, (_row, values) in enumerate(rows)
    )


def _external_choice_records(
    source: ResolvedSource,
    filename: str,
    limits: SourceLimits,
) -> tuple[NativeSourceRecord, ...]:
    normalized = filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or _REMOTE_REFERENCE.match(normalized)
    ):
        raise SourceSecurityError("XLSForm external-choice path is prohibited")
    wanted = Path(*path.parts)
    companion = next(
        (
            candidate
            for candidate in source.companions
            if candidate.relative_to(source.root) == wanted
        ),
        None,
    )
    if companion is None:
        raise SourceFormatError("XLSForm external-choice companion is missing")
    document = CsvAdapter().convert(
        ResolvedSource(root=source.root, primary=companion),
        limits=limits,
    )
    if not document.tables:
        return ()
    headers, rows = _table_records(document.tables[0], required=("name",))
    return _preserved_records("external_choices", headers, rows)


def _choice_reference(row_type: str) -> tuple[str, str] | None:
    parts = row_type.split()
    if len(parts) < 2:
        return None
    normalized = parts[0].casefold()
    if normalized in {"select_one_from_file", "select_multiple_from_file"}:
        return "external", parts[1]
    if normalized in {"select_one", "select_multiple"}:
        return "internal", parts[1]
    return None


def _supported_question_type(row_type: str) -> bool:
    base = row_type.split(maxsplit=1)[0] if row_type else ""
    return base in {
        "acknowledge",
        "audio",
        "barcode",
        "calculate",
        "date",
        "dateTime".casefold(),
        "decimal",
        "file",
        "geopoint",
        "geoshape",
        "geotrace",
        "image",
        "integer",
        "note",
        "range",
        "select_multiple",
        "select_multiple_from_file",
        "select_one",
        "select_one_from_file",
        "start",
        "end",
        "text",
        "time",
        "today",
        "username",
    }


def _preferred_label(values: Mapping[str, str]) -> str:
    direct = values.get("label", "").strip()
    if direct:
        return direct
    return next(
        (
            value.strip()
            for key, value in values.items()
            if key.startswith("label::") and value.strip()
        ),
        "",
    )


def _normalize_header(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _table_block_id(document: SourceDocument, table: SourceTable) -> str:
    return next(
        block.id for block in document.blocks if block.table is table or block.table == table
    )


def _source_span(
    document: SourceDocument,
    table: SourceTable,
    row: tuple[str, ...],
    position: int,
) -> SourceSpan:
    provenance = table.provenance
    return SourceSpan(
        span_id=f"xlsform:temporary:{position:06d}",
        block_id=_table_block_id(document, table),
        source_name=document.source_name,
        pages=provenance.pages,
        sheet=provenance.sheet,
        row_start=provenance.row_start,
        row_end=provenance.row_end,
        source_quote=render_table((row,))[:2_000],
    )


__all__ = [
    "XLSFORM_SUPPORT_MATRIX",
    "XLSFORM_SUPPORT_MATRIX_VERSION",
    "XlsFormAdapter",
]
