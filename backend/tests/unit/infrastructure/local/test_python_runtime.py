"""Pinned local interpreter validation uses synthetic files, never subprocesses."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from ai_workshop.infrastructure.local import python_runtime as runtime


@pytest.fixture
def configured(tmp_path, monkeypatch):
    prefix = tmp_path / "conda"
    (prefix / "conda-meta").mkdir(parents=True)
    executable = prefix / "python.exe"
    executable.write_bytes(b"synthetic-approved-python")
    root = tmp_path / "project"
    (root / "scripts").mkdir(parents=True)
    descriptor = root / "scripts/local_python_runtime.json"
    descriptor.write_text(
        json.dumps(
            {
                "schema": 1,
                "prefix": str(prefix),
                "executable": "python.exe",
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime, "DESCRIPTOR_SHA256", hashlib.sha256(descriptor.read_bytes()).hexdigest()
    )
    monkeypatch.setenv("CONDA_PREFIX", str(prefix))
    monkeypatch.delenv("PYTHONHOME", raising=False)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "executable", str(executable))
    return root, prefix, executable, descriptor


def test_approved_interpreter_requires_active_identity_and_exact_bytes(configured):
    root, _, executable, _ = configured
    approved = runtime.approved_python(root)
    assert approved.executable == executable
    assert approved.sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()


@pytest.mark.parametrize("mutation", ["descriptor", "binary", "missing", "metadata"])
def test_changed_or_missing_runtime_material_refuses_without_fallback(configured, mutation):
    root, prefix, executable, descriptor = configured
    if mutation == "descriptor":
        descriptor.write_bytes(descriptor.read_bytes() + b" ")
    elif mutation == "binary":
        executable.write_bytes(b"different-python")
    elif mutation == "missing":
        executable.unlink()
    else:
        (prefix / "conda-meta").rmdir()
    with pytest.raises(runtime.PythonRuntimeError, match="^local_python_runtime_unverified$"):
        runtime.approved_python(root)


@pytest.mark.parametrize(
    "mutation", ["missing_conda", "other_conda", "sys_prefix", "sys_executable", "pythonhome"]
)
def test_wrong_activation_or_process_identity_refuses(configured, monkeypatch, mutation):
    root, _, _, _ = configured
    if mutation == "missing_conda":
        monkeypatch.delenv("CONDA_PREFIX")
    elif mutation == "other_conda":
        monkeypatch.setenv("CONDA_PREFIX", str(root))
    elif mutation == "sys_prefix":
        monkeypatch.setattr(sys, "prefix", str(root))
    elif mutation == "sys_executable":
        monkeypatch.setattr(sys, "executable", str(root / "python.exe"))
    else:
        monkeypatch.setenv("PYTHONHOME", "")
    with pytest.raises(runtime.PythonRuntimeError):
        runtime.approved_python(root)


def test_descriptor_cannot_select_same_binary_in_different_prefix(configured):
    root, _, _, descriptor = configured
    data = json.loads(descriptor.read_bytes())
    data["prefix"] = str(root)
    descriptor.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(runtime.PythonRuntimeError):
        runtime.approved_python(root)


@pytest.mark.parametrize("target", ["executable", "prefix", "metadata", "descriptor", "scripts"])
def test_any_reparse_component_refuses(configured, monkeypatch, target):
    from types import SimpleNamespace

    root, prefix, executable, descriptor = configured
    selected = {
        "executable": executable,
        "prefix": prefix,
        "metadata": prefix / "conda-meta",
        "descriptor": descriptor,
        "scripts": descriptor.parent,
    }[target]
    original = Path.lstat

    def stat(path):
        if path == selected:
            return SimpleNamespace(st_file_attributes=0x400)
        return original(path)

    monkeypatch.setattr(Path, "lstat", stat)
    with pytest.raises(runtime.PythonRuntimeError):
        runtime.approved_python(root)


def test_second_use_rechecks_binary_instead_of_caching(configured):
    root, _, executable, _ = configured
    runtime.approved_python(root)
    executable.write_bytes(b"changed-after-first-use")
    with pytest.raises(runtime.PythonRuntimeError):
        runtime.approved_python(root)
