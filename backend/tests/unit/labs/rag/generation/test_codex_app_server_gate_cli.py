from __future__ import annotations

import asyncio
import errno
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest

from ai_workshop.labs.rag.generation.codex_app_server_gate import IsolationObservation


def safe_observation() -> IsolationObservation:
    return IsolationObservation(
        cli_version="0.151.0",
        config_read=True,
        requirements_read=True,
        effective_tool_inventory_read=True,
        forbidden_builtin_tool_count=0,
        shell_enabled=False,
        web_enabled=False,
        apps_enabled=False,
        plugins_enabled=False,
        multi_agent_enabled=False,
        mcp_callable_count=0,
        app_callable_count=0,
        plugin_enabled_count=0,
        skill_enabled_count=0,
        hook_enabled_count=0,
        approval_policy="never",
        sandbox_mode="readOnly",
    )


class FakeProbe:
    started = 0
    observation = safe_observation()
    last_kwargs: dict[str, object] = {}
    empty_cwd_was_empty = False

    def __init__(self, **kwargs: object) -> None:
        type(self).started += 1
        self.kwargs = kwargs
        type(self).last_kwargs = kwargs
        type(self).empty_cwd_was_empty = not any(Path(kwargs["empty_cwd"]).iterdir())

    async def probe(self) -> IsolationObservation:
        return type(self).observation


class ExplodingProbe:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def probe(self) -> IsolationObservation:
        raise RuntimeError("secret operational failure")


class SyntheticProbeConstructionError(Exception):
    pass


class ConstructorExplodingProbe:
    def __init__(self, **kwargs: object) -> None:
        raise SyntheticProbeConstructionError(
            f"synthetic secret at {kwargs['empty_cwd']}"
        )


class ContentWritingProbe:
    def __init__(self, **kwargs: object) -> None:
        self.empty_cwd = Path(kwargs["empty_cwd"])

    async def probe(self) -> IsolationObservation:
        (self.empty_cwd / "retained.txt").write_text("retain", encoding="utf-8")
        return safe_observation()


class CancelledProbe:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def probe(self) -> IsolationObservation:
        raise asyncio.CancelledError


class MalformedProbe:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def probe(self) -> object:
        return object()


@pytest.fixture(autouse=True)
def reset_fake_probe() -> None:
    FakeProbe.started = 0
    FakeProbe.observation = safe_observation()
    FakeProbe.last_kwargs = {}
    FakeProbe.empty_cwd_was_empty = False


@pytest.fixture
def repository_root(tmp_path: Path) -> Path:
    (tmp_path / ".local-data").mkdir()
    return tmp_path


def version_runner(command: tuple[str, ...]) -> str:
    assert command == ("safe-codex", "--version")
    return "0.151.0"


def command_args(repository_root: Path) -> list[str]:
    return [
        "--codex-command",
        "safe-codex",
        "--codex-home",
        str(repository_root / ".local-data" / "codex-app-server" / "home"),
        "--report-dir",
        str(repository_root / ".local-data" / "codex-app-server" / "report"),
    ]


def test_cli_writes_only_sanitized_pass_report(
    capsys: pytest.CaptureFixture[str], repository_root: Path
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    report_path = (
        repository_root
        / ".local-data"
        / "codex-app-server"
        / "report"
        / "gate-report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    console = capsys.readouterr().out

    assert exit_code == 0
    assert FakeProbe.started == 1
    assert set(report) == {
        "schema_version",
        "status",
        "safe_error_code",
        "cli_version",
        "violations",
        "observation_hash",
    }
    assert report["status"] == "pass"
    assert report["violations"] == []
    assert str(repository_root) not in console
    assert "status=pass" in console
    assert "observation_hash=" in console
    assert not list(
        (repository_root / ".local-data" / "codex-app-server" / "gate-runs").iterdir()
    )


def test_cli_writes_completed_failure_report(repository_root: Path) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    FakeProbe.observation = replace(safe_observation(), shell_enabled=True)

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    report = json.loads(
        (
            repository_root
            / ".local-data"
            / "codex-app-server"
            / "report"
            / "gate-report.json"
        ).read_text(encoding="utf-8")
    )
    assert exit_code == 1
    assert report["safe_error_code"] == "codex_isolation_not_enforced"
    assert report["violations"] == [{"rule_id": "shell_enabled"}]


def test_version_mismatch_is_invalid_and_never_starts_app_server(
    capsys: pytest.CaptureFixture[str], repository_root: Path
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=lambda _command: "0.152.0",
    )

    assert exit_code == 2
    assert FakeProbe.started == 0
    assert not (
        repository_root
        / ".local-data"
        / "codex-app-server"
        / "report"
        / "gate-report.json"
    ).exists()
    assert str(repository_root) not in capsys.readouterr().out


@pytest.mark.parametrize("target_name", ["home", "report"])
def test_boundary_escape_is_invalid_and_does_not_start_app_server(
    repository_root: Path, target_name: str
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    args = command_args(repository_root)
    option = "--codex-home" if target_name == "home" else "--report-dir"
    index = args.index(option) + 1
    args[index] = str(repository_root / "outside" / target_name)

    exit_code = main(
        args,
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    assert exit_code == 2
    assert FakeProbe.started == 0


def test_non_empty_report_target_is_rejected_without_overwriting(
    repository_root: Path,
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    report_dir = repository_root / ".local-data" / "codex-app-server" / "report"
    report_dir.mkdir(parents=True)
    preserved = report_dir / "unrelated.txt"
    preserved.write_text("keep", encoding="utf-8")

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    assert exit_code == 2
    assert FakeProbe.started == 0
    assert preserved.read_text(encoding="utf-8") == "keep"


def test_existing_report_file_is_never_overwritten(repository_root: Path) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    report_dir = repository_root / ".local-data" / "codex-app-server" / "report"
    report_dir.mkdir(parents=True)
    report_path = report_dir / "gate-report.json"
    report_path.write_text("keep", encoding="utf-8")

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    assert exit_code == 2
    assert FakeProbe.started == 0
    assert report_path.read_text(encoding="utf-8") == "keep"


def test_symlinked_target_is_rejected_where_supported(repository_root: Path) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    boundary = repository_root / ".local-data" / "codex-app-server"
    boundary.mkdir()
    linked_home = boundary / "home"
    try:
        linked_home.symlink_to(repository_root / "outside", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    assert exit_code == 2
    assert FakeProbe.started == 0


def test_console_redacts_version_reader_failure(
    repository_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=lambda _command: (_ for _ in ()).throw(
            RuntimeError(f"secret path {repository_root}")
        ),
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert FakeProbe.started == 0
    assert "secret" not in output
    assert str(repository_root) not in output


def test_probe_exception_writes_a_fail_closed_report_without_traceback(
    capsys: pytest.CaptureFixture[str], repository_root: Path
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=ExplodingProbe,
        version_reader=version_runner,
    )

    report = json.loads(
        (
            repository_root
            / ".local-data"
            / "codex-app-server"
            / "report"
            / "gate-report.json"
        ).read_text(encoding="utf-8")
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert report["status"] == "fail"
    assert "secret" not in output
    assert "Traceback" not in output


def test_probe_constructor_exception_writes_sanitized_fail_closed_report(
    capsys: pytest.CaptureFixture[str], repository_root: Path
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=ConstructorExplodingProbe,
        version_reader=version_runner,
    )

    report = json.loads(
        (
            repository_root
            / ".local-data"
            / "codex-app-server"
            / "report"
            / "gate-report.json"
        ).read_text(encoding="utf-8")
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert report["status"] == "fail"
    assert report["safe_error_code"] == "codex_isolation_not_enforced"
    assert "synthetic secret" not in output
    assert str(repository_root) not in output
    assert "Traceback" not in output


@pytest.mark.parametrize("probe_factory", [CancelledProbe, MalformedProbe])
def test_cancelled_or_malformed_probe_writes_fail_closed_report(
    repository_root: Path, probe_factory: type[object]
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=probe_factory,  # type: ignore[arg-type]
        version_reader=version_runner,
    )

    report = json.loads(
        (
            repository_root
            / ".local-data"
            / "codex-app-server"
            / "report"
            / "gate-report.json"
        ).read_text(encoding="utf-8")
    )
    assert exit_code == 1
    assert report["status"] == "fail"


@pytest.mark.parametrize(
    "home_suffix,report_suffix",
    [("shared", "shared"), ("home", "home/report"), ("report/home", "report")],
)
def test_home_and_report_subtrees_must_be_disjoint(
    repository_root: Path, home_suffix: str, report_suffix: str
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    boundary = repository_root / ".local-data" / "codex-app-server"
    args = [
        "--codex-command",
        "safe-codex",
        "--codex-home",
        str(boundary / home_suffix),
        "--report-dir",
        str(boundary / report_suffix),
    ]

    exit_code = main(
        args,
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    assert exit_code == 2
    assert FakeProbe.started == 0


def test_atomic_report_publication_preserves_concurrent_destination(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    report_path = (
        repository_root
        / ".local-data"
        / "codex-app-server"
        / "report"
        / "gate-report.json"
    )

    def create_competing_report(source: Path, destination: Path) -> None:
        destination.write_bytes(b"preserve")
        raise FileExistsError

    monkeypatch.setattr(cli_module.os, "link", create_competing_report)

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    assert exit_code == 2
    assert report_path.read_bytes() == b"preserve"


def test_atomic_report_publication_preserves_real_competing_destination(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    real_link = os.link
    report_path = (
        repository_root
        / ".local-data"
        / "codex-app-server"
        / "report"
        / "gate-report.json"
    )

    def publish_competing_file(source: Path, destination: Path) -> None:
        destination.write_bytes(b"real competing bytes")
        real_link(source, destination)

    monkeypatch.setattr(cli_module.os, "link", publish_competing_file)

    assert (
        main(
            command_args(repository_root),
            repository_root=repository_root,
            probe_factory=FakeProbe,
            version_reader=version_runner,
        )
        == 2
    )
    assert report_path.read_bytes() == b"real competing bytes"


@pytest.mark.parametrize("mode", ["oversized-stdout", "oversized-stderr", "timeout"])
def test_production_version_reader_rejects_real_helper_process(
    tmp_path: Path, mode: str
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    command = _version_helper(tmp_path, mode)
    started = time.monotonic()
    with pytest.raises(cli_module._InvalidInvocation):
        cli_module._read_cli_version((str(command), "--version"))
    assert time.monotonic() - started < 3.0


def test_version_reader_uses_exact_no_shell_popen_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    popen_calls: list[tuple[object, dict[str, object]]] = []
    stopped: list[object] = []
    closed_handles: list[int] = []

    class SuccessfulProcess:
        args = ("safe-codex", "--version")
        pid = 123

        def poll(self) -> int:
            return 0

    def capture_popen(command: object, **kwargs: object) -> SuccessfulProcess:
        popen_calls.append((command, kwargs))
        kwargs["stdout"].write(b"codex-cli 0.151.0\n")  # type: ignore[union-attr]
        return SuccessfulProcess()

    monkeypatch.setattr(cli_module.subprocess, "Popen", capture_popen)
    monkeypatch.setattr(
        cli_module, "_stop_version_process", lambda process: stopped.append(process)
    )
    monkeypatch.setattr(
        cli_module, "_assign_windows_kill_on_close_job", lambda _process: 246
    )
    monkeypatch.setattr(
        cli_module, "_close_windows_handle", lambda handle: closed_handles.append(handle)
    )

    assert cli_module._read_cli_version(("safe-codex", "--version")) == "0.151.0"

    assert len(popen_calls) == 1
    command, kwargs = popen_calls[0]
    assert command == ("safe-codex", "--version")
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert hasattr(kwargs["stdout"], "write")
    assert hasattr(kwargs["stderr"], "write")
    expected_keys = {"shell", "stdin", "stdout", "stderr"}
    if os.name == "nt":
        assert set(kwargs) == expected_keys
        assert closed_handles == [246]
    else:
        assert set(kwargs) == expected_keys | {"start_new_session"}
        assert kwargs["start_new_session"] is True
        assert closed_handles == []
    assert len(stopped) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects are unavailable")
def test_windows_version_reader_accepts_exact_real_helper(tmp_path: Path) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    command = _version_helper(tmp_path, "exact")

    assert cli_module._read_cli_version((str(command), "--version")) == "0.151.0"


def _version_helper(tmp_path: Path, mode: str) -> Path:
    script = tmp_path / "version_helper.py"
    script.write_text(
        "import sys\n"
        "import time\n"
        "\n"
        "mode = sys.argv[1]\n"
        "if mode == 'oversized-stdout':\n"
        "    sys.stdout.buffer.write(b'x' * 1048576)\n"
        "    sys.stdout.flush()\n"
        "elif mode == 'oversized-stderr':\n"
        "    sys.stderr.buffer.write(b'x' * 1048576)\n"
        "    sys.stderr.flush()\n"
        "elif mode == 'exact':\n"
        "    sys.stdout.buffer.write(b'codex-cli 0.151.0\\n')\n"
        "    sys.stdout.flush()\n"
        "else:\n"
        "    time.sleep(30)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        command = tmp_path / "version-helper.cmd"
        command.write_text(
            f'@"{sys.executable}" "{script}" {mode} %*\r\n', encoding="utf-8"
        )
        return command
    command = tmp_path / "version-helper"
    command.write_text(
        f"#!{sys.executable}\n"
        "import runpy, sys\n"
        f"sys.argv = ['helper', '{mode}'] + sys.argv[1:]\n"
        f"runpy.run_path('{script}')\n",
        encoding="utf-8",
    )
    command.chmod(0o700)
    return command


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor references are unavailable")
def test_posix_stable_reference_survives_path_rename(tmp_path: Path) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    original = tmp_path / "original"
    original.mkdir()
    pinned = cli_module._pin_directory(original)
    try:
        moved = tmp_path / "moved"
        original.rename(moved)
        original.mkdir()
        reference_details = os.stat(pinned.stable_reference())
        moved_details = os.stat(moved)
        replacement_details = os.stat(original)
        assert (reference_details.st_dev, reference_details.st_ino) == (
            moved_details.st_dev,
            moved_details.st_ino,
        )
        assert reference_details.st_ino != replacement_details.st_ino
    finally:
        pinned.close()


def test_process_group_probe_rejects_non_esrch_error() -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    def inaccessible_group(_pid: int, _signal: int) -> None:
        raise PermissionError

    with pytest.raises(cli_module._InvalidInvocation):
        cli_module._process_group_exists(inaccessible_group, 123)


def test_non_esrch_group_probe_still_attempts_sigkill_and_reap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    calls: list[tuple[str, object]] = []

    class ExitedParent:
        pid = 123

        def wait(self, timeout: float | None = None) -> int:
            calls.append(("wait", timeout))
            return 0

    def controlled_killpg(process_id: int, sent_signal: int) -> None:
        calls.append(("killpg", sent_signal))
        if sent_signal == 0:
            raise PermissionError(errno.EPERM, "private cleanup detail")

    monkeypatch.setattr(cli_module.os, "name", "posix")
    monkeypatch.setattr(cli_module.os, "killpg", controlled_killpg, raising=False)
    monkeypatch.setattr(cli_module.signal, "SIGKILL", 9, raising=False)

    with pytest.raises(cli_module._InvalidInvocation):
        cli_module._stop_version_process(ExitedParent())  # type: ignore[arg-type]

    assert ("killpg", signal.SIGTERM) in calls
    assert ("killpg", 9) in calls
    assert ("wait", 0.2) in calls


def test_partial_pin_acquisition_attempts_every_close_and_preserves_failure(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    close_attempts: list[Path] = []
    acquired: list[object] = []

    class FakePin:
        def __init__(self, path: Path, close_fails: bool) -> None:
            self.path = path
            self.close_fails = close_fails

        def close(self) -> None:
            close_attempts.append(self.path)
            if self.close_fails:
                raise OSError("private close detail")

    def fail_after_three(path: Path) -> object:
        if len(acquired) == 3:
            raise OSError("private acquisition detail")
        pin = FakePin(path, close_fails=len(acquired) in {0, 1})
        acquired.append(pin)
        return pin

    monkeypatch.setattr(cli_module, "_pin_directory", fail_after_three)

    with pytest.raises(OSError, match="private acquisition detail"):
        cli_module._pin_directories(
            repository_root,
            repository_root / ".local-data",
            repository_root / ".local-data" / "codex-app-server",
            repository_root / ".local-data" / "codex-app-server" / "home",
        )

    assert close_attempts == [pin.path for pin in reversed(acquired)]


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory fds are unavailable")
def test_report_emptiness_is_checked_on_pinned_directory_not_replacement(
    tmp_path: Path,
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    pinned_path = tmp_path / "pinned-report"
    pinned_path.mkdir()
    (pinned_path / "unexpected.txt").write_text("retain", encoding="utf-8")
    replacement_path = tmp_path / "replacement-report"
    replacement_path.mkdir()
    pinned = cli_module._pin_directory(pinned_path)
    try:
        with pytest.raises(cli_module._InvalidInvocation):
            cli_module._recheck_empty_report_directory(replacement_path, pinned)
    finally:
        pinned.close()


def test_report_emptiness_passes_pinned_fd_to_directory_listing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    listed: list[object] = []
    pinned = cli_module._PinnedDirectory(
        path=tmp_path / "pinned-report",
        device=1,
        inode=2,
        windows_handle=None,
        posix_fd=77,
    )

    def list_pinned(path: object) -> list[str]:
        listed.append(path)
        return ["unexpected.txt"]

    monkeypatch.setattr(cli_module.os, "listdir", list_pinned)
    replacement = tmp_path / "replacement"
    replacement.mkdir()

    with pytest.raises(cli_module._InvalidInvocation):
        cli_module._recheck_empty_report_directory(replacement, pinned)

    assert listed == [77]


@pytest.mark.skipif(os.name == "nt", reason="POSIX dir_fd removal is unavailable")
def test_posix_run_removal_uses_pinned_parent_fd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    run_parent = tmp_path / "gate-runs"
    run_parent.mkdir()
    run_directory = run_parent / "run"
    run_directory.mkdir()
    run_pin = cli_module._pin_directory(run_directory)
    run_parent_pin = cli_module._pin_directory(run_parent)
    real_stat = os.stat
    real_rmdir = os.rmdir
    calls: list[tuple[str, object, object]] = []

    def record_stat(
        path: str, *, dir_fd: int | None = None, follow_symlinks: bool = True
    ) -> os.stat_result:
        calls.append(("stat", dir_fd, follow_symlinks))
        return real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    def record_rmdir(path: str, *, dir_fd: int | None = None) -> None:
        calls.append(("rmdir", dir_fd, path))
        real_rmdir(path, dir_fd=dir_fd)

    monkeypatch.setattr(cli_module.os, "stat", record_stat)
    monkeypatch.setattr(cli_module.os, "rmdir", record_rmdir)
    try:
        cli_module._remove_empty_run_directory(run_directory, run_pin, run_parent_pin)
        assert calls == [
            ("stat", run_parent_pin.posix_fd, False),
            ("rmdir", run_parent_pin.posix_fd, "run"),
        ]
        assert not run_directory.exists()
    finally:
        run_pin.close()
        run_parent_pin.close()


def test_posix_run_removal_calls_parent_fd_relative_stat_and_rmdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    calls: list[tuple[str, object, object]] = []
    run_pin = cli_module._PinnedDirectory(
        path=tmp_path / "gate-runs" / "run",
        device=11,
        inode=22,
        windows_handle=None,
        posix_fd=88,
    )
    parent_pin = cli_module._PinnedDirectory(
        path=tmp_path / "gate-runs",
        device=11,
        inode=21,
        windows_handle=None,
        posix_fd=77,
    )

    class MatchingIdentity:
        st_dev = 11
        st_ino = 22

    def record_stat(
        path: str, *, dir_fd: int | None = None, follow_symlinks: bool = True
    ) -> object:
        calls.append(("stat", dir_fd, follow_symlinks))
        return MatchingIdentity()

    def record_rmdir(path: str, *, dir_fd: int | None = None) -> None:
        calls.append(("rmdir", dir_fd, path))

    monkeypatch.setattr(cli_module.os, "stat", record_stat)
    monkeypatch.setattr(cli_module.os, "rmdir", record_rmdir)

    cli_module._remove_empty_run_directory(run_pin.path, run_pin, parent_pin)

    assert calls == [("stat", 77, False), ("rmdir", 77, "run")]


@pytest.mark.skipif(os.name == "nt", reason="POSIX dir_fd removal is unavailable")
def test_posix_run_removal_rejects_replacement_identity(tmp_path: Path) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    run_parent = tmp_path / "gate-runs"
    run_parent.mkdir()
    run_directory = run_parent / "run"
    run_directory.mkdir()
    run_pin = cli_module._pin_directory(run_directory)
    run_parent_pin = cli_module._pin_directory(run_parent)
    moved_directory = run_parent / "moved-run"
    run_directory.rename(moved_directory)
    run_directory.mkdir()
    try:
        with pytest.raises(cli_module._InvalidInvocation):
            cli_module._remove_empty_run_directory(
                run_directory, run_pin, run_parent_pin
            )
        assert run_directory.is_dir()
        assert moved_directory.is_dir()
    finally:
        run_pin.close()
        run_parent_pin.close()


def test_windows_run_removal_targets_pinned_handle_and_sanitizes_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    calls: list[tuple[int | None, int, int]] = []

    class FakeKernel32:
        def SetFileInformationByHandle(
            self, handle: object, information_class: int, _information: object, size: int
        ) -> int:
            calls.append((handle.value, information_class, size))  # type: ignore[attr-defined]
            return 0

    run_pin = cli_module._PinnedDirectory(
        path=tmp_path / "run",
        device=1,
        inode=2,
        windows_handle=987,
    )
    parent_pin = cli_module._PinnedDirectory(
        path=tmp_path,
        device=1,
        inode=1,
        windows_handle=654,
    )
    monkeypatch.setattr(cli_module, "_windows_kernel32", lambda: FakeKernel32())

    with pytest.raises(cli_module._InvalidInvocation):
        cli_module._remove_empty_run_directory(run_pin.path, run_pin, parent_pin)

    assert calls == [
        (
            987,
            cli_module._FILE_DISPOSITION_INFO,
            cli_module.ctypes.sizeof(cli_module._FileDispositionInformation),
        )
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups are unavailable")
def test_parent_exited_descendant_group_is_killed_within_bound(tmp_path: Path) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    helper = tmp_path / "parent_exits.py"
    helper.write_text(
        "import subprocess\n"
        "import sys\n"
        "\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print(\\\"ready\\\", flush=True); time.sleep(30)'], "
        "stdout=subprocess.PIPE, text=True)\n"
        "assert child.stdout is not None\n"
        "assert child.stdout.readline().strip() == 'ready'\n"
        "print(child.pid, flush=True)\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(helper)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    child_pid = int(process.stdout.readline().strip())
    assert process.wait(timeout=2.0) == 0
    started = time.monotonic()
    try:
        cli_module._stop_version_process(process)  # type: ignore[arg-type]
        while time.monotonic() - started < 2.0:
            state_path = Path(f"/proc/{child_pid}/stat")
            if not state_path.exists() or ") Z " in state_path.read_text(encoding="utf-8"):
                break
            time.sleep(0.01)
        else:
            pytest.fail("descendant process survived bounded process-group cleanup")
    finally:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)

    assert time.monotonic() - started < 2.0


def test_post_publication_identity_failure_returns_invalid_without_rewriting_report(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    original_verify = cli_module._verify_pinned_directories
    calls = 0

    def fail_after_publish(*args: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise cli_module._InvalidInvocation
        original_verify(*args)

    monkeypatch.setattr(cli_module, "_verify_pinned_directories", fail_after_publish)

    assert (
        cli_module.main(
            command_args(repository_root),
            repository_root=repository_root,
            probe_factory=FakeProbe,
            version_reader=version_runner,
        )
        == 2
    )
    assert (
        repository_root
        / ".local-data"
        / "codex-app-server"
        / "report"
        / "gate-report.json"
    ).exists()


def test_run_pin_is_closed_when_identity_removal_fails(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    closed_paths: list[Path] = []
    original_close = cli_module._PinnedDirectory.close

    def record_close(self: object) -> None:
        closed_paths.append(self.path)
        original_close(self)

    def fail_removal(*args: object) -> None:
        raise cli_module._InvalidInvocation

    monkeypatch.setattr(cli_module._PinnedDirectory, "close", record_close)
    monkeypatch.setattr(cli_module, "_remove_empty_run_directory", fail_removal)

    assert (
        cli_module.main(
            command_args(repository_root),
            repository_root=repository_root,
            probe_factory=FakeProbe,
            version_reader=version_runner,
        )
        == 2
    )
    assert any(path.parent.name == "gate-runs" for path in closed_paths)


def test_version_reader_rejects_oversized_output_without_subprocess_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    class OversizedProcess:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = _BytesStream(b"x" * 2048)
            self.stderr = _BytesStream(b"")

        def poll(self) -> int:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

        def terminate(self) -> None:
            self.returncode = 1

        def kill(self) -> None:
            self.returncode = 1

    monkeypatch.setattr(cli_module.subprocess, "run", lambda *args, **kwargs: pytest.fail())
    monkeypatch.setattr(
        cli_module.subprocess, "Popen", lambda *args, **kwargs: OversizedProcess()
    )

    with pytest.raises(cli_module._InvalidInvocation):
        cli_module._read_cli_version(("safe-codex", "--version"))


def test_report_swap_during_version_check_fails_closed(repository_root: Path) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    report_directory = (
        repository_root / ".local-data" / "codex-app-server" / "report"
    )

    def swap_report(command: tuple[str, ...]) -> str:
        report_directory.rename(report_directory.with_name("moved-report"))
        report_directory.mkdir()
        return version_runner(command)

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=swap_report,
    )

    assert exit_code == 2
    assert FakeProbe.started == 0


def test_probe_constructor_receives_isolated_command_and_empty_run_directory(
    repository_root: Path
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    exit_code = main(
        command_args(repository_root),
        repository_root=repository_root,
        probe_factory=FakeProbe,
        version_reader=version_runner,
    )

    assert exit_code == 0
    assert FakeProbe.started == 1
    assert FakeProbe.last_kwargs["command"] == (
        "safe-codex",
        "app-server",
        "--stdio",
        "--strict-config",
    )
    assert FakeProbe.last_kwargs["cli_version"] == "0.151.0"
    assert Path(FakeProbe.last_kwargs["codex_home"]) == (
        repository_root / ".local-data" / "codex-app-server" / "home"
    )
    empty_cwd = Path(FakeProbe.last_kwargs["empty_cwd"])
    assert empty_cwd.parent.name == "gate-runs"
    assert FakeProbe.empty_cwd_was_empty is True


@pytest.mark.parametrize("option", ["--codex-home", "--report-dir"])
def test_reserved_gate_runs_subtree_is_rejected(
    repository_root: Path, option: str
) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    args = command_args(repository_root)
    args[args.index(option) + 1] = str(
        repository_root / ".local-data" / "codex-app-server" / "gate-runs"
    )

    assert (
        main(
            args,
            repository_root=repository_root,
            probe_factory=FakeProbe,
            version_reader=version_runner,
        )
        == 2
    )


def test_non_empty_run_parent_is_rejected(repository_root: Path) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    run_parent = repository_root / ".local-data" / "codex-app-server" / "gate-runs"
    run_parent.mkdir(parents=True)
    (run_parent / "unrelated.txt").write_text("retain", encoding="utf-8")

    assert (
        main(
            command_args(repository_root),
            repository_root=repository_root,
            probe_factory=FakeProbe,
            version_reader=version_runner,
        )
        == 2
    )


def test_pinning_includes_every_existing_ancestor(
    repository_root: Path,
) -> None:
    import ai_workshop.labs.rag.generation.codex_app_server_gate_cli as cli_module

    boundary = repository_root / ".local-data" / "codex-app-server"
    nested_home = boundary / "homes" / "team" / "home"
    nested_report = boundary / "reports" / "team" / "report"
    nested_home.parent.mkdir(parents=True)
    nested_home.mkdir()
    nested_report.parent.mkdir(parents=True)
    nested_report.mkdir()
    run_parent = boundary / "gate-runs"
    run_parent.mkdir()
    run_directory = run_parent / "run"
    run_directory.mkdir()

    pinned = cli_module._pin_directories(
        repository_root, boundary, nested_home, nested_report, run_parent, run_directory
    )
    try:
        assert {item.path for item in pinned} >= {
            repository_root,
            repository_root / ".local-data",
            boundary,
            nested_home.parent.parent,
            nested_home.parent,
            nested_home,
            nested_report.parent.parent,
            nested_report.parent,
            nested_report,
            run_parent,
            run_directory,
        }
        cli_module._verify_pinned_directories(pinned, boundary)
    finally:
        for item in reversed(pinned):
            item.close()


def test_cleanup_preserves_non_empty_generated_run_directory(repository_root: Path) -> None:
    from ai_workshop.labs.rag.generation.codex_app_server_gate_cli import main

    assert (
        main(
            command_args(repository_root),
            repository_root=repository_root,
            probe_factory=ContentWritingProbe,
            version_reader=version_runner,
        )
        == 2
    )
    retained = list(
        (repository_root / ".local-data" / "codex-app-server" / "gate-runs").glob(
            "*/retained.txt"
        )
    )
    assert len(retained) == 1
    assert retained[0].read_text(encoding="utf-8") == "retain"


class _BytesStream:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self, size: int = -1) -> bytes:
        return self.content[:size]
