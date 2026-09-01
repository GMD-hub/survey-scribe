"""Frozen typed extraction results and stable diagnostics."""

from __future__ import annotations

from copy import deepcopy
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictStr, computed_field, model_validator

T = TypeVar("T")

if TYPE_CHECKING:
    from survey_scribe.serialization.artifacts import ArtifactSerializer


class ResultStatus(StrEnum):
    """Derived extraction outcome."""

    success = "success"
    partial = "partial"
    failed = "failed"


class DiagnosticSeverity(StrEnum):
    """Operational effect of a diagnostic."""

    info = "info"
    warning = "warning"
    error = "error"


class DiagnosticCode(StrEnum):
    """Stable built-in diagnostic codes."""

    quality_low_confidence = "QUALITY_LOW_CONFIDENCE"
    quality_missing_categories = "QUALITY_MISSING_CATEGORIES"
    quality_duplicate_raw_name = "QUALITY_DUPLICATE_RAW_NAME"
    quality_overlap_deduped = "QUALITY_OVERLAP_DEDUPED"
    quality_possible_duplicate = "QUALITY_POSSIBLE_DUPLICATE"
    quality_module_reconciled = "QUALITY_MODULE_RECONCILED"
    metadata_incomplete = "METADATA_INCOMPLETE"
    source_unreadable = "SOURCE_UNREADABLE"
    provider_failed = "PROVIDER_FAILED"
    provider_truncated = "PROVIDER_TRUNCATED"
    validation_failed = "VALIDATION_FAILED"
    block_failed = "BLOCK_FAILED"


class Diagnostic(BaseModel):
    """One stable diagnostic without raw provider response data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: DiagnosticCode | str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.warning
    details: dict[str, Any] = Field(default_factory=dict)


class FailedBlock(BaseModel):
    """A source block that did not produce usable structured output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str
    message: str
    source_order: int | None = Field(default=None, ge=0)


class ArtifactKind(StrEnum):
    """Published artifact role."""

    main = "main"
    sidecar = "sidecar"
    manifest = "manifest"
    legacy = "legacy"
    projection = "projection"
    active_pointer = "active_pointer"


class ArtifactReference(BaseModel):
    """Reference to one validated local artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ArtifactKind | str
    path: Path
    generation_id: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
SemanticVersion = Annotated[
    StrictStr,
    Field(
        pattern=(
            r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
            r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
            r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
        )
    ),
]


class PromptArtifactProvenance(BaseModel):
    """One routing prompt identity without prompt or questionnaire content."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    pass_kind: Literal["forward", "incoming_activation", "reviewer"]
    version: SemanticVersion
    prompt_sha256: Sha256


class ArtifactProvenance(BaseModel):
    """Digest-only provenance supplied to an artifact serializer."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    source_sha256: tuple[Sha256, ...]
    model_response_sha256: tuple[Sha256, ...]
    prompt_versions: tuple[PromptArtifactProvenance, ...]

    @model_validator(mode="after")
    def require_stable_unique_records(self) -> ArtifactProvenance:
        """Reject duplicate digests and duplicate prompt identities."""
        if len(set(self.source_sha256)) != len(self.source_sha256):
            raise ValueError("source digests must be unique")
        if len(set(self.model_response_sha256)) != len(self.model_response_sha256):
            raise ValueError("model response digests must be unique")
        prompt_keys = tuple(
            (item.pass_kind, item.version, item.prompt_sha256) for item in self.prompt_versions
        )
        if len(set(prompt_keys)) != len(prompt_keys):
            raise ValueError("prompt provenance records must be unique")
        return self


class ExtractionResult(BaseModel, Generic[T]):
    """Frozen result envelope; caller-owned output ``T`` can remain mutable."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    output: T | None
    survey_id: str | None = None
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    diagnostics: tuple[Diagnostic, ...] = ()
    failed_blocks: tuple[FailedBlock, ...] = ()
    artifacts: tuple[ArtifactReference, ...] = ()
    artifact_provenance: ArtifactProvenance | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    @model_validator(mode="after")
    def derive_survey_id(self) -> ExtractionResult[T]:
        """Use the output survey identifier when no envelope value was supplied."""
        if self.survey_id is None and self.output is not None:
            output_survey_id = getattr(self.output, "survey_id", None)
            if isinstance(output_survey_id, str):
                object.__setattr__(self, "survey_id", output_survey_id)
        return self

    @computed_field(return_type=ResultStatus)
    @property
    def status(self) -> ResultStatus:
        """Derive status from usable output and operational failures.

        Returns:
            ``failed`` without output, ``partial`` after an operational failure,
            or ``success`` when usable output has no operational failure.
        """
        if self.output is None:
            return ResultStatus.failed
        partial_codes = {
            DiagnosticCode.metadata_incomplete,
            DiagnosticCode.source_unreadable,
            DiagnosticCode.provider_failed,
            DiagnosticCode.provider_truncated,
            DiagnosticCode.validation_failed,
            DiagnosticCode.block_failed,
        }
        if self.failed_blocks:
            return ResultStatus.partial
        if any(
            diagnostic.severity is DiagnosticSeverity.error or diagnostic.code in partial_codes
            for diagnostic in self.diagnostics
        ):
            return ResultStatus.partial
        return ResultStatus.success

    def serialization_snapshot(self) -> dict[str, Any]:
        """Return a detached JSON-compatible snapshot of the current envelope.

        Returns:
            A deep-copied dictionary that does not change if caller-owned output
            is later mutated.
        """
        return deepcopy(self.model_dump(mode="json"))

    def write(
        self,
        output_dir: str | PathLike[str],
        *,
        sidecar: bool = True,
        overwrite: bool = False,
        serializer: ArtifactSerializer[T] | None = None,
    ) -> ExtractionResult[T]:
        """Publish one versioned generation and return its artifact references.

        Args:
            output_dir: Trusted local directory for stable and generation files.
            sidecar: Whether to include the diagnostic sidecar.
            overwrite: Whether to publish a new generation when stable artifacts
                already exist.
            serializer: Optional typed serializer. Exact ``SurveySVIS`` uses the
                legacy v1 serializer; other output uses generic JSON by default.

        Returns:
            A new frozen result containing references and SHA-256 digests for the
            published files.

        Raises:
            ArtifactCollisionError: Artifacts exist and overwrite is disabled, or
                another writer holds the survey lock.
            ArtifactWriteError: Validation, generation, projection, pointer, or
                filesystem publication fails.

        Note:
            The process-owned survey lock covers recovery and publication. A
            durable journal repairs a hard exit before another write proceeds.
        """
        from survey_scribe.serialization.artifacts import write_result

        return write_result(
            self,
            Path(output_dir),
            sidecar=sidecar,
            overwrite=overwrite,
            serializer=serializer,
        )
