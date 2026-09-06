import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from re import fullmatch


class ArtifactIntegrityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _File:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _Model:
    runtime_role: str
    model_kind: str
    artifact_sha256: str
    files: tuple[_File, ...]


def provision_artifacts(
    *,
    manifest_path: Path,
    source_root: Path,
    cache_root: Path,
) -> tuple[Path, ...]:
    models = _load_manifest(manifest_path)
    for model in models:
        source = source_root / model.runtime_role
        for item in model.files:
            _verify_file(source / item.path, item)

    installed: list[Path] = []
    for model in models:
        target = cache_root / "ocr" / model.model_kind / model.artifact_sha256
        if target.exists():
            for item in model.files:
                _verify_file(target / item.path, item)
            installed.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".provision-", dir=target.parent))
        try:
            source = source_root / model.runtime_role
            for item in model.files:
                destination = staging / item.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / item.path, destination)
                _verify_file(destination, item)
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        installed.append(target)
    return tuple(installed)


def _load_manifest(path: Path) -> tuple[_Model, ...]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError("The OCR artifact manifest is invalid.") from exc
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        raise ArtifactIntegrityError("The OCR artifact manifest schema is invalid.")
    model_values = value.get("models")
    if not isinstance(model_values, Sequence) or isinstance(model_values, str | bytes):
        raise ArtifactIntegrityError("The OCR artifact manifest models are invalid.")
    models: list[_Model] = []
    roles: set[str] = set()
    for raw_model in model_values:
        if not isinstance(raw_model, Mapping):
            raise ArtifactIntegrityError("An OCR artifact model is invalid.")
        role = _required_string(raw_model, "runtime_role")
        kind = _required_string(raw_model, "model_kind")
        _required_string(raw_model, "name")
        repository = _required_string(raw_model, "repository")
        revision = _required_string(raw_model, "revision")
        license_name = _required_string(raw_model, "license")
        artifact_sha256 = _sha256(raw_model.get("artifact_sha256"))
        if (
            not repository.startswith("PaddlePaddle/")
            or fullmatch(r"[0-9a-f]{40}", revision) is None
            or license_name != "Apache-2.0"
        ):
            raise ArtifactIntegrityError("An OCR artifact model source is invalid.")
        raw_files = raw_model.get("files")
        if (
            role in roles
            or not isinstance(raw_files, Sequence)
            or isinstance(raw_files, str | bytes)
            or not raw_files
        ):
            raise ArtifactIntegrityError("An OCR artifact model is invalid.")
        files: list[_File] = []
        paths: set[str] = set()
        for raw_file in raw_files:
            if not isinstance(raw_file, Mapping):
                raise ArtifactIntegrityError("An OCR artifact file is invalid.")
            relative_path = _safe_relative_path(_required_string(raw_file, "path"))
            size = raw_file.get("size")
            if (
                relative_path in paths
                or not isinstance(size, int)
                or isinstance(size, bool)
                or size < 0
            ):
                raise ArtifactIntegrityError("An OCR artifact file is invalid.")
            files.append(
                _File(relative_path, size, _sha256(raw_file.get("sha256")))
            )
            paths.add(relative_path)
        weight = next(
            (item for item in files if item.path == "inference.pdiparams"),
            None,
        )
        if weight is None or weight.sha256 != artifact_sha256:
            raise ArtifactIntegrityError(
                "The OCR artifact identity must match the inference weight SHA-256."
            )
        models.append(_Model(role, kind, artifact_sha256, tuple(files)))
        roles.add(role)
    if not models:
        raise ArtifactIntegrityError("The OCR artifact manifest models are invalid.")
    return tuple(models)


def _verify_file(path: Path, expected: _File) -> None:
    if not path.is_file() or path.stat().st_size != expected.size:
        raise ArtifactIntegrityError("An OCR artifact file size does not match.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected.sha256:
        raise ArtifactIntegrityError("An OCR artifact file SHA-256 does not match.")


def _required_string(value: Mapping[object, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ArtifactIntegrityError("The OCR artifact manifest is invalid.")
    return item


def _sha256(value: object) -> str:
    if not isinstance(value, str) or fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ArtifactIntegrityError("The OCR artifact manifest SHA-256 is invalid.")
    return value


def _safe_relative_path(value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
        raise ArtifactIntegrityError("An OCR artifact path is invalid.")
    return value
