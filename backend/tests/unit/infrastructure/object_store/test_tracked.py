from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.infrastructure.object_store.tracked import (
    RAG_ARTIFACT_KEY_CONTRACT_VERSION,
    ArtifactStoreError,
    TrackedLocalArtifactStore,
)
from ai_workshop.labs.rag.ingestion.artifact_contracts import (
    ArtifactBinding,
    ArtifactClaim,
    ArtifactRole,
    VerifiedArtifact,
)

_BINDING_ID = UUID("11111111-1111-4111-8111-111111111111")
_PROJECTION_ID = UUID("22222222-2222-4222-8222-222222222222")
_ATTEMPT_ID = UUID("33333333-3333-4333-8333-333333333333")
_CONTENT = b'{"synthetic":true}'
_DIGEST = hashlib.sha256(_CONTENT).hexdigest()


def _binding() -> ArtifactBinding:
    return ArtifactBinding("rag_ingestion_artifacts", _BINDING_ID)


def _write_marker(root: Path, binding: ArtifactBinding | None = None) -> None:
    selected = binding or _binding()
    root.mkdir()
    (root / ".ai-workshop-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": selected.store_id,
                "binding_id": str(selected.binding_id),
            }
        ),
        encoding="utf-8",
    )


def _claim(
    *,
    binding: ArtifactBinding | None = None,
    canonical_key: str | None = None,
    temporary_key: str | None = None,
    proposed_size: int = len(_CONTENT),
    proposed_sha256: str = _DIGEST,
) -> ArtifactClaim:
    canonical = canonical_key or f"rag/parsed/{_PROJECTION_ID}.json"
    temporary = temporary_key or (
        f"rag/parsed/.{_PROJECTION_ID}.json.{_ATTEMPT_ID.hex}.tmp"
    )
    return ArtifactClaim(
        bundle_id=UUID("44444444-4444-4444-8444-444444444444"),
        slot_id=UUID("55555555-5555-4555-8555-555555555555"),
        attempt_id=_ATTEMPT_ID,
        job_id=UUID("66666666-6666-4666-8666-666666666666"),
        projection_id=_PROJECTION_ID,
        role=ArtifactRole.PARSED,
        binding=binding or _binding(),
        canonical_key=canonical,
        temporary_key=temporary,
        proposed_size=proposed_size,
        proposed_sha256=proposed_sha256,
    )


def _verified(**changes: object) -> VerifiedArtifact:
    values: dict[str, object] = {
        "bundle_id": UUID("44444444-4444-4444-8444-444444444444"),
        "slot_id": UUID("55555555-5555-4555-8555-555555555555"),
        "job_id": UUID("66666666-6666-4666-8666-666666666666"),
        "projection_id": _PROJECTION_ID,
        "role": ArtifactRole.PARSED,
        "binding": _binding(),
        "canonical_key": f"rag/parsed/{_PROJECTION_ID}.json",
        "size": len(_CONTENT),
        "sha256": _DIGEST,
    }
    values.update(changes)
    return VerifiedArtifact(**values)  # type: ignore[arg-type]


def test_binding_marker_is_required_exact_and_never_initialized(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    store = TrackedLocalArtifactStore(root, _binding())

    with pytest.raises(ArtifactStoreError) as missing:
        store.verify_binding()
    assert missing.value.code == "artifact_binding_missing"
    assert not (root / ".ai-workshop-store.json").exists()

    (root / ".ai-workshop-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": "another_store",
                "binding_id": str(_BINDING_ID),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ArtifactStoreError) as mismatch:
        store.verify_binding()
    assert mismatch.value.code == "artifact_binding_mismatch"


@pytest.mark.parametrize(
    "marker",
    [
        "not-json",
        "[]",
        json.dumps(
            {
                "schema_version": True,
                "store_id": "rag_ingestion_artifacts",
                "binding_id": str(_BINDING_ID),
            }
        ),
        json.dumps(
            {
                "schema_version": 2,
                "store_id": "rag_ingestion_artifacts",
                "binding_id": str(_BINDING_ID),
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "store_id": "rag_ingestion_artifacts",
                "binding_id": "not-a-uuid",
            }
        ),
        json.dumps(
            {
                "schema_version": 1,
                "store_id": "rag_ingestion_artifacts",
                "binding_id": str(_BINDING_ID),
                "extra": True,
            }
        ),
        "x" * 4097,
    ],
)
def test_binding_marker_rejects_unbounded_or_non_exact_schema(
    tmp_path: Path, marker: str
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    (root / ".ai-workshop-store.json").write_text(marker, encoding="utf-8")

    with pytest.raises(ArtifactStoreError) as error:
        TrackedLocalArtifactStore(root, _binding()).verify_binding()

    assert error.value.code == "artifact_binding_invalid"


@pytest.mark.asyncio
async def test_publish_uses_registered_temp_and_returns_observed_canonical_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    _write_marker(root)
    claim = _claim()
    store = TrackedLocalArtifactStore(root, _binding())

    publication, content = await store.publish(claim, _CONTENT)

    assert RAG_ARTIFACT_KEY_CONTRACT_VERSION == 1
    assert publication.claim == claim
    assert publication.size == len(_CONTENT)
    assert publication.sha256 == _DIGEST
    assert content == _CONTENT
    assert (root / claim.canonical_key).read_bytes() == _CONTENT
    assert not (root / claim.temporary_key).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    [
        _claim(binding=ArtifactBinding("other_store", _BINDING_ID)),
        _claim(canonical_key=f"rag/chunks/{_PROJECTION_ID}.json"),
        _claim(temporary_key=f"rag/parsed/.wrong.{_ATTEMPT_ID.hex}.tmp"),
        _claim(proposed_size=len(_CONTENT) + 1),
        _claim(proposed_sha256="0" * 64),
    ],
)
async def test_publish_rejects_binding_key_or_content_claim_before_object_io(
    tmp_path: Path, claim: ArtifactClaim
) -> None:
    root = tmp_path / "store"
    _write_marker(root)

    with pytest.raises(ArtifactStoreError):
        await TrackedLocalArtifactStore(root, _binding()).publish(claim, _CONTENT)

    assert not (root / "rag").exists()


@pytest.mark.asyncio
async def test_publish_never_overwrites_canonical_or_preexisting_temp(tmp_path: Path) -> None:
    root = tmp_path / "store"
    _write_marker(root)
    claim = _claim()
    canonical = root / claim.canonical_key
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"preexisting")
    store = TrackedLocalArtifactStore(root, _binding())

    with pytest.raises(ArtifactStoreError) as canonical_error:
        await store.publish(claim, _CONTENT)
    assert canonical_error.value.code == "artifact_canonical_conflict"
    assert canonical.read_bytes() == b"preexisting"
    assert not (root / claim.temporary_key).exists()

    canonical.unlink()
    temporary = root / claim.temporary_key
    temporary.write_bytes(b"other-writer")
    with pytest.raises(ArtifactStoreError) as temporary_error:
        await store.publish(claim, _CONTENT)
    assert temporary_error.value.code == "artifact_temporary_conflict"
    assert temporary.read_bytes() == b"other-writer"


@pytest.mark.asyncio
async def test_verified_read_and_inspection_validate_observed_bytes(tmp_path: Path) -> None:
    root = tmp_path / "store"
    _write_marker(root)
    claim = _claim()
    store = TrackedLocalArtifactStore(root, _binding())
    await store.publish(claim, _CONTENT)

    assert await store.read_verified(_verified()) == _CONTENT
    described = await store.inspect_key(claim.canonical_key)
    assert described is not None
    assert described.key == claim.canonical_key
    assert described.size == len(_CONTENT)
    assert described.sha256 == _DIGEST
    assert await store.inspect_key(
        f"rag/chunks/{UUID('77777777-7777-4777-8777-777777777777')}.json"
    ) is None

    with pytest.raises(ArtifactStoreError) as mismatch:
        await store.read_verified(_verified(sha256="0" * 64))
    assert mismatch.value.code == "artifact_integrity_mismatch"


@pytest.mark.asyncio
async def test_publish_revalidates_binding_after_atomic_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    _write_marker(root)
    marker = root / ".ai-workshop-store.json"
    original_link = os.link

    def link_then_change_binding(source: Path, destination: Path) -> None:
        original_link(source, destination)
        marker.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "store_id": "different_store",
                    "binding_id": str(_BINDING_ID),
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(os, "link", link_then_change_binding)
    claim = _claim()

    with pytest.raises(ArtifactStoreError) as error:
        await TrackedLocalArtifactStore(root, _binding()).publish(claim, _CONTENT)

    assert error.value.code == "artifact_binding_mismatch"
    assert (root / claim.canonical_key).read_bytes() == _CONTENT
    assert (root / claim.temporary_key).read_bytes() == _CONTENT
    assert error.value.temporary_absent is False


@pytest.mark.asyncio
async def test_cleanup_never_unlinks_a_replacement_at_the_registered_temp_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    _write_marker(root)
    claim = _claim()
    parsed = root / "rag" / "parsed"
    displaced = root / "rag" / "parsed-displaced"

    def replace_parent_then_fail(_source: Path, _destination: Path) -> None:
        parsed.rename(displaced)
        parsed.mkdir()
        (root / claim.temporary_key).write_bytes(b"unrelated-replacement")
        raise OSError("synthetic private detail")

    monkeypatch.setattr(os, "link", replace_parent_then_fail)
    with pytest.raises(ArtifactStoreError) as error:
        await TrackedLocalArtifactStore(root, _binding()).publish(claim, _CONTENT)

    assert error.value.code == "artifact_io_failed"
    assert error.value.writer_finished is True
    assert error.value.temporary_absent is False
    assert (root / claim.temporary_key).read_bytes() == b"unrelated-replacement"
    assert (displaced / Path(claim.temporary_key).name).read_bytes() == _CONTENT


@pytest.mark.asyncio
async def test_invalid_root_key_alias_and_reparse_are_rejected(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing"
    with pytest.raises(ArtifactStoreError):
        TrackedLocalArtifactStore(missing_root, _binding()).verify_binding()

    root = tmp_path / "store"
    _write_marker(root)
    store = TrackedLocalArtifactStore(root, _binding())
    for invalid_key in ("", ".", "/absolute", "../outside", "rag\\parsed\\file.json"):
        with pytest.raises(ArtifactStoreError) as error:
            await store.inspect_key(invalid_key)
        assert error.value.code == "artifact_key_invalid"

    (root / "RAG").mkdir()
    with pytest.raises(ArtifactStoreError) as alias:
        await store.publish(_claim(), _CONTENT)
    assert alias.value.code == "artifact_path_alias"


def test_root_and_marker_symlinks_are_rejected_when_supported(tmp_path: Path) -> None:
    real_root = tmp_path / "real-store"
    _write_marker(real_root)
    root_alias = tmp_path / "root-alias"
    try:
        root_alias.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(ArtifactStoreError) as root_error:
        TrackedLocalArtifactStore(root_alias, _binding()).verify_binding()
    assert root_error.value.code == "artifact_reparse_path"

    marker_target = tmp_path / "marker-target.json"
    marker_target.write_bytes((real_root / ".ai-workshop-store.json").read_bytes())
    (real_root / ".ai-workshop-store.json").unlink()
    (real_root / ".ai-workshop-store.json").symlink_to(marker_target)
    with pytest.raises(ArtifactStoreError) as marker_error:
        TrackedLocalArtifactStore(real_root, _binding()).verify_binding()
    assert marker_error.value.code == "artifact_reparse_path"


@pytest.mark.asyncio
async def test_failed_publish_reports_only_observed_cleanup_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    _write_marker(root)
    claim = _claim()

    def fail_link(_source: Path, _destination: Path) -> None:
        raise OSError("synthetic private detail")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(ArtifactStoreError) as error:
        await TrackedLocalArtifactStore(root, _binding()).publish(claim, _CONTENT)

    assert error.value.code == "artifact_io_failed"
    assert str(error.value) == "artifact_io_failed"
    assert error.value.writer_finished is True
    assert error.value.temporary_absent is True
    assert not (root / claim.temporary_key).exists()


def test_killed_disposable_writer_leaves_only_registered_temp_key(tmp_path: Path) -> None:
    root = tmp_path / "store"
    _write_marker(root)
    signal = tmp_path / "writer-ready"
    claim = _claim()
    script = r'''
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import time
from uuid import UUID
from ai_workshop.infrastructure.object_store import tracked
from ai_workshop.infrastructure.object_store.tracked import TrackedLocalArtifactStore
from ai_workshop.labs.rag.ingestion.artifact_contracts import (
    ArtifactBinding,
    ArtifactClaim,
    ArtifactRole,
)

root = Path(sys.argv[1])
signal = Path(sys.argv[2])
content = b"child-content"
projection_id = UUID("22222222-2222-4222-8222-222222222222")
attempt_id = UUID("33333333-3333-4333-8333-333333333333")
binding = ArtifactBinding("rag_ingestion_artifacts", UUID("11111111-1111-4111-8111-111111111111"))
claim = ArtifactClaim(
    bundle_id=UUID("44444444-4444-4444-8444-444444444444"),
    slot_id=UUID("55555555-5555-4555-8555-555555555555"),
    attempt_id=attempt_id,
    job_id=UUID("66666666-6666-4666-8666-666666666666"),
    projection_id=projection_id,
    role=ArtifactRole.PARSED,
    binding=binding,
    canonical_key=f"rag/parsed/{projection_id}.json",
    temporary_key=f"rag/parsed/.{projection_id}.json.{attempt_id.hex}.tmp",
    proposed_size=len(content),
    proposed_sha256=hashlib.sha256(content).hexdigest(),
)

def pause_before_link(source, destination):
    signal.write_text("ready", encoding="utf-8")
    while True:
        time.sleep(0.1)

tracked.os.link = pause_before_link
asyncio.run(TrackedLocalArtifactStore(root, binding).publish(claim, content))
'''
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(root), str(signal)],
        cwd=Path(__file__).resolve().parents[4],
    )
    try:
        deadline = time.monotonic() + 10
        while not signal.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert signal.exists(), f"writer exited before pause: {process.returncode}"
        process.terminate()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    assert (root / claim.temporary_key).read_bytes() == b"child-content"
    assert not (root / claim.canonical_key).exists()
    objects = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]
    assert sorted(objects) == sorted([".ai-workshop-store.json", claim.temporary_key])
