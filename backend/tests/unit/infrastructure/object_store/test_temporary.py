import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.object_store import temporary
from ai_workshop.infrastructure.object_store.temporary import TrackedTemporaryStore
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryBinding,
    TemporaryClaim,
    TemporaryContext,
    TemporaryOwnershipError,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows handle mutations")


def setup_store(root: Path) -> tuple[TrackedTemporaryStore, TemporaryClaim]:
    binding = TemporaryBinding("temporary", uuid4())
    (root / ".ai-workshop-temporary-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": binding.store_id,
                "binding_id": str(binding.binding_id),
            }
        ),
        encoding="utf-8",
    )
    claim = TemporaryClaim(
        uuid4(),
        TemporaryContext(SourceIdentity(uuid4(), uuid4(), uuid4())),
        "parsing",
        binding,
        1,
        "bounded",
    )
    return TrackedTemporaryStore(root, binding), claim


def test_exact_owned_discard_and_no_reuse(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    assert not store.observe(claim)
    workspace = store.create(claim)
    try:
        path = workspace.create_file("source.pdf")
        path.write_bytes(b"synthetic source")
        assert path.read_bytes() == b"synthetic source"
        assert store.observe(claim)
        workspace.discard()
        assert not store.observe(claim)
        with pytest.raises(TemporaryOwnershipError):
            store.create(claim)
    finally:
        workspace.close()


@pytest.mark.parametrize("directory", [False, True])
def test_foreign_entry_blocks_entire_discard(tmp_path: Path, directory: bool) -> None:
    store, claim = setup_store(tmp_path)
    workspace = store.create(claim)
    try:
        owned = workspace.create_file("owned.txt")
        owned.write_bytes(b"owned")
        foreign = workspace.root / "foreign"
        if directory:
            foreign.mkdir()
        else:
            foreign.write_bytes(b"synthetic foreign fixture")
        with pytest.raises(TemporaryOwnershipError):
            workspace.discard()
        assert owned.read_bytes() == b"owned"
        assert (
            foreign.is_dir() if directory else foreign.read_bytes() == b"synthetic foreign fixture"
        )
    finally:
        workspace.close()


def test_nonexclusive_root_and_file_rejected(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    (tmp_path / str(claim.id)).mkdir()
    with pytest.raises(TemporaryOwnershipError):
        store.create(claim)
    workspace = store.create(replace(claim, id=uuid4()))
    try:
        foreign = workspace.root / "foreign.txt"
        foreign.write_bytes(b"foreign")
        with pytest.raises(TemporaryOwnershipError):
            workspace.create_file("foreign.txt")
        assert foreign.read_bytes() == b"foreign"
    finally:
        workspace.close()


def test_marker_mismatch_before_creation(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    other = TrackedTemporaryStore(tmp_path, replace(store.binding, binding_id=uuid4()))
    with pytest.raises(TemporaryOwnershipError):
        other.create(replace(claim, binding=other.binding))
    assert not (tmp_path / str(claim.id)).exists()


def test_closed_and_reopened_store_cannot_reclaim(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    workspace = store.create(claim)
    owned = workspace.create_file("owned.txt")
    workspace.close()
    with pytest.raises(TemporaryOwnershipError):
        workspace.discard()
    reopened = TrackedTemporaryStore(tmp_path, store.binding)
    assert reopened.observe(claim)
    with pytest.raises(TemporaryOwnershipError):
        reopened.create(claim)
    assert owned.exists()


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "x:stream", "NUL.txt", "x.", "", ".."])
def test_invalid_names_never_allocate(tmp_path: Path, name: str) -> None:
    store, claim = setup_store(tmp_path)
    workspace = store.create(claim)
    try:
        with pytest.raises(TemporaryOwnershipError):
            workspace.create_file(name)
        assert list(workspace.root.iterdir()) == []
        workspace.discard()
    finally:
        workspace.close()


def test_pins_block_file_root_ancestor_and_marker_replacement(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    store, claim = setup_store(root)
    workspace = store.create(claim)
    try:
        owned = workspace.create_file("source.pdf")
        for path in [owned, workspace.root, root, root / ".ai-workshop-temporary-store.json"]:
            with pytest.raises(OSError):
                path.rename(path.with_name(path.name + "-replacement"))
        with pytest.raises(OSError):
            (root / ".ai-workshop-temporary-store.json").write_bytes(b"modified")
        workspace.discard()
    finally:
        workspace.close()


def test_hardlink_blocks_all_deletion(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    workspace = store.create(claim)
    try:
        first = workspace.create_file("first.txt")
        linked = workspace.create_file("linked.txt")
        linked.write_bytes(b"synthetic linked content")
        external = tmp_path / "external-link.txt"
        os.link(linked, external)
        with pytest.raises(TemporaryOwnershipError):
            workspace.discard()
        assert first.exists()
        assert linked.read_bytes() == external.read_bytes() == b"synthetic linked content"
    finally:
        workspace.close()


def test_replacement_in_delete_handle_gap_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, claim = setup_store(tmp_path)
    workspace = store.create(claim)
    original_delete = temporary.TemporaryWorkspace._delete
    try:
        owned = workspace.create_file("owned.txt")
        owned.write_bytes(b"owned")

        def replace_before_delete(
            path: Path, identity: tuple[int, int], *, directory: bool = False
        ) -> None:
            assert not directory
            path.rename(tmp_path / "moved-owned.txt")
            path.write_bytes(b"synthetic replacement")
            original_delete(path, identity)

        monkeypatch.setattr(
            temporary.TemporaryWorkspace, "_delete", staticmethod(replace_before_delete)
        )
        with pytest.raises(TemporaryOwnershipError):
            workspace.discard()
        assert owned.read_bytes() == b"synthetic replacement"
        assert (tmp_path / "moved-owned.txt").read_bytes() == b"owned"
    finally:
        workspace.close()


def test_non_windows_rejected_before_native_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, claim = setup_store(tmp_path)
    # Replace this module's os reference, never the global os module used by pathlib/pytest.
    from types import SimpleNamespace

    monkeypatch.setattr(temporary, "os", SimpleNamespace(name="posix"))
    with pytest.raises(TemporaryOwnershipError):
        store.create(claim)
    assert not (tmp_path / str(claim.id)).exists()


def test_wrong_claim_binding_rejected_before_allocation(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    with pytest.raises(TemporaryOwnershipError):
        store.create(replace(claim, binding=replace(store.binding, binding_id=uuid4())))
    assert not (tmp_path / str(claim.id)).exists()


def test_child_process_writes_existing_pinned_file(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    workspace = store.create(claim)
    try:
        owned = workspace.create_file("output.bin")
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'child')",
                str(owned),
            ],
            check=True,
            timeout=10,
            capture_output=True,
        )
        assert owned.read_bytes() == b"child"
        workspace.discard()
        assert not store.observe(claim)
    finally:
        workspace.close()


@pytest.mark.parametrize("invalid", ["missing", "malformed", "boolean_schema", "hardlink", "case"])
def test_invalid_marker_prevents_root_allocation(tmp_path: Path, invalid: str) -> None:
    store, claim = setup_store(tmp_path)
    marker = tmp_path / ".ai-workshop-temporary-store.json"
    if invalid == "missing":
        marker.rename(tmp_path / "unrelated.json")
    elif invalid == "malformed":
        marker.write_bytes(b"not json")
    elif invalid == "boolean_schema":
        value = json.loads(marker.read_text(encoding="utf-8"))
        value["schema_version"] = True
        marker.write_text(json.dumps(value), encoding="utf-8")
    elif invalid == "hardlink":
        os.link(marker, tmp_path / "linked-marker.json")
    else:
        marker.rename(tmp_path / marker.name.upper())
    with pytest.raises(TemporaryOwnershipError):
        store.create(claim)
    assert not (tmp_path / str(claim.id)).exists()


def test_store_identity_change_prevents_new_allocation(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    store, claim = setup_store(root)
    assert not store.observe(claim)
    root.rename(tmp_path / "moved-store")
    root.mkdir()
    (root / ".ai-workshop-temporary-store.json").write_bytes(
        (tmp_path / "moved-store" / ".ai-workshop-temporary-store.json").read_bytes()
    )
    with pytest.raises(TemporaryOwnershipError):
        store.create(claim)
    assert not (root / str(claim.id)).exists()


def test_unknown_entry_arriving_after_initial_preflight_blocks_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, claim = setup_store(tmp_path)
    workspace = store.create(claim)
    try:
        owned = workspace.create_file("owned.txt")
        check = workspace._preflight
        foreign = workspace.root / "foreign.txt"

        def add_foreign() -> None:
            check()
            foreign.write_bytes(b"synthetic late foreign fixture")

        monkeypatch.setattr(workspace, "_preflight", add_foreign)
        with pytest.raises(TemporaryOwnershipError):
            workspace.discard()
        assert owned.exists()
        assert foreign.read_bytes() == b"synthetic late foreign fixture"
    finally:
        workspace.close()
