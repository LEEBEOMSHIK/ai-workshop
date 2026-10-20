"""Exercise the Windows launcher without starting Conda, a server, or a model."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "run_backend_conda.ps1"
POWERSHELL = shutil.which("powershell")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell launcher"
)


def _quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _powershell(command: str, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    # Windows PowerShell 5.1 otherwise writes CP949 on Korean Windows, even
    # when its Python parent uses UTF-8 mode. Use strict UTF-8 on both ends.
    preamble = (
        "$utf8 = New-Object System.Text.UTF8Encoding($false)\n"
        "[Console]::OutputEncoding = $utf8\n"
        "$OutputEncoding = $utf8\n"
    )
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", preamble + command],
        cwd=cwd, capture_output=True, encoding="utf-8", timeout=30, check=False,
    )


def test_powershell_preserves_unicode_output_and_errors() -> None:
    result = _powershell(
        "[Console]::WriteLine('한글 출력'); "
        "[Console]::Error.WriteLine('오류 메시지'); exit 19"
    )
    assert result.returncode == 19
    assert result.stdout.strip() == "한글 출력"
    assert result.stderr.strip() == "오류 메시지"


def _run(
    tmp_path: Path, *, activation_exit: int = 0, target_exit: int = 0,
    activation_throws: bool = False, wrong_prefix: bool = False, check_only: bool = False,
    activation_native_exit: int = 0, identity_exit: int = 0, use_defaults: bool = False,
) -> dict[str, Any]:
    assert LAUNCHER.is_file(), "Conda launcher has not been implemented"
    launcher = LAUNCHER
    prefix = tmp_path / "target prefix"
    if use_defaults:
        launcher = tmp_path / "scripts" / LAUNCHER.name
        launcher.parent.mkdir()
        shutil.copyfile(LAUNCHER, launcher)
        prefix = tmp_path / "backend" / ".conda"
    prefix.mkdir(parents=True)
    target = prefix / "python.exe"
    target.touch()
    base = tmp_path / "miniconda3" / "python.exe" if use_defaults else tmp_path / "base python.exe"
    base.parent.mkdir(exist_ok=True)
    base.touch()
    arguments = "" if use_defaults else f"-CondaPython {_quote(base)} -Prefix {_quote(prefix)}"
    activation = (
        "$env:PATH = 'partial-activation'; throw 'activation failed'" if activation_throws else
        f"$env:CONDA_PREFIX = {_quote(tmp_path if wrong_prefix else prefix)}; "
        "$env:PATH = 'fake-path'; $env:LAUNCHER_NEW_VALUE = 'created'; "
        "Remove-Item Env:LAUNCHER_OLD_VALUE; "
        f"$global:LASTEXITCODE = {activation_native_exit}"
    )
    wrapper = f"""
{f"$env:USERPROFILE = {_quote(tmp_path)}" if use_defaults else ""}
$env:LAUNCHER_OLD_VALUE = 'preserve-보존'
$env:PYTHONPATH = 'existing-pythonpath'
$env:PYTHONHOME = 'inherited-unrelated-python'
$before = @{{}}
Get-ChildItem Env: | ForEach-Object {{ $before[$_.Name] = $_.Value }}
$beforeLocation = (Get-Location).Path
$global:activationArguments = @()
$global:targetCall = $null
$global:targetCalls = @()
Set-Item -LiteralPath {_quote('Function:' + str(base))} -Value {{
    $global:activationArguments = @($args)
    {_quote(activation)}
    $global:LASTEXITCODE = {activation_exit}
}}
Set-Item -LiteralPath {_quote('Function:' + str(target))} -Value {{
    $global:targetCall = @{{ arguments = @($args); cwd = (Get-Location).Path;
        pythonpath = $env:PYTHONPATH; pythonhome = $env:PYTHONHOME;
        utf8 = $env:PYTHONUTF8; prefix = $env:CONDA_PREFIX }}
    $global:targetCalls += $global:targetCall
    $global:LASTEXITCODE = if ($args -contains '-c') {{ {identity_exit} }} else {{ {target_exit} }}
}}
& {_quote(launcher)} {arguments} -Port 18123 {
    '-CheckOnly' if check_only else ''}
$code = $LASTEXITCODE
$after = @{{}}
Get-ChildItem Env: | ForEach-Object {{ $after[$_.Name] = $_.Value }}
@{{ code = $code; activation = $global:activationArguments; target = $global:targetCall;
    calls = @($global:targetCalls);
    before = $before; after = $after; beforeLocation = $beforeLocation;
    afterLocation = (Get-Location).Path }} | ConvertTo-Json -Depth 6 -Compress
"""
    result = _powershell(wrapper, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    report: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["before"] == report["after"]
    assert report["beforeLocation"] == report["afterLocation"]
    return report


def test_runs_backend_from_repository_and_propagates_exit(tmp_path: Path) -> None:
    report = _run(tmp_path, target_exit=23)
    assert report["code"] == 23
    assert report["activation"] == [
        "-I", "-B", "-m", "conda", "shell.powershell", "activate", str(tmp_path / "target prefix")
    ]
    call = report["target"]
    assert len(report["calls"]) == 2
    identity_call = report["calls"][0]
    assert identity_call["arguments"][:2] == ["-B", "-c"]
    for key in ("cwd", "pythonpath", "pythonhome", "utf8", "prefix"):
        assert identity_call[key] == call[key]
    assert call["pythonhome"] is None
    assert report["after"]["PYTHONHOME"] == "inherited-unrelated-python"
    assert call["cwd"] == str(ROOT)
    assert call["pythonpath"] == str(ROOT / "backend" / "src") + ";existing-pythonpath"
    assert [str(value) for value in call["arguments"]] == [
        "-B", "-m", "uvicorn", "ai_workshop.main:app", "--loop",
        "ai_workshop.shared.asyncio_policy:create_selector_event_loop",
        "--host", "127.0.0.1", "--port", "18123",
    ]


@pytest.mark.parametrize("activation_exit", [1, 17])
def test_activation_command_failure_never_runs_python(
    tmp_path: Path, activation_exit: int,
) -> None:
    report = _run(tmp_path, activation_exit=activation_exit)
    assert report["code"] != 0
    assert report["target"] is None


def test_activation_script_failure_restores_environment(tmp_path: Path) -> None:
    report = _run(tmp_path, activation_throws=True)
    assert report["code"] != 0
    assert report["target"] is None


def test_wrong_active_prefix_never_runs_python(tmp_path: Path) -> None:
    report = _run(tmp_path, wrong_prefix=True)
    assert report["code"] != 0
    assert report["target"] is None


def test_activation_native_failure_never_runs_python(tmp_path: Path) -> None:
    report = _run(tmp_path, activation_native_exit=9)
    assert report["code"] != 0
    assert report["target"] is None


@pytest.mark.parametrize("check_only", [False, True])
def test_failed_identity_never_starts_server(tmp_path: Path, check_only: bool) -> None:
    report = _run(tmp_path, identity_exit=11, check_only=check_only)
    assert report["code"] == 11
    assert len(report["calls"]) == 1
    assert report["calls"][0]["arguments"][:2] == ["-B", "-c"]
    assert report["calls"][0]["pythonhome"] is None


def test_check_only_runs_identity_check_without_uvicorn(tmp_path: Path) -> None:
    report = _run(tmp_path, check_only=True)
    assert report["code"] == 0
    args = report["target"]["arguments"]
    assert len(report["calls"]) == 1
    assert args[:2] == ["-B", "-c"]
    assert args[-1] == str(tmp_path / "target prefix")
    assert "uvicorn" not in args
    # Run the actual identity program with this test interpreter, without imports
    # from the application or target environment, to exercise both identities.
    base_python = Path(sys.base_prefix) / "python.exe"
    env = dict(os.environ, CONDA_PREFIX=sys.base_prefix, PYTHONIOENCODING="utf-8")
    success = subprocess.run(
        [str(base_python), "-B", "-c", args[2], sys.base_prefix],
        env=env, capture_output=True, encoding="utf-8", check=False,
    )
    assert success.returncode == 0, success.stderr
    identity = json.loads(success.stdout)
    assert Path(identity["executable"]) == base_python
    assert identity["prefix"] == sys.base_prefix
    assert identity["conda_prefix"] == sys.base_prefix
    failure = subprocess.run(
        [str(base_python), "-B", "-c", args[2], str(tmp_path)],
        env=env, capture_output=True, encoding="utf-8", check=False,
    )
    assert failure.returncode != 0
    # Windows PowerShell's legacy native argument quoting must preserve the
    # embedded Python program too; a direct Python subprocess would miss this.
    command = (
        f"$env:CONDA_PREFIX = {_quote(sys.base_prefix)}\n"
        "$env:PYTHONIOENCODING = 'utf-8'\n"
        f"$program = @'\n{args[2]}\n'@\n"
        f"& {_quote(base_python)} -B -c $program {_quote(sys.base_prefix)}\n"
        "exit $LASTEXITCODE"
    )
    native = _powershell(command)
    assert native.returncode == 0, native.stderr
    assert json.loads(native.stdout) == identity


@pytest.mark.parametrize("check_only", [False, True])
def test_defaults_activate_backend_conda_and_restore_caller(
    tmp_path: Path, check_only: bool,
) -> None:
    report = _run(tmp_path, use_defaults=True, check_only=check_only)
    assert report["code"] == 0
    assert report["activation"][-1] == str(tmp_path / "backend" / ".conda")
    assert len(report["calls"]) == (1 if check_only else 2)
    assert report["calls"][0]["cwd"] == str(tmp_path)
    assert report["calls"][0]["prefix"] == str(tmp_path / "backend" / ".conda")
    if not check_only:
        assert report["target"]["arguments"][1:4] == ["-m", "uvicorn", "ai_workshop.main:app"]
