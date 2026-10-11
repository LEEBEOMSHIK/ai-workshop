"""Packet transport matches the actual child's stdin EOF/exit boundary."""

from pathlib import Path

import pytest

from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess
from tests.unit.labs.rag.indexing.access_epoch_native_fixture import PacketKernel


@pytest.mark.parametrize("size", [0, 8192, 8193, 12288, 16384])
def test_complete_synthetic_input_precedes_child_exit(tmp_path: Path, size: int) -> None:
    kernel = PacketKernel()
    kernel.outputs.append(b"synthetic-output")
    native = WindowsControlProcess(kernel)
    token = native.create_suspended(
        ("C:/Windows/System32/synthetic-fixture.exe",), {}, tmp_path, stdin=b"x" * size
    )
    try:
        native.resume(token)
        result = native.wait(token, 1000)
        written = 0
        for call in kernel.calls:
            if call[0] == "private_write":
                assert type(call[2]) is int
                written += call[2]
        assert written == size
        assert result.stdout == b"synthetic-output" and result.exit_code == 0
        assert 105 in kernel.closed
    finally:
        native.close(token)


def test_input_child_stays_active_until_writer_eof(tmp_path: Path) -> None:
    kernel = PacketKernel()
    kernel.outputs.append(b"synthetic-output")
    child = kernel.create(("synthetic",), {}, tmp_path, stdin_pipe=True)
    assert child.stdin is not None
    kernel.resume(child.thread)
    assert not kernel.poll(child.process)
    assert kernel.active_processes(child.job) == 1
    kernel.write(child.stdin, memoryview(b"synthetic-input"))
    assert not kernel.poll(child.process)
    assert kernel.active_processes(child.job) == 1
    kernel.close(child.stdin)
    assert kernel.poll(child.process)
    assert kernel.active_processes(child.job) == 0


def test_writer_eof_is_bound_to_its_exact_child(tmp_path: Path) -> None:
    kernel = PacketKernel()
    kernel.outputs.extend([b"first", b"second"])
    first = kernel.create(("synthetic",), {}, tmp_path, stdin_pipe=True)
    second = kernel.create(("synthetic",), {}, tmp_path, stdin_pipe=True)
    assert first.stdin is not None and second.stdin is not None
    kernel.resume(first.thread)
    kernel.resume(second.thread)
    kernel.close(first.stdin)
    assert kernel.poll(first.process) and kernel.active_processes(first.job) == 0
    assert not kernel.poll(second.process) and kernel.active_processes(second.job) == 1
    kernel.close(second.stdin)
    assert kernel.poll(second.process) and kernel.active_processes(second.job) == 0


def test_no_input_and_fifo_output_recipes_are_preserved(tmp_path: Path) -> None:
    kernel = PacketKernel()
    kernel.outputs.extend([b"first", b"second"])
    native = WindowsControlProcess(kernel)
    for expected in (b"first", b"second"):
        token = native.create_suspended(
            ("C:/Windows/System32/synthetic-fixture.exe",), {}, tmp_path
        )
        try:
            native.resume(token)
            result = native.wait(token, 1000)
            assert result.stdout == expected and result.exit_code == 0
        finally:
            native.close(token)
    assert kernel.created == 2
    assert not any(call[0] == "private_write" for call in kernel.calls)
