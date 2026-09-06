import hashlib
import json
from pathlib import Path

import pytest

from ai_workshop.labs.rag.ocr.artifacts import (
    ArtifactIntegrityError,
    provision_artifacts,
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
