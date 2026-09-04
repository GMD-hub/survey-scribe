"""Deterministic Tier 1 source adapter registry."""

from __future__ import annotations

import hashlib
import time
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    LocalSource,
    ResolvedSource,
    SourceAdapter,
    SourceBundle,
    SourceDocument,
    SourceFormatError,
    SourceLimits,
    resolve_local_source,
    snapshot_resolved_source,
)

if TYPE_CHECKING:
    from datetime import date

    from survey_scribe.models.routing import RoutingSourceBinding
    from survey_scribe.models.svis import SurveySVIS
    from survey_scribe.routing.native import NativeRoutingSemantics


@dataclass(frozen=True, slots=True)
class SourceConversionResult:
    """Additive normalized source result with binding and optional native routing."""

    document: SourceDocument
    source_binding: RoutingSourceBinding
    native: NativeRoutingSemantics | None


@dataclass(frozen=True, slots=True)
class SourceSvisConversionResult:
    """Normalized source plus optional package-native SVIS and routing semantics."""

    document: SourceDocument
    svis: SurveySVIS | None
    native: NativeRoutingSemantics | None


@runtime_checkable
class NativeSourceAdapter(SourceAdapter, Protocol):
    """Optional adapter extension that emits typed native routing semantics."""

    def convert_native(
        self,
        source: ResolvedSource,
        document: SourceDocument,
        *,
        limits: SourceLimits,
    ) -> NativeRoutingSemantics | None:
        """Return native semantics from the active private source snapshot."""
        ...


@runtime_checkable
class DeadlineSourceAdapter(SourceAdapter, Protocol):
    """Adapter extension that accepts one registry-owned conversion deadline."""

    def convert_until(
        self,
        source: ResolvedSource,
        *,
        limits: SourceLimits,
        deadline: float,
    ) -> SourceDocument:
        """Normalize a source before the absolute deadline."""
        ...


@runtime_checkable
class DeadlineNativeSourceAdapter(NativeSourceAdapter, Protocol):
    """Native-routing extension that shares the source conversion deadline."""

    def convert_native_until(
        self,
        source: ResolvedSource,
        document: SourceDocument,
        *,
        limits: SourceLimits,
        deadline: float,
    ) -> NativeRoutingSemantics | None:
        """Parse native routing before the absolute deadline."""
        ...


@runtime_checkable
class NativeSvisSourceAdapter(DeadlineSourceAdapter, Protocol):
    """Source extension that emits authoritative package-native SVIS."""

    def convert_svis_until(
        self,
        source: ResolvedSource,
        document: SourceDocument,
        *,
        limits: SourceLimits,
        deadline: float,
        extraction_date: date,
    ) -> tuple[SurveySVIS, NativeRoutingSemantics] | None:
        """Parse typed SVIS and native routing before the absolute deadline."""
        ...


class SourceRegistry:
    """Map verified file suffixes to minimal source adapters."""

    def __init__(self, adapters: Mapping[str, SourceAdapter]) -> None:
        """Create a suffix-to-adapter registry.

        Args:
            adapters: Adapter mapping keyed by file suffix. Suffix matching is
                case-insensitive.
        """
        self._adapters = {suffix.lower(): adapter for suffix, adapter in adapters.items()}

    @classmethod
    def default(cls) -> SourceRegistry:
        """Create the verified Tier 1 registry without importing optional SDKs.

        Returns:
            A registry for PDF, DOCX, XLSX, CSV, HTML, Markdown, and text files.
        """
        from survey_scribe.sources.docling import (
            DoclingPdfAdapter,
            DocxAdapter,
            HtmlAdapter,
            MarkdownAdapter,
            TextAdapter,
        )
        from survey_scribe.sources.tabular import CsvAdapter
        from survey_scribe.sources.xlsform import XlsFormAdapter

        return cls(
            {
                ".pdf": DoclingPdfAdapter(),
                ".docx": DocxAdapter(),
                ".xlsx": XlsFormAdapter(),
                ".csv": CsvAdapter(),
                ".html": HtmlAdapter(),
                ".htm": HtmlAdapter(),
                ".md": MarkdownAdapter(),
                ".markdown": MarkdownAdapter(),
                ".txt": TextAdapter(),
            }
        )

    def convert(
        self,
        source: LocalSource | SourceBundle,
        *,
        limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
    ) -> SourceDocument:
        """Resolve one local source, verify its format, and normalize it.

        Args:
            source: Existing local file or confined source bundle.
            limits: Resource ceilings for validation and conversion.

        Returns:
            Deterministic ordered blocks with physical source provenance.

        Raises:
            SourceInputError: The local source path is invalid.
            SourceFormatError: The suffix is unsupported or conflicts with the
                file signature.
            SourceSecurityError: Untrusted content contains a prohibited vector.
            SourceDependencyError: An optional adapter dependency is unavailable.
            SourceLimitError: A configured resource ceiling is exceeded.
            SourceConversionError: The selected adapter cannot normalize the file.
            SourceTimeoutError: Killable conversion exceeds its deadline.
        """
        resolved = resolve_local_source(source, limits=limits)
        suffix = resolved.primary.suffix.lower()
        adapter = self._adapters.get(suffix)
        if adapter is None:
            raise SourceFormatError(f"Unsupported source format: {suffix or '<none>'}")
        with snapshot_resolved_source(resolved, limits=limits) as snapshot:
            _verify_signature(snapshot.primary, suffix)
            document = _convert_adapter(adapter, snapshot, limits)
            payload = document.model_dump(mode="python")
            payload["snapshot_sha256"] = snapshot.primary_sha256
            return SourceDocument.model_validate(payload)

    def convert_with_native(
        self,
        source: LocalSource | SourceBundle,
        svis: SurveySVIS,
        *,
        limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
    ) -> SourceConversionResult:
        """Normalize one source and add its exact binding and native semantics."""
        from survey_scribe.routing.identity import create_source_binding

        resolved = resolve_local_source(source, limits=limits)
        suffix = resolved.primary.suffix.lower()
        adapter = self._adapters.get(suffix)
        if adapter is None:
            raise SourceFormatError(f"Unsupported source format: {suffix or '<none>'}")
        with snapshot_resolved_source(resolved, limits=limits) as snapshot:
            _verify_signature(snapshot.primary, suffix)
            deadline = _adapter_deadline(adapter, limits)
            converted = _convert_adapter(adapter, snapshot, limits, deadline=deadline)
            payload = converted.model_dump(mode="python")
            payload["snapshot_sha256"] = _routed_snapshot_sha256(snapshot)
            document = SourceDocument.model_validate(payload)
            source_binding = create_source_binding(document, svis)
            native: NativeRoutingSemantics | None = None
            if isinstance(adapter, DeadlineNativeSourceAdapter):
                assert deadline is not None
                native = adapter.convert_native_until(
                    snapshot,
                    document,
                    limits=limits,
                    deadline=deadline,
                )
            elif isinstance(adapter, NativeSourceAdapter):
                native = adapter.convert_native(snapshot, document, limits=limits)
            return SourceConversionResult(
                document=document,
                source_binding=source_binding,
                native=native,
            )

    def convert_for_svis(
        self,
        source: LocalSource | SourceBundle,
        *,
        extraction_date: date,
        limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
    ) -> SourceSvisConversionResult:
        """Normalize a source and parse package-native SVIS when available."""
        resolved = resolve_local_source(source, limits=limits)
        suffix = resolved.primary.suffix.lower()
        adapter = self._adapters.get(suffix)
        if adapter is None:
            raise SourceFormatError(f"Unsupported source format: {suffix or '<none>'}")
        with snapshot_resolved_source(resolved, limits=limits) as snapshot:
            _verify_signature(snapshot.primary, suffix)
            deadline = _adapter_deadline(adapter, limits)
            converted = _convert_adapter(adapter, snapshot, limits, deadline=deadline)
            payload = converted.model_dump(mode="python")
            payload["snapshot_sha256"] = _routed_snapshot_sha256(snapshot)
            document = SourceDocument.model_validate(payload)
            parsed: tuple[SurveySVIS, NativeRoutingSemantics] | None = None
            if isinstance(adapter, NativeSvisSourceAdapter):
                assert deadline is not None
                parsed = adapter.convert_svis_until(
                    snapshot,
                    document,
                    limits=limits,
                    deadline=deadline,
                    extraction_date=extraction_date,
                )
            return SourceSvisConversionResult(
                document=document,
                svis=(parsed[0] if parsed is not None else None),
                native=(parsed[1] if parsed is not None else None),
            )


def _convert_adapter(
    adapter: SourceAdapter,
    source: ResolvedSource,
    limits: SourceLimits,
    *,
    deadline: float | None = None,
) -> SourceDocument:
    if isinstance(adapter, DeadlineSourceAdapter):
        active_deadline = (
            deadline if deadline is not None else time.monotonic() + limits.deadline_seconds
        )
        return adapter.convert_until(source, limits=limits, deadline=active_deadline)
    return adapter.convert(source, limits=limits)


def _adapter_deadline(adapter: SourceAdapter, limits: SourceLimits) -> float | None:
    if isinstance(adapter, DeadlineSourceAdapter):
        return time.monotonic() + limits.deadline_seconds
    return None


def _routed_snapshot_sha256(snapshot: ResolvedSource) -> str:
    if snapshot.primary_sha256 is None or len(snapshot.companion_sha256) != len(
        snapshot.companions
    ):
        raise SourceFormatError("Validated source snapshot digests are incomplete")
    records = [
        (
            "primary",
            snapshot.primary.relative_to(snapshot.root).as_posix(),
            snapshot.primary_sha256,
        )
    ]
    records.extend(
        (
            f"companion-{index:06d}",
            companion.relative_to(snapshot.root).as_posix(),
            digest,
        )
        for index, (companion, digest) in enumerate(
            zip(snapshot.companions, snapshot.companion_sha256, strict=True),
            start=1,
        )
    )
    digest = hashlib.sha256()
    for value in ("survey-scribe-source-snapshot-v1", *records):
        fields = value if isinstance(value, tuple) else (value,)
        digest.update(len(fields).to_bytes(4, "big"))
        for field in fields:
            encoded = field.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


__all__ = ["SourceConversionResult", "SourceRegistry", "SourceSvisConversionResult"]


def _verify_signature(path: Path, suffix: str) -> None:
    if suffix == ".pdf":
        try:
            with path.open("rb") as stream:
                signature = stream.read(5)
            if signature != b"%PDF-":
                raise SourceFormatError("PDF extension does not match file content")
        except OSError as error:
            raise SourceFormatError("PDF signature could not be inspected") from error
        return
    if suffix not in {".docx", ".xlsx"}:
        return
    if not zipfile.is_zipfile(path):
        raise SourceFormatError(f"{suffix.upper()} extension does not match file content")
    try:
        with zipfile.ZipFile(path) as archive:
            names = {name.replace("\\", "/").lower() for name in archive.namelist()}
    except (OSError, zipfile.BadZipFile) as error:
        raise SourceFormatError("ZIP-based source signature could not be inspected") from error
    has_word = "word/document.xml" in names
    has_workbook = "xl/workbook.xml" in names
    if has_word and has_workbook:
        raise SourceFormatError("ZIP-based source format is ambiguous")
    expected = has_word if suffix == ".docx" else has_workbook
    if not expected:
        raise SourceFormatError(f"{suffix.upper()} extension does not match file content")
