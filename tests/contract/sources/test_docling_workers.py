"""Deterministic contracts for Docling worker messages, reuse, and range deadlines."""

from __future__ import annotations

import os
import threading
from collections import deque
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from queue import Empty
from types import SimpleNamespace
from typing import Any, cast

import pytest

from survey_scribe.sources import docling as docling_source
from survey_scribe.sources.base import (
    SourceConversionError,
    SourceDependencyError,
    SourceError,
    SourceFormatError,
    SourceLimitError,
    SourceSecurityError,
    SourceTimeoutError,
)
from survey_scribe.sources.docling import PdfConversion, PdfConversionBlock

_PATH = Path("questionnaire.pdf")
_RANGES = ((1, 2), (3, 3))
_TEXT = PdfConversion(page_count=3, blocks=(PdfConversionBlock(text="Question", page=1),))
_TABLE = PdfConversion(
    page_count=3,
    blocks=(
        PdfConversionBlock(text="code | label", page=1, table_rows=(("code", "label"),)),
        PdfConversionBlock(text="Question", page=1),
    ),
)


def _convert(path: str, artifacts_path: str | None) -> PdfConversion:
    del path, artifacts_path
    return _TEXT


class FakeQueue:
    """A finite response script; no worker thread or queue feeder is started."""

    def __init__(self, *messages: object) -> None:
        self.messages = deque(messages)
        self.sent: list[object] = []
        self.timeouts: list[float | None] = []
        self.put_error: Exception | None = None
        self.closed = False
        self.joined = False

    def get(self, *, timeout: float | None = None) -> object:
        self.timeouts.append(timeout)
        if not self.messages:
            raise Empty
        message = self.messages.popleft()
        if isinstance(message, BaseException):
            raise message
        return message

    def put(self, message: object) -> None:
        if self.put_error is not None:
            raise self.put_error
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True

    def join_thread(self) -> None:
        self.joined = True


class FakeProcess:
    def __init__(self, *, target: object = None, args: object = ()) -> None:
        self.target = target
        self.args = args
        self.alive = True
        self.daemon = False
        self.started = False
        self.terminated = False
        self.killed = False
        self.exitcode: int | None = None
        self.joins: list[float | None] = []

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        self.joins.append(timeout)

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def kill(self) -> None:
        self.killed = True
        self.alive = False


class FakeContext:
    def __init__(self) -> None:
        self.response_batches: deque[tuple[object, ...]] = deque()
        self.queues: list[FakeQueue] = []
        self.processes: list[FakeProcess] = []

    def Queue(self, maxsize: int = 0) -> FakeQueue:
        assert maxsize in (0, 1)
        queue = FakeQueue(*(self.response_batches.popleft() if maxsize else ()))
        self.queues.append(queue)
        return queue

    def Process(self, *, target: object, args: object) -> FakeProcess:
        process = FakeProcess(target=target, args=args)
        self.processes.append(process)
        return process


@pytest.fixture
def worker_context(monkeypatch: pytest.MonkeyPatch) -> FakeContext:
    context = FakeContext()

    def get_context(method: str) -> FakeContext:
        assert method == "spawn"
        return context

    monkeypatch.setattr(docling_source, "get_context", get_context)
    return context


class RangeConverter:
    def __init__(self, *conversions: PdfConversion) -> None:
        self.conversions = conversions
        self.calls: list[tuple[str, str | None, tuple[tuple[int, int], ...]]] = []
        self.yielded = 0

    def __call__(self, path: str, artifacts_path: str | None) -> PdfConversion:
        pytest.fail("range conversion must not call the whole-document converter")

    def convert_pages(
        self, path: str, artifacts_path: str | None, ranges: tuple[tuple[int, int], ...]
    ) -> Iterator[PdfConversion]:
        self.calls.append((path, artifacts_path, ranges))
        for conversion in self.conversions:
            self.yielded += 1
            yield conversion


@pytest.mark.parametrize(
    ("ready_names", "message", "error_type", "get_count"),
    [
        (("reader",), ("ok", "", _TEXT), None, 1),
        (("reader", "sentinel"), ("ok", "", _TEXT), None, 1),
        (("sentinel",), ("ok", "", _TEXT), None, 1),
        (("sentinel",), Empty(), ChildProcessError, 1),
        ((), ("ok", "", _TEXT), Empty, 0),
    ],
)
def test_wait_protocol_prioritizes_buffered_responses_over_worker_exit(
    monkeypatch: pytest.MonkeyPatch,
    ready_names: tuple[str, ...],
    message: object,
    error_type: type[Exception] | None,
    get_count: int,
) -> None:
    output = FakeQueue(message)
    reader, sentinel = object(), object()
    output_with_reader = cast(Any, output)
    output_with_reader._reader = reader
    process = SimpleNamespace(sentinel=sentinel)
    handles = {"reader": reader, "sentinel": sentinel}

    def wait(objects: tuple[object, ...], *, timeout: float) -> list[object]:
        assert objects == (reader, sentinel)
        assert timeout == 7
        return [handles[name] for name in ready_names]

    monkeypatch.setattr(docling_source, "wait", wait)
    if error_type is None:
        assert docling_source._wait_for_worker_message(output, process, 7) == message
    else:
        with pytest.raises(error_type):
            docling_source._wait_for_worker_message(output, process, 7)
    assert output.timeouts == [0.1] * get_count


@pytest.mark.parametrize("alive", [False, True])
def test_wait_without_native_handles_distinguishes_crash_from_timeout(alive: bool) -> None:
    process = FakeProcess()
    process.alive = alive
    output = FakeQueue(Empty())
    with pytest.raises(Empty if alive else ChildProcessError):
        docling_source._wait_for_worker_message(output, process, 2)
    assert output.timeouts == [2]


def test_reusable_worker_restarts_for_a_new_converter_or_dead_process(
    worker_context: FakeContext,
) -> None:
    worker_context.response_batches.extend(
        [(("ok", "", _TEXT), ("ok", "", _TEXT)), (("ok", "", _TABLE),), (("ok", "", _TEXT),)]
    )
    runner = docling_source._WorkerRunner(block_network=True)
    for _ in range(2):
        assert runner.run_single(_convert, _PATH, artifacts_path="cache", timeout=1) == _TEXT
    assert len(worker_context.processes) == 1
    first = worker_context.processes[0]
    requests, responses = worker_context.queues
    assert first.started and first.daemon
    assert first.target is docling_source._persistent_pdf_worker
    assert first.args == (_convert, True, requests, responses)
    assert requests.sent == [("single", str(_PATH), "cache", None, None)] * 2

    def replacement(path: str, artifacts_path: str | None) -> PdfConversion:
        del path, artifacts_path
        return _TABLE

    assert runner.run_single(replacement, _PATH, artifacts_path=None, timeout=1) == _TABLE
    assert requests.sent[-1] is None
    assert first.terminated
    assert all(queue.closed and queue.joined for queue in (requests, responses))
    second = worker_context.processes[1]
    second.alive = False
    old_requests = worker_context.queues[2]
    assert runner.run_single(replacement, _PATH, artifacts_path=None, timeout=1) == _TEXT
    assert len(worker_context.processes) == 3
    assert old_requests.sent == [("single", str(_PATH), None, None, None)]
    assert not second.terminated
    runner.close()
    runner.close()
    assert all(queue.closed and queue.joined for queue in worker_context.queues)
    assert runner._process is runner._requests is runner._responses is runner._converter is None


@pytest.mark.parametrize("put_error", [ValueError("closed"), OSError("broken pipe")])
def test_shutdown_still_reaps_and_closes_queues_when_stop_message_cannot_be_sent(
    worker_context: FakeContext, put_error: Exception
) -> None:
    worker_context.response_batches.append((("ok", "", _TEXT),))
    runner = docling_source._WorkerRunner(block_network=False)
    runner.run_single(_convert, _PATH, artifacts_path=None, timeout=1)
    worker_context.queues[0].put_error = put_error
    runner.close()
    assert worker_context.processes[0].terminated
    assert worker_context.processes[0].joins == [0.1, 0.5]
    assert all(queue.closed and queue.joined for queue in worker_context.queues)
    assert runner._process is runner._requests is runner._responses is runner._converter is None


@pytest.mark.parametrize(
    ("failure", "error_type", "message"),
    [
        (Empty(), SourceTimeoutError, r"\.xls conversion exceeded the configured deadline"),
        (ChildProcessError(), SourceConversionError, "killed by signal 9 .*likely out of memory"),
    ],
)
def test_single_worker_failure_discards_state_and_next_call_starts_cleanly(
    worker_context: FakeContext,
    failure: Exception,
    error_type: type[Exception],
    message: str,
) -> None:
    worker_context.response_batches.extend([(failure,), (("ok", "", _TEXT),)])
    runner = docling_source._WorkerRunner(block_network=False)
    runner._ensure_started(_convert)
    worker_context.processes[0].exitcode = -9
    with pytest.raises(error_type, match=message):
        runner.run_single(_convert, _PATH, artifacts_path=None, timeout=1, kind=".xls")
    assert worker_context.processes[0].terminated
    assert all(queue.closed and queue.joined for queue in worker_context.queues)
    assert runner._process is runner._requests is runner._responses is runner._converter is None
    try:
        assert runner.run_single(_convert, _PATH, artifacts_path=None, timeout=1) == _TEXT
        assert len(worker_context.processes) == 2
    finally:
        runner.close()


@pytest.mark.parametrize(
    "error_type",
    [
        SourceDependencyError,
        SourceSecurityError,
        SourceLimitError,
        SourceFormatError,
        SourceTimeoutError,
        SourceConversionError,
    ],
)
def test_converter_error_keeps_the_worker_reusable_and_preserves_error_type(
    worker_context: FakeContext, error_type: type[SourceError]
) -> None:
    worker_context.response_batches.append(
        (("error", error_type.code, "cannot convert"), ("ok", "", _TABLE))
    )
    runner = docling_source._WorkerRunner(block_network=False)
    try:
        with pytest.raises(error_type, match="cannot convert") as raised:
            runner.run_single(_convert, _PATH, artifacts_path=None, timeout=1)
        if isinstance(raised.value, SourceLimitError):
            assert raised.value.limit == "max_cells"
        assert (
            runner.run_single(_convert, _PATH, artifacts_path=None, timeout=1, max_cells=2)
            == _TABLE
        )
        assert len(worker_context.processes) == 1
        assert not worker_context.processes[0].terminated
    finally:
        runner.close()


@pytest.mark.parametrize("status", ["ok", "unexpected"])
def test_single_worker_rejects_invalid_success_payloads(
    worker_context: FakeContext, status: str
) -> None:
    worker_context.response_batches.append(((status, "unknown", "not a conversion"),))
    runner = docling_source._WorkerRunner(block_network=False)
    try:
        with pytest.raises(SourceConversionError, match="not a conversion"):
            runner.run_single(_convert, _PATH, artifacts_path=None, timeout=1)
    finally:
        runner.close()


@pytest.mark.parametrize("max_cells", [None, 4])
@pytest.mark.parametrize("report_progress", [False, True])
def test_reusable_worker_streams_ordered_ranges_and_page_weighted_progress(
    worker_context: FakeContext,
    monkeypatch: pytest.MonkeyPatch,
    max_cells: int | None,
    report_progress: bool,
) -> None:
    worker_context.response_batches.append(
        (("chunk", "", _TABLE), ("chunk", "", _TEXT), ("done", "", None))
    )
    monkeypatch.setattr(docling_source.time, "monotonic", lambda: 10)
    runner = docling_source._WorkerRunner(block_network=False)
    calls: list[tuple[int, int]] = []
    try:
        chunks, timed_out = runner.run_ranges(
            RangeConverter(),
            _PATH,
            artifacts_path="cache",
            ranges=_RANGES,
            timeout=5,
            max_cells=max_cells,
            partial_on_deadline=False,
            progress=(lambda done, total: calls.append((done, total))) if report_progress else None,
        )
        assert chunks == [(_RANGES[0], _TABLE), (_RANGES[1], _TEXT)]
        assert timed_out is False
        assert calls == ([(2, 3), (3, 3)] if report_progress else [])
        assert worker_context.queues[0].sent == [
            ("ranges", str(_PATH), "cache", max_cells, _RANGES)
        ]
        assert worker_context.queues[1].timeouts == [5, 5, 5]
        assert worker_context.processes[0].is_alive()
    finally:
        runner.close()


@pytest.mark.parametrize(
    ("messages", "detail", "expected_progress"),
    [
        ((("done", "", "early completion"),), "early completion", []),
        ((("chunk", "", "wrong payload"),), "wrong payload", []),
        (
            (("chunk", "", _TEXT), ("chunk", "", "extra range")),
            "extra range",
            [(1, 1)],
        ),
        (
            (("chunk", "", _TEXT), ("chunk", "", _TEXT)),
            "PdfConversion",
            [(1, 1)],
        ),
        ((("error", SourceFormatError.code, "damaged page"),), "damaged page", []),
    ],
)
def test_range_worker_rejects_out_of_order_or_invalid_messages(
    worker_context: FakeContext,
    messages: tuple[object, ...],
    detail: str,
    expected_progress: list[tuple[int, int]],
) -> None:
    worker_context.response_batches.append(messages)
    runner = docling_source._WorkerRunner(block_network=False)
    progress: list[tuple[int, int]] = []
    try:
        with pytest.raises((SourceConversionError, SourceFormatError), match=detail):
            runner.run_ranges(
                RangeConverter(),
                _PATH,
                artifacts_path=None,
                ranges=((1, 1),),
                timeout=5,
                max_cells=None,
                partial_on_deadline=True,
                progress=lambda done, total: progress.append((done, total)),
            )
        assert progress == expected_progress
    finally:
        runner.close()


@pytest.mark.parametrize(
    ("finished", "partial_on_deadline"), [(False, True), (True, False), (True, True)]
)
def test_range_deadline_returns_only_completed_chunks_and_discards_worker(
    worker_context: FakeContext, finished: bool, partial_on_deadline: bool
) -> None:
    messages: tuple[object, ...] = (("chunk", "", _TEXT), Empty()) if finished else (Empty(),)
    worker_context.response_batches.append(messages)
    runner = docling_source._WorkerRunner(block_network=False)
    progress: list[tuple[int, int]] = []
    kwargs: dict[str, Any] = dict(
        artifacts_path=None,
        ranges=_RANGES,
        timeout=5,
        max_cells=None,
        partial_on_deadline=partial_on_deadline,
        progress=lambda done, total: progress.append((done, total)),
    )
    if finished and partial_on_deadline:
        assert runner.run_ranges(RangeConverter(), _PATH, **kwargs) == ([(_RANGES[0], _TEXT)], True)
    else:
        with pytest.raises(SourceTimeoutError, match="configured deadline"):
            runner.run_ranges(RangeConverter(), _PATH, **kwargs)
    assert progress == ([(2, 3)] if finished else [])
    assert worker_context.processes[0].terminated
    assert all(queue.closed and queue.joined for queue in worker_context.queues)
    assert runner._process is runner._requests is runner._responses is runner._converter is None
    runner._kill()


def test_expired_range_deadline_does_not_wait_for_a_response(
    worker_context: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_context.response_batches.append((("chunk", "", _TEXT),))
    clock = iter((0, 2))
    monkeypatch.setattr(docling_source.time, "monotonic", lambda: next(clock))
    runner = docling_source._WorkerRunner(block_network=False)
    with pytest.raises(SourceTimeoutError):
        runner.run_ranges(
            RangeConverter(),
            _PATH,
            artifacts_path=None,
            ranges=_RANGES,
            timeout=1,
            max_cells=None,
            partial_on_deadline=True,
            progress=None,
        )
    assert worker_context.queues[1].timeouts == []
    assert worker_context.processes[0].terminated


def test_range_worker_crash_is_not_presented_as_a_partial_deadline(
    worker_context: FakeContext,
) -> None:
    worker_context.response_batches.append((("chunk", "", _TEXT), ChildProcessError()))
    runner = docling_source._WorkerRunner(block_network=False)
    converter = RangeConverter()
    runner._ensure_started(converter)
    worker_context.processes[0].exitcode = 87
    with pytest.raises(SourceConversionError, match="exit code 87"):
        runner.run_ranges(
            converter,
            _PATH,
            artifacts_path=None,
            ranges=_RANGES,
            timeout=5,
            max_cells=None,
            partial_on_deadline=True,
            progress=None,
        )
    assert worker_context.processes[0].terminated
    assert all(queue.closed and queue.joined for queue in worker_context.queues)


@pytest.mark.parametrize("max_cells", [None, 2])
def test_inprocess_single_passes_paths_and_does_not_start_a_worker(
    worker_context: FakeContext, max_cells: int | None
) -> None:
    seen: list[tuple[str, str | None]] = []

    def converter(path: str, artifacts_path: str | None) -> PdfConversion:
        seen.append((path, artifacts_path))
        return _TABLE

    runner = docling_source._InProcessRunner()
    assert (
        runner.run_single(
            converter,
            _PATH,
            artifacts_path="cache",
            timeout=-1,
            max_cells=max_cells,
        )
        == _TABLE
    )
    assert seen == [(str(_PATH), "cache")]
    assert worker_context.processes == worker_context.queues == []
    assert runner.close() is None


@pytest.mark.parametrize("max_cells", [None, 4])
@pytest.mark.parametrize("report_progress", [False, True])
def test_inprocess_ranges_preserve_order_and_report_page_counts(
    monkeypatch: pytest.MonkeyPatch, max_cells: int | None, report_progress: bool
) -> None:
    monkeypatch.setattr(docling_source.time, "monotonic", lambda: 10)
    converter = RangeConverter(_TABLE, _TEXT)
    progress: list[tuple[int, int]] = []
    chunks, timed_out = docling_source._InProcessRunner().run_ranges(
        converter,
        _PATH,
        artifacts_path="cache",
        ranges=_RANGES,
        timeout=1,
        max_cells=max_cells,
        partial_on_deadline=False,
        progress=(lambda done, total: progress.append((done, total))) if report_progress else None,
    )
    assert chunks == [(_RANGES[0], _TABLE), (_RANGES[1], _TEXT)]
    assert timed_out is False
    assert progress == ([(2, 3), (3, 3)] if report_progress else [])
    assert converter.calls == [(str(_PATH), "cache", _RANGES)]


@pytest.mark.parametrize("count", [1, 3])
def test_inprocess_range_count_must_match_the_request(count: int) -> None:
    converter = RangeConverter(*([_TEXT] * count))
    with pytest.raises(SourceConversionError, match="fewer" if count == 1 else "more"):
        docling_source._InProcessRunner().run_ranges(
            converter,
            _PATH,
            artifacts_path=None,
            ranges=_RANGES,
            timeout=5,
            max_cells=None,
            partial_on_deadline=True,
            progress=None,
        )


@pytest.mark.parametrize("partial_on_deadline", [False, True])
def test_inprocess_deadline_stops_between_ranges_without_reading_the_next_one(
    monkeypatch: pytest.MonkeyPatch, partial_on_deadline: bool
) -> None:
    clock = iter((0, 2))
    monkeypatch.setattr(docling_source.time, "monotonic", lambda: next(clock))
    converter = RangeConverter(_TEXT, _TABLE)
    progress: list[tuple[int, int]] = []
    kwargs: dict[str, Any] = dict(
        artifacts_path=None,
        ranges=_RANGES,
        timeout=1,
        max_cells=None,
        partial_on_deadline=partial_on_deadline,
        progress=lambda done, total: progress.append((done, total)),
    )
    if partial_on_deadline:
        assert docling_source._InProcessRunner().run_ranges(converter, _PATH, **kwargs) == (
            [(_RANGES[0], _TEXT)],
            True,
        )
    else:
        with pytest.raises(SourceTimeoutError, match="configured deadline"):
            docling_source._InProcessRunner().run_ranges(converter, _PATH, **kwargs)
    assert converter.yielded == 1
    assert progress == [(2, 3)]


@pytest.mark.parametrize("isolation", ["worker", "inprocess"])
def test_ranges_enforce_one_cumulative_cell_limit_before_reporting_progress(
    worker_context: FakeContext, isolation: str
) -> None:
    worker_context.response_batches.append((("chunk", "", _TABLE), ("chunk", "", _TABLE)))
    runner = docling_source._make_pdf_runner(cast(Any, isolation), block_network=False)
    progress: list[tuple[int, int]] = []
    try:
        with pytest.raises(SourceLimitError) as raised:
            runner.run_ranges(
                RangeConverter(_TABLE, _TABLE),
                _PATH,
                artifacts_path=None,
                ranges=_RANGES,
                timeout=5,
                max_cells=3,
                partial_on_deadline=True,
                progress=lambda done, total: progress.append((done, total)),
            )
        assert raised.value.limit == "max_cells"
        assert progress == [(2, 3)]
    finally:
        runner.close()


@pytest.mark.parametrize("failure_kind", ["cells", "callback", "interrupt"])
def test_parent_range_failure_discards_pending_messages_before_the_next_document(
    worker_context: FakeContext, failure_kind: str
) -> None:
    worker_context.response_batches.extend(
        [
            (("chunk", "", _TABLE), ("chunk", "", _TABLE), ("done", "", None)),
            (("chunk", "", _TEXT), ("chunk", "", _TEXT), ("done", "", None)),
        ]
    )
    runner = docling_source._WorkerRunner(block_network=False)
    converter = RangeConverter()
    failure = KeyboardInterrupt() if failure_kind == "interrupt" else RuntimeError("cancelled")

    def progress(_done: int, _total: int) -> None:
        if failure_kind != "cells":
            raise failure

    error_type = SourceLimitError if failure_kind == "cells" else type(failure)
    with pytest.raises(error_type) as raised:
        runner.run_ranges(
            converter,
            _PATH,
            artifacts_path=None,
            ranges=_RANGES,
            timeout=5,
            max_cells=3,
            partial_on_deadline=True,
            progress=progress,
        )
    if failure_kind == "cells":
        assert isinstance(raised.value, SourceLimitError)
        assert raised.value.limit == "max_cells"
    else:
        assert raised.value is failure
    assert worker_context.processes[0].terminated
    assert all(queue.closed and queue.joined for queue in worker_context.queues)
    assert worker_context.queues[1].messages
    assert runner._process is runner._requests is runner._responses is runner._converter is None
    try:
        assert runner.run_ranges(
            converter,
            _PATH,
            artifacts_path=None,
            ranges=_RANGES,
            timeout=5,
            max_cells=None,
            partial_on_deadline=False,
            progress=None,
        ) == ([(_RANGES[0], _TEXT), (_RANGES[1], _TEXT)], False)
        assert len(worker_context.processes) == 2
    finally:
        runner.close()


def test_docling_model_context_reuses_one_pipeline_and_clears_it_after_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    class Pipeline:
        def convert(self, path: str, *, page_range: tuple[int, int] | None = None) -> object:
            calls.append((path, page_range))
            return SimpleNamespace(
                document=SimpleNamespace(
                    pages={1: object(), 2: object()}, iterate_items=lambda: ()
                ),
                input=SimpleNamespace(page_count=2),
            )

    @contextmanager
    def document_converter(artifacts_path: str | None) -> Iterator[Pipeline]:
        calls.append(("load", artifacts_path))
        try:
            yield Pipeline()
        finally:
            calls.append("release")

    converter = docling_source.DoclingConverter()
    monkeypatch.setattr(converter, "_document_converter", document_converter)
    with pytest.raises(RuntimeError, match="cancelled"), converter.opened("cache"):
        assert converter("first.pdf", "cache").page_count == 2
        with converter.opened("cache"):
            assert len(list(converter.convert_pages("second.pdf", "cache", ((1, 2),)))) == 1
        assert converter("third.pdf", "cache").page_count == 2
        raise RuntimeError("cancelled")
    assert converter._active is None
    assert calls == [
        ("load", "cache"),
        ("first.pdf", None),
        ("second.pdf", (1, 2)),
        ("third.pdf", None),
        "release",
    ]
    assert converter("fourth.pdf", "cache").page_count == 2
    assert calls[-3:] == [("load", "cache"), ("fourth.pdf", None), "release"]
    assert converter._active is None


@pytest.fixture
def worker_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # The entry point normally changes only a child's environment; restore it after direct calls.
    for name in (
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "DOCLING_ARTIFACTS_PATH",
        "SURVEY_SCRIBE_PDF_MAX_CELLS",
    ):
        monkeypatch.setenv(name, "original")


@pytest.mark.usefixtures("worker_environment")
@pytest.mark.parametrize("block_network", [False, True])
def test_persistent_worker_opens_models_once_and_streams_single_and_range_jobs(
    monkeypatch: pytest.MonkeyPatch, block_network: bool
) -> None:
    events: list[object] = []

    @contextmanager
    def blocked_network() -> Iterator[None]:
        events.append("network blocked")
        try:
            yield
        finally:
            events.append("network restored")

    class Converter(RangeConverter):
        @contextmanager
        def opened(self, artifacts_path: str | None) -> Iterator[None]:
            events.append(("opened", artifacts_path))
            try:
                yield
            finally:
                events.append("models closed")

        def __call__(self, path: str, artifacts_path: str | None) -> PdfConversion:
            events.append((path, artifacts_path, os.environ.get("SURVEY_SCRIBE_PDF_MAX_CELLS")))
            assert os.environ["HF_HUB_OFFLINE"] == os.environ["TRANSFORMERS_OFFLINE"] == "1"
            return _TABLE

    monkeypatch.setattr(docling_source, "_blocked_network", blocked_network)
    converter = Converter(_TEXT, _TABLE)
    requests = FakeQueue(
        ("single", "first.pdf", "cache", 2, None),
        ("ranges", "second.pdf", "cache", None, _RANGES),
        ("single", "third.pdf", None, None, None),
        None,
    )
    responses = FakeQueue()
    docling_source._persistent_pdf_worker(converter, block_network, requests, responses)
    expected: list[object] = [
        ("opened", "cache"),
        ("first.pdf", "cache", "2"),
        ("third.pdf", None, None),
        "models closed",
    ]
    if block_network:
        expected = ["network blocked", *expected, "network restored"]
    assert events == expected
    assert converter.calls == [("second.pdf", "cache", _RANGES)]
    assert responses.sent == [
        ("ok", "", _TABLE),
        ("chunk", "", _TEXT),
        ("chunk", "", _TABLE),
        ("done", "", None),
        ("ok", "", _TABLE),
    ]
    assert os.environ["DOCLING_ARTIFACTS_PATH"] == "cache"
    assert "SURVEY_SCRIBE_PDF_MAX_CELLS" not in os.environ
    assert not requests.messages


@pytest.mark.usefixtures("worker_environment")
@pytest.mark.parametrize("failure", [EOFError(), OSError("request pipe closed")])
def test_persistent_worker_exits_cleanly_when_the_request_pipe_closes(failure: Exception) -> None:
    responses = FakeQueue()
    docling_source._persistent_pdf_worker(_convert, False, FakeQueue(failure), responses)
    assert responses.sent == []


@pytest.mark.usefixtures("worker_environment")
@pytest.mark.parametrize(
    "failure",
    [SourceFormatError("damaged\npage"), RuntimeError("broken\nconverter"), SystemExit("stop")],
)
def test_persistent_worker_serializes_errors_and_accepts_the_next_document(
    failure: BaseException,
) -> None:
    calls: list[str] = []

    def converter(path: str, artifacts_path: str | None) -> PdfConversion:
        del artifacts_path
        calls.append(path)
        if len(calls) == 1:
            raise failure
        return _TEXT

    requests = FakeQueue(
        ("single", "bad.pdf", None, None, None),
        ("single", "good.pdf", None, None, None),
        None,
    )
    responses = FakeQueue()
    docling_source._persistent_pdf_worker(converter, False, requests, responses)
    status, code, detail = cast(tuple[str, str, str], responses.sent[0])
    assert status == "error"
    assert code == (
        failure.code if isinstance(failure, SourceError) else SourceConversionError.code
    )
    assert " ".join(str(failure).split()) in detail
    assert "\n" not in detail and len(detail) <= 500
    if not isinstance(failure, SourceError):
        assert type(failure).__name__ in detail
        assert "in converter)" in detail
    assert responses.sent[1:] == [("ok", "", _TEXT)]
    assert calls == ["bad.pdf", "good.pdf"]


@pytest.mark.usefixtures("worker_environment")
def test_persistent_worker_rejects_oversized_tables_before_sending_success() -> None:
    def converter(path: str, artifacts_path: str | None) -> PdfConversion:
        del path, artifacts_path
        return _TABLE

    responses = FakeQueue()
    docling_source._persistent_pdf_worker(
        converter,
        False,
        FakeQueue(("single", "large.pdf", None, 1, None), None),
        responses,
    )
    assert len(responses.sent) == 1
    status, code, message = cast(tuple[str, str, str], responses.sent[0])
    assert (status, code) == ("error", SourceLimitError.code)
    assert "cell limit" in message


def test_reusable_worker_serializes_calls_from_different_threads(
    worker_context: FakeContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_context.response_batches.append((("ok", "", _TEXT), ("ok", "", _TABLE)))
    runner = docling_source._WorkerRunner(block_network=False)
    waiting_for_response = threading.Event()
    second_lock_attempt = threading.Event()
    release_response = threading.Event()
    original_lock = runner._lock

    class ObservedLock:
        entries = 0

        def __enter__(self) -> None:
            self.entries += 1
            if self.entries == 2:
                second_lock_attempt.set()
            original_lock.acquire()

        def __exit__(self, *_args: object) -> None:
            original_lock.release()

    monkeypatch.setattr(runner, "_lock", ObservedLock())

    def wait(output: FakeQueue, process: FakeProcess, timeout: float) -> object:
        del process
        if not waiting_for_response.is_set():
            waiting_for_response.set()
            assert release_response.wait(timeout=5)
        return output.get(timeout=timeout)

    monkeypatch.setattr(docling_source, "_wait_for_worker_message", wait)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(
                runner.run_single,
                _convert,
                Path("first.pdf"),
                artifacts_path=None,
                timeout=5,
            )
            try:
                assert waiting_for_response.wait(timeout=5)
                second = executor.submit(
                    runner.run_single,
                    _convert,
                    Path("second.pdf"),
                    artifacts_path=None,
                    timeout=5,
                )
                assert second_lock_attempt.wait(timeout=5)
                assert worker_context.queues[0].sent == [("single", "first.pdf", None, None, None)]
            finally:
                release_response.set()
            assert first.result(timeout=5) == _TEXT
            assert second.result(timeout=5) == _TABLE
        assert len(worker_context.processes) == 1
        assert worker_context.queues[0].sent == [
            ("single", "first.pdf", None, None, None),
            ("single", "second.pdf", None, None, None),
        ]
    finally:
        runner.close()


def test_separate_runners_do_not_share_workers_or_queues(worker_context: FakeContext) -> None:
    worker_context.response_batches.extend([(("ok", "", _TEXT),), (("ok", "", _TABLE),)])
    first = docling_source._WorkerRunner(block_network=False)
    second = docling_source._WorkerRunner(block_network=True)
    try:
        assert first.run_single(_convert, _PATH, artifacts_path=None, timeout=1) == _TEXT
        assert second.run_single(_convert, _PATH, artifacts_path="cache", timeout=1) == _TABLE
        assert first._lock is not second._lock
        assert first._process is not second._process
        assert first._requests is not second._requests
        assert first._responses is not second._responses
        first.close()
        assert second._process is not None and second._process.is_alive()
        assert not worker_context.queues[2].closed
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_pdf_adapter_requires_a_boolean_network_setting(value: object) -> None:
    with pytest.raises(ValueError, match="block_network must be a boolean"):
        docling_source.DoclingPdfAdapter(converter=_convert, block_network=cast(Any, value))


def test_runner_factory_rejects_unknown_isolation() -> None:
    with pytest.raises(ValueError, match="isolation must be one of"):
        docling_source._make_pdf_runner(cast(Any, "invalid"), block_network=False)
