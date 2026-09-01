"""Public questionnaire routing pipeline over native and provider evidence."""

from __future__ import annotations

import asyncio
import re
from typing import cast

from pydantic import ValidationError

from survey_scribe.models.routing import (
    DiagnosticSeverity as GraphDiagnosticSeverity,
)
from survey_scribe.models.routing import (
    QuestionnaireRoutingGraph,
    RoutedAnswerCategory,
    RoutedNumericRange,
    RoutedSurveySVIS,
    RoutedSurveyVariable,
    RoutingSourceBinding,
    TerminalKind,
)
from survey_scribe.models.svis import SurveySVIS, SurveyVariable
from survey_scribe.providers.base import StructuredProvider
from survey_scribe.results import (
    ArtifactProvenance,
    Diagnostic,
    DiagnosticSeverity,
    ExtractionResult,
    FailedBlock,
    PromptArtifactProvenance,
)
from survey_scribe.routing.config import RoutingConfig
from survey_scribe.routing.contracts import NodeKind
from survey_scribe.routing.extraction import (
    ProviderCallRecord,
    RoutingExtractionStatus,
    extract_routing,
)
from survey_scribe.routing.identity import SourceBindingError
from survey_scribe.routing.inventory import InventoryBuildError
from survey_scribe.routing.native import (
    NativeRoutingItem,
    NativeRoutingSemantics,
    PreparedNativeRouting,
    prepare_native_routing,
)
from survey_scribe.routing.reconcile import ReconciliationError, reconcile_routing_graph
from survey_scribe.sources.base import LocalSource, SourceBundle, SourceDocument, SourceError
from survey_scribe.sources.registry import SourceRegistry

_PRINTED_ITEM_ID = re.compile(r"(?i)\b(?:question\s+)?(q[0-9]+[a-z]?)\b")


class QuestionnaireRouter:
    """Route one existing detached SVIS against its exact validated source snapshot."""

    def __init__(
        self,
        provider: StructuredProvider | None,
        *,
        config: RoutingConfig | None = None,
        sources: SourceRegistry | None = None,
    ) -> None:
        self._provider = provider
        self._config = config if config is not None else RoutingConfig()
        self._sources = sources if sources is not None else SourceRegistry.default()

    def route(
        self,
        source: LocalSource | SourceBundle,
        svis: SurveySVIS,
        *,
        source_binding: RoutingSourceBinding,
    ) -> ExtractionResult[RoutedSurveySVIS]:
        """Run routing synchronously when no event loop is active in this thread."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aroute(source, svis, source_binding=source_binding))
        raise RuntimeError("QuestionnaireRouter.route() cannot run inside a running event loop")

    async def aroute(
        self,
        source: LocalSource | SourceBundle,
        svis: SurveySVIS,
        *,
        source_binding: RoutingSourceBinding,
    ) -> ExtractionResult[RoutedSurveySVIS]:
        """Build a routed SVIS with native bypass or provider-backed enrichment."""
        detached = SurveySVIS.model_validate(svis.model_dump(mode="json"))
        try:
            conversion = self._sources.convert_with_native(source, detached)
        except SourceBindingError:
            return _failed(detached.survey_id, "ROUTING_SOURCE_MISMATCH", _SOURCE_MISMATCH)
        except SourceError as error:
            return _failed(
                detached.survey_id, error.code, "The questionnaire source failed conversion."
            )

        if conversion.source_binding != source_binding:
            return _failed(detached.survey_id, "ROUTING_SOURCE_MISMATCH", _SOURCE_MISMATCH)

        native = conversion.native
        if native is None and self._provider is None:
            return _failed(
                detached.survey_id,
                "ROUTING_PROVIDER_REQUIRED",
                "This questionnaire source requires a structured routing provider.",
            )
        try:
            prepared = (
                prepare_native_routing(native, conversion.document, detached)
                if native is not None
                else _prepare_document_routing(conversion.document, detached)
            )
        except InventoryBuildError:
            return _failed(
                detached.survey_id,
                "ROUTING_EMPTY_INVENTORY",
                "The routing inventory is empty or invalid.",
            )
        if not prepared.entry_node_ids:
            return _failed(
                detached.survey_id,
                "ROUTING_EMPTY_INVENTORY",
                "The routing inventory is empty or invalid.",
            )
        if native is not None and not native.complete and self._provider is None:
            return _failed(
                detached.survey_id,
                "ROUTING_PROVIDER_REQUIRED",
                "The native source does not contain complete routing semantics.",
            )

        failed_blocks: tuple[FailedBlock, ...] = _coverage_failures(conversion.document)
        calls: tuple[ProviderCallRecord, ...] = ()
        graph: QuestionnaireRoutingGraph | None
        if native is not None and native.complete:
            try:
                graph = reconcile_routing_graph(
                    nodes=prepared.nodes,
                    entry_node_ids=prepared.entry_node_ids,
                    inventory=prepared.inventory.items,
                    source_binding=conversion.source_binding,
                    verified_evidence=prepared.evidence,
                    source_priorities=prepared.source_priorities,
                )
            except (ReconciliationError, ValidationError):
                return _failed(
                    detached.survey_id,
                    "ROUTING_GRAPH_INVALID",
                    "The routed graph failed a structural invariant.",
                )
        else:
            provider = cast(StructuredProvider, self._provider)
            try:
                extraction = await extract_routing(
                    provider=provider,
                    document=conversion.document,
                    inventory=prepared.inventory.items,
                    nodes=prepared.nodes,
                    entry_node_ids=prepared.entry_node_ids,
                    source_binding=conversion.source_binding,
                    config=self._config,
                    initial_verified_evidence=(prepared.evidence if native is not None else None),
                    source_priorities=(prepared.source_priorities if native is not None else None),
                )
            except Exception:
                return _failed(
                    detached.survey_id,
                    "ROUTING_PROVIDER_FAILED",
                    "The structured routing provider failed before a graph was available.",
                )
            graph = extraction.graph
            calls = extraction.calls
            failed_blocks += tuple(
                FailedBlock(
                    block_id=failure.region_id,
                    message=failure.message,
                    source_order=None,
                )
                for failure in extraction.failures
            )
            if extraction.status is RoutingExtractionStatus.failed or graph is None:
                diagnostics = tuple(
                    Diagnostic(
                        code=failure.code,
                        message=failure.message,
                        severity=DiagnosticSeverity.error,
                    )
                    for failure in extraction.failures
                )
                return ExtractionResult[RoutedSurveySVIS](
                    output=None,
                    survey_id=detached.survey_id,
                    diagnostics=diagnostics
                    or (
                        Diagnostic(
                            code="ROUTING_PROVIDER_FAILED",
                            message="All required routing regions failed.",
                            severity=DiagnosticSeverity.error,
                        ),
                    ),
                )

        if any(
            diagnostic.severity is GraphDiagnosticSeverity.error for diagnostic in graph.diagnostics
        ):
            return _failed(
                detached.survey_id,
                "ROUTING_GRAPH_INVALID",
                "The routed graph failed a structural invariant.",
            )
        routed = _routed_svis(detached, prepared, graph)
        diagnostics = _result_diagnostics(prepared, graph, native)
        return ExtractionResult[RoutedSurveySVIS](
            output=routed,
            survey_id=detached.survey_id,
            diagnostics=diagnostics,
            failed_blocks=failed_blocks,
            artifact_provenance=_artifact_provenance(conversion.source_binding, calls),
        )


def _prepare_document_routing(document: SourceDocument, svis: SurveySVIS) -> PreparedNativeRouting:
    semantics = _document_semantics(document, svis)
    if not semantics.items:
        raise InventoryBuildError("logical inventory extraction must contain at least one item")
    return prepare_native_routing(semantics, document, svis)


def _document_semantics(document: SourceDocument, svis: SurveySVIS) -> NativeRoutingSemantics:
    if not document.blocks:
        return NativeRoutingSemantics(
            schema_version="1.0",
            adapter="survey-scribe/document-inventory/1.0",
            complete=False,
            items=(),
            transitions=(),
            activations=(),
            records=(),
            diagnostics=(),
        )
    first = document.blocks[0]
    last = document.blocks[-1]
    candidates = _question_candidates(document)
    items: list[NativeRoutingItem] = [
        NativeRoutingItem(
            local_id="document:entry",
            source_item_id=None,
            raw_reference="Questionnaire entry",
            label="Questionnaire entry",
            section_path=(),
            source_order=0,
            block_ids=(first.id,),
            kind=NodeKind.entry,
            parent_local_id=None,
            repeat_group_local_id=None,
            is_entry=False,
            linked_variable_names=(),
            source_text=first.text,
            terminal_kind=None,
            repeat_kind=None,
        )
    ]
    for index, variable in enumerate(svis.variables):
        if index < len(candidates):
            source_item_id, source_text, block_id = candidates[index]
        else:
            block = document.blocks[min(index, len(document.blocks) - 1)]
            source_item_id = None
            source_text = _variable_source_text(variable, block.text)
            block_id = block.id
        items.append(
            NativeRoutingItem(
                local_id=f"document:question:{index:06d}",
                source_item_id=source_item_id,
                raw_reference=source_item_id or f"Logical question {index + 1}",
                label=variable.label or variable.question_text or f"Logical question {index + 1}",
                section_path=((variable.module,) if variable.module else ()),
                source_order=index + 1,
                block_ids=(block_id,),
                kind=NodeKind.question,
                parent_local_id=None,
                repeat_group_local_id=None,
                is_entry=False,
                linked_variable_names=(variable.raw_name,),
                source_text=source_text,
                terminal_kind=None,
                repeat_kind=None,
            )
        )
    items.append(
        NativeRoutingItem(
            local_id="document:terminal",
            source_item_id=None,
            raw_reference="Questionnaire complete",
            label="Questionnaire complete",
            section_path=(),
            source_order=len(items),
            block_ids=(last.id,),
            kind=NodeKind.terminal,
            parent_local_id=None,
            repeat_group_local_id=None,
            is_entry=False,
            linked_variable_names=(),
            source_text=last.text,
            terminal_kind=TerminalKind.survey_complete,
            repeat_kind=None,
        )
    )
    return NativeRoutingSemantics(
        schema_version="1.0",
        adapter="survey-scribe/document-inventory/1.0",
        complete=False,
        items=tuple(items),
        transitions=(),
        activations=(),
        records=(),
        diagnostics=(),
    )


def _question_candidates(document: SourceDocument) -> tuple[tuple[str, str, str], ...]:
    candidates: list[tuple[str, str, str]] = []
    for block in document.blocks:
        for line in block.text.splitlines() or (block.text,):
            match = _PRINTED_ITEM_ID.search(line)
            if match is not None:
                candidates.append((match.group(1).upper(), line, block.id))
    return tuple(candidates)


def _variable_source_text(variable: SurveyVariable, block_text: str) -> str:
    for value in (variable.question_text, variable.label):
        if value and value in block_text:
            return value
    return block_text


def _routed_svis(
    svis: SurveySVIS,
    prepared: PreparedNativeRouting,
    graph: QuestionnaireRoutingGraph,
) -> RoutedSurveySVIS:
    variables = tuple(
        _routed_variable(variable, prepared.inventory.variable_node_ids[index])
        for index, variable in enumerate(svis.variables)
    )
    return RoutedSurveySVIS(
        survey_id=svis.survey_id,
        country_code=svis.country_code,
        year=svis.year,
        survey_name=svis.survey_name,
        study_type=svis.study_type,
        data_collection_mode=svis.data_collection_mode,
        language=svis.language,
        variables=variables,
        source_file=svis.source_file,
        source_format=svis.source_format,
        extraction_date=svis.extraction_date,
        extraction_notes=svis.extraction_notes,
        routing_schema_version="1.0",
        routing_graph=graph,
    )


def _routed_variable(variable: SurveyVariable, node_id: str | None) -> RoutedSurveyVariable:
    categories = (
        tuple(
            RoutedAnswerCategory(
                code=category.code,
                label=category.label,
                is_missing=category.is_missing,
            )
            for category in variable.categories
        )
        if variable.categories is not None
        else None
    )
    numeric_range = (
        RoutedNumericRange(
            min_value=variable.numeric_range.min_value,
            max_value=variable.numeric_range.max_value,
            notes=variable.numeric_range.notes,
        )
        if variable.numeric_range is not None
        else None
    )
    return RoutedSurveyVariable(
        raw_name=variable.raw_name,
        label=variable.label,
        question_text=variable.question_text,
        data_type=variable.data_type,
        categories=categories,
        numeric_range=numeric_range,
        universe=variable.universe,
        skip_condition_raw=variable.skip_condition_raw,
        module=variable.module,
        unit_of_analysis=variable.unit_of_analysis,
        source_page=variable.source_page,
        extraction_confidence=variable.extraction_confidence,
        needs_review=variable.needs_review,
        notes=variable.notes,
        routing_node_id=node_id,
    )


def _result_diagnostics(
    prepared: PreparedNativeRouting,
    graph: QuestionnaireRoutingGraph,
    native: NativeRoutingSemantics | None,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(
        Diagnostic(
            code=item.code,
            message=item.message,
            severity=(
                DiagnosticSeverity.error
                if item.code == "UNLINKED_VARIABLE"
                else DiagnosticSeverity.warning
            ),
        )
        for item in prepared.inventory.diagnostics
    )
    diagnostics.extend(
        Diagnostic(
            code=item.code,
            message=item.message,
            severity=DiagnosticSeverity.warning,
        )
        for item in graph.diagnostics
        if item.severity is not GraphDiagnosticSeverity.error
    )
    if native is not None:
        diagnostics.extend(
            Diagnostic(
                code=item.code,
                message="The native source contains a preserved unsupported feature.",
                severity=(
                    DiagnosticSeverity.error
                    if item.severity == "error"
                    else DiagnosticSeverity.warning
                ),
            )
            for item in native.diagnostics
        )
    return tuple(diagnostics)


def _coverage_failures(document: SourceDocument) -> tuple[FailedBlock, ...]:
    return tuple(
        FailedBlock(
            block_id=f"source-{document.coverage.unit}-{unit}",
            message="One source conversion unit failed.",
            source_order=unit - 1,
        )
        for unit in document.coverage.failed_units
    )


def _artifact_provenance(
    source_binding: RoutingSourceBinding,
    calls: tuple[ProviderCallRecord, ...],
) -> ArtifactProvenance:
    prompts: list[PromptArtifactProvenance] = []
    seen_prompts: set[tuple[str, str, str]] = set()
    responses: list[str] = []
    seen_responses: set[str] = set()
    for call in calls:
        pass_kind = "reviewer" if call.pass_kind == "reviewer" else call.pass_kind.value
        prompt_key = (pass_kind, call.prompt_version, call.prompt_sha256)
        if prompt_key not in seen_prompts:
            seen_prompts.add(prompt_key)
            prompts.append(
                PromptArtifactProvenance(
                    pass_kind=pass_kind,  # type: ignore[arg-type]
                    version=call.prompt_version,
                    prompt_sha256=call.prompt_sha256,
                )
            )
        if call.response_sha256 not in seen_responses:
            seen_responses.add(call.response_sha256)
            responses.append(call.response_sha256)
    return ArtifactProvenance(
        source_sha256=(source_binding.snapshot_sha256,),
        model_response_sha256=tuple(responses),
        prompt_versions=tuple(prompts),
    )


def _failed(
    survey_id: str,
    code: str,
    message: str,
) -> ExtractionResult[RoutedSurveySVIS]:
    return ExtractionResult[RoutedSurveySVIS](
        output=None,
        survey_id=survey_id,
        diagnostics=(
            Diagnostic(
                code=code,
                message=message,
                severity=DiagnosticSeverity.error,
            ),
        ),
    )


_SOURCE_MISMATCH = "The routing source binding does not match the validated source snapshot."

__all__ = ["QuestionnaireRouter"]
