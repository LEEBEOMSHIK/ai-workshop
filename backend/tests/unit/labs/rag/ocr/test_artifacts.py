import hashlib
import json
import stat
from pathlib import Path

import pytest

from ai_workshop.labs.rag.ocr.artifacts import (
    ArtifactIntegrityError,
    provision_artifacts,
    verify_artifacts,
)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_manifest(path: Path, *, weight: bytes, metadata: bytes) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pipeline": {
                    "name": "PP-StructureV3",
                    "package_version": "3.7.0",
                },
                "models": [
                    {
                        "runtime_role": "layout",
                        "model_kind": "ocr_layout_detection",
                        "name": "layout-model",
                        "repository": "PaddlePaddle/layout-model",
                        "revision": "a" * 40,
                        "license": "Apache-2.0",
                        "artifact_sha256": _digest(weight),
                        "files": [
                            {
                                "path": "inference.pdiparams",
                                "size": len(weight),
                                "sha256": _digest(weight),
                            },
                            {
                                "path": "inference.yml",
                                "size": len(metadata),
                                "sha256": _digest(metadata),
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_provisioner_verifies_every_file_before_installing_an_immutable_artifact(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "downloads"
    source = source_root / "layout"
    source.mkdir(parents=True)
    weight = b"pinned-weight"
    metadata = b"model-config"
    (source / "inference.pdiparams").write_bytes(weight)
    (source / "inference.yml").write_bytes(metadata)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, weight=weight, metadata=metadata)

    installed = provision_artifacts(
        manifest_path=manifest,
        source_root=source_root,
        cache_root=tmp_path / "models",
    )

    target = (
        tmp_path
        / "models"
        / "ocr"
        / "ocr_layout_detection"
        / _digest(weight)
    )
    assert installed == (target,)
    assert (target / "inference.pdiparams").read_bytes() == weight
    assert (target / "inference.yml").read_bytes() == metadata


def test_provisioner_does_not_copy_restrictive_source_permissions(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "downloads"
    source = source_root / "layout"
    source.mkdir(parents=True)
    weight = b"pinned-weight"
    metadata = b"model-config"
    weight_path = source / "inference.pdiparams"
    metadata_path = source / "inference.yml"
    weight_path.write_bytes(weight)
    metadata_path.write_bytes(metadata)
    weight_path.chmod(0o444)
    metadata_path.chmod(0o444)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, weight=weight, metadata=metadata)

    (target,) = provision_artifacts(
        manifest_path=manifest,
        source_root=source_root,
        cache_root=tmp_path / "models",
    )

    for installed_file in target.iterdir():
        mode = installed_file.stat().st_mode
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR


def test_provisioner_rejects_a_hash_mismatch_without_installing_partial_files(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "downloads"
    source = source_root / "layout"
    source.mkdir(parents=True)
    expected_weight = b"approved-weight"
    (source / "inference.pdiparams").write_bytes(b"tampered-weight")
    (source / "inference.yml").write_bytes(b"model-config")
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        weight=expected_weight,
        metadata=b"model-config",
    )

    with pytest.raises(ArtifactIntegrityError, match="SHA-256"):
        provision_artifacts(
            manifest_path=manifest,
            source_root=source_root,
            cache_root=tmp_path / "models",
        )

    assert not (tmp_path / "models" / "ocr").exists()


def test_provisioner_rejects_an_artifact_identity_that_is_not_the_weight_hash(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "downloads"
    source = source_root / "layout"
    source.mkdir(parents=True)
    weight = b"approved-weight"
    metadata = b"model-config"
    (source / "inference.pdiparams").write_bytes(weight)
    (source / "inference.yml").write_bytes(metadata)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, weight=weight, metadata=metadata)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["models"][0]["artifact_sha256"] = "0" * 64
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError, match="artifact identity"):
        provision_artifacts(
            manifest_path=manifest,
            source_root=source_root,
            cache_root=tmp_path / "models",
        )

    assert not (tmp_path / "models" / "ocr").exists()


def test_verifier_accepts_only_complete_installed_artifacts(tmp_path: Path) -> None:
    weight = b"approved-weight"
    metadata = b"model-config"
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, weight=weight, metadata=metadata)
    target = (
        tmp_path
        / "models"
        / "ocr"
        / "ocr_layout_detection"
        / _digest(weight)
    )
    target.mkdir(parents=True)
    (target / "inference.pdiparams").write_bytes(weight)
    (target / "inference.yml").write_bytes(metadata)

    assert verify_artifacts(manifest_path=manifest, cache_root=tmp_path / "models") == (
        target,
    )


def test_verifier_rejects_tampered_installed_artifacts(tmp_path: Path) -> None:
    weight = b"approved-weight"
    metadata = b"model-config"
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, weight=weight, metadata=metadata)
    target = (
        tmp_path
        / "models"
        / "ocr"
        / "ocr_layout_detection"
        / _digest(weight)
    )
    target.mkdir(parents=True)
    (target / "inference.pdiparams").write_bytes(b"tampered-weight")
    (target / "inference.yml").write_bytes(metadata)

    with pytest.raises(ArtifactIntegrityError, match="SHA-256 does not match"):
        verify_artifacts(manifest_path=manifest, cache_root=tmp_path / "models")


def test_verifier_converts_file_access_failures_to_safe_domain_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    weight = b"approved-weight"
    metadata = b"model-config"
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, weight=weight, metadata=metadata)
    target = (
        tmp_path
        / "models"
        / "ocr"
        / "ocr_layout_detection"
        / _digest(weight)
    )
    target.mkdir(parents=True)
    weight_path = target / "inference.pdiparams"
    weight_path.write_bytes(weight)
    (target / "inference.yml").write_bytes(metadata)
    original_open = Path.open

    def deny_weight(path: Path, *args, **kwargs):
        if path == weight_path:
            raise PermissionError("private physical path")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_weight)

    with pytest.raises(ArtifactIntegrityError, match="file is unavailable") as caught:
        verify_artifacts(manifest_path=manifest, cache_root=tmp_path / "models")

    assert "private physical path" not in str(caught.value)
