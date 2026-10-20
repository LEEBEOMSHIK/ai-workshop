"""Prepare and apply hash-locked wheels without replacing Conda numeric packages.

Preparation is local/read-only outside the output directory. Installation is an
explicit separate command for the owner of the existing prefix; it never creates
an environment, changes permissions, activates a service, or invokes a model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import sysconfig
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from packaging.requirements import Requirement
from packaging.tags import Tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

PROTECTED = frozenset({"python", "numpy", "numpy-base", "scipy", "libopenblas", "blas"})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(prefix: Path, relative: str) -> Path:
    path = (prefix / relative).resolve()
    if not path.is_relative_to(prefix.resolve()):
        raise ValueError(f"Path outside protected prefix: {relative}")
    return path


def hash_files(prefix: Path, files: list[str]) -> dict[str, str]:
    return {name: sha256(safe_path(prefix, name)) for name in sorted(set(files))}


def verify_files(prefix: Path, expected: dict[str, str]) -> None:
    for name, digest in expected.items():
        path = safe_path(prefix, name)
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f"Protected file changed or missing: {name}")


def select_wheels(exported: str, lock: dict[str, Any], tags: list[Tag]) -> list[dict[str, str]]:
    """Select exact compatible official wheel URLs from an attested uv export."""
    ranks = {tag: rank for rank, tag in enumerate(tags)}
    rows: list[dict[str, str]] = []
    names: set[str] = set()
    for line in exported.replace("\\\n", " ").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(" --hash=sha256:")
        requirement = Requirement(parts[0].strip())
        name = canonicalize_name(requirement.name)
        if name in PROTECTED:
            raise ValueError(f"Pip input contains protected package: {name}")
        if requirement.marker and not requirement.marker.evaluate():
            continue
        specs = list(requirement.specifier)
        if requirement.url or len(specs) != 1 or specs[0].operator != "==":
            raise ValueError(f"Requirement is not exactly pinned: {name}")
        version = specs[0].version
        if name in names:
            raise ValueError(f"Duplicate active package: {name}")
        names.add(name)
        allowed_hashes = {part.strip() for part in parts[1:]}
        candidates: list[tuple[int, dict[str, str]]] = []
        for package in lock["package"]:
            if package["name"] != name or package["version"] != version:
                continue
            for wheel in package.get("wheels", []):
                url = wheel["url"]
                source = urlsplit(url)
                official = (source.hostname == "files.pythonhosted.org" and name != "torch") or (
                    source.hostname in {"download.pytorch.org", "download-r2.pytorch.org"}
                    and name == "torch"
                    and source.path.startswith("/whl/cpu/")
                )
                if source.scheme != "https" or source.username or not official:
                    raise ValueError(f"Unapproved wheel source for {name}")
                _, _, _, wheel_tags = parse_wheel_filename(unquote(source.path.rsplit("/", 1)[1]))
                matches = [ranks[tag] for tag in wheel_tags if tag in ranks]
                digest = wheel["hash"].removeprefix("sha256:")
                if matches and digest in allowed_hashes:
                    candidates.append(
                        (
                            min(matches),
                            {"name": name, "version": version, "url": url, "sha256": digest},
                        )
                    )
        if not candidates:
            raise ValueError(f"No hash-locked compatible official wheel for {name}=={version}")
        rows.append(min(candidates, key=lambda item: (item[0], item[1]["url"]))[1])
    if not rows:
        raise ValueError("Empty wheel plan")
    return rows


def validate_report(report: dict[str, Any], rows: list[dict[str, str]]) -> None:
    expected = {row["name"]: row for row in rows}
    seen: set[str] = set()
    for item in report["install"]:
        name = canonicalize_name(item["metadata"]["name"])
        if name in PROTECTED or name not in expected or name in seen:
            raise ValueError(f"Pip reported unplanned package: {name}")
        seen.add(name)
        row = expected[name]
        download = item["download_info"]
        if (
            item["metadata"]["version"] != row["version"]
            or download["url"] != row["url"]
            or download["archive_info"]["hashes"].get("sha256") != row["sha256"]
        ):
            raise ValueError(f"Pip archive differs from plan: {name}")


def pip_arguments(requirements: Path, report: Path, *, dry_run: bool) -> list[str]:
    args = [
        sys.executable,
        "-I",
        "-B",
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "install",
        "--no-deps",
        "--no-index",
        "--require-hashes",
        "--only-binary=:all:",
        "--no-input",
        "--retries",
        "0",
        "--report",
        str(report),
        "-r",
        str(requirements),
    ]
    if dry_run:
        args.append("--dry-run")
    return args


def protected_snapshot(prefix: Path, manifest_path: Path) -> dict[str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sysconfig.get_platform() != manifest["platform"]:
        raise ValueError("Run with the target Windows AMD64 Python")
    files: list[str] = []
    for name, expected in manifest["packages"].items():
        record = prefix / "conda-meta" / f"{name}-{expected['version']}-{expected['build']}.json"
        actual = json.loads(record.read_text(encoding="utf-8"))
        for key in ("version", "build", "sha256"):
            if actual[key] != expected[key]:
                raise ValueError(f"Conda metadata differs for {name}: {key}")
        if not actual["url"].startswith("https://repo.anaconda.com/pkgs/main/win-64/"):
            raise ValueError(f"Unapproved Conda source: {name}")
        files.extend(actual["files"])
        files.append(record.relative_to(prefix).as_posix())
    return hash_files(prefix, files)


def require_interpreter(prefix: Path) -> None:
    if Path(sys.prefix).resolve() != prefix.resolve():
        raise ValueError("Run this script with the existing target prefix's python.exe")
    if Path(sys.executable).resolve() != (prefix / "python.exe").resolve():
        raise ValueError("Unexpected Python executable")


def prepare(args: argparse.Namespace) -> None:
    prefix = args.prefix.resolve()
    require_interpreter(prefix)
    repo = Path(__file__).resolve().parents[1]
    sources = {
        "uv_lock": repo / "backend/uv.lock",
        "pyproject": repo / "backend/pyproject.toml",
        "numeric_lock": repo / "backend/conda-numeric-lock.json",
        "export": args.export.resolve(),
    }
    attestation = json.loads(args.attestation.read_text(encoding="utf-8"))
    for key, expected_key in (
        ("uv_lock", "uv_lock_sha256"),
        ("pyproject", "pyproject_sha256"),
        ("export", "requirements_sha256"),
    ):
        if sha256(sources[key]) != attestation[expected_key]:
            raise ValueError(f"Stale or changed export input: {key}")
    rows = select_wheels(
        sources["export"].read_text(encoding="utf-8"),
        tomllib.loads(sources["uv_lock"].read_text(encoding="utf-8")),
        list(sys_tags()),
    )
    protected = protected_snapshot(prefix, sources["numeric_lock"])
    requirements = "".join(
        f"{row['name']} @ {row['url']} --hash=sha256:{row['sha256']}\n" for row in rows
    )
    plan = {
        "schema_version": 1,
        "prefix": str(prefix),
        "rows": rows,
        "sources": {
            name: {"path": str(path), "sha256": sha256(path)} for name, path in sources.items()
        },
        "protected_files": protected,
        "requirements_sha256": hashlib.sha256(requirements.encode()).hexdigest(),
    }
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "wheels.txt").write_text(requirements, encoding="utf-8", newline="\n")
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "prepared": len(rows),
                "protected_files": len(protected),
                "plan": str(args.output / "plan.json"),
            }
        )
    )


def install(args: argparse.Namespace) -> None:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    prefix = Path(plan["prefix"])
    require_interpreter(prefix)
    for name, source in plan["sources"].items():
        if sha256(Path(source["path"])) != source["sha256"]:
            raise ValueError(f"Plan input changed: {name}")
    folder = args.plan.resolve().parent
    requirements = folder / "wheels.txt"
    if sha256(requirements) != plan["requirements_sha256"]:
        raise ValueError("Wheel requirements changed")
    verify_files(prefix, plan["protected_files"])
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PIP_CONFIG_FILE=os.devnull)
    dry_report = folder / "pip-dry-run.json"
    subprocess.run(pip_arguments(requirements, dry_report, dry_run=True), env=env, check=True)
    validate_report(json.loads(dry_report.read_text(encoding="utf-8")), plan["rows"])
    verify_files(prefix, plan["protected_files"])
    report = folder / "pip-install.json"
    try:
        subprocess.run(pip_arguments(requirements, report, dry_run=False), env=env, check=True)
    except BaseException as install_error:
        try:
            verify_files(prefix, plan["protected_files"])
        except BaseException as protection_error:
            raise BaseExceptionGroup(
                "Installation failed and protected Conda files changed",
                [install_error, protection_error],
            ) from None
        raise
    verify_files(prefix, plan["protected_files"])
    validate_report(json.loads(report.read_text(encoding="utf-8")), plan["rows"])
    for row in plan["rows"]:
        if importlib.metadata.version(row["name"]) != row["version"]:
            raise ValueError(f"Installed version differs: {row['name']}")
    subprocess.run([sys.executable, "-I", "-B", "-m", "pip", "check"], env=env, check=True)
    print("Locked dependencies installed; protected Conda files unchanged. Runtime checks remain.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("--prefix", type=Path, required=True)
    create.add_argument("--export", type=Path, required=True)
    create.add_argument("--attestation", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    apply = commands.add_parser("install")
    apply.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    else:
        install(args)


if __name__ == "__main__":
    main()
