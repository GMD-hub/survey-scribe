"""Safe document adapters, including killable local Docling PDF conversion."""

from __future__ import annotations

import mmap
import os
import re
import socket
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib import import_module
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from typing import Any, Protocol
from xml.etree import ElementTree

from survey_scribe.sources.base import (
    ResolvedSource,
    SourceBlock,
    SourceConversionError,
    SourceCoverage,
    SourceDependencyError,
    SourceDiagnostic,
    SourceDocument,
    SourceError,
    SourceFormatError,
    SourceLimitError,
    SourceLimits,
    SourceProvenance,
    SourceSecurityError,
    SourceTable,
    SourceTimeoutError,
    inspect_zip_archive,
    read_utf8_text,
    render_table,
)

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_PAGE_PATTERN = re.compile(rb"/Type\s*/Page\b")


@dataclass(frozen=True, slots=True)
class PdfConversionBlock:
    """Serializable local Docling output returned through the worker boundary."""

    text: str
    page: int | None = None
    pages: tuple[int, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        pages = self.pages
        if self.page is not None and not pages:
            pages = (self.page,)
            object.__setattr__(self, "pages", pages)
        elif self.page is None and pages:
            object.__setattr__(self, "page", pages[0])
        if any(isinstance(page, bool) or page < 1 for page in pages):
            raise ValueError("PDF block pages must be positive integers")
        if tuple(sorted(set(pages))) != pages:
            raise ValueError("PDF block pages must be unique and ordered")
        if pages and self.page != pages[0]:
            raise ValueError("PDF block page must be its first provenance page")


@dataclass(frozen=True, slots=True)
class PdfConversion:
    """Serializable PDF conversion result with physical page count."""

    page_count: int
    blocks: tuple[PdfConversionBlock, ...]
    coverage: SourceCoverage | None = None
    diagnostics: tuple[SourceDiagnostic, ...] = ()


class PdfConverter(Protocol):
    """Injectable, pickle-safe PDF conversion callable."""

    def __call__(self, path: str, artifacts_path: str | None) -> PdfConversion:
        """Convert one PDF using local resources only."""
        ...


class DoclingConverter:
    """Lazy Docling converter configured for local PDFium and full-page OCR."""

    def __call__(self, path: str, artifacts_path: str | None) -> PdfConversion:
        if artifacts_path is None:
            raise SourceDependencyError(
                "PDF OCR artifacts are not configured; set DOCLING_ARTIFACTS_PATH"
            )
        artifact_root = Path(artifacts_path)
        if not artifact_root.is_dir():
            raise SourceDependencyError("Configured PDF OCR artifact directory does not exist")
        try:
            backend_module = import_module("docling.backend.pypdfium2_backend")
            base_module = import_module("docling.datamodel.base_models")
            pipeline_module = import_module("docling.datamodel.pipeline_options")
            converter_module = import_module("docling.document_converter")
        except ModuleNotFoundError as error:
            raise SourceDependencyError(
                "PDF conversion requires the optional 'pdf' dependencies"
            ) from error

        pipeline_options = pipeline_module.PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.do_table_structure = True
        pipeline_options.enable_remote_services = False
        pipeline_options.artifacts_path = artifact_root
        pipeline_options.ocr_options = pipeline_module.EasyOcrOptions(force_full_page_ocr=True)
        format_option = converter_module.PdfFormatOption(
            pipeline_options=pipeline_options,
            backend=backend_module.PyPdfiumDocumentBackend,
        )
        converter = converter_module.DocumentConverter(
            format_options={base_module.InputFormat.PDF: format_option}
        )
        result = converter.convert(path)
        document = result.document
        blocks: list[PdfConversionBlock] = []
        for item, _level in document.iterate_items():
            pages = _docling_pages(item)
            page = pages[0] if pages else None
            label = str(getattr(item, "label", "")).lower()
            if "table" in label:
                table_text = _docling_table_markdown(item, document)
                rows = _parse_markdown_table(table_text.splitlines())
                if rows:
                    blocks.append(
                        PdfConversionBlock(
                            text=render_table(rows),
                            page=page,
                            pages=pages,
                            table_rows=rows,
                        )
                    )
                continue
            text = _normalize_text(str(getattr(item, "text", "")))
            if text:
                blocks.append(PdfConversionBlock(text=text, page=page, pages=pages))
        page_count = _docling_page_count(result, document, blocks)
        failed_pages = _docling_failed_pages(result)
        if failed_pages and (page_count == 0 or failed_pages[-1] > page_count):
            raise SourceConversionError("PDF conversion returned invalid failed-page metadata")
        if _docling_conversion_incomplete(result) and not failed_pages:
            raise SourceConversionError("PDF conversion was incomplete without page coverage")
        coverage = None
        diagnostics: tuple[SourceDiagnostic, ...] = ()
        if page_count:
            failed = set(failed_pages)
            coverage = SourceCoverage(
                unit="page",
                total_units=page_count,
                converted_units=tuple(
                    page for page in range(1, page_count + 1) if page not in failed
                ),
                failed_units=failed_pages,
            )
            diagnostics = tuple(
                SourceDiagnostic(
                    code="PDF_PAGE_CONVERSION_FAILED",
                    message="PDF page conversion failed",
                    unit="page",
                    unit_index=page,
                )
                for page in failed_pages
            )
        return PdfConversion(
            page_count=page_count,
            blocks=tuple(blocks),
            coverage=coverage,
            diagnostics=diagnostics,
        )


class DoclingPdfAdapter:
    """Normalize a local PDF in a fresh killable, network-disabled process."""

    def __init__(
        self,
        *,
        converter: PdfConverter | None = None,
        artifacts_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._converter = converter or DoclingConverter()
        configured = (
            os.environ.get("DOCLING_ARTIFACTS_PATH") if artifacts_path is None else artifacts_path
        )
        self._artifacts_path = os.fspath(configured) if configured is not None else None

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        page_count = _inspect_pdf(source.primary, limits)
        conversion = _run_pdf_worker(
            self._converter,
            source.primary,
            artifacts_path=self._artifacts_path,
            timeout=_remaining_deadline(deadline),
        )
        effective_page_count = max(page_count, conversion.page_count)
        if effective_page_count > limits.max_pages:
            raise SourceLimitError("max_pages", "PDF exceeds the configured page limit")

        blocks: list[SourceBlock] = []
        table_index = 0
        for converted in conversion.blocks:
            if converted.pages and converted.pages[-1] > limits.max_pages:
                raise SourceLimitError("max_pages", "PDF block exceeds the configured page limit")
            if converted.pages and converted.pages[-1] > effective_page_count:
                raise SourceConversionError("PDF block provenance exceeds the converted page count")
            provenance = SourceProvenance(
                source_name=source.primary.name,
                page=converted.page,
                pages=converted.pages,
            )
            table: SourceTable | None = None
            kind = "text"
            if converted.table_rows:
                table_index += 1
                table = SourceTable(
                    id=f"table-{table_index:06d}",
                    rows=converted.table_rows,
                    provenance=provenance,
                )
                kind = "table"
            text = (
                render_table(converted.table_rows)
                if converted.table_rows
                else converted.text.strip()
            )
            if not text:
                continue
            blocks.append(
                SourceBlock(
                    id=f"block-{len(blocks) + 1:06d}",
                    order=len(blocks),
                    kind=kind,
                    text=text,
                    provenance=provenance,
                    table=table,
                )
            )
        coverage = conversion.coverage
        if coverage is not None:
            if coverage.unit != "page" or coverage.total_units != effective_page_count:
                raise SourceConversionError("PDF conversion coverage does not match its page count")
        elif effective_page_count:
            coverage = SourceCoverage(
                unit="page",
                total_units=effective_page_count,
                converted_units=tuple(range(1, effective_page_count + 1)),
            )
        else:
            coverage = SourceCoverage()
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/pdf",
            blocks=tuple(blocks),
            coverage=coverage,
            diagnostics=conversion.diagnostics,
        )


class DocxAdapter:
    """Parse DOCX XML as inert text after strict archive inspection."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        entries = inspect_zip_archive(source.primary, limits)
        _remaining_deadline(deadline)
        names = {entry.filename.replace("\\", "/").lower() for entry in entries}
        if any(name.endswith("vbaproject.bin") or "macrosheets/" in name for name in names):
            raise SourceSecurityError("DOCX macro content is prohibited")
        try:
            with zipfile.ZipFile(source.primary) as archive:
                _inspect_docx_content_types(archive, names)
                _inspect_relationships(archive, names)
                document_xml = archive.read("word/document.xml")
        except KeyError as error:
            raise SourceFormatError("DOCX is missing word/document.xml") from error
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise SourceFormatError("DOCX archive could not be read") from error

        try:
            root = ElementTree.fromstring(document_xml)
        except ElementTree.ParseError as error:
            raise SourceFormatError("DOCX document XML is malformed") from error
        body = root.find(f"{{{_WORD_NAMESPACE}}}body")
        if body is None:
            raise SourceFormatError("DOCX document body is missing")

        blocks: list[SourceBlock] = []
        table_index = 0
        for child in body:
            _remaining_deadline(deadline)
            if child.tag == f"{{{_WORD_NAMESPACE}}}p":
                text = _word_text(child)
                if text:
                    blocks.append(_text_block(source.primary.name, len(blocks), text))
            elif child.tag == f"{{{_WORD_NAMESPACE}}}tbl":
                rows = _word_table_rows(child)
                if not rows:
                    continue
                table_index += 1
                provenance = SourceProvenance(
                    source_name=source.primary.name,
                    row_start=1,
                    row_end=len(rows),
                )
                table = SourceTable(id=f"table-{table_index:06d}", rows=rows, provenance=provenance)
                blocks.append(
                    SourceBlock(
                        id=f"block-{len(blocks) + 1:06d}",
                        order=len(blocks),
                        kind="table",
                        text=render_table(rows),
                        provenance=provenance,
                        table=table,
                    )
                )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            blocks=tuple(blocks),
        )


class HtmlAdapter:
    """Normalize visible HTML text and tables without loading active resources."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        parser = _SafeHtmlParser()
        try:
            parser.feed(read_utf8_text(source.primary))
            parser.close()
        except (ElementTree.ParseError, ValueError) as error:
            raise SourceFormatError("HTML source could not be parsed") from error
        _remaining_deadline(deadline)
        blocks = _events_to_blocks(source.primary.name, parser.events)
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/html",
            blocks=blocks,
        )


class MarkdownAdapter:
    """Normalize UTF-8 Markdown while preserving preamble and complete tables."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        events = _markdown_events(read_utf8_text(source.primary))
        _remaining_deadline(deadline)
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/markdown",
            blocks=_events_to_blocks(source.primary.name, events),
        )


class TextAdapter:
    """Normalize local UTF-8 text without interpreting its instructions."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        text = read_utf8_text(source.primary)
        paragraphs = tuple(
            part.strip() for part in re.split(r"\r?\n\s*\r?\n", text) if part.strip()
        )
        _remaining_deadline(deadline)
        blocks = tuple(
            _text_block(source.primary.name, order, paragraph)
            for order, paragraph in enumerate(paragraphs)
        )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/plain",
            blocks=blocks,
        )


def _run_pdf_worker(
    converter: PdfConverter,
    path: Path,
    *,
    artifacts_path: str | None,
    timeout: float,
) -> PdfConversion:
    context = get_context("spawn")
    output = context.Queue(maxsize=1)
    process = context.Process(
        target=_pdf_worker,
        args=(converter, str(path), artifacts_path, output),
    )
    try:
        process.start()
        try:
            status, code, payload = output.get(timeout=timeout)
        except Empty:
            if process.is_alive():
                process.terminate()
            process.join()
            raise SourceTimeoutError("PDF conversion exceeded the configured deadline") from None
        process.join(timeout=min(timeout, 5.0))
        if process.is_alive():
            process.terminate()
            process.join()
        if status == "ok" and isinstance(payload, PdfConversion):
            return payload
        if code == SourceDependencyError.code:
            raise SourceDependencyError(str(payload))
        if code == SourceSecurityError.code:
            raise SourceSecurityError(str(payload))
        raise SourceConversionError("PDF conversion failed in the isolated worker")
    except (KeyboardInterrupt, SystemExit):
        if process.is_alive():
            process.terminate()
        process.join()
        raise
    finally:
        output.close()
        output.join_thread()


def _pdf_worker(
    converter: PdfConverter,
    path: str,
    artifacts_path: str | None,
    output: Any,
) -> None:
    if artifacts_path is not None:
        os.environ["DOCLING_ARTIFACTS_PATH"] = artifacts_path
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        with _blocked_network():
            conversion = converter(path, artifacts_path)
        output.put(("ok", "", conversion))
    except SourceError as error:
        output.put(("error", error.code, str(error)))
    except BaseException:
        output.put(("error", SourceConversionError.code, "PDF conversion failed"))


@contextmanager
def _blocked_network() -> Any:
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect

    def deny_connection(*_args: object, **_kwargs: object) -> None:
        raise OSError("Network access is disabled during source conversion")

    socket.create_connection = deny_connection
    socket.socket.connect = deny_connection
    try:
        yield
    finally:
        socket.create_connection = original_create_connection
        socket.socket.connect = original_connect


def _inspect_pdf(path: Path, limits: SourceLimits) -> int:
    try:
        with (
            path.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
        ):
            if data[:5] != b"%PDF-":
                raise SourceFormatError("PDF extension does not match file content")
            if data.find(b"/Encrypt") >= 0:
                raise SourceSecurityError("encrypted PDF sources are not supported")
            count = 0
            for _match in _PAGE_PATTERN.finditer(data):
                count += 1
                if count > limits.max_pages:
                    raise SourceLimitError("max_pages", "PDF exceeds the configured page limit")
            return count
    except (SourceError, ValueError):
        raise
    except OSError as error:
        raise SourceConversionError("PDF source could not be inspected") from error


def _inspect_docx_content_types(archive: zipfile.ZipFile, names: set[str]) -> None:
    content_name = next(
        (name for name in archive.namelist() if name.lower() == "[content_types].xml"), None
    )
    if content_name is None:
        raise SourceFormatError("DOCX is missing [Content_Types].xml")
    content_types = archive.read(content_name).lower()
    if b"macroenabled" in content_types or any("vbaproject.bin" in name for name in names):
        raise SourceSecurityError("DOCX macro content is prohibited")


def _inspect_relationships(archive: zipfile.ZipFile, names: set[str]) -> None:
    for original_name in archive.namelist():
        name = original_name.replace("\\", "/").lower()
        if not name.endswith(".rels") or name not in names:
            continue
        try:
            root = ElementTree.fromstring(archive.read(original_name))
        except ElementTree.ParseError as error:
            raise SourceFormatError("DOCX relationship XML is malformed") from error
        for relationship in root.findall(f"{{{_RELATIONSHIP_NAMESPACE}}}Relationship"):
            mode = relationship.attrib.get("TargetMode", "").lower()
            target = relationship.attrib.get("Target", "")
            if mode == "external" or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                raise SourceSecurityError("DOCX external relationship is prohibited")


def _word_text(element: ElementTree.Element) -> str:
    text = "".join(node.text or "" for node in element.iter(f"{{{_WORD_NAMESPACE}}}t"))
    return _normalize_text(text)


def _word_table_rows(table: ElementTree.Element) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for row in table.findall(f"{{{_WORD_NAMESPACE}}}tr"):
        cells = tuple(_word_text(cell) for cell in row.findall(f"{{{_WORD_NAMESPACE}}}tc"))
        if cells:
            rows.append(cells)
    return tuple(rows)


def _text_block(source_name: str, order: int, text: str) -> SourceBlock:
    return SourceBlock(
        id=f"block-{order + 1:06d}",
        order=order,
        kind="text",
        text=text,
        provenance=SourceProvenance(source_name=source_name),
    )


class _SafeHtmlParser(HTMLParser):
    _BLOCKED = {"script", "style", "noscript", "template", "iframe", "object", "embed"}
    _BLOCKS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "pre",
        "section",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, object]] = []
        self._blocked_depth = 0
        self._text: list[str] = []
        self._table_depth = 0
        self._rows: list[tuple[str, ...]] = []
        self._cells: list[str] = []
        self._cell_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in self._BLOCKED:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if tag == "table":
            self._flush_text()
            self._table_depth += 1
            if self._table_depth == 1:
                self._rows = []
            return
        if self._table_depth:
            if tag == "tr":
                self._cells = []
            elif tag in {"td", "th"}:
                self._cell_text = []
            return
        if tag in self._BLOCKS:
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._BLOCKED:
            if self._blocked_depth:
                self._blocked_depth -= 1
            return
        if self._blocked_depth:
            return
        if self._table_depth:
            if tag in {"td", "th"} and self._cell_text is not None:
                self._cells.append(_normalize_text(" ".join(self._cell_text)))
                self._cell_text = None
            elif tag == "tr" and self._cells:
                self._rows.append(tuple(self._cells))
                self._cells = []
            elif tag == "table":
                self._table_depth -= 1
                if self._table_depth == 0 and self._rows:
                    self.events.append(("table", tuple(self._rows)))
            return
        if tag in self._BLOCKS:
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        if self._table_depth and self._cell_text is not None:
            self._cell_text.append(data)
        elif not self._table_depth:
            self._text.append(data)

    def close(self) -> None:
        super().close()
        self._flush_text()

    def _flush_text(self) -> None:
        text = _normalize_text(" ".join(self._text))
        self._text = []
        if text:
            self.events.append(("text", text))


def _events_to_blocks(
    source_name: str, events: list[tuple[str, object]] | tuple[tuple[str, object], ...]
) -> tuple[SourceBlock, ...]:
    blocks: list[SourceBlock] = []
    table_index = 0
    for kind, value in events:
        if kind == "text":
            blocks.append(_text_block(source_name, len(blocks), str(value)))
            continue
        rows = tuple(tuple(str(cell) for cell in row) for row in value)  # type: ignore[union-attr]
        if not rows:
            continue
        table_index += 1
        provenance = SourceProvenance(source_name=source_name, row_start=1, row_end=len(rows))
        table = SourceTable(id=f"table-{table_index:06d}", rows=rows, provenance=provenance)
        blocks.append(
            SourceBlock(
                id=f"block-{len(blocks) + 1:06d}",
                order=len(blocks),
                kind="table",
                text=render_table(rows),
                provenance=provenance,
                table=table,
            )
        )
    return tuple(blocks)


def _markdown_events(text: str) -> list[tuple[str, object]]:
    lines = text.splitlines()
    events: list[tuple[str, object]] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        rendered = "\n".join(paragraph).strip()
        paragraph.clear()
        if rendered:
            events.append(("text", rendered))

    while index < len(lines):
        line = lines[index]
        if "|" in line and index + 1 < len(lines) and "|" in lines[index + 1]:
            table_lines: list[str] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            rows = _parse_markdown_table(table_lines)
            if rows:
                flush_paragraph()
                events.append(("table", rows))
                continue
            paragraph.extend(table_lines)
            continue
        if not line.strip():
            flush_paragraph()
        else:
            paragraph.append(line.rstrip())
        index += 1
    flush_paragraph()
    return events


def _parse_markdown_table(lines: list[str]) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for line in lines:
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if any(cells):
            rows.append(cells)
    return tuple(rows)


def _docling_page(item: object) -> int | None:
    pages = _docling_pages(item)
    return pages[0] if pages else None


def _docling_pages(item: object) -> tuple[int, ...]:
    provenance = getattr(item, "prov", ()) or ()
    pages = {
        page
        for origin in provenance
        if isinstance((page := getattr(origin, "page_no", None)), int)
        and not isinstance(page, bool)
        and page >= 1
    }
    return tuple(sorted(pages))


def _docling_failed_pages(result: object) -> tuple[int, ...]:
    failed: set[int] = set()
    for error in getattr(result, "errors", ()) or ():
        page = getattr(error, "page_no", None)
        if page is None:
            page = getattr(error, "page", None)
        if isinstance(page, int) and not isinstance(page, bool) and page >= 1:
            failed.add(page)
            continue
        failed.update(_docling_pages(error))
    return tuple(sorted(failed))


def _docling_page_count(
    result: object,
    document: object,
    blocks: list[PdfConversionBlock],
) -> int:
    candidates = [max((page for block in blocks for page in block.pages), default=0)]
    pages = getattr(document, "pages", ()) or ()
    keys = getattr(pages, "keys", None)
    if callable(keys):
        page_keys: Any = keys()
        candidates.append(
            max(
                (
                    page
                    for page in page_keys
                    if isinstance(page, int) and not isinstance(page, bool) and page >= 1
                ),
                default=0,
            )
        )
    else:
        candidates.append(len(pages))
    source_input = getattr(result, "input", None)
    reported = getattr(source_input, "page_count", 0)
    if isinstance(reported, int) and not isinstance(reported, bool) and reported >= 0:
        candidates.append(reported)
    return max(candidates)


def _docling_conversion_incomplete(result: object) -> bool:
    errors = getattr(result, "errors", ()) or ()
    if errors:
        return True
    status = getattr(result, "status", None)
    if status is None:
        return False
    value = getattr(status, "value", status)
    normalized = str(value).lower()
    return any(marker in normalized for marker in ("partial", "failure", "failed", "error"))


def _docling_table_markdown(item: object, document: object) -> str:
    exporter = getattr(item, "export_to_markdown", None)
    if not callable(exporter):
        return ""
    try:
        return str(exporter(doc=document))
    except TypeError:
        return str(exporter())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _remaining_deadline(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceTimeoutError("Source conversion exceeded the configured deadline")
    return remaining
