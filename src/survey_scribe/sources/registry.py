"""Deterministic Tier 1 source adapter registry."""

from __future__ import annotations

import zipfile
from collections.abc import Mapping
from pathlib import Path

from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    LocalSource,
    SourceAdapter,
    SourceBundle,
    SourceDocument,
    SourceFormatError,
    SourceLimits,
    resolve_local_source,
)


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
        from survey_scribe.sources.tabular import CsvAdapter, XlsxAdapter

        return cls(
            {
                ".pdf": DoclingPdfAdapter(),
                ".docx": DocxAdapter(),
                ".xlsx": XlsxAdapter(),
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
        _verify_signature(resolved.primary, suffix)
        return adapter.convert(resolved, limits=limits)


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
