"""Safe document adapters, including killable local Docling PDF conversion."""

from __future__ import annotations

import os
import re
import socket
import time
import zipfile
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib import import_module
from io import BytesIO
from multiprocessing import get_context
from multiprocessing.connection import wait
from pathlib import Path
from queue import Empty
from typing import Any, Protocol, cast
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
from survey_scribe.sources.ocr import (
    OcrCacheError,
    resolve_ocr_cache,
    validated_ocr_model_snapshot,
)

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_RELATIONSHIP_NAMESPACE = "http://schemas.openxmlformats.org/package/2006/relationships"
_WORD_TRANSPARENT_CONTAINERS = frozenset(
    {
        "customXml",
        "del",
        "fldSimple",
        "ins",
        "moveFrom",
        "moveTo",
        "sdt",
        "sdtContent",
        "smartTag",
    }
)
_WORD_METADATA_ELEMENTS = frozenset(
    {
        "bookmarkEnd",
        "bookmarkStart",
        "commentRangeEnd",
        "commentRangeStart",
        "customXmlDelRangeEnd",
        "customXmlDelRangeStart",
        "customXmlInsRangeEnd",
        "customXmlInsRangeStart",
        "moveFromRangeEnd",
        "moveFromRangeStart",
        "moveToRangeEnd",
        "moveToRangeStart",
        "permEnd",
        "permStart",
        "proofErr",
        "sdtEndPr",
        "sdtPr",
        "sectPr",
    }
)


@dataclass(frozen=True, slots=True)
class PdfConversionBlock:
    """Serializable local Docling output returned through the worker boundary."""

    text: str
    page: int | None = None
    pages: tuple[int, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()
    section_path: tuple[str, ...] = ()

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
        try:
            artifact_root = resolve_ocr_cache(Path(artifacts_path))
        except OcrCacheError as error:
            raise SourceDependencyError(str(error)) from None
        try:
            backend_module = import_module("docling.backend.pypdfium2_backend")
            base_module = import_module("docling.datamodel.base_models")
            pipeline_module = import_module("docling.datamodel.pipeline_options")
            converter_module = import_module("docling.document_converter")
        except ModuleNotFoundError as error:
            raise SourceDependencyError(
                "PDF conversion requires the optional 'pdf' dependencies"
            ) from error

        with validated_ocr_model_snapshot(artifact_root) as model_root:
            pipeline_options = pipeline_module.PdfPipelineOptions()
            pipeline_options.do_ocr = True
            pipeline_options.do_table_structure = True
            pipeline_options.enable_remote_services = False
            pipeline_options.artifacts_path = artifact_root
            pipeline_options.ocr_options = pipeline_module.EasyOcrOptions(
                lang=["en"],
                force_full_page_ocr=True,
                model_storage_directory=str(model_root),
                download_enabled=False,
            )
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
        configured_max_cells = os.environ.get("SURVEY_SCRIBE_PDF_MAX_CELLS")
        max_cells = int(configured_max_cells) if configured_max_cells is not None else None
        table_cells = 0
        current_section: tuple[str, ...] = ()
        for item, _level in document.iterate_items():
            pages = _docling_pages(item)
            page = pages[0] if pages else None
            label = str(getattr(item, "label", "")).lower()
            if "table" in label:
                remaining_cells = None if max_cells is None else max(max_cells - table_cells, 0)
                rows = _docling_table_rows(
                    item,
                    document,
                    max_cells=remaining_cells,
                )
                if rows:
                    if max_cells is not None:
                        table_cells = _add_table_cells(table_cells, rows, max_cells)
                    blocks.append(
                        PdfConversionBlock(
                            text=render_table(rows),
                            page=page,
                            pages=pages,
                            table_rows=rows,
                            section_path=current_section,
                        )
                    )
                continue
            text = _normalize_text(str(getattr(item, "text", "")))
            if text:
                if any(name in label for name in ("section", "title", "heading")):
                    current_section = (text,)
                blocks.append(
                    PdfConversionBlock(
                        text=text,
                        page=page,
                        pages=pages,
                        section_path=current_section,
                    )
                )
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
        page_count = _inspect_pdf(
            source.primary,
            limits,
            timeout=_remaining_deadline(deadline),
        )
        conversion = _run_pdf_worker(
            self._converter,
            source.primary,
            artifacts_path=self._artifacts_path,
            timeout=_remaining_deadline(deadline),
            max_cells=limits.max_cells,
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
                section_path=converted.section_path,
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
        entries = inspect_zip_archive(source.primary, limits, deadline=deadline)
        _remaining_deadline(deadline)
        names = {entry.filename.replace("\\", "/").lower() for entry in entries}
        if any(name.endswith("vbaproject.bin") or "macrosheets/" in name for name in names):
            raise SourceSecurityError("DOCX macro content is prohibited")
        try:
            with zipfile.ZipFile(source.primary) as archive:
                _inspect_docx_content_types(archive, names, limits, deadline)
                _inspect_relationships(archive, names, limits, deadline)
                document_xml = _read_zip_part(
                    archive,
                    "word/document.xml",
                    limits=limits,
                    deadline=deadline,
                )
        except KeyError as error:
            raise SourceFormatError("DOCX is missing word/document.xml") from error
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            raise SourceFormatError("DOCX archive could not be read") from error

        try:
            root = _parse_bounded_xml(
                document_xml,
                limits=limits,
                deadline=deadline,
                malformed_message="DOCX document XML is malformed",
            )
        except ElementTree.ParseError as error:
            raise SourceFormatError("DOCX document XML is malformed") from error
        body = root.find(f"{{{_WORD_NAMESPACE}}}body")
        if body is None:
            raise SourceFormatError("DOCX document body is missing")

        blocks: list[SourceBlock] = []
        table_index = 0
        table_cells = 0
        current_section: tuple[str, ...] = ()
        word_blocks, unsupported_containers = _word_body_blocks(body)
        for child in word_blocks:
            _remaining_deadline(deadline)
            if child.tag == f"{{{_WORD_NAMESPACE}}}p":
                text = _word_text(child)
                if text:
                    if _word_is_heading(child):
                        current_section = (text,)
                    blocks.append(
                        _text_block(
                            source.primary.name,
                            len(blocks),
                            text,
                            section_path=current_section,
                        )
                    )
            else:
                rows = _word_table_rows(child)
                if not rows:
                    continue
                table_cells = _add_table_cells(table_cells, rows, limits.max_cells)
                table_index += 1
                provenance = SourceProvenance(
                    source_name=source.primary.name,
                    section_path=current_section,
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
        diagnostics = tuple(
            SourceDiagnostic(
                code="DOCX_CONTAINER_UNSUPPORTED",
                message="DOCX contains a nonempty unsupported document container",
                unit="document",
                unit_index=1,
            )
            for _ in range(unsupported_containers)
        )
        coverage = (
            SourceCoverage(total_units=1, converted_units=(), failed_units=(1,))
            if unsupported_containers
            else SourceCoverage()
        )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            blocks=tuple(blocks),
            coverage=coverage,
            diagnostics=diagnostics,
        )


class HtmlAdapter:
    """Normalize visible HTML text and tables without loading active resources."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        parser = _SafeHtmlParser(max_cells=limits.max_cells)
        try:
            parser.feed(read_utf8_text(source.primary))
            parser.close()
        except (ElementTree.ParseError, ValueError) as error:
            raise SourceFormatError("HTML source could not be parsed") from error
        _remaining_deadline(deadline)
        blocks = _events_to_blocks(
            source.primary.name,
            parser.events,
            max_cells=limits.max_cells,
        )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/html",
            blocks=blocks,
        )


class MarkdownAdapter:
    """Normalize UTF-8 Markdown while preserving preamble and complete tables."""

    def convert(self, source: ResolvedSource, *, limits: SourceLimits) -> SourceDocument:
        deadline = time.monotonic() + limits.deadline_seconds
        events = _markdown_events(read_utf8_text(source.primary), max_cells=limits.max_cells)
        _remaining_deadline(deadline)
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/markdown",
            blocks=_events_to_blocks(source.primary.name, events, max_cells=limits.max_cells),
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
        blocks: list[SourceBlock] = []
        current_section: tuple[str, ...] = ()
        for paragraph in paragraphs:
            if _plain_text_heading(paragraph):
                current_section = (paragraph.strip(),)
            blocks.append(
                _text_block(
                    source.primary.name,
                    len(blocks),
                    paragraph,
                    section_path=current_section,
                )
            )
        return SourceDocument(
            source_name=source.primary.name,
            media_type="text/plain",
            blocks=tuple(blocks),
        )


def _run_pdf_worker(
    converter: PdfConverter,
    path: Path,
    *,
    artifacts_path: str | None,
    timeout: float,
    max_cells: int | None = None,
) -> PdfConversion:
    context = get_context("spawn")
    output = context.Queue(maxsize=1)
    process = context.Process(
        target=_pdf_worker,
        args=(converter, str(path), artifacts_path, max_cells, output),
    )
    try:
        process.start()
        try:
            status, code, payload = _wait_for_worker_message(output, process, timeout)
        except Empty:
            _bounded_process_cleanup(process)
            raise SourceTimeoutError("PDF conversion exceeded the configured deadline") from None
        except ChildProcessError:
            _bounded_process_cleanup(process)
            raise SourceConversionError(
                "PDF conversion worker exited before returning a result"
            ) from None
        _bounded_process_cleanup(process)
        if status == "ok" and isinstance(payload, PdfConversion):
            if max_cells is not None:
                _validate_pdf_table_cells(payload, max_cells)
            return payload
        if code == SourceDependencyError.code:
            raise SourceDependencyError(str(payload))
        if code == SourceSecurityError.code:
            raise SourceSecurityError(str(payload))
        if code == SourceLimitError.code:
            raise SourceLimitError("max_cells", str(payload))
        raise SourceConversionError("PDF conversion failed in the isolated worker")
    except (KeyboardInterrupt, SystemExit):
        _bounded_process_cleanup(process)
        raise
    finally:
        output.close()
        output.join_thread()


def _pdf_worker(
    converter: PdfConverter,
    path: str,
    artifacts_path: str | None,
    max_cells: int | None,
    output: Any,
) -> None:
    if artifacts_path is not None:
        os.environ["DOCLING_ARTIFACTS_PATH"] = artifacts_path
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if max_cells is not None:
        os.environ["SURVEY_SCRIBE_PDF_MAX_CELLS"] = str(max_cells)
    try:
        with _blocked_network():
            conversion = converter(path, artifacts_path)
        if max_cells is not None:
            _validate_pdf_table_cells(conversion, max_cells)
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


def _inspect_pdf(
    path: Path,
    limits: SourceLimits,
    *,
    timeout: float | None = None,
) -> int:
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise SourceFormatError("PDF extension does not match file content")
    except (SourceError, ValueError):
        raise
    except OSError as error:
        raise SourceConversionError("PDF source could not be inspected") from error
    return _run_pdf_preflight(
        path,
        max_pages=limits.max_pages,
        timeout=(limits.deadline_seconds if timeout is None else timeout),
    )


def _run_pdf_preflight(path: Path, *, max_pages: int, timeout: float) -> int:
    context = get_context("spawn")
    output = context.Queue(maxsize=1)
    process = context.Process(
        target=_pdf_preflight_worker,
        args=(str(path), max_pages, output),
    )
    try:
        process.start()
        try:
            status, code, payload = _wait_for_worker_message(output, process, timeout)
        except Empty:
            _bounded_process_cleanup(process)
            raise SourceTimeoutError("PDF inspection exceeded the configured deadline") from None
        except ChildProcessError:
            _bounded_process_cleanup(process)
            raise SourceConversionError(
                "PDF inspection worker exited before returning a result"
            ) from None
        _bounded_process_cleanup(process)
        if status == "ok" and isinstance(payload, int) and not isinstance(payload, bool):
            return payload
        if code == SourceSecurityError.code:
            raise SourceSecurityError(str(payload))
        if code == SourceLimitError.code:
            raise SourceLimitError("max_pages", str(payload))
        if code == SourceDependencyError.code:
            raise SourceDependencyError(str(payload))
        if code == SourceFormatError.code:
            raise SourceFormatError(str(payload))
        raise SourceConversionError("PDF source could not be inspected")
    except (KeyboardInterrupt, SystemExit):
        _bounded_process_cleanup(process)
        raise
    finally:
        output.close()
        output.join_thread()


def _wait_for_worker_message(output: Any, process: Any, timeout: float) -> Any:
    reader = getattr(output, "_reader", None)
    sentinel = getattr(process, "sentinel", None)
    if reader is not None and sentinel is not None:
        ready = wait((reader, sentinel), timeout=timeout)
        if reader in ready:
            return output.get(timeout=0.1)
        if sentinel in ready:
            try:
                return output.get(timeout=0.1)
            except Empty:
                raise ChildProcessError from None
        raise Empty
    try:
        return output.get(timeout=timeout)
    except Empty:
        if not process.is_alive():
            raise ChildProcessError from None
        raise


def _bounded_process_cleanup(process: Any) -> None:
    process.join(timeout=0.1)
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=0.5)
    if not process.is_alive():
        return
    kill = getattr(process, "kill", None)
    if callable(kill):
        kill()
    process.join(timeout=0.5)
    if process.is_alive():
        raise SourceConversionError("PDF worker cleanup did not complete")


def _pdf_preflight_worker(path: str, max_pages: int, output: Any) -> None:
    try:
        pdfium = import_module("pypdfium2")
        pdfium_raw = import_module("pypdfium2.raw")
    except ModuleNotFoundError:
        output.put(
            (
                "error",
                SourceDependencyError.code,
                "PDF inspection requires the optional 'pdf' dependencies",
            )
        )
        return
    document = None
    try:
        document = pdfium.PdfDocument(path)
        if pdfium_raw.FPDF_GetSecurityHandlerRevision(document.raw) >= 0:
            output.put(
                ("error", SourceSecurityError.code, "encrypted PDF sources are not supported")
            )
            return
        page_count = len(document)
        if page_count > max_pages:
            output.put(("error", SourceLimitError.code, "PDF exceeds the configured page limit"))
            return
        output.put(("ok", "", page_count))
    except BaseException:
        last_error = int(pdfium_raw.FPDF_GetLastError())
        if last_error == int(pdfium_raw.FPDF_ERR_PASSWORD):
            output.put(
                ("error", SourceSecurityError.code, "encrypted PDF sources are not supported")
            )
        else:
            output.put(
                ("error", SourceFormatError.code, "PDF extension does not match file content")
            )
    finally:
        if document is not None:
            document.close()


def _inspect_docx_content_types(
    archive: zipfile.ZipFile,
    names: set[str],
    limits: SourceLimits,
    deadline: float,
) -> None:
    content_name = next(
        (name for name in archive.namelist() if name.lower() == "[content_types].xml"), None
    )
    if content_name is None:
        raise SourceFormatError("DOCX is missing [Content_Types].xml")
    content_types = _read_zip_part(
        archive,
        content_name,
        limits=limits,
        deadline=deadline,
    )
    _parse_bounded_xml(
        content_types,
        limits=limits,
        deadline=deadline,
        malformed_message="DOCX content type XML is malformed",
    )
    content_types = content_types.lower()
    if b"macroenabled" in content_types or any("vbaproject.bin" in name for name in names):
        raise SourceSecurityError("DOCX macro content is prohibited")


def _inspect_relationships(
    archive: zipfile.ZipFile,
    names: set[str],
    limits: SourceLimits,
    deadline: float,
) -> None:
    for original_name in archive.namelist():
        name = original_name.replace("\\", "/").lower()
        if not name.endswith(".rels") or name not in names:
            continue
        try:
            root = _parse_bounded_xml(
                _read_zip_part(
                    archive,
                    original_name,
                    limits=limits,
                    deadline=deadline,
                ),
                limits=limits,
                deadline=deadline,
                malformed_message="DOCX relationship XML is malformed",
            )
        except ElementTree.ParseError as error:
            raise SourceFormatError("DOCX relationship XML is malformed") from error
        for relationship in root.findall(f"{{{_RELATIONSHIP_NAMESPACE}}}Relationship"):
            mode = relationship.attrib.get("TargetMode", "").lower()
            target = relationship.attrib.get("Target", "")
            if mode == "external" or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE):
                raise SourceSecurityError("DOCX external relationship is prohibited")


def _read_zip_part(
    archive: zipfile.ZipFile,
    name: str,
    *,
    limits: SourceLimits,
    deadline: float,
) -> bytes:
    try:
        information = archive.getinfo(name)
    except KeyError:
        raise
    if information.file_size > limits.max_xml_part_bytes:
        raise SourceLimitError(
            "max_xml_part_bytes",
            "DOCX XML part exceeds the configured byte limit",
        )
    payload = bytearray()
    with archive.open(information) as stream:
        while chunk := stream.read(min(1024 * 1024, limits.max_xml_part_bytes + 1)):
            _remaining_deadline(deadline)
            payload.extend(chunk)
            if len(payload) > limits.max_xml_part_bytes:
                raise SourceLimitError(
                    "max_xml_part_bytes",
                    "DOCX XML part exceeds the configured byte limit",
                )
    return bytes(payload)


def _parse_bounded_xml(
    payload: bytes,
    *,
    limits: SourceLimits,
    deadline: float,
    malformed_message: str,
) -> ElementTree.Element:
    parser = ElementTree.iterparse(BytesIO(payload), events=("start", "end"))
    count = 0
    depth = 0
    root: ElementTree.Element | None = None
    try:
        for event, element in parser:
            if event == "start":
                if root is None:
                    root = element
                count += 1
                depth += 1
                if count > limits.max_xml_elements:
                    raise SourceLimitError(
                        "max_xml_elements",
                        "DOCX XML exceeds the configured element limit",
                    )
                if depth > limits.max_xml_depth:
                    raise SourceLimitError(
                        "max_xml_depth",
                        "DOCX XML exceeds the configured depth limit",
                    )
                if count % 1024 == 0:
                    _remaining_deadline(deadline)
            else:
                depth -= 1
    except ElementTree.ParseError:
        raise SourceFormatError(malformed_message) from None
    _remaining_deadline(deadline)
    if root is None:
        raise SourceFormatError(malformed_message)
    return root


def _word_text(element: ElementTree.Element) -> str:
    text = "".join(node.text or "" for node in element.iter(f"{{{_WORD_NAMESPACE}}}t"))
    return _normalize_text(text)


def _word_body_blocks(
    body: ElementTree.Element,
) -> tuple[tuple[ElementTree.Element, ...], int]:
    blocks: list[ElementTree.Element] = []
    unsupported = 0

    stack = [iter(body)]
    while stack:
        try:
            child = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        local_name = _word_local_name(child.tag)
        if local_name in {"p", "tbl"}:
            blocks.append(child)
        elif local_name in _WORD_TRANSPARENT_CONTAINERS:
            stack.append(iter(child))
        elif local_name not in _WORD_METADATA_ELEMENTS and _word_element_is_nonempty(child):
            unsupported += 1
    return tuple(blocks), unsupported


def _word_local_name(tag: str) -> str:
    prefix = f"{{{_WORD_NAMESPACE}}}"
    return tag[len(prefix) :] if tag.startswith(prefix) else tag


def _word_element_is_nonempty(element: ElementTree.Element) -> bool:
    return bool(
        element.attrib
        or len(element)
        or (element.text is not None and element.text.strip())
        or _word_text(element)
    )


def _word_table_rows(table: ElementTree.Element) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for row in table.findall(f"{{{_WORD_NAMESPACE}}}tr"):
        cells = tuple(_word_text(cell) for cell in row.findall(f"{{{_WORD_NAMESPACE}}}tc"))
        if cells:
            rows.append(cells)
    return tuple(rows)


def _text_block(
    source_name: str,
    order: int,
    text: str,
    *,
    section_path: tuple[str, ...] = (),
) -> SourceBlock:
    return SourceBlock(
        id=f"block-{order + 1:06d}",
        order=order,
        kind="text",
        text=text,
        provenance=SourceProvenance(source_name=source_name, section_path=section_path),
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

    def __init__(self, *, max_cells: int | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, object]] = []
        self._blocked_depth = 0
        self._text: list[str] = []
        self._table_depth = 0
        self._rows: list[tuple[str, ...]] = []
        self._cells: list[str] = []
        self._cell_text: list[str] | None = None
        self._max_cells = max_cells
        self._cell_count = 0
        self._heading_tag: str | None = None

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
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush_text()
            self._heading_tag = tag
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
                self._cell_count += 1
                if self._max_cells is not None and self._cell_count > self._max_cells:
                    raise SourceLimitError(
                        "max_cells", "Document tables exceed the configured cell limit"
                    )
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
        if tag == self._heading_tag:
            text = _normalize_text(" ".join(self._text))
            self._text = []
            self._heading_tag = None
            if text:
                self.events.append(("section", text))
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
    source_name: str,
    events: list[tuple[str, object]] | tuple[tuple[str, object], ...],
    *,
    max_cells: int | None = None,
) -> tuple[SourceBlock, ...]:
    blocks: list[SourceBlock] = []
    table_index = 0
    table_cells = 0
    current_section: tuple[str, ...] = ()
    for kind, value in events:
        if kind == "section":
            current_section = (str(value),)
            blocks.append(
                _text_block(
                    source_name,
                    len(blocks),
                    str(value),
                    section_path=current_section,
                )
            )
            continue
        if kind == "text":
            blocks.append(
                _text_block(
                    source_name,
                    len(blocks),
                    str(value),
                    section_path=current_section,
                )
            )
            continue
        rows = tuple(tuple(str(cell) for cell in row) for row in value)  # type: ignore[union-attr]
        if not rows:
            continue
        if max_cells is not None:
            table_cells = _add_table_cells(table_cells, rows, max_cells)
        table_index += 1
        provenance = SourceProvenance(
            source_name=source_name,
            section_path=current_section,
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
    return tuple(blocks)


def _markdown_events(text: str, *, max_cells: int | None = None) -> list[tuple[str, object]]:
    lines = text.splitlines()
    events: list[tuple[str, object]] = []
    paragraph: list[str] = []
    index = 0
    table_cells = 0

    def flush_paragraph() -> None:
        rendered = "\n".join(paragraph).strip()
        paragraph.clear()
        if rendered:
            events.append(("text", rendered))

    while index < len(lines):
        line = lines[index]
        heading = re.fullmatch(r"\s{0,3}#{1,6}\s+(.+?)\s*#*\s*", line)
        if heading is not None:
            flush_paragraph()
            events.append(("section", heading.group(1)))
            index += 1
            continue
        if "|" in line and index + 1 < len(lines) and "|" in lines[index + 1]:
            table_lines: list[str] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                table_lines.append(lines[index])
                index += 1
            remaining_cells = None if max_cells is None else max(max_cells - table_cells, 0)
            rows = _parse_markdown_table(table_lines, max_cells=remaining_cells)
            if rows:
                if max_cells is not None:
                    table_cells = _add_table_cells(table_cells, rows, max_cells)
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


def _word_is_heading(paragraph: ElementTree.Element) -> bool:
    properties = paragraph.find(f"{{{_WORD_NAMESPACE}}}pPr")
    if properties is None:
        return False
    style = properties.find(f"{{{_WORD_NAMESPACE}}}pStyle")
    value = style.attrib.get(f"{{{_WORD_NAMESPACE}}}val", "") if style is not None else ""
    return value.casefold().startswith(("heading", "title"))


def _plain_text_heading(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if "\n" in stripped or len(stripped) > 120:
        return False
    return bool(re.match(r"(?i)^(?:section|module)\b", stripped)) or (
        len(stripped.split()) <= 12 and stripped.isupper()
    )


def _parse_markdown_table(
    lines: list[str],
    *,
    max_cells: int | None = None,
) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    cell_count = 0
    for line in lines:
        cells = _split_markdown_table_row(line)
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if any(cells):
            cell_count += len(cells)
            if max_cells is not None and cell_count > max_cells:
                raise SourceLimitError(
                    "max_cells", "Document tables exceed the configured cell limit"
                )
            rows.append(cells)
    return tuple(rows)


def _split_markdown_table_row(line: str) -> tuple[str, ...]:
    cells: list[list[str]] = [[]]
    code_delimiter = 0
    index = 0
    while index < len(line):
        character = line[index]
        if character == "`":
            end = index + 1
            while end < len(line) and line[end] == "`":
                end += 1
            count = end - index
            cells[-1].append(line[index:end])
            if code_delimiter == 0:
                code_delimiter = count
            elif code_delimiter == count:
                code_delimiter = 0
            index = end
            continue
        if character == "\\" and code_delimiter == 0:
            end = index + 1
            while end < len(line) and line[end] == "\\":
                end += 1
            count = end - index
            if end < len(line) and line[end] == "|":
                cells[-1].append("\\" * (count // 2))
                if count % 2:
                    cells[-1].append("|")
                else:
                    cells.append([])
                index = end + 1
                continue
            cells[-1].append("\\" * count)
            index = end
            continue
        if character == "|" and code_delimiter == 0:
            cells.append([])
        else:
            cells[-1].append(character)
        index += 1

    rendered = ["".join(cell).strip() for cell in cells]
    if len(rendered) > 1 and not rendered[0]:
        rendered.pop(0)
    if len(rendered) > 1 and not rendered[-1]:
        rendered.pop()
    return tuple(rendered)


def _add_table_cells(
    current: int,
    rows: tuple[tuple[str, ...], ...],
    max_cells: int,
) -> int:
    total = current + sum(len(row) for row in rows)
    if total > max_cells:
        raise SourceLimitError("max_cells", "Document tables exceed the configured cell limit")
    return total


def _validate_pdf_table_cells(conversion: PdfConversion, max_cells: int) -> None:
    total = 0
    for block in conversion.blocks:
        if block.table_rows:
            total = _add_table_cells(total, block.table_rows, max_cells)


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


def _docling_table_rows(
    item: object,
    document: object,
    *,
    max_cells: int | None,
) -> tuple[tuple[str, ...], ...]:
    dataframe_exporter = getattr(item, "export_to_dataframe", None)
    if callable(dataframe_exporter):
        try:
            dataframe = dataframe_exporter(doc=document)
        except TypeError:
            dataframe = dataframe_exporter()
        columns = getattr(dataframe, "columns", None)
        row_exporter = getattr(dataframe, "itertuples", None)
        if columns is not None and callable(row_exporter):
            column_values = cast(Iterable[object], columns)
            row_values = cast(
                Iterable[Iterable[object]],
                row_exporter(index=False, name=None),
            )
            rows = (tuple(str(value) for value in column_values),) + tuple(
                tuple(str(value) for value in row) for row in row_values
            )
            if max_cells is not None:
                _add_table_cells(0, rows, max_cells)
            return rows
    table_text = _docling_table_markdown(item, document)
    return _parse_markdown_table(table_text.splitlines(), max_cells=max_cells)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _remaining_deadline(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SourceTimeoutError("Source conversion exceeded the configured deadline")
    return remaining
