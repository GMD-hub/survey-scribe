"""Durable, recoverable local artifact generation and publication."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Generic, Literal, Protocol, TypeAlias, TypeVar
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from survey_scribe.errors import (
    ArtifactCollisionError,
    ArtifactWriteError,
    redact_exception,
)
from survey_scribe.models.svis import SurveySVIS
from survey_scribe.results import (
    ArtifactKind,
    ArtifactProvenance,
    ArtifactReference,
    ExtractionResult,
    PromptArtifactProvenance,
)
from survey_scribe.serialization.legacy import legacy_json_bytes

T = TypeVar("T")
T_contra = TypeVar("T_contra", contravariant=True)

_INTERNAL_ROOT = ".survey-scribe"
_SURVEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", re.ASCII)
_GENERATION_ID = re.compile(r"^[0-9a-f]{32}$", re.ASCII)
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$", re.ASCII)
_RESERVED_WINDOWS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_ACTIVE_DIRECTORY_IDENTITIES: ContextVar[tuple[tuple[Path, int, int], ...]] = ContextVar(
    "survey_scribe_artifact_directory_identities",
    default=(),
)


class ArtifactFileRecord(BaseModel):
    """One digest-only immutable file record in an artifact manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: StrictStr
    path: StrictStr
    sha256: StrictStr = Field(pattern=_SHA256_PATTERN)
    size: StrictInt = Field(ge=0)


class RoutedManifestMetadata(BaseModel):
    """Typed routed metadata supplied before generation IDs are assigned."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    routing_schema_version: Literal["1.0"]
    graph_schema_version: Literal["1.0"]
    routed_main_sha256: StrictStr = Field(pattern=_SHA256_PATTERN)
    legacy_projection_sha256: StrictStr = Field(pattern=_SHA256_PATTERN)
    prompt_versions: tuple[PromptArtifactProvenance, ...]
    source_sha256: tuple[Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)], ...]
    model_response_sha256: tuple[Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)], ...]

    @model_validator(mode="after")
    def validate_digest_metadata(self) -> RoutedManifestMetadata:
        if self.routing_schema_version != self.graph_schema_version:
            raise ValueError("routed manifest versions must be equal")
        for values, label in (
            (self.source_sha256, "source digests"),
            (self.model_response_sha256, "model response digests"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        if len(set(self.prompt_versions)) != len(self.prompt_versions):
            raise ValueError("prompt version records must be unique")
        return self


class ArtifactManifestV1(BaseModel):
    """Strict parser for the unchanged legacy artifact manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[1]
    survey_id: StrictStr
    run_id: StrictStr
    generation_id: StrictStr = Field(pattern=r"^[0-9a-f]{32}$")
    files: tuple[ArtifactFileRecord, ...]


class ArtifactManifestV2(BaseModel):
    """Strict routed manifest with versions and digests but no prose fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[2]
    survey_id: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    run_id: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    generation_id: StrictStr = Field(pattern=r"^[0-9a-f]{32}$")
    routing_schema_version: Literal["1.0"]
    graph_schema_version: Literal["1.0"]
    routed_main_sha256: StrictStr = Field(pattern=_SHA256_PATTERN)
    legacy_projection_sha256: StrictStr = Field(pattern=_SHA256_PATTERN)
    prompt_versions: tuple[PromptArtifactProvenance, ...]
    source_sha256: tuple[Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)], ...]
    model_response_sha256: tuple[Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)], ...]
    files: tuple[ArtifactFileRecord, ...]

    @model_validator(mode="after")
    def validate_routed_file_hashes(self) -> ArtifactManifestV2:
        if self.routing_schema_version != self.graph_schema_version:
            raise ValueError("routed manifest versions must be equal")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("manifest file paths must be unique")
        if any(
            item.kind
            not in {
                ArtifactKind.main.value,
                ArtifactKind.projection.value,
                ArtifactKind.sidecar.value,
            }
            or _SAFE_FILENAME.fullmatch(item.path) is None
            for item in self.files
        ):
            raise ValueError("routed manifest file records must use fixed kinds and safe paths")
        main = tuple(item for item in self.files if item.kind == ArtifactKind.main.value)
        projection = tuple(
            item for item in self.files if item.kind == ArtifactKind.projection.value
        )
        if len(main) != 1 or main[0].sha256 != self.routed_main_sha256:
            raise ValueError("routed main manifest digest does not match")
        if len(projection) != 1 or projection[0].sha256 != self.legacy_projection_sha256:
            raise ValueError("legacy projection manifest digest does not match")
        if len(set(self.source_sha256)) != len(self.source_sha256):
            raise ValueError("source digests must be unique")
        if len(set(self.model_response_sha256)) != len(self.model_response_sha256):
            raise ValueError("model response digests must be unique")
        if len(set(self.prompt_versions)) != len(self.prompt_versions):
            raise ValueError("prompt version records must be unique")
        return self


ArtifactManifest: TypeAlias = Annotated[
    ArtifactManifestV1 | ArtifactManifestV2,
    Field(discriminator="schema_version"),
]
_MANIFEST_ADAPTER = TypeAdapter(ArtifactManifest)


class _RoutedArtifactSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal[2] = 2
    survey_id: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    run_id: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    generation_id: StrictStr = Field(pattern=r"^[0-9a-f]{32}$")
    routing_schema_version: Literal["1.0"]
    graph_schema_version: Literal["1.0"]
    routed_main_sha256: StrictStr = Field(pattern=_SHA256_PATTERN)
    legacy_projection_sha256: StrictStr = Field(pattern=_SHA256_PATTERN)
    prompt_versions: tuple[PromptArtifactProvenance, ...]
    source_sha256: tuple[Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)], ...]
    model_response_sha256: tuple[Annotated[StrictStr, Field(pattern=_SHA256_PATTERN)], ...]


@dataclass(frozen=True)
class SerializedArtifact:
    """One immutable generation file and its optional stable publication."""

    kind: ArtifactKind | str
    generation_filename: str
    content: bytes
    publication_filename: str | None = None
    publication_kind: ArtifactKind | str | None = None


@dataclass(frozen=True)
class ArtifactPlan:
    """Detached serializer output consumed by the publication transaction."""

    survey_id: str
    files: tuple[SerializedArtifact, ...]
    manifest_schema_version: int = 1
    routed_metadata: RoutedManifestMetadata | None = None

    def __post_init__(self) -> None:
        _validate_survey_id(self.survey_id)
        if self.manifest_schema_version not in {1, 2}:
            raise ArtifactWriteError(
                "validation", "Artifact manifest schema version is unsupported"
            )
        if self.manifest_schema_version == 1 and self.routed_metadata is not None:
            raise ArtifactWriteError(
                "validation", "Artifact manifest schema version 1 cannot contain routed metadata"
            )
        if self.manifest_schema_version == 2 and self.routed_metadata is None:
            raise ArtifactWriteError(
                "validation", "Artifact manifest schema version 2 requires routed metadata"
            )
        if sum(str(file.kind) == ArtifactKind.main.value for file in self.files) != 1:
            raise ArtifactWriteError(
                "validation", "An artifact plan must contain exactly one main file"
            )
        generation_names: set[str] = set()
        publication_names: set[str] = set()
        for file in self.files:
            _validate_artifact_filename(file.generation_filename)
            if file.generation_filename in generation_names:
                raise ArtifactWriteError(
                    "validation", "Artifact generation filenames must be unique"
                )
            generation_names.add(file.generation_filename)
            if not isinstance(file.content, bytes):
                raise ArtifactWriteError("validation", "Serialized artifact content must be bytes")
            if file.publication_filename is None:
                if file.publication_kind is not None:
                    raise ArtifactWriteError(
                        "validation", "A publication kind requires a publication filename"
                    )
                continue
            _validate_artifact_filename(file.publication_filename)
            if file.publication_kind is None:
                raise ArtifactWriteError(
                    "validation", "A publication filename requires a publication kind"
                )
            if file.publication_filename in publication_names:
                raise ArtifactWriteError(
                    "validation", "Artifact publication filenames must be unique"
                )
            publication_names.add(file.publication_filename)


class ArtifactSerializer(Protocol[T_contra]):
    """Port that creates a detached, typed artifact plan for one output."""

    def build_plan(self, output: T_contra, *, survey_id: str) -> ArtifactPlan:
        """Build a complete detached plan without filesystem side effects."""
        ...


class JsonArtifactSerializer(Generic[T]):
    """Typed JSON serializer for generic non-SVIS Pydantic-compatible output."""

    def __init__(self, output_type: type[T], *, filename_suffix: str = "_result.json") -> None:
        self._output_type = output_type
        self._filename_suffix = filename_suffix

    def build_plan(self, output: T, *, survey_id: str) -> ArtifactPlan:
        """Revalidate a detached JSON snapshot and build a generic JSON plan."""
        if type(output) is not self._output_type:
            raise ArtifactWriteError("validation", "The serializer output type does not match")
        try:
            adapter = TypeAdapter(self._output_type)
            dumped = deepcopy(adapter.dump_python(output, mode="json"))
            snapshot = adapter.validate_python(dumped)
        except (TypeError, ValueError, ValidationError) as error:
            raise ArtifactWriteError("validation", redact_exception(error)) from None
        _require_snapshot_identity(snapshot, survey_id)
        filename = f"{survey_id}{self._filename_suffix}"
        _validate_artifact_filename(filename)
        try:
            content = legacy_json_bytes(snapshot)
        except (TypeError, ValueError) as error:
            raise ArtifactWriteError("validation", redact_exception(error)) from None
        return ArtifactPlan(
            survey_id=survey_id,
            files=(
                SerializedArtifact(
                    kind=ArtifactKind.main,
                    generation_filename=filename,
                    content=content,
                    publication_filename=filename,
                    publication_kind=ArtifactKind.projection,
                ),
            ),
        )


class SurveySVISArtifactSerializer:
    """Exact-type legacy v1 SurveySVIS serializer."""

    def build_plan(self, output: SurveySVIS, *, survey_id: str) -> ArtifactPlan:
        """Revalidate a detached exact SurveySVIS snapshot and preserve v1 bytes."""
        if type(output) is not SurveySVIS:
            raise ArtifactWriteError(
                "validation", "Legacy SVIS serialization requires exact output type"
            )
        try:
            snapshot = SurveySVIS.model_validate(deepcopy(output.model_dump(mode="json")))
        except ValidationError as error:
            raise ArtifactWriteError("validation", redact_exception(error)) from None
        _require_snapshot_identity(snapshot, survey_id)
        filename = f"{survey_id}_svis.json"
        content = legacy_json_bytes(snapshot)
        return ArtifactPlan(
            survey_id=survey_id,
            files=(
                SerializedArtifact(
                    kind=ArtifactKind.main,
                    generation_filename=filename,
                    content=content,
                    publication_filename=filename,
                    publication_kind=ArtifactKind.legacy,
                ),
            ),
        )


def parse_artifact_manifest(content: bytes | str) -> ArtifactManifestV1 | ArtifactManifestV2:
    """Parse one strict v1 or routed v2 manifest with a fixed safe failure."""
    try:
        values = json.loads(content)
        if not isinstance(values, Mapping) or type(values.get("schema_version")) is not int:
            raise ValueError
        return _MANIFEST_ADAPTER.validate_python(values)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
        raise ArtifactWriteError("validation", "Artifact manifest is invalid") from None


class _ActivePointer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    survey_id: str
    run_id: str
    generation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    path: str = Field(pattern=r"^generations/[0-9a-f]{32}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _JournalPublication(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    source_filename: str
    kind: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _JournalBackup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: Literal["output", "survey"]
    filename: str
    backup_filename: str | None


class _PublicationJournal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    survey_id: str
    generation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    phase: Literal["prepared", "projection_published", "pointer_published"]
    pointer: _ActivePointer
    publications: tuple[_JournalPublication, ...]
    backups: tuple[_JournalBackup, ...]


@dataclass(frozen=True)
class _Generation:
    generation_id: str
    directory: Path
    manifest_content: bytes
    references: tuple[ArtifactReference, ...]
    publications: tuple[_JournalPublication, ...]


def write_result(
    result: ExtractionResult[T],
    output_dir: Path,
    *,
    sidecar: bool = True,
    overwrite: bool = False,
    serializer: ArtifactSerializer[T] | None = None,
) -> ExtractionResult[T]:
    """Publish one immutable generation through a recoverable transaction."""
    if result.output is None:
        raise ArtifactWriteError("validation", "A failed result has no main output to write")
    survey_id = result.survey_id
    if survey_id is None:
        raise ArtifactWriteError("validation", "The result has no survey_id")
    _validate_survey_id(survey_id)
    sensitive_values = _source_derived_strings(result.output)
    selected_serializer = serializer or _default_serializer(
        result.output,
        provenance=result.artifact_provenance,
    )
    try:
        plan = selected_serializer.build_plan(result.output, survey_id=survey_id)
    except ArtifactWriteError:
        raise
    except Exception as error:
        raise ArtifactWriteError(
            "validation",
            redact_exception(error, sensitive_values=sensitive_values),
        ) from None
    if plan.survey_id != survey_id:
        raise ArtifactWriteError(
            "validation", "The artifact plan survey_id does not match the result"
        )
    routed_publication = plan.routed_metadata is not None

    root = output_dir.resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        internal_root = _ensure_directory(root, _INTERNAL_ROOT)
        aliases_root = _ensure_directory(internal_root, "aliases")
        surveys_root = _ensure_directory(internal_root, "surveys")
    except ArtifactWriteError:
        raise
    except OSError as error:
        if routed_publication:
            raise ArtifactWriteError("setup", "Routed artifact setup failed") from None
        raise ArtifactWriteError(
            "setup",
            redact_exception(error, sensitive_values=sensitive_values),
        ) from None

    alias_key = _identity_key(_portable_identity(survey_id))
    lock_path = aliases_root / f"{alias_key}.lock"
    with _survey_lock(lock_path, survey_id, anchor_path=root) as verify_lock:
        try:
            verify_lock()
            _claim_identity_alias(root, aliases_root, alias_key, survey_id, plan)
            survey_root = _prepare_survey_root(surveys_root, survey_id)
            active_path = survey_root / "active.json"
            _recover_transaction(root, survey_root, survey_id)
            _cleanup_staging(survey_root)
        except ArtifactWriteError:
            raise
        except Exception as error:
            if routed_publication:
                raise ArtifactWriteError("recovery", "Routed artifact recovery failed") from None
            raise ArtifactWriteError(
                "recovery",
                redact_exception(error, sensitive_values=sensitive_values),
            ) from None

        publication_paths = [
            root / file.publication_filename
            for file in plan.files
            if file.publication_filename is not None
        ]
        if not overwrite and (
            _path_exists_no_follow(active_path)
            or any(_path_exists_no_follow(path) for path in publication_paths)
        ):
            raise ArtifactCollisionError(
                "Artifacts already exist for this survey; pass overwrite=True"
            )

        try:
            generation = _write_generation(result, plan, survey_root, sidecar=sidecar)
            verify_lock()
        except Exception as error:
            if isinstance(error, ArtifactWriteError):
                raise
            if routed_publication:
                raise ArtifactWriteError(
                    "generation", "Routed artifact generation failed"
                ) from None
            raise ArtifactWriteError(
                "generation", redact_exception(error, sensitive_values=sensitive_values)
            ) from None

        pointer = _ActivePointer(
            survey_id=survey_id,
            run_id=result.run_id,
            generation_id=generation.generation_id,
            path=f"generations/{generation.generation_id}",
            manifest_sha256=_sha256(generation.manifest_content),
        )
        try:
            verify_lock()
            transaction = _prepare_transaction(
                root,
                survey_root,
                survey_id,
                generation,
                pointer,
            )
        except ArtifactWriteError:
            raise
        except Exception as error:
            if routed_publication:
                raise ArtifactWriteError("journal", "Routed artifact journal failed") from None
            raise ArtifactWriteError(
                "journal",
                redact_exception(error, sensitive_values=sensitive_values),
            ) from None
        journal = _load_journal(transaction / "journal.json", survey_id)
        published = False
        stage = "projection"
        try:
            verify_lock()
            _publication_checkpoint("before_projection")
            published = bool(journal.publications)
            # The active pointer is the public commit marker. Remove it before
            # changing stable projections so a hard exit cannot expose a
            # projection from one generation under another generation's marker.
            _remove_file_durable(active_path)
            _publication_checkpoint("after_commit_marker_clear")
            for publication in journal.publications:
                source = generation.directory / publication.source_filename
                content = _read_bytes_no_follow(source)
                if _sha256(content) != publication.sha256:
                    raise OSError("Generation publication digest changed")
                _atomic_write_bytes(root / publication.filename, content)
            _publication_checkpoint("after_projection")
            journal = _replace_journal_phase(transaction, journal, "projection_published")

            stage = "pointer"
            verify_lock()
            _publication_checkpoint("before_pointer")
            pointer_content = _model_json_bytes(pointer)
            _atomic_write_bytes(active_path, pointer_content)
            _publication_checkpoint("after_pointer")
            journal = _replace_journal_phase(transaction, journal, "pointer_published")
            _safe_remove_tree(transaction)
            verify_lock()
        except Exception as error:
            rollback_error = _rollback_transaction(
                root,
                survey_root,
                transaction,
                journal,
                restore_publications=published,
                restore_pointer=True,
            )
            if routed_publication:
                raise ArtifactWriteError(stage, "Routed artifact publication failed") from None
            message = redact_exception(error, sensitive_values=sensitive_values)
            if rollback_error is not None:
                message = (
                    f"{message}; rollback: "
                    f"{redact_exception(rollback_error, sensitive_values=sensitive_values)}"
                )
            raise ArtifactWriteError(stage, message) from None

        pointer_content = _model_json_bytes(pointer)
        publication_references = tuple(
            ArtifactReference(
                kind=publication.kind,
                path=root / publication.filename,
                generation_id=generation.generation_id,
                sha256=publication.sha256,
            )
            for publication in generation.publications
        )
        references = (
            generation.references
            + publication_references
            + (
                ArtifactReference(
                    kind=ArtifactKind.active_pointer,
                    path=active_path,
                    generation_id=generation.generation_id,
                    sha256=_sha256(pointer_content),
                ),
            )
        )
        return result.model_copy(update={"artifacts": references})


def _default_serializer(
    output: T,
    *,
    provenance: ArtifactProvenance | None,
) -> ArtifactSerializer[T]:
    if type(output) is SurveySVIS:
        return SurveySVISArtifactSerializer()  # type: ignore[return-value]
    from survey_scribe.models.routing import RoutedSurveySVIS

    if type(output) is RoutedSurveySVIS:
        from survey_scribe.serialization.routing import RoutedSurveySVISArtifactSerializer

        return RoutedSurveySVISArtifactSerializer(  # type: ignore[return-value]
            provenance=provenance
        )
    return JsonArtifactSerializer(type(output))


def _require_snapshot_identity(snapshot: Any, survey_id: str) -> None:
    missing = object()
    snapshot_id = getattr(snapshot, "survey_id", missing)
    if snapshot_id is missing and isinstance(snapshot, Mapping):
        snapshot_id = snapshot.get("survey_id", missing)
    if snapshot_id is missing:
        return
    if not isinstance(snapshot_id, str) or snapshot_id != survey_id:
        raise ArtifactWriteError(
            "validation", "The detached output survey_id does not match the result survey_id"
        )


def _validate_survey_id(survey_id: str) -> None:
    reserved_stem = survey_id.split(".", 1)[0].upper()
    if (
        survey_id in {".", ".."}
        or survey_id.endswith((".", " "))
        or _SURVEY_ID.fullmatch(survey_id) is None
        or reserved_stem in _RESERVED_WINDOWS_NAMES
    ):
        raise ArtifactWriteError(
            "validation",
            "survey_id must be a portable non-reserved filename identifier",
        )


def _validate_artifact_filename(filename: str) -> None:
    reserved_stem = filename.split(".", 1)[0].upper()
    if (
        Path(filename).name != filename
        or filename.endswith((".", " "))
        or _SAFE_FILENAME.fullmatch(filename) is None
        or reserved_stem in _RESERVED_WINDOWS_NAMES
    ):
        raise ArtifactWriteError("validation", "Artifact filename is not portable and safe")


def _portable_identity(value: str) -> str:
    return value.rstrip(" .").casefold()


def _prepare_survey_root(surveys_root: Path, survey_id: str) -> Path:
    exact_key = _identity_key(survey_id)
    survey_root = _ensure_directory(surveys_root, exact_key)
    generations = _ensure_directory(survey_root, "generations")
    _reject_reparse(generations, require_directory=True)
    identity_path = survey_root / "identity.json"
    expected = _json_bytes({"schema_version": 1, "survey_id": survey_id})
    if _path_exists_no_follow(identity_path):
        if _read_bytes_no_follow(identity_path) != expected:
            raise ArtifactWriteError("validation", "Internal exact survey identity does not match")
    else:
        _atomic_write_bytes(identity_path, expected)
    return survey_root


def _claim_identity_alias(
    root: Path,
    aliases_root: Path,
    alias_key: str,
    survey_id: str,
    plan: ArtifactPlan,
) -> None:
    expected_names = {
        file.publication_filename for file in plan.files if file.publication_filename is not None
    }
    normalized_names = {name.casefold(): name for name in expected_names}
    for entry in root.iterdir():
        expected = normalized_names.get(entry.name.rstrip(" .").casefold())
        if expected is not None and entry.name != expected:
            raise ArtifactWriteError("validation", "Artifact filename aliases an existing path")

    identity_path = aliases_root / f"{alias_key}.json"
    expected = _json_bytes({"schema_version": 1, "survey_id": survey_id})
    if _path_exists_no_follow(identity_path):
        try:
            identity = json.loads(_read_bytes_no_follow(identity_path))
        except (OSError, ValueError, TypeError) as error:
            raise ArtifactWriteError("validation", redact_exception(error)) from None
        if identity != {"schema_version": 1, "survey_id": survey_id}:
            raise ArtifactWriteError("validation", "survey_id aliases another portable identity")
    else:
        _atomic_write_bytes(identity_path, expected)


@contextmanager
def _survey_lock(lock_path: Path, survey_id: str, *, anchor_path: Path | None = None) -> Any:
    del survey_id
    anchor = anchor_path or lock_path.parent
    identity_paths = tuple(dict.fromkeys((anchor, lock_path.parent.parent, lock_path.parent)))
    with (
        _directory_identity_scope(identity_paths),
        _cooperative_directory_lock(anchor),
        _secured_directory(lock_path.parent) as parent_descriptor,
    ):
        descriptor: int | None = None
        try:
            flags = os.O_CREAT | os.O_RDWR | _O_NOFOLLOW
            descriptor = (
                _open_windows_lock_file(lock_path)
                if parent_descriptor is None
                else os.open(lock_path.name, flags, 0o600, dir_fd=parent_descriptor)
            )
            expected_identity = os.fstat(descriptor)
            if not stat.S_ISREG(expected_identity.st_mode):
                raise OSError("Artifact lock is not a regular file")
            if expected_identity.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            _lock_descriptor(descriptor)
        except OSError as error:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise ArtifactCollisionError(
                    "Another artifact writer is active for this survey"
                ) from None
            raise ArtifactWriteError("lock", redact_exception(error)) from None

        def verify_identity() -> None:
            try:
                current = (
                    os.lstat(lock_path)
                    if parent_descriptor is None
                    else os.stat(lock_path.name, dir_fd=parent_descriptor, follow_symlinks=False)
                )
            except OSError:
                raise ArtifactWriteError("lock", "Artifact lock identity changed") from None
            if (
                stat.S_ISLNK(current.st_mode)
                or getattr(current, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
                or (current.st_dev, current.st_ino)
                != (expected_identity.st_dev, expected_identity.st_ino)
            ):
                raise ArtifactWriteError("lock", "Artifact lock identity changed")

        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
            os.fsync(descriptor)
            verify_identity()
            yield verify_identity
            verify_identity()
        finally:
            with suppress(OSError):
                _unlock_descriptor(descriptor)
            os.close(descriptor)


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _write_generation(
    result: ExtractionResult[T],
    plan: ArtifactPlan,
    survey_root: Path,
    *,
    sidecar: bool,
) -> _Generation:
    generation_id = uuid4().hex
    generations = survey_root / "generations"
    _reject_reparse(generations, require_directory=True)
    staging = generations / f".{generation_id}.staging"
    final = generations / generation_id
    _ensure_directory(generations, staging.name)
    references: list[ArtifactReference] = []
    publications: list[_JournalPublication] = []
    file_records: list[dict[str, Any]] = []
    committed = False
    operation = "file"
    try:
        for file in plan.files:
            path = staging / file.generation_filename
            _write_new_file(path, file.content)
            digest = _sha256(file.content)
            file_records.append(
                {
                    "kind": str(file.kind),
                    "path": file.generation_filename,
                    "sha256": digest,
                    "size": len(file.content),
                }
            )
            if file.publication_filename is not None and file.publication_kind is not None:
                publications.append(
                    _JournalPublication(
                        filename=file.publication_filename,
                        source_filename=file.generation_filename,
                        kind=str(file.publication_kind),
                        sha256=digest,
                    )
                )
        if sidecar:
            operation = "sidecar"
            sidecar_name = f"{plan.survey_id}_sidecar.json"
            _validate_artifact_filename(sidecar_name)
            if plan.routed_metadata is None:
                sidecar_content = _json_bytes(_operational_sidecar(result))
            else:
                sidecar_content = _model_json_bytes(
                    _RoutedArtifactSidecar(
                        survey_id=plan.survey_id,
                        run_id=result.run_id,
                        generation_id=generation_id,
                        **plan.routed_metadata.model_dump(mode="python"),
                    )
                )
            _write_new_file(staging / sidecar_name, sidecar_content)
            file_records.append(
                {
                    "kind": ArtifactKind.sidecar.value,
                    "path": sidecar_name,
                    "sha256": _sha256(sidecar_content),
                    "size": len(sidecar_content),
                }
            )
        operation = "manifest"
        manifest_values = {
            "schema_version": plan.manifest_schema_version,
            "survey_id": plan.survey_id,
            "run_id": result.run_id,
            "generation_id": generation_id,
            "files": file_records,
        }
        if plan.routed_metadata is not None:
            manifest_values.update(plan.routed_metadata.model_dump(mode="json"))
            manifest_content = _model_json_bytes(ArtifactManifestV2.model_validate(manifest_values))
        else:
            manifest_content = _json_bytes(manifest_values)
        _write_new_file(staging / "manifest.json", manifest_content)
        operation = "validation"
        _validate_generation(staging, file_records, staging / "manifest.json")
        operation = "commit"
        _fsync_directory(staging)
        _publication_checkpoint("before_generation_commit")
        _durable_replace(staging, final)
        committed = True
        _register_directory_identity(final)
        _fsync_directory(generations)
        _publication_checkpoint("after_generation_commit")

        for file in plan.files:
            references.append(
                ArtifactReference(
                    kind=file.kind,
                    path=final / file.generation_filename,
                    generation_id=generation_id,
                    sha256=_sha256(file.content),
                )
            )
        if sidecar:
            references.append(
                ArtifactReference(
                    kind=ArtifactKind.sidecar,
                    path=final / f"{plan.survey_id}_sidecar.json",
                    generation_id=generation_id,
                    sha256=str(file_records[-1]["sha256"]),
                )
            )
        references.append(
            ArtifactReference(
                kind=ArtifactKind.manifest,
                path=final / "manifest.json",
                generation_id=generation_id,
                sha256=_sha256(manifest_content),
            )
        )
    except Exception as error:
        if not committed and _path_exists_no_follow(staging):
            _safe_remove_tree(staging)
        if plan.routed_metadata is not None and not isinstance(error, ArtifactWriteError):
            raise ArtifactWriteError(
                "generation", f"Routed artifact generation {operation} failed"
            ) from None
        raise
    return _Generation(
        generation_id=generation_id,
        directory=final,
        manifest_content=manifest_content,
        references=tuple(references),
        publications=tuple(publications),
    )


def _prepare_transaction(
    root: Path,
    survey_root: Path,
    survey_id: str,
    generation: _Generation,
    pointer: _ActivePointer,
) -> Path:
    transaction = survey_root / "transaction"
    staging = survey_root / f".transaction.{generation.generation_id}.staging"
    if _path_exists_no_follow(transaction) or _path_exists_no_follow(staging):
        raise ArtifactWriteError("recovery", "An unrecovered artifact transaction already exists")
    _ensure_directory(survey_root, staging.name)
    backups: list[_JournalBackup] = []
    try:
        for index, publication in enumerate(generation.publications):
            backups.append(
                _backup_target(
                    root / publication.filename,
                    staging,
                    scope="output",
                    index=index,
                )
            )
        backups.append(
            _backup_target(
                survey_root / "active.json",
                staging,
                scope="survey",
                index=len(backups),
            )
        )
        journal = _PublicationJournal(
            survey_id=survey_id,
            generation_id=generation.generation_id,
            phase="prepared",
            pointer=pointer,
            publications=generation.publications,
            backups=tuple(backups),
        )
        _write_new_file(staging / "journal.json", _model_json_bytes(journal))
        _fsync_directory(staging)
        _durable_replace(staging, transaction)
        _register_directory_identity(transaction)
        _fsync_directory(survey_root)
    except Exception:
        if _path_exists_no_follow(staging):
            _safe_remove_tree(staging)
        raise
    return transaction


def _backup_target(
    target: Path,
    transaction_staging: Path,
    *,
    scope: Literal["output", "survey"],
    index: int,
) -> _JournalBackup:
    if not _path_exists_no_follow(target):
        return _JournalBackup(scope=scope, filename=target.name, backup_filename=None)
    _reject_reparse(target, require_directory=False)
    backup_name = f"backup-{index}.bin"
    _write_new_file(transaction_staging / backup_name, _read_bytes_no_follow(target))
    return _JournalBackup(scope=scope, filename=target.name, backup_filename=backup_name)


def _replace_journal_phase(
    transaction: Path,
    journal: _PublicationJournal,
    phase: Literal["projection_published", "pointer_published"],
) -> _PublicationJournal:
    updated = journal.model_copy(update={"phase": phase})
    _atomic_write_bytes(transaction / "journal.json", _model_json_bytes(updated))
    return updated


def _rollback_transaction(
    root: Path,
    survey_root: Path,
    transaction: Path,
    journal: _PublicationJournal,
    *,
    restore_publications: bool,
    restore_pointer: bool,
) -> OSError | None:
    try:
        for backup in journal.backups:
            if backup.scope == "output" and not restore_publications:
                continue
            if backup.scope == "survey" and not restore_pointer:
                continue
            parent = root if backup.scope == "output" else survey_root
            target = parent / backup.filename
            if backup.backup_filename is None:
                _remove_file_durable(target)
            else:
                content = _read_bytes_no_follow(transaction / backup.backup_filename)
                _atomic_write_bytes(target, content)
        _safe_remove_tree(transaction)
    except OSError as error:
        return error
    return None


def _recover_transaction(root: Path, survey_root: Path, survey_id: str) -> None:
    transaction = survey_root / "transaction"
    if not _path_exists_no_follow(transaction):
        return
    _reject_reparse(transaction, require_directory=True)
    journal = _load_journal(transaction / "journal.json", survey_id)
    generation = survey_root / "generations" / journal.generation_id
    _reject_reparse(generation, require_directory=True)
    manifest = generation / "manifest.json"
    manifest_content = _read_bytes_no_follow(manifest)
    if _sha256(manifest_content) != journal.pointer.manifest_sha256:
        raise ArtifactWriteError("recovery", "Recovery generation manifest digest does not match")
    parsed_manifest = parse_artifact_manifest(manifest_content)
    manifest_files = {item.path: item for item in parsed_manifest.files}
    expected_publications = tuple(
        (
            item.path,
            item.path,
            (
                ArtifactKind.legacy.value
                if parsed_manifest.schema_version == 2 or item.path.endswith("_svis.json")
                else ArtifactKind.projection.value
            ),
            item.sha256,
        )
        for item in parsed_manifest.files
        if (parsed_manifest.schema_version == 1 and item.kind == ArtifactKind.main.value)
        or (parsed_manifest.schema_version == 2 and item.kind == ArtifactKind.projection.value)
    )
    actual_publications = tuple(
        (
            item.filename,
            item.source_filename,
            item.kind,
            item.sha256,
        )
        for item in journal.publications
    )
    if actual_publications != expected_publications:
        raise ArtifactWriteError("recovery", "Recovery publications do not match the manifest")
    for publication in journal.publications:
        _validate_artifact_filename(publication.filename)
        _validate_artifact_filename(publication.source_filename)
        source_content = _read_bytes_no_follow(generation / publication.source_filename)
        manifest_file = manifest_files.get(publication.source_filename)
        if (
            manifest_file is None
            or manifest_file.sha256 != publication.sha256
            or manifest_file.size != len(source_content)
            or _sha256(source_content) != publication.sha256
        ):
            raise ArtifactWriteError("recovery", "Recovery publication digest does not match")
        _atomic_write_bytes(root / publication.filename, source_content)
    _atomic_write_bytes(survey_root / "active.json", _model_json_bytes(journal.pointer))
    _safe_remove_tree(transaction)


def _load_journal(path: Path, survey_id: str) -> _PublicationJournal:
    try:
        journal = _PublicationJournal.model_validate_json(_read_bytes_no_follow(path))
    except (OSError, ValidationError, ValueError) as error:
        raise ArtifactWriteError("recovery", redact_exception(error)) from None
    if journal.survey_id != survey_id or journal.pointer.survey_id != survey_id:
        raise ArtifactWriteError("recovery", "Recovery journal survey identity does not match")
    if journal.generation_id != journal.pointer.generation_id:
        raise ArtifactWriteError("recovery", "Recovery journal generation identity does not match")
    if journal.pointer.path != f"generations/{journal.generation_id}":
        raise ArtifactWriteError("recovery", "Recovery pointer path is invalid")
    for publication in journal.publications:
        _validate_artifact_filename(publication.filename)
        _validate_artifact_filename(publication.source_filename)
    for backup in journal.backups:
        if backup.scope == "output":
            _validate_artifact_filename(backup.filename)
        elif backup.filename != "active.json":
            raise ArtifactWriteError("recovery", "Recovery pointer backup path is invalid")
        if (
            backup.backup_filename is not None
            and re.fullmatch(r"backup-[0-9]+\.bin", backup.backup_filename, re.ASCII) is None
        ):
            raise ArtifactWriteError("recovery", "Recovery backup path is invalid")
    return journal


def _cleanup_staging(survey_root: Path) -> None:
    generations = survey_root / "generations"
    _reject_reparse(generations, require_directory=True)
    for path in generations.iterdir():
        if path.name.startswith(".") and path.name.endswith(".staging"):
            generation_id = path.name[1:-8]
            if _GENERATION_ID.fullmatch(generation_id) is None:
                raise ArtifactWriteError("recovery", "Unexpected generation staging path")
            _safe_remove_tree(path)
    for path in survey_root.iterdir():
        if path.name.startswith(".transaction.") and path.name.endswith(".staging"):
            generation_id = path.name[len(".transaction.") : -len(".staging")]
            if _GENERATION_ID.fullmatch(generation_id) is None:
                raise ArtifactWriteError("recovery", "Unexpected transaction staging path")
            _safe_remove_tree(path)


def _write_new_file(path: Path, content: bytes) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    flags |= _O_NOFOLLOW
    with _secured_directory(path.parent) as parent_descriptor:
        descriptor = (
            os.open(path, flags, 0o600)
            if parent_descriptor is None
            else os.open(path.name, flags, 0o600, dir_fd=parent_descriptor)
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)


def _validate_generation(
    generation_directory: Path,
    file_records: list[dict[str, Any]],
    manifest_path: Path,
) -> None:
    manifest_content = _read_bytes_no_follow(manifest_path)
    json.loads(manifest_content)
    try:
        manifest = parse_artifact_manifest(manifest_content)
    except ArtifactWriteError:
        raise OSError("Artifact manifest validation failed") from None
    if tuple(item.model_dump(mode="json") for item in manifest.files) != tuple(file_records):
        raise OSError("Artifact manifest file records do not match the generation")
    for record in file_records:
        filename = str(record["path"])
        _validate_artifact_filename(filename)
        content = _read_bytes_no_follow(generation_directory / filename)
        json.loads(content)
        if len(content) != record["size"] or _sha256(content) != record["sha256"]:
            raise OSError("Artifact generation validation failed")


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    with _secured_directory(path.parent) as parent_descriptor:
        if _path_exists_no_follow(path):
            _reject_reparse(path, require_directory=False)
        if parent_descriptor is None:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                _durable_replace(temporary_path, path)
                _fsync_directory(path.parent)
            finally:
                if _path_exists_no_follow(temporary_path):
                    temporary_path.unlink()
            return

        temporary_name = f".{path.name}.{uuid4().hex}.tmp"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_descriptor)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.fsync(parent_descriptor)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=parent_descriptor)


def _read_bytes_no_follow(path: Path) -> bytes:
    with _secured_directory(path.parent) as parent_descriptor:
        before = _reject_reparse(path, require_directory=False)
        flags = os.O_RDONLY | _O_NOFOLLOW
        descriptor = (
            _open_windows_file_no_follow(path)
            if parent_descriptor is None
            else os.open(path.name, flags, dir_fd=parent_descriptor)
        )
        try:
            after = os.fstat(descriptor)
            if not stat.S_ISREG(after.st_mode):
                raise OSError("Artifact path is not a regular file")
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise OSError("Artifact path changed during no-follow open")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(descriptor)


def _path_exists_no_follow(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


@contextmanager
def _directory_identity_scope(paths: tuple[Path, ...]) -> Any:
    identities: list[tuple[Path, int, int]] = []
    try:
        for path in paths:
            details = os.lstat(path)
            if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                raise ArtifactWriteError("path", "Internal directory anchor is unsafe")
            identities.append((path, details.st_dev, details.st_ino))
    except OSError as error:
        raise ArtifactWriteError("path", redact_exception(error)) from None
    token = _ACTIVE_DIRECTORY_IDENTITIES.set(tuple(identities))
    try:
        yield
    finally:
        _ACTIVE_DIRECTORY_IDENTITIES.reset(token)


def _register_directory_identity(path: Path) -> None:
    active = _ACTIVE_DIRECTORY_IDENTITIES.get()
    if not active or any(expected == path for expected, _device, _inode in active):
        return
    details = os.lstat(path)
    _ACTIVE_DIRECTORY_IDENTITIES.set(active + ((path, details.st_dev, details.st_ino),))


def _verify_active_directory_chain(path: Path) -> None:
    for expected, device, inode in _ACTIVE_DIRECTORY_IDENTITIES.get():
        if path != expected and not path.is_relative_to(expected):
            continue
        try:
            current = os.lstat(expected)
        except OSError:
            raise ArtifactWriteError("path", "Internal directory anchor changed") from None
        if (
            not stat.S_ISDIR(current.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or getattr(current, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
            or (current.st_dev, current.st_ino) != (device, inode)
        ):
            raise ArtifactWriteError("path", "Internal directory anchor changed")


@contextmanager
def _cooperative_directory_lock(path: Path) -> Any:
    with _secured_directory(path) as descriptor:
        if descriptor is None:
            yield
            return
        try:
            _lock_descriptor(descriptor)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise ArtifactCollisionError(
                    "Another artifact writer is active for this output root"
                ) from None
            raise ArtifactWriteError("lock", redact_exception(error)) from None
        try:
            yield
        finally:
            with suppress(OSError):
                _unlock_descriptor(descriptor)


def _reject_reparse(
    path: Path,
    *,
    require_directory: bool,
) -> os.stat_result:
    _verify_active_directory_chain(path)
    details = os.lstat(path)
    if stat.S_ISLNK(details.st_mode) or (
        getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    ):
        raise ArtifactWriteError("path", "Internal symlink or reparse path is not allowed")
    if require_directory and not stat.S_ISDIR(details.st_mode):
        raise ArtifactWriteError("path", "Internal path component is not a directory")
    if not require_directory and not stat.S_ISREG(details.st_mode):
        raise ArtifactWriteError("path", "Artifact path is not a regular file")
    return details


@contextmanager
def _secured_directory(path: Path) -> Any:
    """Retain a verified directory while a path-relative operation uses it."""
    _verify_active_directory_chain(path)
    before = _reject_reparse(path, require_directory=True)
    if os.name == "nt":
        handle, file_index = _open_windows_handle(path, require_directory=True)
        try:
            if before.st_ino and before.st_ino != file_index:
                raise ArtifactWriteError("path", "Internal directory changed during secure open")
            yield None
        finally:
            _close_windows_handle(handle)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        after = os.fstat(descriptor)
        if not stat.S_ISDIR(after.st_mode):
            raise ArtifactWriteError("path", "Internal path component is not a directory")
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ArtifactWriteError("path", "Internal directory changed during secure open")
        _verify_active_directory_chain(path)
        yield descriptor
    finally:
        os.close(descriptor)


def _open_windows_handle(
    path: Path,
    *,
    require_directory: bool,
    create: bool = False,
    write: bool = False,
) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    win_dll = ctypes.WinDLL  # type: ignore[attr-defined]
    win_error = ctypes.WinError  # type: ignore[attr-defined]
    get_last_error = ctypes.get_last_error  # type: ignore[attr-defined]
    kernel32 = win_dll("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)]
    get_information.restype = wintypes.BOOL

    generic_read = 0x80000000
    generic_write = 0x40000000
    share_read_write = 0x1 | 0x2
    open_existing = 3
    open_always = 4
    open_reparse_point = 0x00200000
    backup_semantics = 0x02000000 if require_directory else 0
    handle = create_file(
        str(path),
        generic_read | (generic_write if write else 0),
        share_read_write,
        None,
        open_always if create else open_existing,
        open_reparse_point | backup_semantics,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise win_error(get_last_error())

    information = _ByHandleFileInformation()
    if not get_information(handle, ctypes.byref(information)):
        error = win_error(get_last_error())
        _close_windows_handle(int(handle))
        raise error
    attributes = int(information.file_attributes)
    is_directory = bool(attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10))
    if attributes & _REPARSE_ATTRIBUTE or is_directory != require_directory:
        _close_windows_handle(int(handle))
        message = (
            "Internal symlink or reparse path is not allowed"
            if attributes & _REPARSE_ATTRIBUTE
            else "Internal path has an unexpected type"
        )
        raise ArtifactWriteError("path", message)
    file_index = (int(information.file_index_high) << 32) | int(information.file_index_low)
    return int(handle), file_index


def _close_windows_handle(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    win_dll = ctypes.WinDLL  # type: ignore[attr-defined]
    win_error = ctypes.WinError  # type: ignore[attr-defined]
    get_last_error = ctypes.get_last_error  # type: ignore[attr-defined]
    close_handle = win_dll("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        raise win_error(get_last_error())


def _open_windows_file_no_follow(path: Path) -> int:
    import msvcrt

    handle, _ = _open_windows_handle(path, require_directory=False)
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY)  # type: ignore[attr-defined]
    except Exception:
        _close_windows_handle(handle)
        raise


def _open_windows_lock_file(path: Path) -> int:
    import msvcrt

    handle, _ = _open_windows_handle(
        path,
        require_directory=False,
        create=True,
        write=True,
    )
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDWR)  # type: ignore[attr-defined]
    except Exception:
        _close_windows_handle(handle)
        raise


def _ensure_directory(parent: Path, name: str) -> Path:
    path = parent / name
    with _secured_directory(parent) as parent_descriptor:
        try:
            if parent_descriptor is None:
                os.mkdir(path)
            else:
                os.mkdir(name, dir_fd=parent_descriptor)
        except FileExistsError:
            pass
        else:
            if parent_descriptor is None:
                _fsync_directory(parent)
            else:
                os.fsync(parent_descriptor)
        _reject_reparse(path, require_directory=True)
        _register_directory_identity(path)
    return path


def _safe_remove_tree(path: Path) -> None:
    parent = path.parent
    with _secured_directory(parent) as parent_descriptor:
        if parent_descriptor is None:
            _safe_remove_tree_windows(path)
            _fsync_directory(parent)
            return
        _safe_remove_tree_at(parent_descriptor, path.name)
        os.fsync(parent_descriptor)


def _safe_remove_tree_at(parent_descriptor: int, name: str) -> None:
    details = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    if stat.S_ISLNK(details.st_mode):
        raise OSError("Refusing to remove a symlink or reparse path")
    if not stat.S_ISDIR(details.st_mode):
        raise OSError("Refusing to remove an unexpected artifact path")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _O_NOFOLLOW
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        opened = os.fstat(descriptor)
        if (details.st_dev, details.st_ino) != (opened.st_dev, opened.st_ino):
            raise OSError("Artifact directory changed during secure open")
        with os.scandir(descriptor) as entries:
            for entry in entries:
                entry_details = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISLNK(entry_details.st_mode):
                    raise OSError("Refusing to remove a symlink or reparse path")
                if stat.S_ISDIR(entry_details.st_mode):
                    _safe_remove_tree_at(descriptor, entry.name)
                elif stat.S_ISREG(entry_details.st_mode):
                    os.unlink(entry.name, dir_fd=descriptor)
                else:
                    raise OSError("Refusing to remove an unexpected artifact path")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.rmdir(name, dir_fd=parent_descriptor)


def _safe_remove_tree_windows(path: Path) -> None:
    with _secured_directory(path):
        for entry in path.iterdir():
            details = os.lstat(entry)
            if stat.S_ISLNK(details.st_mode) or (
                getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
            ):
                raise OSError("Refusing to remove a symlink or reparse path")
            if stat.S_ISDIR(details.st_mode):
                _safe_remove_tree_windows(entry)
            elif stat.S_ISREG(details.st_mode):
                entry.unlink()
            else:
                raise OSError("Refusing to remove an unexpected artifact path")
    path.rmdir()


def _remove_file_durable(path: Path) -> None:
    with _secured_directory(path.parent) as parent_descriptor:
        if not _path_exists_no_follow(path):
            return
        _reject_reparse(path, require_directory=False)
        if parent_descriptor is None:
            path.unlink()
            _fsync_directory(path.parent)
        else:
            os.unlink(path.name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)


def _durable_replace(source: Path, destination: Path) -> None:
    if os.name != "nt":
        if source.parent == destination.parent:
            with _secured_directory(source.parent) as parent_descriptor:
                if parent_descriptor is None:  # pragma: no cover - guarded by os.name
                    raise OSError("POSIX directory descriptor is unavailable")
                os.replace(
                    source.name,
                    destination.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                )
            return
        with (
            _secured_directory(source.parent) as source_descriptor,
            _secured_directory(destination.parent) as destination_descriptor,
        ):
            if source_descriptor is None or destination_descriptor is None:  # pragma: no cover
                raise OSError("POSIX directory descriptor is unavailable")
            os.replace(
                source.name,
                destination.name,
                src_dir_fd=source_descriptor,
                dst_dir_fd=destination_descriptor,
            )
        return
    import ctypes
    from ctypes import wintypes

    move_file = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move_file.restype = wintypes.BOOL
    replace_existing = 0x1
    write_through = 0x8
    if not move_file(str(source), str(destination), replace_existing | write_through):
        raise ctypes.WinError(ctypes.get_last_error())


def _fsync_directory(path: Path) -> None:
    """Flush directory metadata and propagate every unsupported/error result."""
    if os.name != "nt":
        with _secured_directory(path) as descriptor:
            if descriptor is None:  # pragma: no cover - guarded by os.name
                raise OSError("POSIX directory descriptor is unavailable")
            os.fsync(descriptor)
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flush_file = kernel32.FlushFileBuffers
    flush_file.argtypes = [wintypes.HANDLE]
    flush_file.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    generic_write = 0x40000000
    share_all = 0x1 | 0x2 | 0x4
    open_existing = 3
    backup_semantics = 0x02000000
    handle = create_file(
        str(path),
        generic_write,
        share_all,
        None,
        open_existing,
        backup_semantics,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not flush_file(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)


def _operational_sidecar(result: ExtractionResult[Any]) -> dict[str, Any]:
    values = result.model_dump(mode="json", exclude={"output", "artifacts"})
    values["diagnostics"] = [
        {
            "code": "OPERATIONAL_DIAGNOSTIC",
            "message": "Diagnostic content omitted from artifact sidecar.",
            "severity": diagnostic.severity.value,
            "details": {},
        }
        for diagnostic in result.diagnostics
    ]
    values["failed_blocks"] = [
        {
            "block_id": f"failed-block-{index:06d}",
            "message": "Source block content omitted from artifact sidecar.",
            "source_order": failed.source_order,
        }
        for index, failed in enumerate(result.failed_blocks, start=1)
    ]
    return values


def _source_derived_strings(output: Any) -> tuple[str, ...]:
    """Collect every exact string value in an output at the write boundary."""
    found: list[str] = []
    seen: set[int] = set()

    def collect(value: Any) -> None:
        if isinstance(value, str):
            if value:
                found.append(value)
            return
        if value is None or isinstance(value, bool | int | float | bytes):
            return
        identity = id(value)
        if identity in seen:
            return
        seen.add(identity)
        if isinstance(value, BaseModel):
            collect(value.__dict__)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                collect(key)
                collect(item)
        elif isinstance(value, list | tuple | set | frozenset):
            for item in value:
                collect(item)

    collect(output)
    return tuple(dict.fromkeys(found))


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _model_json_bytes(value: BaseModel) -> bytes:
    return _json_bytes(value.model_dump(mode="json"))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _identity_key(value: str) -> str:
    """Return a bounded exact key that stays below legacy Windows path limits."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _publication_checkpoint(stage: str) -> None:
    """Provide a no-op boundary for subprocess hard-exit fault injection."""
    del stage
