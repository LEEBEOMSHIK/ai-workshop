import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from packaging.tags import Tag
from scripts import conda_backend_dependencies as subject


def wheel_package(
    name: str, version: str, *, host: str = "files.pythonhosted.org"
) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "wheels": [
            {
                "url": f"https://{host}/packages/{name}-{version}-py3-none-any.whl",
                "hash": "sha256:" + "a" * 64,
            }
        ],
    }


def test_selects_hash_locked_official_wheel_without_numeric_packages() -> None:
    lock = {"package": [wheel_package("example", "1.0")]}
    rows = subject.select_wheels(
        "example==1.0 \\\n    --hash=sha256:" + "a" * 64 + "\n",
        lock,
        [Tag("py3", "none", "any")],
    )
    assert rows[0]["name"] == "example"
    assert rows[0]["sha256"] == "a" * 64


@pytest.mark.parametrize("name", ["numpy", "scipy", "numpy-base", "libopenblas", "blas"])
def test_rejects_numeric_package_in_pip_input(name: str) -> None:
    with pytest.raises(ValueError, match="protected"):
        subject.select_wheels(
            f"{name}==1.0 --hash=sha256:" + "a" * 64,
            {"package": [wheel_package(name, "1.0")]},
            [Tag("py3", "none", "any")],
        )


def test_rejects_nonofficial_host_even_when_hash_matches() -> None:
    with pytest.raises(ValueError, match="source"):
        subject.select_wheels(
            "example==1.0 --hash=sha256:" + "a" * 64,
            {"package": [wheel_package("example", "1.0", host="mirror.invalid")]},
            [Tag("py3", "none", "any")],
        )


def test_preserves_official_cpu_torch_archive_host_from_lock() -> None:
    package = wheel_package("torch", "2.13.0+cpu")
    package["wheels"][0]["url"] = (
        "https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu-py3-none-any.whl"
    )
    rows = subject.select_wheels(
        "torch==2.13.0+cpu --hash=sha256:" + "a" * 64,
        {"package": [package]},
        [Tag("py3", "none", "any")],
    )
    assert rows[0]["url"] == package["wheels"][0]["url"]


def test_rejects_incompatible_wheel_instead_of_building_source() -> None:
    with pytest.raises(ValueError, match="wheel"):
        subject.select_wheels(
            "example==1.0 --hash=sha256:" + "a" * 64,
            {"package": [wheel_package("example", "1.0")]},
            [Tag("cp313", "cp313", "win_amd64")],
        )


def test_rejects_unpinned_requirement_and_hidden_options() -> None:
    for text in ("example>=1", "--extra-index-url https://mirror.invalid"):
        with pytest.raises(ValueError):
            subject.select_wheels(text, {"package": []}, [Tag("py3", "none", "any")])


def test_report_cannot_add_unplanned_dependency_or_change_archive() -> None:
    rows = [
        {
            "name": "example",
            "version": "1.0",
            "url": "https://files.pythonhosted.org/a.whl",
            "sha256": "a" * 64,
        }
    ]
    entry: dict[str, Any] = {
        "metadata": {"name": "example", "version": "1.0"},
        "download_info": {"url": rows[0]["url"], "archive_info": {"hashes": {"sha256": "a" * 64}}},
    }
    subject.validate_report({"install": [entry]}, rows)
    entry["metadata"]["name"] = "numpy"
    with pytest.raises(ValueError, match="unplanned"):
        subject.validate_report({"install": [entry]}, rows)
    entry["metadata"]["name"] = "example"
    entry["download_info"]["archive_info"]["hashes"]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="archive"):
        subject.validate_report({"install": [entry]}, rows)


def test_protected_files_reject_changes_and_escape(tmp_path: Path) -> None:
    native = tmp_path / "native.pyd"
    native.write_bytes(b"signed native")
    before = subject.hash_files(tmp_path, ["native.pyd"])
    subject.verify_files(tmp_path, before)
    native.write_bytes(b"replaced")
    with pytest.raises(ValueError, match="changed"):
        subject.verify_files(tmp_path, before)
    with pytest.raises(ValueError, match="outside"):
        subject.hash_files(tmp_path, ["../escape.pyd"])


def test_install_uses_only_explicit_archives_without_dependency_resolution(tmp_path: Path) -> None:
    args = subject.pip_arguments(tmp_path / "locked.txt", tmp_path / "report.json", dry_run=True)
    assert "--no-deps" in args
    assert "--require-hashes" in args
    assert "--no-index" in args
    assert "--only-binary=:all:" in args
    assert "--dry-run" in args
    assert args[args.index("--retries") + 1] == "0"
    assert "--upgrade" not in args
    assert "--force-reinstall" not in args


@pytest.mark.parametrize("failure", ["dry-run", "bad-report", "install", "install-and-protection"])
def test_install_failure_stops_and_preserves_all_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    native = tmp_path / "native.pyd"
    native.write_bytes(b"original")
    requirements = tmp_path / "wheels.txt"
    requirements.write_text("example==1.0", encoding="utf-8")
    row = {
        "name": "example",
        "version": "1.0",
        "url": "https://files.pythonhosted.org/a.whl",
        "sha256": "a" * 64,
    }
    plan = {
        "prefix": str(tmp_path),
        "sources": {},
        "rows": [row],
        "protected_files": subject.hash_files(tmp_path, ["native.pyd"]),
        "requirements_sha256": subject.sha256(requirements),
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(subject, "require_interpreter", lambda _: None)
    attempted_install = False

    def pip_boundary(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        nonlocal attempted_install
        if "--dry-run" in args:
            if failure == "dry-run":
                raise subprocess.CalledProcessError(1, args)
            report = {
                "install": [
                    {
                        "metadata": {
                            "name": "numpy" if failure == "bad-report" else "example",
                            "version": "1.0",
                        },
                        "download_info": {
                            "url": row["url"],
                            "archive_info": {"hashes": {"sha256": row["sha256"]}},
                        },
                    }
                ]
            }
            Path(args[args.index("--report") + 1]).write_text(json.dumps(report), encoding="utf-8")
            return subprocess.CompletedProcess(args, 0)
        attempted_install = True
        if failure == "install-and-protection":
            native.write_bytes(b"unexpected replacement")
        raise subprocess.CalledProcessError(17, args)

    monkeypatch.setattr("scripts.conda_backend_dependencies.subprocess.run", pip_boundary)
    args = argparse.Namespace(plan=plan_path)
    if failure == "install-and-protection":
        with pytest.raises(BaseExceptionGroup) as caught:
            subject.install(args)
        assert any(isinstance(e, subprocess.CalledProcessError) for e in caught.value.exceptions)
        assert any(
            isinstance(e, ValueError) and "changed" in str(e) for e in caught.value.exceptions
        )
    elif failure == "bad-report":
        with pytest.raises(ValueError, match="unplanned"):
            subject.install(args)
    else:
        with pytest.raises(subprocess.CalledProcessError):
            subject.install(args)
    assert attempted_install == failure.startswith("install")
