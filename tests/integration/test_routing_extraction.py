"""Adaptive routing extraction, verification, review, limits, and cache behavior."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable

import pytest

from survey_scribe.config import RetryConfig
from survey_scribe.models.routing import (
    CandidateEdge,
    CandidateStatus,
    Containment,
    DiscrepancyKind,
    EdgeKind,
    EvidenceRecord,
    InventoryItem,
    ReviewAction,
    RoutingDiscrepancy,
    RoutingNode,
    RoutingSourceBinding,
    TerminalKind,
)
from survey_scribe.providers.base import (
    ConcurrencyLimiter,
    ProviderCapabilityError,
    ProviderMessage,
    ProviderTransportError,
)
from survey_scribe.providers.capabilities import CapabilityEvidence, ModelCapabilities
from survey_scribe.providers.testing import DeterministicFakeProvider, FakeRequest, FakeStep
from survey_scribe.routing.config import RoutingConfig
from survey_scribe.routing.contracts import (
    ConditionOperator,
    EvidenceOrigin,
    EvidencePerspective,
    ExtractedRoutingCondition,
    ItemReference,
    NodeKind,
    RoutingEvidenceBatch,
    RoutingPassKind,
    SourceSpan,
    TransitionEvidence,
    TransitionKind,
)
from survey_scribe.routing.extraction import (
    ParsedModelCache,
    ProviderCacheKey,
    RiskPredicate,
    RoutingExtractionStatus,
    _generate_cached,
    _relevant_inventory,
    extract_routing,
    select_pass_b_targets,
)
from survey_scribe.routing.prompts import (
    ReviewerDecisionOutput,
    ReviewerPromptPacket,
    RoutingReviewerResponse,
    render_system_prompt,
)
from survey_scribe.routing.review import (
    ReviewValidationError,
    _coalesced_discrepancy_batches,
    build_review_decisions,
)
from survey_scribe.sources.base import SourceBlock, SourceCoverage, SourceDocument, SourceProvenance


def _capabilities(**changes: object) -> ModelCapabilities:
    values: dict[str, object] = {
        "provider": "fake",
        "model": "routing-fake-v1",
        "structured_output": True,
        "strict_schema": True,
        "max_input_tokens": 200_000,
        "max_output_tokens": 4_096,
        "supported_generation_settings": frozenset({"temperature", "max_output_tokens", "seed"}),
        "evidence": CapabilityEvidence.verified,
        "tested_sdk_version": "fake-1",
    }
    values.update(changes)
    return ModelCapabilities(**values)  # type: ignore[arg-type]


def _document(count: int = 6) -> SourceDocument:
    provenance = SourceProvenance(source_name="questionnaire.txt", page=1)
    blocks = tuple(
        SourceBlock(
            id=f"block:{index}",
            order=index,
            kind="text",
            text=f"Q{index}: synthetic item {index}. Go to Q{index + 1}.",
            provenance=provenance,
        )
        for index in range(count)
    )
    return SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=blocks,
        coverage=SourceCoverage(),
        snapshot_sha256="a" * 64,
    )


def _binding() -> RoutingSourceBinding:
    return RoutingSourceBinding(
        survey_id="TST_2024_SYNTH",
        source_name="questionnaire.txt",
        media_type="text/plain",
        snapshot_sha256="a" * 64,
        source_conversion_schema_version="1.0",
    )


def _item(
    item_id: str,
    order: int,
    *,
    section: tuple[str, ...] = ("Main",),
    kind: NodeKind = NodeKind.question,
) -> InventoryItem:
    prefix = kind.value
    return InventoryItem(
        node_id=f"{prefix}:{'/'.join(section).casefold()}:{item_id.casefold()}",
        source_item_id=item_id,
        raw_reference=item_id,
        section_path=section,
        source_order=order,
        block_ids=(f"block:{order}",),
        kind=kind,
        repeat_group_node_id=None,
        parent_node_id=None,
        linked_variable_indices=(),
    )


def _inventory(count: int = 6) -> tuple[InventoryItem, ...]:
    return tuple(_item(f"Q{index}", index) for index in range(count))


def _node(item: InventoryItem) -> RoutingNode:
    return RoutingNode(
        node_id=item.node_id,
        kind=item.kind,
        source_item_id=item.source_item_id,
        raw_name=item.raw_reference.casefold() if item.kind is NodeKind.question else None,
        label=item.raw_reference,
        terminal_kind=(TerminalKind.survey_complete if item.kind is NodeKind.terminal else None),
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


def _nodes(inventory: tuple[InventoryItem, ...]) -> tuple[RoutingNode, ...]:
    nodes = tuple(_node(item) for item in inventory)
    return (
        nodes[0].model_copy(update={"kind": NodeKind.entry, "raw_name": None}),
        *nodes[1:],
    )


def _reference(
    item_id: str,
    *,
    section: tuple[str, ...] = ("Main",),
) -> ItemReference:
    return ItemReference(
        raw_reference=item_id,
        source_item_id=item_id,
        canonical_hint=None,
        section_path=section,
        node_kind=NodeKind.question,
    )


def _span(index: int, quote: str | None = None) -> SourceSpan:
    return SourceSpan(
        span_id=f"temporary:{index}",
        block_id=f"block:{index}",
        source_name="questionnaire.txt",
        pages=(1,),
        sheet=None,
        row_start=None,
        row_end=None,
        source_quote=quote or f"Go to Q{index + 1}.",
    )


def _transition(
    local_id: str,
    source: str,
    target: str,
    *,
    source_order: int,
    source_section: tuple[str, ...] = ("Main",),
    target_section: tuple[str, ...] = ("Main",),
    condition: ExtractedRoutingCondition | None = None,
    confidence: float = 0.9,
) -> TransitionEvidence:
    return TransitionEvidence(
        evidence_type="transition",
        local_id=local_id,
        perspective=EvidencePerspective.outgoing,
        origin=EvidenceOrigin.forward_extraction,
        source=_reference(source, section=source_section),
        target=_reference(target, section=target_section),
        transition_kind=(
            TransitionKind.conditional if condition is not None else TransitionKind.unconditional
        ),
        condition=condition,
        source_span=_span(source_order),
        native_expression=None,
        explicitly_stated=True,
        confidence=confidence,
        ambiguity_note=None,
    )


def _condition(*, opaque: bool = False) -> ExtractedRoutingCondition:
    if opaque:
        return ExtractedRoutingCondition(
            operator=ConditionOperator.opaque,
            item_reference=None,
            value=None,
            values=None,
            children=None,
            raw_text="opaque synthetic rule",
        )
    return ExtractedRoutingCondition(
        operator=ConditionOperator.equals,
        item_reference=_reference("Q0"),
        value=1,
        values=None,
        children=None,
        raw_text="Q0 = 1",
    )


def _batch(
    evidence: tuple[TransitionEvidence, ...],
    *,
    examined: tuple[str, ...] | None = None,
    unresolved: tuple[ItemReference, ...] = (),
) -> RoutingEvidenceBatch:
    return RoutingEvidenceBatch(
        chunk_id="forward-000001",
        pass_kind=RoutingPassKind.forward,
        examined_item_ids=examined
        or tuple(
            dict.fromkeys(
                item.source.source_item_id or item.source.raw_reference for item in evidence
            )
        ),
        evidence=evidence,
        unresolved_references=unresolved,
        notes=(),
    )


def _data_block(content: str, name: str) -> object:
    start = f"BEGIN_UNTRUSTED_{name}_JSON\n"
    end = f"\nEND_UNTRUSTED_{name}_JSON"
    return json.loads(content.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0])


def _task_message(request: FakeRequest) -> str:
    return next(message.content for message in request.messages if message.role == "user")


def _empty_batch_responder(
    *,
    delay: Callable[[str], float] | None = None,
    fail_chunk: str | None = None,
) -> Callable[[FakeRequest], object]:
    async def respond(request: FakeRequest) -> object:
        task = _task_message(request)
        if request.response_model is not RoutingEvidenceBatch:
            raise AssertionError("review was not expected")
        if task.startswith("PASS: forward"):
            chunk_id = json.loads(task.split("CHUNK_JSON: ", maxsplit=1)[1].splitlines()[0])
            inventory = _data_block(task, "ITEM_INVENTORY")
            pass_kind = RoutingPassKind.forward
        else:
            chunk_id = json.loads(task.split("CHUNK_JSON: ", maxsplit=1)[1].splitlines()[0])
            inventory = _data_block(task, "TARGET_ITEMS")
            pass_kind = RoutingPassKind.incoming_activation
            assert "Pass A output" not in task.replace("Pass A output is not supplied", "")
        if delay is not None:
            await asyncio.sleep(delay(chunk_id))
        if chunk_id == fail_chunk:
            raise ProviderTransportError(retryable=False)
        assert isinstance(inventory, list)
        examined = tuple(item["source_item_id"] or item["raw_reference"] for item in inventory)
        return RoutingEvidenceBatch(
            chunk_id=chunk_id,
            pass_kind=pass_kind,
            examined_item_ids=examined,
            evidence=(),
            unresolved_references=(),
            notes=(),
        )

    return respond


def _provider(responder: Callable[[FakeRequest], object]) -> DeterministicFakeProvider:
    return DeterministicFakeProvider(capabilities=_capabilities(), responder=responder)


def test_routing_config_freezes_every_named_plan_limit() -> None:
    config = RoutingConfig()
    assert config.max_source_quote_chars == 2_000
    assert config.max_request_tokens == 32_000
    assert config.max_inventory_items_per_call == 250
    assert config.max_candidate_targets_per_reference == 10
    assert config.max_discrepancies_per_review_call == 25
    assert config.max_source_spans_per_decision == 8
    assert config.max_condition_depth == 6
    assert config.max_condition_nodes == 100
    assert config.low_confidence_threshold == 0.70
    assert config.unusual_in_degree_threshold == 4
    assert config.unusual_out_degree_threshold == 3


@pytest.mark.asyncio
async def test_empty_inventory_and_source_mismatch_fail_before_provider_transport() -> None:
    provider = _provider(_empty_batch_responder())
    empty = await extract_routing(
        provider=provider,
        document=_document(2),
        inventory=(),
        nodes=(),
        entry_node_ids=(),
        source_binding=_binding(),
    )
    assert empty.status is RoutingExtractionStatus.failed
    assert empty.failures[0].code == "ROUTING_EMPTY_INVENTORY"
    assert provider.call_count == 0

    inventory = _inventory(2)
    mismatch = _binding().model_copy(update={"snapshot_sha256": "b" * 64})
    with pytest.raises(ValueError, match="validated source"):
        await extract_routing(
            provider=provider,
            document=_document(2),
            inventory=inventory,
            nodes=_nodes(inventory),
            entry_node_ids=(inventory[0].node_id,),
            source_binding=mismatch,
        )
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_structurally_invalid_preliminary_graph_fails_without_artifact() -> None:
    inventory = _inventory(2)
    result = await extract_routing(
        provider=_provider(_empty_batch_responder()),
        document=_document(2),
        inventory=inventory,
        nodes=tuple(_node(item) for item in inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
    )
    assert result.status is RoutingExtractionStatus.failed
    assert result.graph is None
    assert result.failures[-1].code == "ROUTING_GRAPH_INVALID"


@pytest.mark.asyncio
async def test_complete_request_cache_hits_only_inside_one_open_run() -> None:
    batch = RoutingEvidenceBatch(
        chunk_id="forward-000001",
        pass_kind=RoutingPassKind.forward,
        examined_item_ids=("Q0",),
        evidence=(),
        unresolved_references=(),
        notes=(),
    )
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(FakeStep.output(batch),),
    )
    descriptor = provider.inspect_schema(RoutingEvidenceBatch)
    prompt = render_system_prompt()
    messages = (ProviderMessage(role="user", content=prompt.content),)
    limiter = ConcurrencyLimiter(1)
    cache = ParsedModelCache()
    kwargs = {
        "provider": provider,
        "messages": messages,
        "response_model": RoutingEvidenceBatch,
        "config": RoutingConfig(),
        "pass_kind": RoutingPassKind.forward,
        "chunk_id": "forward-000001",
        "prompt": prompt,
        "expected_descriptor": descriptor,
        "limiter": limiter,
        "cache": cache,
    }
    first = await _generate_cached(**kwargs)  # type: ignore[arg-type]
    second = await _generate_cached(**kwargs)  # type: ignore[arg-type]
    assert first.call.cache_hit is False
    assert second.call.cache_hit is True
    assert second.call.transport_attempts == 0
    assert provider.call_count == 1
    with pytest.raises(TypeError, match="validated Pydantic"):
        cache.put(next(iter(cache._values)), "not-a-model")  # type: ignore[arg-type,attr-defined]
    cache.close()


@pytest.mark.parametrize(
    ("reason", "inventory", "batch"),
    (
        (
            RiskPredicate.branch_target,
            _inventory(4),
            _batch(
                (
                    _transition("a", "Q0", "Q1", source_order=0, condition=_condition()),
                    _transition("b", "Q0", "Q2", source_order=0, condition=_condition()),
                )
            ),
        ),
        (
            RiskPredicate.cross_section,
            (
                _item("Q0", 0, section=("A",)),
                _item("Q1", 1, section=("B",)),
            ),
            _batch(
                (
                    _transition(
                        "a",
                        "Q0",
                        "Q1",
                        source_order=0,
                        source_section=("A",),
                        target_section=("B",),
                    ),
                )
            ),
        ),
        (
            RiskPredicate.unresolved_target,
            _inventory(2),
            _batch((_transition("a", "Q0", "MISSING", source_order=0),)),
        ),
        (
            RiskPredicate.ambiguous_target,
            (
                _item("Q0", 0),
                _item("Q1", 1),
                _item("Q1", 2).model_copy(update={"node_id": "question:main:q1-duplicate"}),
            ),
            _batch((_transition("a", "Q0", "Q1", source_order=0),)),
        ),
        (
            RiskPredicate.opaque_condition,
            _inventory(2),
            _batch(
                (_transition("a", "Q0", "Q1", source_order=0, condition=_condition(opaque=True)),)
            ),
        ),
        (
            RiskPredicate.cycle,
            _inventory(3),
            _batch(
                (
                    _transition("a", "Q0", "Q1", source_order=0),
                    _transition("b", "Q1", "Q0", source_order=1),
                )
            ),
        ),
        (
            RiskPredicate.low_confidence,
            _inventory(2),
            _batch((_transition("a", "Q0", "Q1", source_order=0, confidence=0.69),)),
        ),
        (
            RiskPredicate.unusual_in_degree,
            _inventory(5),
            _batch(
                tuple(
                    _transition(f"in-{index}", f"Q{index}", "Q4", source_order=index)
                    for index in range(4)
                )
            ),
        ),
        (
            RiskPredicate.unusual_out_degree,
            _inventory(4),
            _batch(
                tuple(
                    _transition(f"out-{index}", "Q0", f"Q{index}", source_order=0)
                    for index in range(1, 4)
                )
            ),
        ),
    ),
)
def test_each_fixed_risk_predicate_selects_pass_b(
    reason: RiskPredicate,
    inventory: tuple[InventoryItem, ...],
    batch: RoutingEvidenceBatch,
) -> None:
    selected = select_pass_b_targets(inventory, (batch,), RoutingConfig())

    assert selected
    assert any(reason in target.reasons for target in selected)
    assert tuple(target.source_order for target in selected) == tuple(
        sorted(target.source_order for target in selected)
    )


def test_unresolved_reference_field_also_selects_examined_region() -> None:
    batch = _batch(
        (),
        examined=("Q0",),
        unresolved=(_reference("UNKNOWN"),),
    )
    selected = select_pass_b_targets(_inventory(2), (batch,), RoutingConfig())
    assert selected[0].node_id.endswith(":q0")
    assert RiskPredicate.unresolved_target in selected[0].reasons


@pytest.mark.asyncio
async def test_no_risk_sections_use_one_forward_pass_and_stable_chunks() -> None:
    provider = _provider(_empty_batch_responder())
    inventory = _inventory(6)
    result = await extract_routing(
        provider=provider,
        document=_document(6),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(max_inventory_items_per_call=2),
    )

    assert result.status is RoutingExtractionStatus.success
    assert result.graph is not None
    assert provider.call_count == 3
    assert [record.chunk_id for record in result.calls] == [
        "forward-000001",
        "forward-000002",
        "forward-000003",
    ]
    assert all(record.pass_kind is RoutingPassKind.forward for record in result.calls)


@pytest.mark.asyncio
async def test_one_failed_chunk_is_partial_and_all_failed_chunks_have_no_graph() -> None:
    inventory = _inventory(4)
    one_failure = _provider(_empty_batch_responder(fail_chunk="forward-000002"))
    partial = await extract_routing(
        provider=one_failure,
        document=_document(4),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(
            max_inventory_items_per_call=2,
            retry=RetryConfig(max_attempts=1),
        ),
    )
    assert partial.status is RoutingExtractionStatus.partial
    assert partial.graph is not None
    assert [failure.code for failure in partial.failures] == ["ROUTING_PROVIDER_TRANSPORT"]

    async def all_fail(_request: FakeRequest) -> object:
        raise ProviderTransportError(retryable=False)

    failed_provider = _provider(all_fail)
    failed = await extract_routing(
        provider=failed_provider,
        document=_document(4),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(
            max_inventory_items_per_call=2,
            retry=RetryConfig(max_attempts=1),
        ),
    )
    assert failed.status is RoutingExtractionStatus.failed
    assert failed.graph is None


@pytest.mark.asyncio
async def test_routing_normalizes_retry_success_truncation_and_malformed_region() -> None:
    inventory = _inventory(2)
    valid = RoutingEvidenceBatch(
        chunk_id="forward-000001",
        pass_kind=RoutingPassKind.forward,
        examined_item_ids=("Q0", "Q1"),
        evidence=(),
        unresolved_references=(),
        notes=(),
    )
    retrying = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(
            FakeStep.transport_error(retryable=True),
            FakeStep.output(valid),
        ),
    )
    retried = await extract_routing(
        provider=retrying,
        document=_document(2),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(retry=RetryConfig(initial_delay_seconds=0.0, max_delay_seconds=0.0)),
    )
    assert retried.status is RoutingExtractionStatus.success
    assert retried.calls[0].transport_attempts == 2

    truncated_provider = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(FakeStep.output(valid, finish_reason="length"),),
    )
    truncated = await extract_routing(
        provider=truncated_provider,
        document=_document(2),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(retry=RetryConfig(max_attempts=1)),
    )
    assert truncated.status is RoutingExtractionStatus.failed
    assert truncated.failures[0].code == "ROUTING_RESPONSE_TRUNCATED"

    wrong_region = valid.model_copy(update={"chunk_id": "wrong-region"})
    malformed_provider = DeterministicFakeProvider(
        capabilities=_capabilities(),
        steps=(FakeStep.output(wrong_region),),
    )
    malformed = await extract_routing(
        provider=malformed_provider,
        document=_document(2),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
    )
    assert malformed.status is RoutingExtractionStatus.failed
    assert malformed.failures[0].code == "ROUTING_RESPONSE_INVALID"


def _incoming_transition() -> TransitionEvidence:
    return TransitionEvidence(
        evidence_type="transition",
        local_id="incoming:1",
        perspective=EvidencePerspective.incoming,
        origin=EvidenceOrigin.incoming_extraction,
        source=_reference("Q0"),
        target=_reference("Q1"),
        transition_kind=TransitionKind.unconditional,
        condition=None,
        source_span=_span(0),
        native_expression=None,
        explicitly_stated=True,
        confidence=0.95,
        ambiguity_note=None,
    )


@pytest.mark.asyncio
async def test_risky_region_runs_independent_pass_b_and_merges_evidence() -> None:
    seen_passes: list[str] = []

    async def respond(request: FakeRequest) -> object:
        task = _task_message(request)
        if task.startswith("PASS: forward"):
            seen_passes.append("forward")
            return RoutingEvidenceBatch(
                chunk_id="forward-000001",
                pass_kind=RoutingPassKind.forward,
                examined_item_ids=("Q0", "Q1"),
                evidence=(
                    _transition(
                        "forward:1",
                        "Q0",
                        "Q1",
                        source_order=0,
                        confidence=0.6,
                    ),
                ),
                unresolved_references=(),
                notes=(),
            )
        seen_passes.append("incoming")
        assert "forward:1" not in task
        assert "confidence" not in task
        return RoutingEvidenceBatch(
            chunk_id="incoming-000001",
            pass_kind=RoutingPassKind.incoming_activation,
            examined_item_ids=("Q1",),
            evidence=(_incoming_transition(),),
            unresolved_references=(),
            notes=(),
        )

    inventory = _inventory(2)
    result = await extract_routing(
        provider=_provider(respond),
        document=_document(2),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
    )

    assert result.status is RoutingExtractionStatus.success
    assert seen_passes == ["forward", "incoming"]
    assert result.graph is not None
    assert len(result.graph.edges) == 1
    assert len(result.graph.edges[0].evidence_ids) == 2
    assert [call.pass_kind for call in result.calls] == [
        RoutingPassKind.forward,
        RoutingPassKind.incoming_activation,
    ]


@pytest.mark.asyncio
async def test_cross_section_pass_b_packet_includes_independent_predecessor_context() -> None:
    inventory = (
        _item("Q0", 0, section=("A",)),
        _item("Q1", 1, section=("A",)),
        _item("Q2", 2, section=("B",)),
        _item("Q3", 3, section=("B",)),
    )

    async def respond(request: FakeRequest) -> object:
        task = _task_message(request)
        chunk_id = json.loads(task.split("CHUNK_JSON: ", maxsplit=1)[1].splitlines()[0])
        if task.startswith("PASS: forward"):
            items = _data_block(task, "ITEM_INVENTORY")
            assert isinstance(items, list)
            examined = tuple(item["source_item_id"] for item in items)
            evidence = (
                (
                    _transition(
                        "forward:cross-section",
                        "Q1",
                        "Q2",
                        source_order=1,
                        source_section=("A",),
                        target_section=("B",),
                    ),
                )
                if examined == ("Q0", "Q1")
                else ()
            )
            return RoutingEvidenceBatch(
                chunk_id=chunk_id,
                pass_kind=RoutingPassKind.forward,
                examined_item_ids=examined,
                evidence=evidence,
                unresolved_references=(),
                notes=(),
            )

        relevant = _data_block(task, "RELEVANT_ITEM_INVENTORY")
        assert isinstance(relevant, list)
        relevant_ids = tuple(item["source_item_id"] for item in relevant)
        windows = _data_block(task, "RETRIEVED_SOURCE_WINDOWS")
        assert isinstance(windows, str)
        assert "Q1" in relevant_ids
        assert "Q1: synthetic item 1" in windows
        incoming = _incoming_transition().model_copy(
            update={
                "source": _reference("Q1", section=("A",)),
                "target": _reference("Q2", section=("B",)),
                "source_span": _span(1),
            }
        )
        return RoutingEvidenceBatch(
            chunk_id=chunk_id,
            pass_kind=RoutingPassKind.incoming_activation,
            examined_item_ids=("Q2",),
            evidence=(incoming,),
            unresolved_references=(),
            notes=(),
        )

    result = await extract_routing(
        provider=_provider(respond),
        document=_document(4),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(max_inventory_items_per_call=2),
    )

    assert result.status is RoutingExtractionStatus.success
    assert result.graph is not None
    assert len(result.graph.edges) == 1
    assert len(result.graph.edges[0].evidence_ids) == 2


def test_full_pass_b_target_chunk_keeps_separate_predecessor_context() -> None:
    inventory = (
        _item("Q0", 0, section=("A",)),
        _item("Q1", 1, section=("B",)),
        _item("Q2", 2, section=("B",)),
    )
    targets = inventory[1:]

    relevant = _relevant_inventory(targets, inventory, maximum=2)

    assert [item.source_item_id for item in relevant] == ["Q0"]


@pytest.mark.asyncio
async def test_invalid_source_quote_discards_entire_region_with_safe_failure() -> None:
    async def respond(_request: FakeRequest) -> object:
        invalid = _transition("bad", "Q0", "Q1", source_order=0).model_copy(
            update={"source_span": _span(0, quote="private nonmatching quote")}
        )
        return RoutingEvidenceBatch(
            chunk_id="forward-000001",
            pass_kind=RoutingPassKind.forward,
            examined_item_ids=("Q0", "Q1"),
            evidence=(invalid,),
            unresolved_references=(),
            notes=(),
        )

    inventory = _inventory(2)
    result = await extract_routing(
        provider=_provider(respond),
        document=_document(2),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
    )
    assert result.status is RoutingExtractionStatus.failed
    assert result.failures[-1].code == "ROUTING_EVIDENCE_INVALID"
    assert "private nonmatching quote" not in repr(result.failures)


@pytest.mark.asyncio
@pytest.mark.parametrize("review_mode", ("valid", "invalid-citation", "provider-failure"))
async def test_reviewer_orchestration_appends_only_valid_cited_decisions(
    review_mode: str,
) -> None:
    async def respond(request: FakeRequest) -> object:
        task = _task_message(request)
        if task.startswith("PASS: forward"):
            return RoutingEvidenceBatch(
                chunk_id="forward-000001",
                pass_kind=RoutingPassKind.forward,
                examined_item_ids=("Q0", "Q1"),
                evidence=(_transition("unresolved", "Q0", "MISSING", source_order=0),),
                unresolved_references=(_reference("MISSING"),),
                notes=(),
            )
        if task.startswith("PASS: incoming_activation"):
            targets = _data_block(task, "TARGET_ITEMS")
            assert isinstance(targets, list)
            return RoutingEvidenceBatch(
                chunk_id="incoming-000001",
                pass_kind=RoutingPassKind.incoming_activation,
                examined_item_ids=tuple(item["source_item_id"] for item in targets),
                evidence=(),
                unresolved_references=(),
                notes=(),
            )
        if review_mode == "provider-failure":
            raise ProviderTransportError(retryable=False)
        packet = _data_block(task, "REVIEW_PACKET")
        assert isinstance(packet, dict)
        discrepancy = packet["discrepancies"][0]
        candidate = packet["candidates"][0]
        evidence = packet["evidence"][0]
        cited = (
            evidence["observation"]["source_span"]["span_id"]
            if review_mode == "valid"
            else "span:not-supplied"
        )
        return RoutingReviewerResponse(
            reviewed_discrepancy_ids=(discrepancy["discrepancy_id"],),
            decisions=(
                ReviewerDecisionOutput(
                    discrepancy_ids=(discrepancy["discrepancy_id"],),
                    candidate_ids=(candidate["candidate_id"],),
                    evidence_ids=(evidence["evidence_id"],),
                    cited_span_ids=(cited,),
                    action=ReviewAction.reject_candidate,
                    replacement=None,
                    rationale="native reviewer prose",
                    confidence=0.8,
                    needs_human_review=False,
                ),
            ),
        )

    inventory = _inventory(2)
    result = await extract_routing(
        provider=_provider(respond),
        document=_document(2),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
    )
    assert result.graph is not None
    decisions = result.graph.routing_audit.review_decisions
    if review_mode == "valid":
        assert result.calls[-1].pass_kind == "reviewer"
        assert result.status is RoutingExtractionStatus.success
        assert len(decisions) == 1
        assert decisions[0].action is ReviewAction.reject_candidate
        assert "native reviewer prose" not in decisions[0].rationale
    else:
        assert result.status is RoutingExtractionStatus.partial
        assert decisions == ()
        expected = (
            "ROUTING_REVIEW_INVALID"
            if review_mode == "invalid-citation"
            else "ROUTING_PROVIDER_TRANSPORT"
        )
        assert result.failures[-1].code == expected


@pytest.mark.asyncio
async def test_completion_order_does_not_change_stable_result_order() -> None:
    inventory = _inventory(6)
    provider = _provider(
        _empty_batch_responder(
            delay=lambda chunk_id: {
                "forward-000001": 0.03,
                "forward-000002": 0.02,
                "forward-000003": 0.01,
            }[chunk_id]
        )
    )
    result = await extract_routing(
        provider=provider,
        document=_document(6),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(max_inventory_items_per_call=2, max_concurrency=3),
    )
    assert [record.chunk_id for record in result.calls] == [
        "forward-000001",
        "forward-000002",
        "forward-000003",
    ]


@pytest.mark.asyncio
async def test_shared_limiter_enforces_exact_ceiling_across_parallel_calls() -> None:
    inventory = _inventory(6)
    provider = _provider(_empty_batch_responder(delay=lambda _chunk_id: 0.02))
    result = await extract_routing(
        provider=provider,
        document=_document(6),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
        config=RoutingConfig(max_inventory_items_per_call=1, max_concurrency=2),
    )
    assert result.peak_concurrency == 2
    assert provider.peak_concurrency == 2


@pytest.mark.asyncio
async def test_routing_propagates_cancellation() -> None:
    control = asyncio.CancelledError()

    async def stop(_request: FakeRequest) -> object:
        raise control

    inventory = _inventory(2)
    with pytest.raises(type(control)):
        await extract_routing(
            provider=_provider(stop),
            document=_document(2),
            inventory=inventory,
            nodes=_nodes(inventory),
            entry_node_ids=(inventory[0].node_id,),
            source_binding=_binding(),
        )


@pytest.mark.asyncio
async def test_capability_rejection_and_schema_drift_happen_before_source_send() -> None:
    sent = False

    async def responder(_request: FakeRequest) -> object:
        nonlocal sent
        sent = True
        raise AssertionError

    unsupported = DeterministicFakeProvider(
        capabilities=_capabilities(strict_schema=False),
        responder=responder,
    )
    inventory = _inventory(2)
    with pytest.raises(ProviderCapabilityError, match="strict structured output"):
        await extract_routing(
            provider=unsupported,
            document=_document(2),
            inventory=inventory,
            nodes=_nodes(inventory),
            entry_node_ids=(inventory[0].node_id,),
            source_binding=_binding(),
        )
    assert sent is False

    drifting = _provider(_empty_batch_responder())
    drifting.schema_drift_after_inspections = 2
    with pytest.raises(ProviderCapabilityError, match="schema descriptor changed"):
        await extract_routing(
            provider=drifting,
            document=_document(2),
            inventory=inventory,
            nodes=_nodes(inventory),
            entry_node_ids=(inventory[0].node_id,),
            source_binding=_binding(),
        )


@pytest.mark.asyncio
async def test_request_limit_rejects_before_provider_call_with_safe_error() -> None:
    provider = DeterministicFakeProvider(
        capabilities=_capabilities(max_input_tokens=4_100),
        responder=_empty_batch_responder(),
    )
    inventory = _inventory(2)
    result = await extract_routing(
        provider=provider,
        document=_document(2),
        inventory=inventory,
        nodes=_nodes(inventory),
        entry_node_ids=(inventory[0].node_id,),
        source_binding=_binding(),
    )
    assert result.status is RoutingExtractionStatus.failed
    assert provider.call_count == 0
    assert result.failures[0].message == "The routing request exceeds its token limit."
    assert "synthetic item" not in repr(result)


def _review_packet() -> ReviewerPromptPacket:
    inventory = (_item("Q0", 0), _item("Q1", 1))
    span = _span(0)
    observation = _transition("review", "Q0", "Q1", source_order=0)
    record = EvidenceRecord(evidence_id="evidence:1", observation=observation)
    candidate = CandidateEdge(
        candidate_id="candidate:1",
        source_node_id=inventory[0].node_id,
        target_node_id=inventory[1].node_id,
        target_reference=_reference("Q1"),
        kind=EdgeKind.unconditional,
        condition=None,
        priority=None,
        evidence_ids=(record.evidence_id,),
        confidence=0.6,
        status=CandidateStatus.needs_agent_review,
    )
    discrepancy = RoutingDiscrepancy(
        discrepancy_id="discrepancy:1",
        kind=DiscrepancyKind.incoming_mismatch,
        candidate_ids=(candidate.candidate_id,),
        evidence_ids=(record.evidence_id,),
        source_span_ids=(span.span_id,),
        summary="A fixed safe discrepancy summary.",
        needs_human_review=False,
        resolved_by_decision_id=None,
    )
    return ReviewerPromptPacket(
        item_inventory=inventory,
        discrepancies=(discrepancy,),
        candidates=(candidate,),
        evidence=(record,),
        source_spans=(span,),
    )


@pytest.mark.parametrize(
    "action",
    (
        ReviewAction.confirm_candidate,
        ReviewAction.reject_candidate,
        ReviewAction.unresolved,
    ),
)
def test_reviewer_actions_become_append_only_safe_decisions(action: ReviewAction) -> None:
    packet = _review_packet()
    output = ReviewerDecisionOutput(
        discrepancy_ids=("discrepancy:1",),
        candidate_ids=("candidate:1",),
        evidence_ids=("evidence:1",),
        cited_span_ids=("temporary:0",),
        action=action,
        replacement=None,
        rationale="model-native prose must not be retained",
        confidence=0.8,
        needs_human_review=action is ReviewAction.unresolved,
    )
    response = RoutingReviewerResponse(
        reviewed_discrepancy_ids=("discrepancy:1",),
        decisions=(output,),
    )
    decisions = build_review_decisions(
        packet=packet,
        response=response,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
    )
    assert decisions[0].action is action
    assert decisions[0].rationale == "The bounded cited evidence supports the recorded action."
    assert "model-native prose" not in repr(decisions)


def test_overlapping_reviewer_decisions_chain_and_discrepancies_share_packets() -> None:
    base_packet = _review_packet()
    first = base_packet.discrepancies[0]
    overlapping = first.model_copy(update={"discrepancy_id": "discrepancy:2"})
    packet = base_packet.model_copy(update={"discrepancies": (first, overlapping)})
    output = ReviewerDecisionOutput(
        discrepancy_ids=("discrepancy:1",),
        candidate_ids=("candidate:1",),
        evidence_ids=("evidence:1",),
        cited_span_ids=("temporary:0",),
        action=ReviewAction.reject_candidate,
        replacement=None,
        rationale="first then second",
        confidence=0.8,
        needs_human_review=False,
    )
    second_output = output.model_copy(update={"discrepancy_ids": ("discrepancy:2",)})
    response = RoutingReviewerResponse(
        reviewed_discrepancy_ids=("discrepancy:1", "discrepancy:2"),
        decisions=(output, second_output),
    )

    decisions = build_review_decisions(
        packet=packet,
        response=response,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
    )

    assert decisions[0].supersedes_decision_id is None
    assert decisions[1].supersedes_decision_id == decisions[0].decision_id
    assert decisions[1].decision_id != decisions[0].decision_id
    follow_up = build_review_decisions(
        packet=packet,
        response=response,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
        existing_decisions=decisions,
    )
    assert follow_up[0].supersedes_decision_id == decisions[-1].decision_id
    assert follow_up[1].supersedes_decision_id == follow_up[0].decision_id

    separate = first.model_copy(
        update={
            "discrepancy_id": "discrepancy:3",
            "candidate_ids": ("candidate:other",),
        }
    )
    batches = _coalesced_discrepancy_batches((first, overlapping, separate), 2)
    assert [[item.discrepancy_id for item in batch] for batch in batches] == [
        ["discrepancy:1", "discrepancy:2"],
        ["discrepancy:3"],
    ]


def test_reviewer_replace_round_trips_and_invalid_citations_change_nothing() -> None:
    packet = _review_packet()
    replacement = packet.candidates[0]
    replacement_payload = {
        "source_node_id": replacement.source_node_id,
        "target_node_id": replacement.target_node_id,
        "target_reference": replacement.target_reference,
        "kind": replacement.kind,
        "condition": replacement.condition,
        "priority": replacement.priority,
        "evidence_ids": replacement.evidence_ids,
    }
    output = ReviewerDecisionOutput(
        discrepancy_ids=("discrepancy:1",),
        candidate_ids=("candidate:1",),
        evidence_ids=("evidence:1",),
        cited_span_ids=("temporary:0",),
        action=ReviewAction.replace_candidate,
        replacement=replacement_payload,  # type: ignore[arg-type]
        rationale="replace",
        confidence=0.9,
        needs_human_review=False,
    )
    base_response = RoutingReviewerResponse(
        reviewed_discrepancy_ids=("discrepancy:1",),
        decisions=(output,),
    )
    response = base_response.model_copy(
        update={"decisions": (output,)},
    )
    decisions = build_review_decisions(
        packet=packet,
        response=response,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
    )
    assert decisions[0].replacement is not None

    assert output.replacement is not None
    contradictory_replacement = output.replacement.model_copy(
        update={"target_reference": _reference("Q0")}
    )
    contradictory = response.model_copy(
        update={
            "decisions": (output.model_copy(update={"replacement": contradictory_replacement}),)
        }
    )
    with pytest.raises(ReviewValidationError, match="review citations are invalid"):
        build_review_decisions(
            packet=packet,
            response=contradictory,
            prompt_version="1.0.0",
            prompt_sha256="b" * 64,
        )

    invalid = response.model_copy(
        update={
            "decisions": (output.model_copy(update={"cited_span_ids": ("span:not-supplied",)}),)
        }
    )
    with pytest.raises(ReviewValidationError, match="review citations are invalid"):
        build_review_decisions(
            packet=packet,
            response=invalid,
            prompt_version="1.0.0",
            prompt_sha256="b" * 64,
        )

    wrong_coverage = response.model_copy(
        update={"reviewed_discrepancy_ids": ("discrepancy:not-supplied",)}
    )
    with pytest.raises(ReviewValidationError, match="review citations are invalid"):
        build_review_decisions(
            packet=packet,
            response=wrong_coverage,
            prompt_version="1.0.0",
            prompt_sha256="b" * 64,
        )
    with pytest.raises(ReviewValidationError, match="review citations are invalid"):
        build_review_decisions(
            packet=packet,
            response=response,
            prompt_version="1.0.0",
            prompt_sha256="b" * 64,
            max_source_spans_per_decision=0,
        )


@pytest.mark.parametrize(
    "failure",
    (
        "unknown_discrepancy",
        "unknown_candidate",
        "unknown_evidence",
        "outside_span_closure",
        "unknown_replacement_endpoint",
    ),
)
def test_reviewer_rejection_matrix_creates_no_decision_or_packet_mutation(failure: str) -> None:
    packet = _review_packet()
    candidate = packet.candidates[0]
    replacement = {
        "source_node_id": candidate.source_node_id,
        "target_node_id": candidate.target_node_id,
        "target_reference": candidate.target_reference,
        "kind": candidate.kind,
        "condition": candidate.condition,
        "priority": candidate.priority,
        "evidence_ids": candidate.evidence_ids,
    }
    output = ReviewerDecisionOutput(
        discrepancy_ids=("discrepancy:1",),
        candidate_ids=("candidate:1",),
        evidence_ids=("evidence:1",),
        cited_span_ids=("temporary:0",),
        action=ReviewAction.replace_candidate,
        replacement=replacement,  # type: ignore[arg-type]
        rationale="replace",
        confidence=0.9,
        needs_human_review=False,
    )
    base_response = RoutingReviewerResponse(
        reviewed_discrepancy_ids=("discrepancy:1",),
        decisions=(output,),
    )
    if failure == "unknown_discrepancy":
        output = output.model_copy(update={"discrepancy_ids": ("discrepancy:missing",)})
    elif failure == "unknown_candidate":
        output = output.model_copy(update={"candidate_ids": ("candidate:missing",)})
    elif failure == "unknown_evidence":
        output = output.model_copy(update={"evidence_ids": ("evidence:missing",)})
    elif failure == "outside_span_closure":
        extra_span = _span(1).model_copy(update={"span_id": "temporary:outside"})
        packet = packet.model_copy(update={"source_spans": packet.source_spans + (extra_span,)})
        output = output.model_copy(update={"cited_span_ids": (extra_span.span_id,)})
    else:
        assert output.replacement is not None
        output = output.model_copy(
            update={
                "replacement": output.replacement.model_copy(
                    update={"target_node_id": "question:missing"}
                )
            }
        )
    response = base_response.model_copy(
        update={"decisions": (output,)},
    )
    before = packet.model_dump_json()
    decisions = ()

    with pytest.raises(ReviewValidationError, match="review citations are invalid"):
        decisions = build_review_decisions(
            packet=packet,
            response=response,
            prompt_version="1.0.0",
            prompt_sha256="b" * 64,
        )

    assert decisions == ()
    assert packet.model_dump_json() == before


def test_cache_key_contains_every_contract_component_and_cache_is_destroyed() -> None:
    base = ProviderCacheKey(
        adapter_identity="fake-adapter-v1",
        provider="fake",
        model="routing-fake-v1",
        pass_kind="forward",
        prompt_version="1.0.0",
        prompt_sha256="a" * 64,
        canonical_schema_sha256="b" * 64,
        request_schema_sha256="c" * 64,
        generation_settings=(("temperature", "0.0"),),
        request_sha256="d" * 64,
    )
    variants = (
        base.__class__(**(base.__dict__ | {"adapter_identity": "other"})),
        base.__class__(**(base.__dict__ | {"provider": "other"})),
        base.__class__(**(base.__dict__ | {"model": "other"})),
        base.__class__(**(base.__dict__ | {"pass_kind": "review"})),
        base.__class__(**(base.__dict__ | {"prompt_version": "2.0.0"})),
        base.__class__(**(base.__dict__ | {"prompt_sha256": "e" * 64})),
        base.__class__(**(base.__dict__ | {"canonical_schema_sha256": "e" * 64})),
        base.__class__(**(base.__dict__ | {"request_schema_sha256": "e" * 64})),
        base.__class__(**(base.__dict__ | {"generation_settings": (("seed", "1"),)})),
        base.__class__(**(base.__dict__ | {"request_sha256": "e" * 64})),
    )
    assert all(variant != base for variant in variants)

    cache = ParsedModelCache()
    cache.put(
        base,
        RoutingEvidenceBatch(
            chunk_id="forward-000001",
            pass_kind=RoutingPassKind.forward,
            examined_item_ids=("Q0",),
            evidence=(),
            unresolved_references=(),
            notes=(),
        ),
    )
    assert cache.size == 1
    cache.close()
    assert cache.size == 0
    with pytest.raises(RuntimeError, match="cache is closed"):
        cache.get(base)


@pytest.mark.asyncio
async def test_parsed_model_cache_does_not_survive_between_runs() -> None:
    provider = _provider(_empty_batch_responder())
    inventory = _inventory(2)
    kwargs = {
        "provider": provider,
        "document": _document(2),
        "inventory": inventory,
        "nodes": _nodes(inventory),
        "entry_node_ids": (inventory[0].node_id,),
        "source_binding": _binding(),
    }
    first = await extract_routing(**kwargs)
    second = await extract_routing(**kwargs)
    assert first.cache_entries_after_run == 0
    assert second.cache_entries_after_run == 0
    assert provider.call_count == 2


def test_review_response_digest_is_deterministic_without_storing_response_body() -> None:
    packet = _review_packet()
    output = ReviewerDecisionOutput(
        discrepancy_ids=("discrepancy:1",),
        candidate_ids=("candidate:1",),
        evidence_ids=("evidence:1",),
        cited_span_ids=("temporary:0",),
        action=ReviewAction.reject_candidate,
        replacement=None,
        rationale="private reviewer prose",
        confidence=0.8,
        needs_human_review=False,
    )
    response = RoutingReviewerResponse(
        reviewed_discrepancy_ids=("discrepancy:1",), decisions=(output,)
    )
    decisions = build_review_decisions(
        packet=packet,
        response=response,
        prompt_version="1.0.0",
        prompt_sha256="b" * 64,
    )
    expected = hashlib.sha256(
        json.dumps(
            response.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert decisions[0].provider_response_sha256 == expected
    assert "private reviewer prose" not in decisions[0].rationale
