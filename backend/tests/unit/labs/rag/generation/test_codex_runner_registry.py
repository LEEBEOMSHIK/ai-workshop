import hashlib
import importlib
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType
from typing import BinaryIO

import pytest
from pydantic import ValidationError


@pytest.fixture
def registry_module() -> ModuleType:
    return importlib.import_module("ai_workshop.labs.rag.generation.codex_runner_registry")


@pytest.fixture
def runner_data(tmp_path: Path) -> dict[str, object]:
    install = tmp_path / "installation"
    install.mkdir()
    executable = install / "synthetic.exe"
    executable.write_bytes(b"synthetic executable fixture, never executed")
    root = tmp_path / "requests"
    root.mkdir()
    return {
        "executable": executable,
        "expected_cli_version": "1.2.3",
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "request_root": root,
        "environment": {},
    }


def make_registry(module: ModuleType, data: dict[str, object], tmp_path: Path, **kwargs: object):
    return module.CodexRunnerRegistry(
        {"codex-test-v1": module.CodexRunnerSettings(**data)},
        environment=kwargs.get("environment", "test"),
        protected_roots=kwargs.get("protected_roots", (tmp_path / "repo", tmp_path / "objects")),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_cli_version", ""),
        ("expected_cli_version", "v1.2.3"),
        ("expected_cli_version", "1.2.3-beta"),
        ("expected_cli_version", 123),
        ("executable_sha256", "A" * 64),
        ("executable_sha256", "a" * 63),
        ("argv", ["--unsafe"]),
        ("model", "synthetic-model"),
        ("secret", "synthetic-secret"),
        ("config_override", {}),
    ],
)
def test_settings_reject_invalid_and_arbitrary_fields(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    field: str,
    value: object,
) -> None:
    runner_data[field] = value
    with pytest.raises(ValidationError) as error:
        registry_module.CodexRunnerSettings(**runner_data)
    assert "synthetic-secret" not in str(error.value)
    assert str(runner_data["executable"]) not in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        "relative/path",
        "C:",
        "C:relative",
        "C:/",
        "//server/share/path",
        "\\\\?\\C:\\synthetic",
        "\\\\.\\C:\\synthetic",
        "C:/safe/../unsafe",
        "C:/safe/\0bad",
        "C:/safe/trailing.",
        "C:/safe/stream:other",
        "C:/safe/%USERPROFILE%",
        "C:/safe/COM\u00b9",
        "C:/safe/LPT\u00b2.txt",
        "C:/safe/COM\u00b3.log",
        "C:/safe/CON .txt",
    ],
)
@pytest.mark.parametrize("field", ["executable", "request_root"])
def test_settings_reject_unsafe_paths_syntactically(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    field: str,
    value: str,
) -> None:
    runner_data[field] = value
    with pytest.raises(ValidationError) as error:
        registry_module.CodexRunnerSettings(**runner_data)
    assert "input_value" not in str(error.value)


@pytest.mark.parametrize("name", ["COM10", "LPT20.txt", "CONSOLE.txt", "COM\u2074"])
def test_settings_accept_non_reserved_windows_near_names(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    name: str,
) -> None:
    runner_data["request_root"] = f"C:/safe/{name}"

    settings = registry_module.CodexRunnerSettings(**runner_data)

    assert settings.request_root == Path(f"C:/safe/{name}")


@pytest.mark.parametrize(
    "limits",
    [
        {"timeout_seconds": True},
        {"timeout_seconds": "60"},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 3601},
        {"timeout_seconds": 0},
        {"cleanup_seconds": -1},
        {"cleanup_seconds": "1"},
        {"cleanup_seconds": False},
        {"stdin_bytes": -1},
        {"stdin_bytes": True},
        {"stdout_bytes": "1000000"},
        {"stdout_bytes": 0},
        {"stderr_bytes": 64 * 1024 * 1024 + 1},
        {"max_line_bytes": 1_048_577},
        {"max_events": 0},
        {"max_input_tokens": -1},
        {"max_output_tokens": 1.5},
        {"max_concurrent_requests": 0},
        {"other": 1},
    ],
)
def test_limits_are_strict_and_bounded(
    registry_module: ModuleType,
    limits: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        registry_module.CodexRunnerLimits(**limits)


@pytest.mark.parametrize(
    "environment",
    [
        {"OPENAI_API_KEY": "synthetic-secret"},
        {"PATH": "C:/synthetic"},
        {"NODE_OPTIONS": "--unsafe"},
        {"PYTHONPATH": "C:/synthetic"},
        {"HTTPS_PROXY": "https://synthetic.invalid"},
        {"DATABASE_URL": "synthetic-secret"},
        {"TEMP": "C:/synthetic", "temp": "C:/different"},
        {"TEMP": ""},
        {"TEMP": "relative"},
        {"TEMP": "C:/synthetic/../other"},
        {"TEMP": 1},
    ],
)
def test_environment_is_explicit_allowlist(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    environment: dict[str, object],
) -> None:
    runner_data["environment"] = environment
    with pytest.raises(ValidationError) as error:
        registry_module.CodexRunnerSettings(**runner_data)
    assert "synthetic-secret" not in str(error.value)


def test_resolution_is_read_only_immutable_and_does_not_inherit_environment(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-global-secret")
    monkeypatch.setenv("PATH", "synthetic-global-path")

    def forbid_process(*args: object, **kwargs: object) -> None:
        pytest.fail("Registry attempted process execution")

    monkeypatch.setattr("subprocess.Popen", forbid_process)
    monkeypatch.setattr("os.system", forbid_process)
    before = sorted(str(path) for path in tmp_path.rglob("*"))
    runner_data["environment"] = {"temp": str(tmp_path)}
    entry = registry_module.CodexRunnerSettings(**runner_data)
    entries = {"codex-test-v1": entry}
    registry = registry_module.CodexRunnerRegistry(
        entries,
        environment="test",
        protected_roots=(tmp_path / "repo",),
    )
    entry.environment["TEMP"] = str(tmp_path / "missing")
    entries.clear()
    resolved = registry.resolve("codex-test-v1")
    assert resolved.environment == {"TEMP": str(tmp_path)}
    assert resolved.expected_cli_version == "1.2.3"
    assert resolved.process_limits.stdout_bytes == 1_048_576
    assert resolved.event_limits.max_total_bytes == 1_048_576
    assert resolved.max_concurrent_requests == 1
    assert not hasattr(resolved, "ready")
    assert not hasattr(resolved, "observed_cli_version")
    assert str(tmp_path) not in repr(entry)
    assert str(tmp_path) not in repr(resolved)
    with pytest.raises(TypeError):
        resolved.environment["TEMP"] = "other"
    with pytest.raises(FrozenInstanceError):
        resolved.reference = "other-reference"
    assert sorted(str(path) for path in tmp_path.rglob("*")) == before
    executable = Path(runner_data["executable"])
    assert executable.read_bytes() == b"synthetic executable fixture, never executed"


@pytest.mark.parametrize("environment", ["production", "unknown", "", "LOCAL"])
def test_resolution_rejects_non_development_environments(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    environment: str,
) -> None:
    registry = make_registry(registry_module, runner_data, tmp_path, environment=environment)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        registry.resolve("codex-test-v1")
    assert error.value.code == "codex_runner_environment_forbidden"


@pytest.mark.parametrize("reference", ["codex-missing", "synthetic-secret/path", "sk-private"])
def test_lookup_errors_hide_submitted_references(
    registry_module: ModuleType,
    tmp_path: Path,
    reference: str,
) -> None:
    registry = registry_module.CodexRunnerRegistry(
        {},
        environment="test",
        protected_roots=(tmp_path / "repo",),
    )
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        registry.resolve(reference)
    assert reference not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize("root_kind", ["equal", "inside", "contains", "install", "install-child"])
def test_request_root_rejects_protected_and_installation_overlap(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    root_kind: str,
) -> None:
    protected = tmp_path / "repo"
    protected.mkdir()
    choices = {
        "equal": protected,
        "inside": protected / "requests",
        "contains": tmp_path,
        "install": tmp_path / "installation",
        "install-child": tmp_path / "installation" / "cwd",
    }
    request_root = choices[root_kind]
    request_root.mkdir(exist_ok=True)
    runner_data["request_root"] = request_root
    registry = make_registry(registry_module, runner_data, tmp_path)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        registry.resolve("codex-test-v1")
    assert error.value.code == "codex_runner_path_overlap"


@pytest.mark.parametrize(
    "change", ["missing-exe", "missing-root", "root-file", "wrong-suffix", "hash"]
)
def test_missing_invalid_files_and_changed_executable_are_rejected(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    change: str,
) -> None:
    registry = make_registry(registry_module, runner_data, tmp_path)
    registry.resolve("codex-test-v1")
    if change == "hash":
        Path(runner_data["executable"]).write_bytes(b"mutated synthetic bytes")
    elif change == "missing-exe":
        Path(runner_data["executable"]).unlink()
    elif change == "missing-root":
        Path(runner_data["request_root"]).rmdir()
    elif change == "root-file":
        Path(runner_data["request_root"]).rmdir()
        Path(runner_data["request_root"]).write_bytes(b"not a directory")
    else:
        destination = tmp_path / "installation" / "synthetic.txt"
        Path(runner_data["executable"]).rename(destination)
        runner_data["executable"] = destination
        registry = make_registry(registry_module, runner_data, tmp_path)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        registry.resolve("codex-test-v1")
    assert str(tmp_path) not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    if change == "hash":
        assert error.value.code == "codex_runner_hash_mismatch"


def test_registry_revalidates_constructed_and_mutated_models(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
) -> None:
    entry = registry_module.CodexRunnerSettings(**runner_data)
    for invalid in (
        entry.model_copy(update={"executable": "synthetic-secret/relative"}),
        entry.model_copy(
            update={
                "limits": registry_module.CodexRunnerLimits.model_construct(
                    timeout_seconds=True,
                )
            }
        ),
        entry.model_copy(update={"environment": {"OPENAI_API_KEY": "synthetic-secret"}}),
    ):
        with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
            registry_module.CodexRunnerRegistry(
                {"codex-test-v1": invalid},
                environment="test",
                protected_roots=(tmp_path / "repo",),
            )
        assert error.value.code == "codex_runner_configuration_invalid"
        assert "synthetic-secret" not in str(error.value)
        assert error.value.__context__ is None


def test_fingerprint_is_order_independent_and_covers_configuration(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
) -> None:
    runner_data["environment"] = {"TEMP": str(tmp_path), "TMP": str(tmp_path)}
    original = make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")
    runner_data["environment"] = {"TMP": str(tmp_path), "temp": str(tmp_path)}
    reordered = make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")
    assert original.configuration_sha256 == reordered.configuration_sha256
    assert len(original.configuration_sha256) == 64
    other_root = tmp_path / "other-requests"
    other_root.mkdir()
    for field, value in (
        ("expected_cli_version", "1.2.4"),
        ("request_root", other_root),
        ("environment", {}),
        ("limits", {"max_concurrent_requests": 2}),
    ):
        changed = dict(runner_data, **{field: value})
        resolved = make_registry(registry_module, changed, tmp_path).resolve("codex-test-v1")
        assert resolved.configuration_sha256 != original.configuration_sha256


@pytest.mark.parametrize("protected_roots", [(), (Path("relative"),), (Path("C:/"),)])
def test_registry_requires_explicit_nonempty_safe_protected_roots(
    registry_module: ModuleType,
    protected_roots: tuple[Path, ...],
) -> None:
    with pytest.raises(registry_module.CodexRunnerReferenceError):
        registry_module.CodexRunnerRegistry({}, environment="test", protected_roots=protected_roots)


@pytest.mark.parametrize("target", ["executable", "request_root", "environment", "protected"])
def test_simulated_reparse_point_in_ancestor_is_rejected_before_open(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    environment_root = tmp_path / "synthetic-env"
    environment_root.mkdir()
    protected = tmp_path / "repo"
    protected.mkdir()
    runner_data["environment"] = {"TEMP": str(environment_root)}
    registry = make_registry(registry_module, runner_data, tmp_path)
    original = Path.lstat
    ancestor = {
        "executable": tmp_path / "installation",
        "request_root": Path(runner_data["request_root"]),
        "environment": environment_root,
        "protected": protected,
    }[target]

    def fake_lstat(path: Path, *args: object, **kwargs: object):
        result = original(path, *args, **kwargs)
        if path == ancestor:
            from types import SimpleNamespace

            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        registry.resolve("codex-test-v1")
    assert error.value.code == "codex_runner_reparse_path"


def test_unreadable_file_error_has_no_raw_cause_or_context(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = make_registry(registry_module, runner_data, tmp_path)

    def deny_open(*args: object, **kwargs: object) -> None:
        raise PermissionError("synthetic-private-path-and-secret")

    monkeypatch.setattr(Path, "open", deny_open)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        registry.resolve("codex-test-v1")
    assert error.value.code == "codex_runner_unavailable"
    assert "synthetic-private" not in str(error.value)
    assert error.value.__context__ is None
    assert error.value.__cause__ is None


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_environment_roots_must_be_existing_directories(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    kind: str,
) -> None:
    environment_root = tmp_path / "synthetic-home"
    if kind == "file":
        environment_root.write_bytes(b"synthetic")
    runner_data["environment"] = {"CODEX_HOME": str(environment_root)}
    with pytest.raises(registry_module.CodexRunnerReferenceError):
        make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")


def test_settings_syntax_validation_never_stats_paths(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_stat(*args: object, **kwargs: object) -> None:
        pytest.fail("Settings parsing touched the filesystem")

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "stat", deny_stat)
        scoped.setattr(Path, "lstat", deny_stat)
        scoped.setattr(Path, "resolve", deny_stat)
        settings = registry_module.CodexRunnerSettings(**runner_data)
    assert settings.executable == runner_data["executable"]


def test_canonical_path_alias_cannot_bypass_protected_root_overlap(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulates a Windows short-name alias using real synthetic directories.
    request_root = Path(runner_data["request_root"])
    protected = tmp_path / "repo"
    protected.mkdir()
    original = Path.resolve

    def canonical_alias(path: Path, *args: object, **kwargs: object) -> Path:
        if path == request_root:
            return protected
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", canonical_alias)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")
    assert error.value.code == "codex_runner_path_overlap"


@pytest.mark.parametrize("mutation", ["none", "grow", "same-size", "shrink"])
def test_hash_reads_are_bounded_and_detect_mutation_during_read(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    executable = Path(runner_data["executable"])
    content = b"synthetic bytes" * 12000
    executable.write_bytes(content)
    runner_data["executable_sha256"] = hashlib.sha256(content).hexdigest()
    original_open = Path.open
    reads: list[int] = []

    class InspectedStream:
        def __init__(self, stream: BinaryIO):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            self.stream.close()

        def fileno(self) -> int:
            return self.stream.fileno()

        def read(self, size: int = -1) -> bytes:
            assert 0 < size <= 65536
            reads.append(size)
            chunk = self.stream.read(size)
            if mutation == "grow":
                with original_open(executable, "ab") as writer:
                    writer.write(b"growing" * 10000)
            elif mutation in ("same-size", "shrink") and len(reads) == 1:
                with original_open(executable, "r+b") as writer:
                    writer.write(b"changed")
                    if mutation == "shrink":
                        writer.truncate(1)
                timestamp = executable.stat().st_mtime_ns + 1_000_000_000
                os.utime(executable, ns=(timestamp, timestamp))
            return chunk

    def inspected_open(path: Path, *args: object, **kwargs: object):
        stream = original_open(path, *args, **kwargs)
        return InspectedStream(stream) if path == executable else stream

    monkeypatch.setattr(Path, "open", inspected_open)
    registry = make_registry(registry_module, runner_data, tmp_path)
    if mutation == "none":
        assert (
            registry.resolve("codex-test-v1").executable_sha256 == runner_data["executable_sha256"]
        )
    else:
        with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
            registry.resolve("codex-test-v1")
        assert error.value.code == "codex_runner_executable_changed"
    assert sum(reads) <= len(content)
    assert reads[0] == 65536


@pytest.mark.parametrize("target", ["executable", "request_root", "environment", "protected"])
def test_real_symlink_is_rejected_when_os_permits_link_creation(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    target: str,
) -> None:
    link = tmp_path / ("link.exe" if target == "executable" else "link")
    destination = Path(runner_data["executable" if target == "executable" else "request_root"])
    try:
        link.symlink_to(destination, target_is_directory=target != "executable")
    except OSError:
        pytest.skip("Synthetic symlink creation is not available under current OS permissions")
    kwargs: dict[str, object] = {}
    if target in ("executable", "request_root"):
        runner_data[target] = link
    elif target == "environment":
        runner_data["environment"] = {"TEMP": str(link)}
    else:
        kwargs["protected_roots"] = (link,)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        make_registry(registry_module, runner_data, tmp_path, **kwargs).resolve("codex-test-v1")
    assert error.value.code == "codex_runner_reparse_path"


@pytest.mark.parametrize(
    "budget,value",
    [
        ("timeout_seconds", 61),
        ("stdin_bytes", 0),
        ("stdout_bytes", 1_048_577),
        ("stderr_bytes", 0),
        ("cleanup_seconds", 6),
        ("max_line_bytes", 262_145),
        ("max_events", 65),
        ("max_input_tokens", 131_073),
        ("max_output_tokens", 16_385),
        ("max_concurrent_requests", 2),
    ],
)
def test_fingerprint_includes_every_budget(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
    budget: str,
    value: int,
) -> None:
    baseline = make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")
    runner_data["limits"] = {budget: value}
    changed = make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")
    assert baseline.configuration_sha256 != changed.configuration_sha256


def test_fingerprint_includes_executable_location_and_digest(
    registry_module: ModuleType,
    runner_data: dict[str, object],
    tmp_path: Path,
) -> None:
    baseline = make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")
    other = tmp_path / "installation" / "other.exe"
    other.write_bytes(Path(runner_data["executable"]).read_bytes())
    runner_data["executable"] = other
    changed_location = make_registry(registry_module, runner_data, tmp_path).resolve(
        "codex-test-v1"
    )
    assert baseline.configuration_sha256 != changed_location.configuration_sha256
    other.write_bytes(b"different synthetic executable")
    runner_data["executable_sha256"] = hashlib.sha256(other.read_bytes()).hexdigest()
    changed_digest = make_registry(registry_module, runner_data, tmp_path).resolve("codex-test-v1")
    assert changed_location.configuration_sha256 != changed_digest.configuration_sha256


@pytest.mark.parametrize("nested", [False, True])
def test_unknown_field_names_cannot_leak_private_paths_in_validation_errors(
    registry_module: ModuleType, runner_data: dict[str, object], nested: bool,
) -> None:
    private = "C:/synthetic-private-path"
    if nested:
        runner_data["limits"] = {private: "synthetic-secret"}
    else:
        runner_data[private] = "synthetic-secret"
    with pytest.raises(ValidationError) as error:
        registry_module.CodexRunnerSettings(**runner_data)
    assert private not in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_open_handle_identity_changes_fail_safely(
    registry_module: ModuleType, runner_data: dict[str, object], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = make_registry(registry_module, runner_data, tmp_path)
    original = os.fstat
    calls = 0
    class ChangedIdentity:
        def __init__(self, actual: os.stat_result):
            self.actual = actual
        def __getattr__(self, key: str):
            value = getattr(self.actual, key)
            return value + 1 if key == "st_ino" else value
    def changed_fstat(descriptor: int):
        nonlocal calls
        calls += 1
        actual = original(descriptor)
        return actual if calls == 1 else ChangedIdentity(actual)
    monkeypatch.setattr(os, "fstat", changed_fstat)
    with pytest.raises(registry_module.CodexRunnerReferenceError) as error:
        registry.resolve("codex-test-v1")
    assert error.value.code == "codex_runner_executable_changed"
    assert error.value.__context__ is None


def test_all_allowed_environment_keys_are_normalized_and_copied(
    registry_module: ModuleType, runner_data: dict[str, object], tmp_path: Path,
) -> None:
    keys = ("SystemRoot", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "CODEX_HOME")
    environment = {key.lower(): str(tmp_path) for key in keys}
    runner_data["environment"] = environment
    registry = make_registry(registry_module, runner_data, tmp_path)
    environment.clear()
    resolved = registry.resolve("codex-test-v1")
    assert resolved.environment == {key: str(tmp_path) for key in keys}
