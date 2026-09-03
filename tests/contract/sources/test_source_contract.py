"""Shared source input, limit, registry, and normalized-model contracts."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import IO, Any

import pytest

from survey_scribe.sources import base as source_base
from survey_scribe.sources import registry as source_registry
from survey_scribe.sources.base import (
    DEFAULT_SOURCE_LIMITS,
    ResolvedSource,
    SourceBlock,
    SourceBundle,
    SourceConversionError,
    SourceCoverage,
    SourceDiagnostic,
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
    snapshot_resolved_source,
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
        max_archive_entries=10_000,
        max_archive_filename_chars=512,
        max_archive_path_depth=20,
        max_xml_part_bytes=64 * 1024 * 1024,
        max_xml_elements=2_000_000,
        max_xml_depth=256,
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
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe.xml", "<x/>")

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


@pytest.mark.parametrize(
    ("entry_name", "limit_changes", "expected_limit"),
    [
        ("a/b/c/file.xml", {"max_archive_path_depth": 3}, "max_archive_path_depth"),
        ("very-long-name.xml", {"max_archive_filename_chars": 8}, "max_archive_filename_chars"),
    ],
)
def test_archive_inspection_enforces_name_and_depth_limits(
    tmp_path: Path,
    entry_name: str,
    limit_changes: dict[str, int],
    expected_limit: str,
) -> None:
    archive_path = tmp_path / "bounded.docx"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(entry_name, "<x/>")

    with pytest.raises(SourceLimitError) as raised:
        inspect_zip_archive(
            archive_path,
            replace(DEFAULT_SOURCE_LIMITS, **limit_changes),
        )

    assert raised.value.limit == expected_limit


def test_archive_inspection_enforces_entry_count_limit(tmp_path: Path) -> None:
    archive_path = tmp_path / "many-entries.docx"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for index in range(3):
            archive.writestr(f"entry-{index}.xml", "<x/>")

    with pytest.raises(SourceLimitError) as raised:
        inspect_zip_archive(
            archive_path,
            replace(DEFAULT_SOURCE_LIMITS, max_archive_entries=2),
        )

    assert raised.value.limit == "max_archive_entries"


def test_archive_preflight_rejects_zip64_missing_and_central_directory_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zip64 = tmp_path / "zip64.docx"
    end_record = bytearray(22)
    end_record[:4] = b"PK\x05\x06"
    end_record[10:12] = b"\xff\xff"
    zip64.write_bytes(end_record)
    with pytest.raises(SourceLimitError) as zip64_error:
        inspect_zip_archive(zip64, DEFAULT_SOURCE_LIMITS)
    assert zip64_error.value.limit == "max_archive_entries"

    with pytest.raises(SourceFormatError, match="valid ZIP"):
        inspect_zip_archive(tmp_path / "missing.docx", DEFAULT_SOURCE_LIMITS)

    archive_path = tmp_path / "mismatch.docx"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.xml", "<x/>")

    class MismatchedArchive:
        def __enter__(self) -> MismatchedArchive:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def infolist(self) -> list[object]:
            return [
                SimpleNamespace(filename="one.xml", flag_bits=0, file_size=4),
                SimpleNamespace(filename="two.xml", flag_bits=0, file_size=4),
            ]

    monkeypatch.setattr(source_base.zipfile, "ZipFile", lambda _path: MismatchedArchive())
    with pytest.raises(SourceLimitError) as mismatch:
        inspect_zip_archive(archive_path, DEFAULT_SOURCE_LIMITS)
    assert mismatch.value.limit == "max_archive_entries"


def test_archive_wraps_zipfile_failure_after_valid_eocd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "broken-central.docx"
    with zipfile.ZipFile(archive_path, "w"):
        pass
    monkeypatch.setattr(
        source_base.zipfile,
        "ZipFile",
        lambda _path: (_ for _ in ()).throw(zipfile.BadZipFile()),
    )

    with pytest.raises(SourceFormatError, match="valid ZIP"):
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


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"converted_units": (0,)}, "positive integers"),
        ({"converted_units": (True,)}, "positive integers"),
        ({"total_units": 2, "converted_units": (2, 1)}, "unique and ordered"),
        ({"total_units": 2, "converted_units": (1, 1)}, "unique and ordered"),
        ({"converted_units": (1,), "failed_units": (1,)}, "must not overlap"),
        ({"total_units": 2, "converted_units": (1,)}, "every source unit"),
    ],
)
def test_source_coverage_rejects_invalid_accounting_states(
    values: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SourceCoverage.model_validate(values)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"pages": (True,)}, "positive integers"),
        ({"pages": (0,)}, "positive integers"),
        ({"pages": (2, 1)}, "unique and ordered"),
        ({"pages": (1, 1)}, "unique and ordered"),
        ({"page": 2, "pages": (1, 2)}, "first provenance page"),
    ],
)
def test_source_provenance_rejects_invalid_page_states(
    values: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SourceProvenance.model_validate({"source_name": "questionnaire.pdf", **values})


def test_source_provenance_synchronizes_legacy_page_and_complete_pages() -> None:
    from_page = SourceProvenance(source_name="questionnaire.pdf", page=2)
    from_pages = SourceProvenance(source_name="questionnaire.pdf", pages=(3, 4))

    assert (from_page.page, from_page.pages) == (2, (2,))
    assert (from_pages.page, from_pages.pages) == (3, (3, 4))


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"unit": "page"}, "provided together"),
        ({"unit_index": 1}, "provided together"),
    ],
)
def test_source_diagnostic_rejects_partial_unit_references(
    values: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SourceDiagnostic.model_validate({"code": "FAILED", "message": "failed", **values})


def test_failed_coverage_requires_a_matching_error_diagnostic() -> None:
    coverage = SourceCoverage(
        unit="page",
        total_units=2,
        converted_units=(1,),
        failed_units=(2,),
    )

    with pytest.raises(ValueError, match="failed source unit"):
        SourceDocument(
            source_name="questionnaire.pdf",
            media_type="application/pdf",
            blocks=(),
            coverage=coverage,
            diagnostics=(
                SourceDiagnostic(
                    code="WARNING",
                    message="not an error",
                    severity="warning",
                    unit="page",
                    unit_index=2,
                ),
            ),
        )


@pytest.mark.parametrize(
    "digest",
    ["", "0" * 63, "0" * 65, "g" * 64, "A" * 64],
)
def test_source_document_rejects_invalid_snapshot_digests(digest: str) -> None:
    with pytest.raises(ValueError, match="snapshot_sha256"):
        SourceDocument(
            source_name="questionnaire.txt",
            media_type="text/plain",
            blocks=(),
            snapshot_sha256=digest,
        )


def test_private_snapshot_hashes_primary_and_companions(tmp_path: Path) -> None:
    primary = tmp_path / "questionnaire.txt"
    companion = tmp_path / "labels.txt"
    primary.write_text("Question", encoding="utf-8")
    companion.write_text("Labels", encoding="utf-8")
    resolved = resolve_local_source(
        SourceBundle(root=tmp_path, primary=primary, companions=(companion,))
    )

    with snapshot_resolved_source(resolved) as snapshot:
        snapshot_primary = snapshot.primary
        snapshot_companion = snapshot.companions[0]
        assert snapshot_primary.read_text(encoding="utf-8") == "Question"
        assert snapshot_companion.read_text(encoding="utf-8") == "Labels"
        assert snapshot.primary_sha256 == hashlib.sha256(b"Question").hexdigest()
        assert snapshot.companion_sha256 == (hashlib.sha256(b"Labels").hexdigest(),)

    assert snapshot_primary.exists() is False
    assert snapshot_companion.exists() is False


def test_snapshot_uses_filename_for_a_source_outside_declared_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    primary = tmp_path / "questionnaire.txt"
    primary.write_text("Question", encoding="utf-8")
    resolved = ResolvedSource(root=root.resolve(), primary=primary.resolve())

    with snapshot_resolved_source(resolved) as snapshot:
        assert snapshot.primary.name == primary.name
        assert snapshot.primary.parent == snapshot.root


def test_snapshot_rechecks_size_and_detects_source_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "questionnaire.txt"
    primary.write_text("Question", encoding="utf-8")
    resolved = resolve_local_source(primary)

    with (
        pytest.raises(SourceLimitError, match="byte limit"),
        snapshot_resolved_source(
            resolved,
            limits=replace(DEFAULT_SOURCE_LIMITS, max_source_bytes=7),
        ),
    ):
        pytest.fail("an oversized snapshot must not be yielded")

    original_fstat = source_base.os.fstat
    calls = 0

    def changed_fstat(file_descriptor: int) -> object:
        nonlocal calls
        result = original_fstat(file_descriptor)
        calls += 1
        if calls == 2:
            return SimpleNamespace(
                st_size=result.st_size,
                st_mtime_ns=result.st_mtime_ns + 1,
            )
        return result

    monkeypatch.setattr(source_base.os, "fstat", changed_fstat)
    with (
        pytest.raises(SourceInputError, match="changed"),
        snapshot_resolved_source(resolved),
    ):
        pytest.fail("a changed snapshot must not be yielded")


def test_snapshot_copy_io_errors_are_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    primary = tmp_path / "questionnaire.txt"
    primary.write_text("Question", encoding="utf-8")
    resolved = resolve_local_source(primary)
    original_open = Path.open

    def fail_source_open(
        path: Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO[Any]:
        if path == primary.resolve():
            raise OSError("unreadable")
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", fail_source_open)

    with (
        pytest.raises(SourceInputError, match="copied"),
        snapshot_resolved_source(resolved),
    ):
        pytest.fail("an unreadable snapshot must not be yielded")


def test_registry_signature_edges_include_xlsx_and_non_container_formats(tmp_path: Path) -> None:
    pdf = tmp_path / "questionnaire.pdf"
    pdf.write_bytes(b"%PDF-")
    workbook = tmp_path / "questionnaire.xlsx"
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr("XL\\WORKBOOK.XML", "<workbook/>")

    source_registry._verify_signature(pdf, ".pdf")
    source_registry._verify_signature(workbook, ".xlsx")
    source_registry._verify_signature(tmp_path / "not-opened.txt", ".txt")

    word_package = tmp_path / "questionnaire.xlsx"
    with zipfile.ZipFile(word_package, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
    with pytest.raises(SourceFormatError, match="does not match"):
        source_registry._verify_signature(word_package, ".xlsx")
