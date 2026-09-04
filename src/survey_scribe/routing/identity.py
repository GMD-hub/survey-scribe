"""Deterministic identity, source binding, and evidence mechanics for routing."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from typing import Literal, TypeAlias

from pydantic import model_validator

from survey_scribe.models.routing import EvidenceRecord, InventoryItem, RoutingSourceBinding
from survey_scribe.models.svis import SurveySVIS
from survey_scribe.routing.contracts import (
    CanonicalRoutingCondition,
    EvidenceObservation,
    ExtractedRoutingCondition,
    ItemReference,
    NodeKind,
    NonEmptyStr,
    PositiveInt,
    SourceSpan,
    StrictRoutingModel,
)
from survey_scribe.routing.normalization import (
    identity_slug,
    normalize_section_path_value,
    normalized_alias_value,
)
from survey_scribe.sources.base import SourceDocument, render_table

SOURCE_CONVERSION_SCHEMA_VERSION = "1.0"

DigestFactory: TypeAlias = Callable[[bytes], str]
ResolutionStatus: TypeAlias = Literal["resolved", "ambiguous", "unresolved"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPES_BY_FORMAT: Mapping[str, frozenset[str]] = {
    "csv": frozenset({"text/csv"}),
    "docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    "htm": frozenset({"text/html"}),
    "html": frozenset({"text/html"}),
    "markdown": frozenset({"text/markdown"}),
    "md": frozenset({"text/markdown"}),
    "pdf": frozenset({"application/pdf"}),
    "text": frozenset({"text/plain"}),
    "txt": frozenset({"text/plain"}),
    "xlsx": frozenset({"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
}


class IdentityError(ValueError):
    """Base error for deterministic routing identity mechanics."""


class IdentityCollisionError(IdentityError):
    """Two distinct routing facts received one deterministic identifier."""


class SourceBindingError(IdentityError):
    """A routing binding does not identify the supplied validated snapshot."""


class SourceEvidenceError(IdentityError):
    """Source evidence cannot be verified against its normalized block."""


class NodeIdentityInput(StrictRoutingModel):
    """Stable inputs used by Python to assign one canonical node identifier."""

    source_item_id: NonEmptyStr | None
    raw_reference: NonEmptyStr
    section_path: tuple[NonEmptyStr, ...]
    logical_ordinal: PositiveInt
    normalized_source_text: NonEmptyStr
    kind: NodeKind


class ReferenceResolution(StrictRoutingModel):
    """Exact resolution result that retains every ordered ambiguous candidate."""

    status: ResolutionStatus
    node_id: NonEmptyStr | None
    candidate_node_ids: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def validate_resolution_shape(self) -> ReferenceResolution:
        if len(set(self.candidate_node_ids)) != len(self.candidate_node_ids):
            raise ValueError("reference resolution candidates must be unique")
        if self.status == "resolved":
            if self.node_id is None or self.candidate_node_ids != (self.node_id,):
                raise ValueError("resolved references require exactly one matching node")
        elif self.node_id is not None:
            raise ValueError("non-resolved references cannot have a resolved node")
        elif self.status == "ambiguous" and len(self.candidate_node_ids) < 2:
            raise ValueError("ambiguous references require at least two candidates")
        elif self.status == "unresolved" and self.candidate_node_ids:
            raise ValueError("unresolved references cannot have candidates")
        return self


class ConditionResolution(StrictRoutingModel):
    """Canonical condition projection or its ordered failed reference results."""

    condition: CanonicalRoutingCondition | None
    references: tuple[ReferenceResolution, ...]


class VerifiedEvidence(StrictRoutingModel):
    """Verified, de-duplicated source spans and Python-identified evidence."""

    source_spans: tuple[SourceSpan, ...]
    records: tuple[EvidenceRecord, ...]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _digest(payload: bytes, digest_factory: DigestFactory) -> str:
    value = digest_factory(payload)
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise IdentityError("identity digest factory must return one lowercase SHA-256 value")
    return value


def normalize_section_path(section_path: Iterable[str]) -> tuple[str, ...]:
    """Normalize a section namespace without discarding its hierarchy."""
    try:
        return normalize_section_path_value(section_path)
    except ValueError as error:
        raise IdentityError(str(error)) from None


def normalized_alias(value: str) -> str:
    """Return one bounded exact alias key without semantic or fuzzy matching."""
    try:
        return normalized_alias_value(value)
    except ValueError as error:
        raise IdentityError(str(error)) from None


def printed_identity_key(
    source_item_id: str,
    section_path: Iterable[str],
    kind: NodeKind,
) -> tuple[tuple[str, ...], NodeKind, str]:
    """Return the exact section-scoped key used for printed item identity."""
    return normalize_section_path(section_path), kind, normalized_alias(source_item_id)


def assign_node_ids(
    identities: Iterable[NodeIdentityInput],
    *,
    survey_id: str,
    source_version_digest: str,
    digest_factory: DigestFactory = _sha256,
) -> tuple[str, ...]:
    """Assign canonical IDs from printed identity or source-scoped fallback inputs."""
    seeds = tuple(identities)
    if not survey_id.strip():
        raise IdentityError("survey identity must be nonempty")
    _require_source_digest(source_version_digest)

    bases: list[str] = []
    fallback_flags: list[bool] = []
    for seed in seeds:
        if seed.source_item_id is not None:
            namespace = "/".join(normalize_section_path(seed.section_path)) or "root"
            base = f"{seed.kind.value}:{namespace}:{normalized_alias(seed.source_item_id)}"
            fallback_flags.append(False)
        else:
            normalized_text = _normalize_source_text(seed.normalized_source_text)
            text_digest = _digest(normalized_text.encode("utf-8"), digest_factory)
            payload = _canonical_json(
                {
                    "identity_schema": "routing-node-fallback-v1",
                    "logical_ordinal": seed.logical_ordinal,
                    "normalized_section_path": normalize_section_path(seed.section_path),
                    "normalized_source_text_sha256": text_digest,
                    "source_version_sha256": source_version_digest,
                    "survey_id": unicodedata.normalize("NFKC", survey_id).strip(),
                }
            )
            base = f"{seed.kind.value}:fallback:{_digest(payload, digest_factory)}"
            fallback_flags.append(True)
        bases.append(base)

    positions: dict[str, list[int]] = {}
    for position, base in enumerate(bases):
        positions.setdefault(base, []).append(position)

    assigned = list(bases)
    for base, duplicates in positions.items():
        if len(duplicates) == 1:
            continue
        if any(fallback_flags[position] for position in duplicates):
            raise IdentityCollisionError("fallback node identity collision")
        for position in duplicates:
            assigned[position] = f"{base}:duplicate-{seeds[position].logical_ordinal}"
    if len(set(assigned)) != len(assigned):
        raise IdentityCollisionError("canonical node identity collision")
    return tuple(assigned)


class IdentityResolver:
    """Resolve bounded exact aliases against one stable logical inventory."""

    def __init__(self, inventory: Iterable[InventoryItem]) -> None:
        ordered = tuple(
            item
            for _position, item in sorted(
                enumerate(inventory),
                key=lambda pair: (pair[1].source_order, pair[0]),
            )
        )
        if len({item.node_id for item in ordered}) != len(ordered):
            raise IdentityError("identity resolver inventory node identifiers must be unique")
        scoped: dict[tuple[tuple[str, ...], NodeKind, str], list[str]] = {}
        global_index: dict[tuple[NodeKind, str], list[str]] = {}
        for item in ordered:
            identity = item.source_item_id or item.raw_reference
            alias = normalized_alias(identity)
            section = normalize_section_path(item.section_path)
            scoped.setdefault((section, item.kind, alias), []).append(item.node_id)
            global_index.setdefault((item.kind, alias), []).append(item.node_id)
        self._scoped = {key: tuple(values) for key, values in scoped.items()}
        self._global = {key: tuple(values) for key, values in global_index.items()}

    def resolve(
        self,
        reference: ItemReference,
        *,
        default_section_path: tuple[str, ...] = (),
    ) -> ReferenceResolution:
        """Resolve one exact item reference; canonical hints are never consulted."""
        identity = reference.source_item_id or reference.raw_reference
        alias = normalized_alias(identity)
        section_path = reference.section_path or default_section_path
        if section_path:
            candidates = self._scoped.get(
                (normalize_section_path(section_path), reference.node_kind, alias),
                (),
            )
            if not candidates and not reference.section_path:
                candidates = self._global.get((reference.node_kind, alias), ())
        else:
            candidates = self._global.get((reference.node_kind, alias), ())
        if len(candidates) == 1:
            return ReferenceResolution(
                status="resolved",
                node_id=candidates[0],
                candidate_node_ids=candidates,
            )
        if candidates:
            return ReferenceResolution(
                status="ambiguous",
                node_id=None,
                candidate_node_ids=candidates,
            )
        return ReferenceResolution(status="unresolved", node_id=None, candidate_node_ids=())


def resolve_extracted_condition(
    condition: ExtractedRoutingCondition,
    resolver: IdentityResolver,
    *,
    default_section_path: tuple[str, ...] = (),
) -> ConditionResolution:
    """Convert extracted references only when every controlling question is exact."""
    references: list[ReferenceResolution] = []

    def project(current: ExtractedRoutingCondition) -> CanonicalRoutingCondition | None:
        question_node_id: str | None = None
        failed = False
        if current.item_reference is not None:
            resolution = resolver.resolve(
                current.item_reference,
                default_section_path=default_section_path,
            )
            references.append(resolution)
            question_node_id = resolution.node_id
            failed = resolution.status != "resolved"
        canonical_children: tuple[CanonicalRoutingCondition, ...] | None = None
        if current.children is not None:
            projected = tuple(project(child) for child in current.children)
            if any(child is None for child in projected):
                failed = True
            else:
                canonical_children = tuple(child for child in projected if child is not None)
        if failed:
            return None
        return CanonicalRoutingCondition(
            operator=current.operator,
            question_node_id=question_node_id,
            value=current.value,
            values=current.values,
            children=canonical_children,
            raw_text=current.raw_text,
        )

    return ConditionResolution(condition=project(condition), references=tuple(references))


def create_source_binding(
    document: SourceDocument,
    svis: SurveySVIS,
    *,
    source_conversion_schema_version: str = SOURCE_CONVERSION_SCHEMA_VERSION,
) -> RoutingSourceBinding:
    """Create a binding from a converted document's validated private snapshot."""
    digest = _document_source_digest(document)
    _validate_svis_source(svis, document)
    if not source_conversion_schema_version.strip():
        raise SourceBindingError("source conversion schema version must be nonempty")
    if not svis.survey_id.strip():
        raise SourceBindingError("survey identity must be nonempty")
    return RoutingSourceBinding(
        survey_id=svis.survey_id,
        source_name=document.source_name,
        media_type=document.media_type,
        snapshot_sha256=digest,
        source_conversion_schema_version=source_conversion_schema_version,
    )


def validate_source_binding(
    binding: RoutingSourceBinding,
    document: SourceDocument,
    svis: SurveySVIS,
    *,
    source_conversion_schema_version: str = SOURCE_CONVERSION_SCHEMA_VERSION,
) -> None:
    """Validate a binding without reopening or rehashing an untrusted path."""
    expected = create_source_binding(
        document,
        svis,
        source_conversion_schema_version=source_conversion_schema_version,
    )
    if binding != expected:
        raise SourceBindingError("routing source binding does not match the validated snapshot")


def verify_source_quote(span: SourceSpan, document: SourceDocument) -> None:
    """Verify exact source provenance and bounded whitespace-normalized quote text."""
    blocks = {block.id: block for block in document.blocks}
    block = blocks.get(span.block_id)
    if block is None:
        raise SourceEvidenceError("evidence names an unknown normalized source block")
    provenance = block.provenance
    if span.source_name != document.source_name or span.source_name != provenance.source_name:
        raise SourceEvidenceError("evidence source name does not match its normalized source block")
    if span.pages != provenance.pages or span.sheet != provenance.sheet:
        raise SourceEvidenceError("evidence provenance does not match its normalized source block")
    expected_text = block.text
    if block.table is not None and span.row_start is not None and span.row_end is not None:
        table_start = provenance.row_start
        table_end = provenance.row_end
        if (
            table_start is None
            or table_end is None
            or span.row_start < table_start
            or span.row_end > table_end
        ):
            raise SourceEvidenceError(
                "evidence provenance does not match its normalized source block"
            )
        first = span.row_start - table_start
        last = span.row_end - table_start + 1
        expected_text = render_table(block.table.rows[first:last])
    elif span.row_start != provenance.row_start or span.row_end != provenance.row_end:
        raise SourceEvidenceError("evidence provenance does not match its normalized source block")
    quote = _normalize_evidence_quote(span.source_quote)
    expected_quote = _normalize_evidence_quote(expected_text)
    if not quote or quote not in expected_quote:
        raise SourceEvidenceError("evidence quote does not match its normalized source block")


def build_evidence_records(
    observations: Iterable[EvidenceObservation],
    document: SourceDocument,
    *,
    digest_factory: DigestFactory = _sha256,
) -> VerifiedEvidence:
    """Verify evidence and assign source-version-scoped span and evidence IDs."""
    source_digest = _document_source_digest(document)
    spans_by_id: dict[str, tuple[bytes, SourceSpan]] = {}
    evidence_by_id: dict[str, tuple[bytes, EvidenceRecord]] = {}
    for observation in observations:
        verify_source_quote(observation.source_span, document)
        span_data = observation.source_span.model_dump(mode="json")
        span_data.pop("span_id", None)
        span_payload = _canonical_json(
            {
                "source_span": span_data,
                "source_version_sha256": source_digest,
                "span_schema": "routing-source-span-v1",
            }
        )
        span_id = f"span:{_digest(span_payload, digest_factory)}"
        stable_span = observation.source_span.model_copy(update={"span_id": span_id})
        existing_span = spans_by_id.get(span_id)
        if existing_span is not None and existing_span[0] != span_payload:
            raise IdentityCollisionError("source span identity collision")
        spans_by_id.setdefault(span_id, (span_payload, stable_span))

        semantic_data = observation.model_dump(mode="json")
        semantic_data.pop("local_id", None)
        source_span_data = semantic_data.get("source_span")
        if isinstance(source_span_data, dict):
            source_span_data.pop("span_id", None)
        _remove_model_identity_hints(semantic_data)
        evidence_payload = _canonical_json(
            {
                "evidence": semantic_data,
                "evidence_schema": "routing-evidence-v1",
                "source_version_sha256": source_digest,
            }
        )
        evidence_id = f"evidence:{_digest(evidence_payload, digest_factory)}"
        existing_evidence = evidence_by_id.get(evidence_id)
        if existing_evidence is not None:
            if existing_evidence[0] != evidence_payload:
                raise IdentityCollisionError("evidence identity collision")
            continue
        stable_observation = observation.model_copy(update={"source_span": stable_span})
        evidence_by_id[evidence_id] = (
            evidence_payload,
            EvidenceRecord(evidence_id=evidence_id, observation=stable_observation),
        )
    return VerifiedEvidence(
        source_spans=tuple(span for _payload, span in spans_by_id.values()),
        records=tuple(record for _payload, record in evidence_by_id.values()),
    )


def _slug(value: str) -> str:
    return identity_slug(value)


def _normalize_source_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _normalize_evidence_quote(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split())


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_source_digest(value: str) -> None:
    if _SHA256_RE.fullmatch(value) is None:
        raise SourceBindingError("source document requires one validated snapshot digest")


def _document_source_digest(document: SourceDocument) -> str:
    digest = document.snapshot_sha256
    if digest is None:
        raise SourceBindingError("source document requires one validated snapshot digest")
    _require_source_digest(digest)
    return digest


def _validate_svis_source(svis: SurveySVIS, document: SourceDocument) -> None:
    if svis.source_file != document.source_name:
        raise SourceBindingError("SVIS source name does not match the normalized source")
    source_format = unicodedata.normalize("NFKC", svis.source_format).strip().casefold()
    normalized_format = source_format.removeprefix(".")
    accepted_media_types = _MEDIA_TYPES_BY_FORMAT.get(normalized_format)
    if source_format != document.media_type.casefold() and (
        accepted_media_types is None or document.media_type.casefold() not in accepted_media_types
    ):
        raise SourceBindingError("SVIS source format does not match the normalized media type")


def _remove_model_identity_hints(value: object) -> None:
    if isinstance(value, dict):
        value.pop("canonical_hint", None)
        for nested in value.values():
            _remove_model_identity_hints(nested)
    elif isinstance(value, list):
        for nested in value:
            _remove_model_identity_hints(nested)


__all__ = [
    "ConditionResolution",
    "DigestFactory",
    "IdentityCollisionError",
    "IdentityError",
    "IdentityResolver",
    "NodeIdentityInput",
    "ReferenceResolution",
    "SOURCE_CONVERSION_SCHEMA_VERSION",
    "SourceBindingError",
    "SourceEvidenceError",
    "VerifiedEvidence",
    "assign_node_ids",
    "build_evidence_records",
    "create_source_binding",
    "normalize_section_path",
    "normalized_alias",
    "printed_identity_key",
    "resolve_extracted_condition",
    "validate_source_binding",
    "verify_source_quote",
]
