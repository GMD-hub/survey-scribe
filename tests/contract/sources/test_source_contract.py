"""Shared source input, limit, registry, and normalized-model contracts."""

from __future__ import annotations

import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import IO

import pytest

from survey_scribe.sources import base as source_base
from survey_scribe.sources import registry as source_registry
from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    SourceBlock,
    SourceBundle,
    SourceConversionError,
    SourceDocument,
    SourceFormatError,
    SourceInputError,
    SourceLimitError,
    SourceLimits,
    SourceProvenance,
    SourceSecurityError,
    SourceTable,
    SourceTimeoutError,
    inspect_zip_archive,
    read_utf8_text,
    resolve_local_source,
)
from survey_scribe.sources.registry import SourceRegistry


class CustomPath:
    """Small PathLike implementation used to verify the public input contract."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __fspath__(self) -> str:
        return str(self.path)


class InvalidPath:
    """PathLike whose conversion fails at the local source boundary."""

    def __fspath__(self) -> str:
        raise TypeError("invalid path")


class BytesPath:
    """PathLike that violates the string-only public input contract."""

    def __fspath__(self) -> bytes:
        return b"questionnaire.txt"


def test_source_limit_defaults_match_the_normative_contract() -> None:
    expected = SourceLimits(
        max_source_bytes=250 * 1024 * 1024,
        max_pages=2_000,
        max_archive_expanded_bytes=1024 * 1024 * 1024,
        max_archive_ratio=100.0,
        max_cells=2_000_000,
        max_companions=100,
        deadline_seconds=30 * 60.0,
    )
    assert expected == DEFAULT_SOURCE_LIMITS


def test_local_str_pathlike_and_confined_bundle_are_accepted(tmp_path: Path) -> None:
    primary = tmp_path / "questionnaire.txt"
    companion = tmp_path / "labels.txt"
    primary.write_text("Question", encoding="utf-8")
    companion.write_text("Labels", encoding="utf-8")

    assert resolve_local_source(str(primary)).primary == primary.resolve()
    assert resolve_local_source(primary.resolve().as_posix()).primary == primary.resolve()
    assert resolve_local_source(CustomPath(primary)).primary == primary.resolve()

    resolved = resolve_local_source(
        SourceBundle(root=tmp_path, primary=Path("questionnaire.txt"), companions=(companion,))
    )
    assert resolved.root == tmp_path.resolve()
    assert resolved.primary == primary.resolve()
    assert resolved.companions == (companion.resolve(),)


@pytest.mark.parametrize(
    "source",
    [
        b"questionnaire",
        bytearray(b"questionnaire"),
        "https://example.invalid/questionnaire.pdf",
        "HTTP://example.invalid/questionnaire.pdf",
        "file:///tmp/questionnaire.pdf",
    ],
)
def test_bytes_and_remote_urls_are_rejected(source: object) -> None:
    with pytest.raises(SourceInputError):
        resolve_local_source(source)  # type: ignore[arg-type]


def test_file_objects_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "questionnaire.txt"
    path.write_text("Question", encoding="utf-8")

    stream: IO[str]
    with path.open(encoding="utf-8") as stream, pytest.raises(SourceInputError):
        resolve_local_source(stream)  # type: ignore[arg-type]


def test_bundle_paths_are_confined_after_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    primary = root / "questionnaire.txt"
    primary.write_text("Question", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("Private", encoding="utf-8")

    with pytest.raises(SourceInputError, match="outside bundle root"):
        resolve_local_source(SourceBundle(root=root, primary=primary, companions=(outside,)))

    link = root / "escaped.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        original_resolve = Path.resolve

        def resolve_link(path: Path, strict: bool = False) -> Path:
            if path == link:
                return outside.resolve(strict=strict)
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", resolve_link)
    with pytest.raises(SourceInputError, match="outside bundle root"):
        resolve_local_source(SourceBundle(root=root, primary=primary, companions=(link,)))


def test_limits_are_configurable_and_checked_before_adapter_work(tmp_path: Path) -> None:
    source = tmp_path / "questionnaire.txt"
    source.write_text("12345", encoding="utf-8")
    limits = replace(DEFAULT_SOURCE_LIMITS, max_source_bytes=4)

    with pytest.raises(SourceLimitError) as raised:
        SourceRegistry.default().convert(source, limits=limits)

    assert raised.value.code == "SOURCE_LIMIT_EXCEEDED"
    assert raised.value.limit == "max_source_bytes"


def test_non_pdf_adapter_enforces_total_conversion_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "questionnaire.txt"
    source.write_text("Question", encoding="utf-8")
    moments = iter((100.0, 101.0))
    monkeypatch.setattr("survey_scribe.sources.docling.time.monotonic", lambda: next(moments))
    limits = replace(DEFAULT_SOURCE_LIMITS, deadline_seconds=0.5)

    with pytest.raises(SourceTimeoutError):
        SourceRegistry.default().convert(source, limits=limits)


def test_companion_count_is_checked_before_paths_are_processed(tmp_path: Path) -> None:
    primary = tmp_path / "questionnaire.txt"
    primary.write_text("Question", encoding="utf-8")
    limits = replace(DEFAULT_SOURCE_LIMITS, max_companions=1)
    bundle = SourceBundle(
        root=tmp_path,
        primary=primary,
        companions=(Path("missing-a"), Path("missing-b")),
    )

    with pytest.raises(SourceLimitError) as raised:
        resolve_local_source(bundle, limits=limits)

    assert raised.value.limit == "max_companions"


def test_registry_rejects_unsupported_and_ambiguous_formats(tmp_path: Path) -> None:
    unsupported = tmp_path / "questionnaire.bin"
    unsupported.write_bytes(b"not a supported format")
    disguised_pdf = tmp_path / "questionnaire.pdf"
    disguised_pdf.write_text("not a pdf", encoding="utf-8")

    registry = SourceRegistry.default()
    with pytest.raises(SourceFormatError, match="Unsupported"):
        registry.convert(unsupported)
    with pytest.raises(SourceFormatError, match="does not match"):
        registry.convert(disguised_pdf)

    ambiguous = tmp_path / "ambiguous.docx"
    with zipfile.ZipFile(ambiguous, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(SourceFormatError, match="ambiguous"):
        registry.convert(ambiguous)


def test_normalized_models_are_frozen_and_preserve_stable_source_order() -> None:
    provenance = SourceProvenance(source_name="questionnaire.txt")
    document = SourceDocument(
        source_name="questionnaire.txt",
        media_type="text/plain",
        blocks=(
            SourceBlock(
                id="block-000001", order=0, kind="text", text="Preamble", provenance=provenance
            ),
            SourceBlock(
                id="block-000002", order=1, kind="text", text="Question", provenance=provenance
            ),
        ),
    )

    assert tuple(block.order for block in document.blocks) == (0, 1)
    with pytest.raises(Exception, match="frozen"):
        document.source_name = "changed.txt"


@pytest.mark.parametrize(
    "changes",
    [
        {"max_source_bytes": True},
        {"max_pages": 1.5},
        {"max_archive_ratio": float("nan")},
        {"max_archive_ratio": float("inf")},
        {"deadline_seconds": float("nan")},
        {"deadline_seconds": float("inf")},
    ],
)
def test_source_limits_reject_wrong_types_and_non_finite_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SourceLimits(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"max_pages": 0},
        {"max_archive_ratio": 0},
        {"deadline_seconds": 0},
    ],
)
def test_source_limits_reject_non_positive_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SourceLimits(**changes)  # type: ignore[arg-type]


def test_normalized_document_rejects_inconsistent_table_provenance() -> None:
    block_provenance = SourceProvenance(source_name="questionnaire.csv", row_start=1, row_end=1)
    other_provenance = SourceProvenance(source_name="other.csv", row_start=1, row_end=1)
    table = SourceTable(id="table-1", rows=(("Q1",),), provenance=other_provenance)

    with pytest.raises(ValueError, match="provenance"):
        SourceDocument(
            source_name="questionnaire.csv",
            media_type="text/csv",
            blocks=(
                SourceBlock(
                    id="block-1",
                    order=0,
                    kind="table",
                    text="Q1",
                    provenance=block_provenance,
                    table=table,
                ),
            ),
        )


def test_normalized_document_rejects_duplicate_table_ids() -> None:
    provenance = SourceProvenance(source_name="questionnaire.csv", row_start=1, row_end=1)
    table = SourceTable(id="table-1", rows=(("Q1",),), provenance=provenance)

    with pytest.raises(ValueError, match="table identifiers"):
        SourceDocument(
            source_name="questionnaire.csv",
            media_type="text/csv",
            blocks=tuple(
                SourceBlock(
                    id=f"block-{index}",
                    order=index,
                    kind="table",
                    text="Q1",
                    provenance=provenance,
                    table=table,
                )
                for index in range(2)
            ),
        )


@pytest.mark.parametrize(
    ("row_start", "row_end"),
    [
        (1, None),
        (None, 1),
    ],
)
def test_provenance_requires_paired_row_endpoints(
    row_start: int | None, row_end: int | None
) -> None:
    with pytest.raises(ValueError, match="together"):
        SourceProvenance(source_name="questionnaire.csv", row_start=row_start, row_end=row_end)


def test_normalized_models_reject_invalid_structure() -> None:
    provenance = SourceProvenance(source_name="questionnaire.csv", row_start=2, row_end=2)
    table = SourceTable(id="table-1", rows=(("Q1",),), provenance=provenance)

    with pytest.raises(ValueError, match="precede"):
        SourceProvenance(source_name="questionnaire.csv", row_start=2, row_end=1)
    with pytest.raises(ValueError, match="table blocks"):
        SourceBlock(
            id="block-1",
            order=0,
            kind="text",
            text="Q1",
            provenance=provenance,
            table=table,
        )
    with pytest.raises(ValueError, match="contiguous"):
        SourceDocument(
            source_name="questionnaire.csv",
            media_type="text/csv",
            blocks=(
                SourceBlock(
                    id="block-1",
                    order=1,
                    kind="table",
                    text="Q1",
                    provenance=provenance,
                    table=table,
                ),
            ),
        )

    block = SourceBlock(
        id="block-1",
        order=0,
        kind="table",
        text="Q1",
        provenance=provenance,
        table=table,
    )
    with pytest.raises(ValueError, match="block identifiers"):
        SourceDocument(
            source_name="questionnaire.csv",
            media_type="text/csv",
            blocks=(block, block.model_copy(update={"order": 1})),
        )
    with pytest.raises(ValueError, match="document source"):
        SourceDocument(
            source_name="other.csv",
            media_type="text/csv",
            blocks=(block,),
        )
    mismatched_provenance = provenance.model_copy(update={"row_end": 3})
    with pytest.raises(ValueError, match="row range"):
        SourceDocument(
            source_name="questionnaire.csv",
            media_type="text/csv",
            blocks=(
                block.model_copy(
                    update={
                        "provenance": mismatched_provenance,
                        "table": table.model_copy(update={"provenance": mismatched_provenance}),
                    }
                ),
            ),
        )


def test_local_source_rejects_invalid_paths_and_bundle_roots(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    file_root = tmp_path / "root.txt"
    file_root.write_text("root", encoding="utf-8")

    for source in (tmp_path / "missing.txt", directory, InvalidPath(), BytesPath()):
        with pytest.raises(SourceInputError):
            resolve_local_source(source)  # type: ignore[arg-type]
    with pytest.raises(SourceInputError, match="root must be a directory"):
        resolve_local_source(SourceBundle(root=file_root, primary=file_root))


def test_text_reader_rejects_binary_invalid_utf8_and_io_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"question\x00hidden")
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"\xff")

    with pytest.raises(SourceFormatError, match="NUL"):
        read_utf8_text(binary)
    with pytest.raises(SourceFormatError, match="UTF-8"):
        read_utf8_text(invalid)

    def fail_read(_path: Path) -> bytes:
        raise OSError

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(SourceConversionError, match="could not be read"):
        read_utf8_text(tmp_path / "unreadable.txt")


def test_archive_inspection_rejects_invalid_and_encrypted_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = tmp_path / "invalid.docx"
    invalid.write_bytes(b"not a zip")
    with pytest.raises(SourceFormatError, match="valid ZIP"):
        inspect_zip_archive(invalid, DEFAULT_SOURCE_LIMITS)

    archive_path = tmp_path / "encrypted.docx"
    archive_path.write_bytes(b"archive")

    class FakeArchive:
        def __enter__(self) -> FakeArchive:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def infolist(self) -> list[object]:
            return [SimpleNamespace(filename="safe.xml", flag_bits=1, file_size=1)]

    monkeypatch.setattr(source_base.zipfile, "ZipFile", lambda _path: FakeArchive())
    with pytest.raises(SourceSecurityError, match="Encrypted"):
        inspect_zip_archive(archive_path, DEFAULT_SOURCE_LIMITS)


def test_file_size_inspection_error_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "questionnaire.txt"

    def fail_stat(_path: Path) -> object:
        raise OSError

    monkeypatch.setattr(Path, "stat", fail_stat)
    with pytest.raises(SourceInputError, match="size could not be inspected"):
        source_base._check_file_size(path, DEFAULT_SOURCE_LIMITS)


def test_registry_signature_failures_are_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "questionnaire.pdf"
    pdf.write_bytes(b"%PDF-")

    def fail_open(*_args: object, **_kwargs: object) -> object:
        raise OSError

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(SourceFormatError, match="signature could not be inspected"):
        source_registry._verify_signature(pdf, ".pdf")


def test_registry_rejects_non_zip_mismatch_zip_errors_and_wrong_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disguised = tmp_path / "questionnaire.docx"
    disguised.write_bytes(b"not a zip")
    with pytest.raises(SourceFormatError, match="does not match"):
        source_registry._verify_signature(disguised, ".docx")

    monkeypatch.setattr(source_registry.zipfile, "is_zipfile", lambda _path: True)

    def fail_zip(_path: Path) -> zipfile.ZipFile:
        raise zipfile.BadZipFile

    monkeypatch.setattr(source_registry.zipfile, "ZipFile", fail_zip)
    with pytest.raises(SourceFormatError, match="could not be inspected"):
        source_registry._verify_signature(disguised, ".docx")

    monkeypatch.undo()
    workbook = tmp_path / "workbook.docx"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(SourceFormatError, match="does not match"):
        source_registry._verify_signature(workbook, ".docx")
