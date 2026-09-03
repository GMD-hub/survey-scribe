"""Adaptive provider-backed routing extraction and independent verification."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Literal, TypeVar, cast

from pydantic import BaseModel

from survey_scribe.models.routing import (
    InventoryItem,
    QuestionnaireRoutingGraph,
    RoutingNode,
    RoutingSourceBinding,
)
from survey_scribe.providers.base import (
    ConcurrencyLimiter,
    ProviderCapabilityError,
    ProviderError,
    ProviderMessage,
    ProviderResponse,
    ProviderTransportError,
    ProviderTruncationError,
    ProviderValidationError,
    SchemaDescriptor,
    StructuredProvider,
)
from survey_scribe.routing.algorithms import iterative_strongly_connected_components
from survey_scribe.routing.config import RoutingConfig
from survey_scribe.routing.contracts import (
    ConditionOperator,
    ItemReference,
    RoutingEvidenceBatch,
    RoutingPassKind,
    TransitionEvidence,
)
from survey_scribe.routing.identity import (
    IdentityError,
    IdentityResolver,
    SourceEvidenceError,
    VerifiedEvidence,
    build_evidence_records,
)
from survey_scribe.routing.prompts import (
    REVIEWER_PROMPT_VERSION,
    RenderedPrompt,
    RoutingReviewerResponse,
    render_forward_prompt,
    render_incoming_activation_prompt,
    render_reviewer_prompt,
    render_system_prompt,
)
from survey_scribe.routing.reconcile import (
    ReconciliationError,
    append_review_decisions,
    reconcile_routing_graph,
)
from survey_scribe.routing.review import (
    ReviewValidationError,
    build_review_decisions,
    build_reviewer_packets,
)
from survey_scribe.routing.validate import KnownCategoryCodes
from survey_scribe.sources.base import SourceDocument

T = TypeVar("T", bound=BaseModel)
PassName = RoutingPassKind | Literal["reviewer"]


class RoutingExtractionStatus(str, Enum):
    """Completeness of the structured routing evidence stage."""

    success = "success"
    partial = "partial"
    failed = "failed"


class RiskPredicate(str, Enum):
    """Fixed reasons that select one inventory region for independent Pass B."""

    branch_target = "branch_target"
    cross_section = "cross_section"
    unresolved_target = "unresolved_target"
    ambiguous_target = "ambiguous_target"
    opaque_condition = "opaque_condition"
    cycle = "cycle"
    low_confidence = "low_confidence"
    unusual_in_degree = "unusual_in_degree"
    unusual_out_degree = "unusual_out_degree"


@dataclass(frozen=True, slots=True)
class PassBTarget:
    """One source-ordered independent-verification target and its fixed reasons."""

    node_id: str
    source_order: int
    reasons: tuple[RiskPredicate, ...]


@dataclass(frozen=True, slots=True)
class RoutingRegionFailure:
    """One safe failed model region without request, source, or response prose."""

    region_id: str
    pass_kind: PassName
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ProviderCallRecord:
    """Non-sensitive provider metadata for one stable routing region."""

    chunk_id: str
    pass_kind: PassName
    provider: str
    model: str
    prompt_version: str
    prompt_sha256: str
    response_sha256: str
    canonical_schema_sha256: str
    request_schema_sha256: str
    transport_attempts: int
    validation_attempts: int
    finish_reason: str | None
    cache_hit: bool


@dataclass(frozen=True, slots=True)
class SchemaCapabilityRecord:
    """The two recorded hashes for one canonical response model."""

    response_model: str
    canonical_schema_sha256: str
    request_schema_sha256: str


@dataclass(frozen=True, slots=True)
class RoutingExtractionResult:
    """Structured extraction result before pipeline or artifact assembly."""

    status: RoutingExtractionStatus
    graph: QuestionnaireRoutingGraph | None
    failures: tuple[RoutingRegionFailure, ...]
    calls: tuple[ProviderCallRecord, ...]
    schema_capabilities: tuple[SchemaCapabilityRecord, ...]
    peak_concurrency: int
    cache_entries_after_run: int


@dataclass(frozen=True)
class ProviderCacheKey:
    """Complete per-run parsed-model cache identity from the routing contract."""

    adapter_identity: str
    provider: str
    model: str
    pass_kind: str
    prompt_version: str
    prompt_sha256: str
    canonical_schema_sha256: str
    request_schema_sha256: str
    generation_settings: tuple[tuple[str, str], ...]
    request_sha256: str


class ParsedModelCache:
    """Per-run in-memory cache that contains only validated parsed models."""

    def __init__(self) -> None:
        self._values: dict[ProviderCacheKey, BaseModel] = {}
        self._closed = False

    @property
    def size(self) -> int:
        return len(self._values)

    def get(self, key: ProviderCacheKey) -> BaseModel | None:
        self._require_open()
        return self._values.get(key)

    def put(self, key: ProviderCacheKey, value: BaseModel) -> None:
        self._require_open()
        if not isinstance(value, BaseModel):
            raise TypeError("parsed-model cache accepts only validated Pydantic models")
        self._values[key] = value

    def close(self) -> None:
        self._values.clear()
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("parsed-model cache is closed")


@dataclass(frozen=True, slots=True)
class _Generated:
    output: BaseModel
    call: ProviderCallRecord


@dataclass(frozen=True, slots=True)
class _RegionOutcome:
    chunk_id: str
    pass_kind: PassName
    batch: RoutingEvidenceBatch | None
    reviewer_response: RoutingReviewerResponse | None
    call: ProviderCallRecord | None
    failure: RoutingRegionFailure | None
    prompt: RenderedPrompt | None = None


@dataclass(frozen=True, slots=True)
class _ReferenceResolution:
    status: Literal["resolved", "ambiguous", "unresolved"]
    candidates: tuple[InventoryItem, ...]


async def extract_routing(
    *,
    provider: StructuredProvider,
    document: SourceDocument,
    inventory: Sequence[InventoryItem],
    nodes: Sequence[RoutingNode],
    entry_node_ids: tuple[str, ...],
    source_binding: RoutingSourceBinding,
    config: RoutingConfig | None = None,
    initial_verified_evidence: VerifiedEvidence | None = None,
    source_priorities: Mapping[str, int] | None = None,
    known_category_codes: KnownCategoryCodes | None = None,
) -> RoutingExtractionResult:
    """Run forward extraction, adaptive Pass B, and bounded discrepancy review."""
    policy = config or RoutingConfig()
    ordered_inventory = tuple(sorted(inventory, key=lambda item: item.source_order))
    if not ordered_inventory:
        return RoutingExtractionResult(
            status=RoutingExtractionStatus.failed,
            graph=None,
            failures=(
                RoutingRegionFailure(
                    region_id="inventory",
                    pass_kind=RoutingPassKind.forward,
                    code="ROUTING_EMPTY_INVENTORY",
                    message="The routing inventory is empty.",
                ),
            ),
            calls=(),
            schema_capabilities=(),
            peak_concurrency=0,
            cache_entries_after_run=0,
        )
    _validate_source_identity(document, source_binding)
    extraction_schema = provider.inspect_schema(RoutingEvidenceBatch)
    reviewer_schema = provider.inspect_schema(RoutingReviewerResponse)
    schema_records = (
        _schema_record(RoutingEvidenceBatch, extraction_schema),
        _schema_record(RoutingReviewerResponse, reviewer_schema),
    )
    limiter = ConcurrencyLimiter(policy.max_concurrency)
    cache = ParsedModelCache()
    try:
        result = await _extract_routing_run(
            provider=provider,
            document=document,
            inventory=ordered_inventory,
            nodes=tuple(nodes),
            entry_node_ids=entry_node_ids,
            source_binding=source_binding,
            config=policy,
            extraction_schema=extraction_schema,
            reviewer_schema=reviewer_schema,
            schema_records=schema_records,
            limiter=limiter,
            cache=cache,
            initial_verified_evidence=initial_verified_evidence
            or VerifiedEvidence(
                source_spans=(),
                records=(),
            ),
            source_priorities=source_priorities,
            known_category_codes=known_category_codes,
        )
    finally:
        cache.close()
    return replace(
        result,
        peak_concurrency=limiter.peak_active,
        cache_entries_after_run=cache.size,
    )


async def _extract_routing_run(
    *,
    provider: StructuredProvider,
    document: SourceDocument,
    inventory: tuple[InventoryItem, ...],
    nodes: tuple[RoutingNode, ...],
    entry_node_ids: tuple[str, ...],
    source_binding: RoutingSourceBinding,
    config: RoutingConfig,
    extraction_schema: SchemaDescriptor,
    reviewer_schema: SchemaDescriptor,
    schema_records: tuple[SchemaCapabilityRecord, ...],
    limiter: ConcurrencyLimiter,
    cache: ParsedModelCache,
    initial_verified_evidence: VerifiedEvidence,
    source_priorities: Mapping[str, int] | None,
    known_category_codes: KnownCategoryCodes | None,
) -> RoutingExtractionResult:
    system = render_system_prompt()
    forward_chunks = _stable_chunks(inventory, config.max_inventory_items_per_call)
    forward_tasks = tuple(
        _extract_forward_region(
            index=index,
            chunk=chunk,
            chunks=forward_chunks,
            provider=provider,
            document=document,
            source_binding=source_binding,
            config=config,
            system=system,
            descriptor=extraction_schema,
            limiter=limiter,
            cache=cache,
        )
        for index, chunk in enumerate(forward_chunks)
    )
    forward = tuple(await asyncio.gather(*forward_tasks))
    calls = [outcome.call for outcome in forward if outcome.call is not None]
    failures = [outcome.failure for outcome in forward if outcome.failure is not None]
    forward_batches = tuple(outcome.batch for outcome in forward if outcome.batch is not None)
    if not forward_batches:
        if initial_verified_evidence.records:
            try:
                graph = reconcile_routing_graph(
                    nodes=nodes,
                    entry_node_ids=entry_node_ids,
                    inventory=inventory,
                    source_binding=source_binding,
                    verified_evidence=initial_verified_evidence,
                    source_priorities=source_priorities,
                    known_category_codes=known_category_codes,
                )
            except ReconciliationError:
                failures.append(_graph_failure())
                graph = None
            return _result(
                status=(
                    RoutingExtractionStatus.partial
                    if graph is not None
                    else RoutingExtractionStatus.failed
                ),
                graph=graph,
                failures=failures,
                calls=calls,
                schema_records=schema_records,
                limiter=limiter,
                cache=cache,
            )
        return _result(
            status=RoutingExtractionStatus.failed,
            graph=None,
            failures=failures,
            calls=calls,
            schema_records=schema_records,
            limiter=limiter,
            cache=cache,
        )

    model_verified_forward, evidence_failures = _verified_batches(
        forward_batches,
        document,
        config,
    )
    verified_forward = _merge_verified(initial_verified_evidence, model_verified_forward)
    failures.extend(evidence_failures)
    successful_forward_ids = {batch.chunk_id for batch in forward_batches}.difference(
        failure.region_id for failure in evidence_failures
    )
    if not successful_forward_ids:
        return _result(
            status=RoutingExtractionStatus.failed,
            graph=None,
            failures=failures,
            calls=calls,
            schema_records=schema_records,
            limiter=limiter,
            cache=cache,
        )
    try:
        reconcile_routing_graph(
            nodes=nodes,
            entry_node_ids=entry_node_ids,
            inventory=inventory,
            source_binding=source_binding,
            verified_evidence=verified_forward,
            source_priorities=source_priorities,
            known_category_codes=known_category_codes,
        )
    except ReconciliationError:
        failures.append(_graph_failure())
        return _result(
            status=RoutingExtractionStatus.failed,
            graph=None,
            failures=failures,
            calls=calls,
            schema_records=schema_records,
            limiter=limiter,
            cache=cache,
        )

    pass_b_targets = select_pass_b_targets(inventory, forward_batches, config)
    incoming: tuple[_RegionOutcome, ...] = ()
    if pass_b_targets:
        incoming = tuple(
            await asyncio.gather(
                *(
                    _extract_incoming_region(
                        index=index,
                        target_chunk=target_chunk,
                        inventory=inventory,
                        provider=provider,
                        document=document,
                        source_binding=source_binding,
                        config=config,
                        system=system,
                        descriptor=extraction_schema,
                        limiter=limiter,
                        cache=cache,
                    )
                    for index, target_chunk in enumerate(
                        _stable_target_chunks(
                            pass_b_targets,
                            inventory,
                            config.max_inventory_items_per_call,
                        )
                    )
                )
            )
        )
        calls.extend(outcome.call for outcome in incoming if outcome.call is not None)
        failures.extend(outcome.failure for outcome in incoming if outcome.failure is not None)

    incoming_batches = tuple(outcome.batch for outcome in incoming if outcome.batch is not None)
    verified_incoming, incoming_evidence_failures = _verified_batches(
        incoming_batches,
        document,
        config,
    )
    failures.extend(incoming_evidence_failures)
    verified = _merge_verified(verified_forward, verified_incoming)
    try:
        graph = reconcile_routing_graph(
            nodes=nodes,
            entry_node_ids=entry_node_ids,
            inventory=inventory,
            source_binding=source_binding,
            verified_evidence=verified,
            source_priorities=source_priorities,
            known_category_codes=known_category_codes,
        )
    except ReconciliationError:
        failures.append(_graph_failure())
        return _result(
            status=RoutingExtractionStatus.failed,
            graph=None,
            failures=failures,
            calls=calls,
            schema_records=schema_records,
            limiter=limiter,
            cache=cache,
        )

    packets = build_reviewer_packets(graph, config)
    if packets:
        reviews = tuple(
            await asyncio.gather(
                *(
                    _review_region(
                        index=index,
                        packet=packet,
                        provider=provider,
                        config=config,
                        system=system,
                        descriptor=reviewer_schema,
                        limiter=limiter,
                        cache=cache,
                    )
                    for index, packet in enumerate(packets)
                )
            )
        )
        calls.extend(outcome.call for outcome in reviews if outcome.call is not None)
        failures.extend(outcome.failure for outcome in reviews if outcome.failure is not None)
        for packet, outcome in zip(packets, reviews, strict=True):
            if outcome.reviewer_response is None or outcome.prompt is None:
                continue
            try:
                decisions = build_review_decisions(
                    packet=packet,
                    response=outcome.reviewer_response,
                    prompt_version=REVIEWER_PROMPT_VERSION,
                    prompt_sha256=outcome.prompt.sha256,
                    max_source_spans_per_decision=config.max_source_spans_per_decision,
                    existing_decisions=graph.routing_audit.review_decisions,
                )
                graph = append_review_decisions(
                    graph,
                    decisions,
                    known_category_codes=known_category_codes,
                )
            except (ReviewValidationError, ReconciliationError):
                failures.append(
                    RoutingRegionFailure(
                        region_id=outcome.chunk_id,
                        pass_kind="reviewer",
                        code="ROUTING_REVIEW_INVALID",
                        message="The routing review response failed citation validation.",
                    )
                )

    return _result(
        status=(RoutingExtractionStatus.partial if failures else RoutingExtractionStatus.success),
        graph=graph,
        failures=failures,
        calls=calls,
        schema_records=schema_records,
        limiter=limiter,
        cache=cache,
    )


async def _extract_forward_region(
    *,
    index: int,
    chunk: tuple[InventoryItem, ...],
    chunks: tuple[tuple[InventoryItem, ...], ...],
    provider: StructuredProvider,
    document: SourceDocument,
    source_binding: RoutingSourceBinding,
    config: RoutingConfig,
    system: RenderedPrompt,
    descriptor: SchemaDescriptor,
    limiter: ConcurrencyLimiter,
    cache: ParsedModelCache,
) -> _RegionOutcome:
    chunk_id = f"forward-{index + 1:06d}"
    previous = chunks[index - 1][-1:] if index else ()
    following = chunks[index + 1][:1] if index + 1 < len(chunks) else ()
    prompt = render_forward_prompt(
        survey_id=source_binding.survey_id,
        chunk_id=chunk_id,
        item_inventory=chunk,
        previous_boundary_context=_boundary_context(previous),
        source_text=_source_text(document, chunk),
        next_boundary_context=_boundary_context(following),
    )
    return await _evidence_region(
        chunk_id=chunk_id,
        pass_kind=RoutingPassKind.forward,
        expected_items=chunk,
        provider=provider,
        config=config,
        system=system,
        prompt=prompt,
        descriptor=descriptor,
        limiter=limiter,
        cache=cache,
    )


async def _extract_incoming_region(
    *,
    index: int,
    target_chunk: tuple[InventoryItem, ...],
    inventory: tuple[InventoryItem, ...],
    provider: StructuredProvider,
    document: SourceDocument,
    source_binding: RoutingSourceBinding,
    config: RoutingConfig,
    system: RenderedPrompt,
    descriptor: SchemaDescriptor,
    limiter: ConcurrencyLimiter,
    cache: ParsedModelCache,
) -> _RegionOutcome:
    chunk_id = f"incoming-{index + 1:06d}"
    relevant = _relevant_inventory(
        target_chunk,
        inventory,
        config.max_inventory_items_per_call,
    )
    prompt = render_incoming_activation_prompt(
        survey_id=source_binding.survey_id,
        chunk_id=chunk_id,
        target_items=target_chunk,
        relevant_item_inventory=relevant,
        retrieved_source_windows=_source_text(document, relevant),
    )
    return await _evidence_region(
        chunk_id=chunk_id,
        pass_kind=RoutingPassKind.incoming_activation,
        expected_items=target_chunk,
        provider=provider,
        config=config,
        system=system,
        prompt=prompt,
        descriptor=descriptor,
        limiter=limiter,
        cache=cache,
    )


async def _evidence_region(
    *,
    chunk_id: str,
    pass_kind: RoutingPassKind,
    expected_items: tuple[InventoryItem, ...],
    provider: StructuredProvider,
    config: RoutingConfig,
    system: RenderedPrompt,
    prompt: RenderedPrompt,
    descriptor: SchemaDescriptor,
    limiter: ConcurrencyLimiter,
    cache: ParsedModelCache,
) -> _RegionOutcome:
    try:
        generated = await _generate_cached(
            provider=provider,
            messages=(
                ProviderMessage(role="system", content=system.content),
                ProviderMessage(role="user", content=prompt.content),
            ),
            response_model=RoutingEvidenceBatch,
            config=config,
            pass_kind=pass_kind,
            chunk_id=chunk_id,
            prompt=prompt,
            expected_descriptor=descriptor,
            limiter=limiter,
            cache=cache,
        )
    except ProviderCapabilityError:
        raise
    except ProviderError as error:
        return _failed_region(chunk_id, pass_kind, error)
    batch = cast(RoutingEvidenceBatch, generated.output)
    expected_ids = tuple(item.source_item_id or item.raw_reference for item in expected_items)
    if (
        batch.chunk_id != chunk_id
        or batch.pass_kind is not pass_kind
        or batch.examined_item_ids != expected_ids
    ):
        return _local_invalid_region(chunk_id, pass_kind, generated.call)
    return _RegionOutcome(
        chunk_id=chunk_id,
        pass_kind=pass_kind,
        batch=batch,
        reviewer_response=None,
        call=generated.call,
        failure=None,
    )


async def _review_region(
    *,
    index: int,
    packet: object,
    provider: StructuredProvider,
    config: RoutingConfig,
    system: RenderedPrompt,
    descriptor: SchemaDescriptor,
    limiter: ConcurrencyLimiter,
    cache: ParsedModelCache,
) -> _RegionOutcome:
    chunk_id = f"review-{index + 1:06d}"
    prompt = render_reviewer_prompt(packet=packet)  # type: ignore[arg-type]
    try:
        generated = await _generate_cached(
            provider=provider,
            messages=(
                ProviderMessage(role="system", content=system.content),
                ProviderMessage(role="user", content=prompt.content),
            ),
            response_model=RoutingReviewerResponse,
            config=config,
            pass_kind="reviewer",
            chunk_id=chunk_id,
            prompt=prompt,
            expected_descriptor=descriptor,
            limiter=limiter,
            cache=cache,
        )
    except ProviderCapabilityError:
        raise
    except ProviderError as error:
        return _failed_region(chunk_id, "reviewer", error, prompt=prompt)
    return _RegionOutcome(
        chunk_id=chunk_id,
        pass_kind="reviewer",
        batch=None,
        reviewer_response=cast(RoutingReviewerResponse, generated.output),
        call=generated.call,
        failure=None,
        prompt=prompt,
    )


async def _generate_cached(
    *,
    provider: StructuredProvider,
    messages: tuple[ProviderMessage, ...],
    response_model: type[T],
    config: RoutingConfig,
    pass_kind: PassName,
    chunk_id: str,
    prompt: RenderedPrompt,
    expected_descriptor: SchemaDescriptor,
    limiter: ConcurrencyLimiter,
    cache: ParsedModelCache,
) -> _Generated:
    current_descriptor = provider.inspect_schema(response_model)
    if current_descriptor != expected_descriptor:
        raise ProviderCapabilityError("drift")
    effective_limit = min(
        config.max_request_tokens,
        provider.max_input_tokens - config.generation.max_output_tokens,
    )
    if effective_limit < 1 or provider.estimate_tokens(messages) > effective_limit:
        raise _RequestLimitError()
    key = ProviderCacheKey(
        adapter_identity=provider.adapter_identity,
        provider=provider.provider_name,
        model=provider.model,
        pass_kind=(pass_kind.value if isinstance(pass_kind, RoutingPassKind) else pass_kind),
        prompt_version=prompt.version,
        prompt_sha256=prompt.sha256,
        canonical_schema_sha256=current_descriptor.canonical_schema_sha256,
        request_schema_sha256=current_descriptor.request_schema_sha256,
        generation_settings=_generation_settings(config),
        request_sha256=_request_sha256(messages),
    )
    cached = cache.get(key)
    if cached is not None:
        return _Generated(
            output=cached,
            call=ProviderCallRecord(
                chunk_id=chunk_id,
                pass_kind=pass_kind,
                provider=provider.provider_name,
                model=provider.model,
                prompt_version=prompt.version,
                prompt_sha256=prompt.sha256,
                response_sha256=_model_sha256(cached),
                canonical_schema_sha256=current_descriptor.canonical_schema_sha256,
                request_schema_sha256=current_descriptor.request_schema_sha256,
                transport_attempts=0,
                validation_attempts=0,
                finish_reason=None,
                cache_hit=True,
            ),
        )
    response: ProviderResponse[T] = await provider.generate(
        messages=messages,
        response_model=response_model,
        generation=config.generation,
        retry=config.retry,
        limiter=limiter,
    )
    response.require_complete()
    cache.put(key, response.output)
    return _Generated(
        output=response.output,
        call=ProviderCallRecord(
            chunk_id=chunk_id,
            pass_kind=pass_kind,
            provider=response.provider,
            model=response.model,
            prompt_version=prompt.version,
            prompt_sha256=prompt.sha256,
            response_sha256=_model_sha256(response.output),
            canonical_schema_sha256=current_descriptor.canonical_schema_sha256,
            request_schema_sha256=current_descriptor.request_schema_sha256,
            transport_attempts=response.transport_attempts,
            validation_attempts=response.validation_attempts,
            finish_reason=response.finish_reason,
            cache_hit=False,
        ),
    )


class _RequestLimitError(ProviderError):
    code = "ROUTING_REQUEST_LIMIT"
    safe_message = "The routing request exceeds its token limit."


def select_pass_b_targets(
    inventory: Sequence[InventoryItem],
    batches: Sequence[RoutingEvidenceBatch],
    config: RoutingConfig,
) -> tuple[PassBTarget, ...]:
    """Apply every fixed risk predicate without using Pass A output in Pass B prompts."""
    ordered = tuple(sorted(inventory, key=lambda item: item.source_order))
    by_node = {item.node_id: item for item in ordered}
    resolver = IdentityResolver(ordered)
    reasons: dict[str, set[RiskPredicate]] = {}
    transitions = tuple(
        observation
        for batch in batches
        for observation in batch.evidence
        if isinstance(observation, TransitionEvidence)
    )
    resolved: list[tuple[TransitionEvidence, InventoryItem | None, _ReferenceResolution]] = []

    def mark(items: Iterable[InventoryItem], reason: RiskPredicate) -> None:
        for item in items:
            reasons.setdefault(item.node_id, set()).add(reason)

    for observation in transitions:
        source_resolution = _resolve_reference(ordered, resolver, observation.source)
        source = source_resolution.candidates[0] if source_resolution.status == "resolved" else None
        target_resolution = _resolve_reference(
            ordered,
            resolver,
            observation.target,
            default_section=(source.section_path if source is not None else ()),
        )
        resolved.append((observation, source, target_resolution))
        targets = target_resolution.candidates
        fallback = targets or ((source,) if source is not None else ())
        if target_resolution.status == "unresolved":
            mark(fallback, RiskPredicate.unresolved_target)
        elif target_resolution.status == "ambiguous":
            bounded = (
                targets
                if len(targets) <= config.max_candidate_targets_per_reference
                else ((source,) if source is not None else ())
            )
            mark(bounded, RiskPredicate.ambiguous_target)
        if (
            source is not None
            and targets
            and any(target.section_path != source.section_path for target in targets)
        ):
            mark(fallback, RiskPredicate.cross_section)
        if observation.condition is not None and _has_opaque_condition(observation.condition):
            mark(fallback, RiskPredicate.opaque_condition)
        if observation.confidence < config.low_confidence_threshold:
            mark(fallback, RiskPredicate.low_confidence)

    for batch in batches:
        if not batch.unresolved_references:
            continue
        examined = tuple(
            item
            for item in ordered
            if (item.source_item_id or item.raw_reference) in batch.examined_item_ids
        )
        mark(examined, RiskPredicate.unresolved_target)

    outgoing: dict[str, list[InventoryItem]] = {}
    incoming: dict[str, list[InventoryItem]] = {}
    adjacency: dict[str, list[str]] = {item.node_id: [] for item in ordered}
    for _observation, source, target_resolution in resolved:
        if source is None or target_resolution.status != "resolved":
            continue
        target = target_resolution.candidates[0]
        outgoing.setdefault(source.node_id, []).append(target)
        incoming.setdefault(target.node_id, []).append(source)
        adjacency[source.node_id].append(target.node_id)
    for targets in outgoing.values():
        if len(targets) >= 2:
            mark(targets, RiskPredicate.branch_target)
        if len(targets) >= config.unusual_out_degree_threshold:
            mark(targets, RiskPredicate.unusual_out_degree)
    for target_id, sources in incoming.items():
        if len(sources) >= config.unusual_in_degree_threshold:
            mark((by_node[target_id],), RiskPredicate.unusual_in_degree)
    for component in iterative_strongly_connected_components(
        (item.node_id for item in ordered),
        adjacency,
    ):
        cyclic = len(component) > 1 or any(node_id in adjacency[node_id] for node_id in component)
        if cyclic:
            mark((by_node[node_id] for node_id in component), RiskPredicate.cycle)

    reason_order = {reason: index for index, reason in enumerate(RiskPredicate)}
    return tuple(
        PassBTarget(
            node_id=item.node_id,
            source_order=item.source_order,
            reasons=tuple(sorted(reasons[item.node_id], key=reason_order.__getitem__)),
        )
        for item in ordered
        if item.node_id in reasons
    )


def _resolve_reference(
    inventory: tuple[InventoryItem, ...],
    resolver: IdentityResolver,
    reference: ItemReference,
    *,
    default_section: tuple[str, ...] = (),
) -> _ReferenceResolution:
    by_node = {item.node_id: item for item in inventory}
    try:
        resolution = resolver.resolve(reference, default_section_path=default_section)
    except IdentityError:
        return _ReferenceResolution(status="unresolved", candidates=())
    return _ReferenceResolution(
        status=resolution.status,
        candidates=tuple(by_node[node_id] for node_id in resolution.candidate_node_ids),
    )


def _has_opaque_condition(condition: object) -> bool:
    stack = [condition]
    while stack:
        current = stack.pop()
        if getattr(current, "operator", None) is ConditionOperator.opaque:
            return True
        children = getattr(current, "children", None)
        if children:
            stack.extend(children)
    return False


def _stable_chunks(
    inventory: tuple[InventoryItem, ...],
    maximum: int,
) -> tuple[tuple[InventoryItem, ...], ...]:
    groups: list[tuple[InventoryItem, ...]] = []
    current: list[InventoryItem] = []
    current_key: tuple[tuple[str, ...], str | None] | None = None
    for item in inventory:
        key = (item.section_path, item.repeat_group_node_id)
        if current and key != current_key:
            groups.append(tuple(current))
            current = []
        current.append(item)
        current_key = key
    if current:
        groups.append(tuple(current))

    chunks: list[tuple[InventoryItem, ...]] = []
    pending: list[InventoryItem] = []
    for group in groups:
        for start in range(0, len(group), maximum):
            part = group[start : start + maximum]
            if pending and len(pending) + len(part) > maximum:
                chunks.append(tuple(pending))
                pending = []
            pending.extend(part)
            if len(pending) == maximum:
                chunks.append(tuple(pending))
                pending = []
    if pending:
        chunks.append(tuple(pending))
    return tuple(chunks)


def _stable_target_chunks(
    selected: tuple[PassBTarget, ...],
    inventory: tuple[InventoryItem, ...],
    maximum: int,
) -> tuple[tuple[InventoryItem, ...], ...]:
    selected_ids = {item.node_id for item in selected}
    targets = tuple(item for item in inventory if item.node_id in selected_ids)
    return _stable_chunks(targets, maximum)


def _relevant_inventory(
    targets: tuple[InventoryItem, ...],
    inventory: tuple[InventoryItem, ...],
    maximum: int,
) -> tuple[InventoryItem, ...]:
    sections = {item.section_path for item in targets}
    target_ids = {item.node_id for item in targets}
    selected_by_id: dict[str, InventoryItem] = {}

    def add(item: InventoryItem) -> None:
        if len(selected_by_id) < maximum:
            selected_by_id.setdefault(item.node_id, item)

    ordered = tuple(sorted(inventory, key=lambda item: item.source_order))
    for target in sorted(targets, key=lambda item: item.source_order):
        preceding = tuple(item for item in ordered if item.source_order < target.source_order)
        for item in reversed(preceding[-3:]):
            if item.node_id not in target_ids:
                add(item)
        seen_sections: set[tuple[str, ...]] = set()
        for item in reversed(preceding):
            if item.section_path in seen_sections:
                continue
            seen_sections.add(item.section_path)
            if item.node_id not in target_ids:
                add(item)

    relevant = tuple(item for item in ordered if item.section_path in sections)
    for item in relevant:
        if len(selected_by_id) >= maximum:
            break
        if item.node_id not in target_ids:
            add(item)

    if not selected_by_id:
        for target in targets:
            add(target)

    selected = list(selected_by_id.values())
    selected.sort(key=lambda item: item.source_order)
    return tuple(selected)


def _source_text(document: SourceDocument, inventory: Sequence[InventoryItem]) -> str:
    wanted = {block_id for item in inventory for block_id in item.block_ids}
    return "\n\n".join(block.text for block in document.blocks if block.id in wanted)


def _boundary_context(inventory: Sequence[InventoryItem]) -> str:
    return json.dumps(
        [
            {
                "kind": item.kind.value,
                "raw_reference": item.raw_reference,
                "section_path": item.section_path,
                "source_item_id": item.source_item_id,
            }
            for item in inventory
        ],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _verified_batches(
    batches: Sequence[RoutingEvidenceBatch],
    document: SourceDocument,
    config: RoutingConfig,
) -> tuple[VerifiedEvidence, tuple[RoutingRegionFailure, ...]]:
    verified_parts: list[VerifiedEvidence] = []
    failures: list[RoutingRegionFailure] = []
    for batch in batches:
        try:
            _validate_batch_limits(batch, config)
            verified_parts.append(build_evidence_records(batch.evidence, document))
        except (SourceEvidenceError, ValueError):
            failures.append(
                RoutingRegionFailure(
                    region_id=batch.chunk_id,
                    pass_kind=batch.pass_kind,
                    code="ROUTING_EVIDENCE_INVALID",
                    message="The routing evidence failed local source validation.",
                )
            )
    return _merge_verified(*verified_parts), tuple(failures)


def _validate_batch_limits(batch: RoutingEvidenceBatch, config: RoutingConfig) -> None:
    for observation in batch.evidence:
        if len(observation.source_span.source_quote) > config.max_source_quote_chars:
            raise ValueError("source quote limit")
        condition = getattr(observation, "condition", None)
        if condition is not None and (
            condition.ast_depth > config.max_condition_depth
            or condition.ast_node_count > config.max_condition_nodes
        ):
            raise ValueError("condition limit")


def _merge_verified(*values: VerifiedEvidence) -> VerifiedEvidence:
    spans: dict[str, object] = {}
    records: dict[str, object] = {}
    for value in values:
        for span in value.source_spans:
            spans.setdefault(span.span_id, span)
        for record in value.records:
            records.setdefault(record.evidence_id, record)
    return VerifiedEvidence(
        source_spans=tuple(spans.values()),  # type: ignore[arg-type]
        records=tuple(records.values()),  # type: ignore[arg-type]
    )


def _validate_source_identity(
    document: SourceDocument,
    source_binding: RoutingSourceBinding,
) -> None:
    if (
        document.source_name != source_binding.source_name
        or document.media_type != source_binding.media_type
        or (
            document.snapshot_sha256 is not None
            and document.snapshot_sha256 != source_binding.snapshot_sha256
        )
    ):
        raise ValueError("routing source binding does not match the validated source")


def _generation_settings(config: RoutingConfig) -> tuple[tuple[str, str], ...]:
    values = config.generation.model_dump(mode="json")
    return tuple(
        (name, json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")))
        for name, value in sorted(values.items())
    )


def _request_sha256(messages: tuple[ProviderMessage, ...]) -> str:
    payload = json.dumps(
        [{"content": item.content, "role": item.role} for item in messages],
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _model_sha256(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema_record(
    response_model: type[BaseModel],
    descriptor: SchemaDescriptor,
) -> SchemaCapabilityRecord:
    return SchemaCapabilityRecord(
        response_model=response_model.__name__,
        canonical_schema_sha256=descriptor.canonical_schema_sha256,
        request_schema_sha256=descriptor.request_schema_sha256,
    )


def _failed_region(
    chunk_id: str,
    pass_kind: PassName,
    error: ProviderError,
    *,
    prompt: RenderedPrompt | None = None,
) -> _RegionOutcome:
    code = {
        ProviderTruncationError: "ROUTING_RESPONSE_TRUNCATED",
        ProviderValidationError: "ROUTING_RESPONSE_INVALID",
        ProviderTransportError: "ROUTING_PROVIDER_TRANSPORT",
        _RequestLimitError: "ROUTING_REQUEST_LIMIT",
    }.get(type(error), error.code)
    return _RegionOutcome(
        chunk_id=chunk_id,
        pass_kind=pass_kind,
        batch=None,
        reviewer_response=None,
        call=None,
        failure=RoutingRegionFailure(
            region_id=chunk_id,
            pass_kind=pass_kind,
            code=code,
            message=str(error),
        ),
        prompt=prompt,
    )


def _local_invalid_region(
    chunk_id: str,
    pass_kind: RoutingPassKind,
    call: ProviderCallRecord,
) -> _RegionOutcome:
    return _RegionOutcome(
        chunk_id=chunk_id,
        pass_kind=pass_kind,
        batch=None,
        reviewer_response=None,
        call=call,
        failure=RoutingRegionFailure(
            region_id=chunk_id,
            pass_kind=pass_kind,
            code="ROUTING_RESPONSE_INVALID",
            message="The structured routing response failed its region contract.",
        ),
    )


def _graph_failure() -> RoutingRegionFailure:
    return RoutingRegionFailure(
        region_id="graph",
        pass_kind=RoutingPassKind.forward,
        code="ROUTING_GRAPH_INVALID",
        message="The reconciled routing graph failed a structural invariant.",
    )


def _result(
    *,
    status: RoutingExtractionStatus,
    graph: QuestionnaireRoutingGraph | None,
    failures: Iterable[RoutingRegionFailure | None],
    calls: Iterable[ProviderCallRecord | None],
    schema_records: tuple[SchemaCapabilityRecord, ...],
    limiter: ConcurrencyLimiter,
    cache: ParsedModelCache,
) -> RoutingExtractionResult:
    return RoutingExtractionResult(
        status=status,
        graph=graph,
        failures=tuple(item for item in failures if item is not None),
        calls=tuple(item for item in calls if item is not None),
        schema_capabilities=schema_records,
        peak_concurrency=limiter.peak_active,
        cache_entries_after_run=cache.size,
    )


__all__ = [
    "ParsedModelCache",
    "PassBTarget",
    "ProviderCacheKey",
    "ProviderCallRecord",
    "RiskPredicate",
    "RoutingExtractionResult",
    "RoutingExtractionStatus",
    "RoutingRegionFailure",
    "SchemaCapabilityRecord",
    "extract_routing",
    "select_pass_b_targets",
]
