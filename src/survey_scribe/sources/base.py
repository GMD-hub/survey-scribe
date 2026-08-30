"""Typed source port, normalized models, limits, and local-path confinement."""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

LocalSource: TypeAlias = str | os.PathLike[str]


@dataclass(frozen=True, slots=True)
class SourceLimits:
    """Resource ceilings applied before or during local source conversion."""

    max_source_bytes: int = 250 * 1024 * 1024
    max_pages: int = 2_000
    max_archive_expanded_bytes: int = 1024 * 1024 * 1024
    max_archive_ratio: float = 100.0
    max_cells: int = 2_000_000
    max_companions: int = 100
    deadline_seconds: float = 30 * 60.0

    def __post_init__(self) -> None:
        for name in (
            "max_source_bytes",
            "max_pages",
            "max_archive_expanded_bytes",
            "max_cells",
            "max_companions",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be at least 1")
        if (
            isinstance(self.max_archive_ratio, bool)
            or not isinstance(self.max_archive_ratio, int | float)
            or not isfinite(self.max_archive_ratio)
            or self.max_archive_ratio <= 0
        ):
            raise ValueError("max_archive_ratio must be greater than 0")
        if (
            isinstance(self.deadline_seconds, bool)
            or not isinstance(self.deadline_seconds, int | float)
            or not isfinite(self.deadline_seconds)
            or self.deadline_seconds <= 0
        ):
            raise ValueError("deadline_seconds must be greater than 0")


DEFAULT_SOURCE_LIMITS = SourceLimits()


@dataclass(frozen=True, slots=True)
class SourceBundle:
    """One primary local source and explicitly confined companion files."""

    root: Path
    primary: Path
    companions: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """Validated absolute paths passed from the source port to adapters."""

    root: Path
    primary: Path
    companions: tuple[Path, ...] = ()


class SourceProvenance(BaseModel):
    """Available physical origin for normalized source content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str
    page: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    row_start: int | None = Field(default=None, ge=1)
    row_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_row_range(self) -> SourceProvenance:
        if (self.row_start is None) != (self.row_end is None):
            raise ValueError("row_start and row_end must be provided together")
        if (
            self.row_start is not None
            and self.row_end is not None
            and self.row_end < self.row_start
        ):
            raise ValueError("row_end must not precede row_start")
        return self


class SourceTable(BaseModel):
    """A table preserved as ordered text cells without formula execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    rows: tuple[tuple[str, ...], ...]
    provenance: SourceProvenance


class SourceBlock(BaseModel):
    """One ordered text or complete-table unit from an untrusted source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    order: int = Field(ge=0)
    kind: Literal["text", "table"]
    text: str
    provenance: SourceProvenance
    table: SourceTable | None = None

    @model_validator(mode="after")
    def validate_table_kind(self) -> SourceBlock:
        if (self.kind == "table") != (self.table is not None):
            raise ValueError("table blocks must contain one table and text blocks must not")
        return self


class SourceDocument(BaseModel):
    """Deterministic normalized content; all source text remains untrusted data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str
    media_type: str
    blocks: tuple[SourceBlock, ...]
    trust: Literal["untrusted"] = "untrusted"

    @model_validator(mode="after")
    def validate_stable_order(self) -> SourceDocument:
        expected = tuple(range(len(self.blocks)))
        actual = tuple(block.order for block in self.blocks)
        if actual != expected:
            raise ValueError("source block order must be contiguous and start at zero")
        if len({block.id for block in self.blocks}) != len(self.blocks):
            raise ValueError("source block identifiers must be unique")
        tables = tuple(block.table for block in self.blocks if block.table is not None)
        if len({table.id for table in tables}) != len(tables):
            raise ValueError("source table identifiers must be unique")
        for block in self.blocks:
            if block.provenance.source_name != self.source_name:
                raise ValueError("block provenance must match the document source")
            if block.table is None:
                continue
            if block.table.provenance != block.provenance:
                raise ValueError("table provenance must match its block provenance")
            provenance = block.table.provenance
            if (
                provenance.row_start is not None
                and provenance.row_end is not None
                and provenance.row_end - provenance.row_start + 1 != len(block.table.rows)
            ):
                raise ValueError("table provenance row range must match its rows")
        return self

    @property
    def tables(self) -> tuple[SourceTable, ...]:
        """Return complete tables in stable source order."""
        return tuple(block.table for block in self.blocks if block.table is not None)


class SourceDiagnostic(BaseModel):
    """Stable source diagnostic attached to a typed conversion error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class SourceError(Exception):
    """Base class for source-port errors with stable machine-readable codes."""

    code = "SOURCE_ERROR"

    def __init__(self, message: str) -> None:
        self.diagnostic = SourceDiagnostic(code=self.code, message=message)
        super().__init__(message)


class SourceInputError(SourceError, ValueError):
    """The caller supplied a non-local, missing, or unconfined source."""

    code = "SOURCE_INPUT_INVALID"


class SourceFormatError(SourceError, ValueError):
    """The local file format is unsupported, corrupt, or ambiguous."""

    code = "SOURCE_FORMAT_UNSUPPORTED"


class SourceSecurityError(SourceError):
    """Untrusted content contains a prohibited execution or escape vector."""

    code = "SOURCE_SECURITY_REJECTED"


class SourceDependencyError(SourceError, ImportError):
    """A lazy optional source dependency is unavailable or unconfigured."""

    code = "SOURCE_DEPENDENCY_MISSING"


class SourceConversionError(SourceError):
    """An adapter could not normalize the source safely."""

    code = "SOURCE_CONVERSION_FAILED"


class SourceTimeoutError(SourceError, TimeoutError):
    """Killable source conversion exceeded its configured deadline."""

    code = "SOURCE_TIMEOUT"


class SourceLimitError(SourceError):
    """A configured source resource ceiling was exceeded."""

    code = "SOURCE_LIMIT_EXCEEDED"

    def __init__(self, limit: str, message: str) -> None:
        self.limit = limit
        super().__init__(message)


class SourceAdapter(Protocol):
    """Minimal adapter port used by the source registry."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        """Normalize one validated local source without external side effects."""
        ...


_REMOTE_PATH = re.compile(r"^[a-z][a-z0-9+.-]*:(?://|/)", re.IGNORECASE)
_WINDOWS_DRIVE_PATH = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)


def resolve_local_source(
    source: LocalSource | SourceBundle,
    *,
    limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
) -> ResolvedSource:
    """Validate local-only input and confine every bundle path after resolution."""
    if isinstance(source, SourceBundle):
        if len(source.companions) > limits.max_companions:
            raise SourceLimitError(
                "max_companions",
                f"Source bundle exceeds the {limits.max_companions} companion-file limit",
            )
        root = _resolve_path(source.root, label="bundle root", require_file=False)
        if not root.is_dir():
            raise SourceInputError("Source bundle root must be a directory")
        primary = _resolve_bundle_member(root, source.primary, label="primary source")
        companions = tuple(
            _resolve_bundle_member(root, companion, label="companion")
            for companion in source.companions
        )
    else:
        primary = _resolve_path(source, label="source", require_file=True)
        root = primary.parent
        companions = ()

    _check_file_size(primary, limits)
    for companion in companions:
        _check_file_size(companion, limits)
    return ResolvedSource(root=root, primary=primary, companions=companions)


def inspect_zip_archive(path: Path, limits: SourceLimits) -> tuple[zipfile.ZipInfo, ...]:
    """Inspect ZIP metadata without extraction and enforce archive ceilings."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = tuple(archive.infolist())
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        raise SourceFormatError("Source is not a valid ZIP-based document") from error

    expanded = 0
    for entry in entries:
        _validate_archive_name(entry.filename)
        if entry.flag_bits & 0x1:
            raise SourceSecurityError("Encrypted archive entries are not supported")
        expanded += entry.file_size
        if expanded > limits.max_archive_expanded_bytes:
            raise SourceLimitError(
                "max_archive_expanded_bytes",
                "Archive exceeds the configured expanded-size limit",
            )
    source_size = max(path.stat().st_size, 1)
    if expanded / source_size > limits.max_archive_ratio:
        raise SourceLimitError(
            "max_archive_ratio",
            "Archive exceeds the configured expansion-ratio limit",
        )
    return entries


def read_utf8_text(path: Path) -> str:
    """Read deterministic UTF-8 text and reject binary or ambiguous encodings."""
    try:
        payload = path.read_bytes()
        if b"\x00" in payload:
            raise SourceFormatError("Text source contains binary NUL bytes")
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceFormatError("Text source must use UTF-8 encoding") from error
    except OSError as error:
        raise SourceConversionError("Text source could not be read") from error


def render_table(rows: tuple[tuple[str, ...], ...]) -> str:
    """Render table cells deterministically without interpreting their contents."""
    return "\n".join(" | ".join(row) for row in rows)


def _resolve_bundle_member(root: Path, value: LocalSource, *, label: str) -> Path:
    raw = _coerce_path(value, label=label)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = _resolve_path(candidate, label=label, require_file=True)
    if not resolved.is_relative_to(root):
        raise SourceInputError(f"{label.capitalize()} resolves outside bundle root")
    return resolved


def _resolve_path(value: object, *, label: str, require_file: bool) -> Path:
    path = _coerce_path(value, label=label)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise SourceInputError(
            f"{label.capitalize()} does not exist or cannot be resolved"
        ) from error
    if require_file and not resolved.is_file():
        raise SourceInputError(f"{label.capitalize()} must be a local file")
    return resolved


def _coerce_path(value: object, *, label: str) -> Path:
    if isinstance(value, bytes | bytearray) or not isinstance(value, str | os.PathLike):
        raise SourceInputError(f"{label.capitalize()} must be a local str or PathLike path")
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise SourceInputError(
            f"{label.capitalize()} must be a local str or PathLike path"
        ) from error
    if isinstance(raw, bytes):
        raise SourceInputError(f"{label.capitalize()} must not be a bytes path")
    if (
        (_REMOTE_PATH.match(raw) and not _WINDOWS_DRIVE_PATH.match(raw))
        or raw.startswith("//")
        or raw.startswith("\\\\")
    ):
        raise SourceInputError("Remote URLs and network paths are not supported")
    return Path(raw)


def _check_file_size(path: Path, limits: SourceLimits) -> None:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise SourceInputError("Source file size could not be inspected") from error
    if size > limits.max_source_bytes:
        raise SourceLimitError(
            "max_source_bytes",
            f"Source exceeds the {limits.max_source_bytes}-byte limit",
        )


def _validate_archive_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized) or ".." in path.parts:
        raise SourceSecurityError("Archive contains a path traversal entry")
