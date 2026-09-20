import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.infrastructure.object_store import originals
from ai_workshop.infrastructure.object_store.originals import TrackedOriginalStore
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.upload_contracts import (
    OriginalStoreBinding,
    UploadClaim,
    UploadOwnershipError,
)

windows_mutation = pytest.mark.skipif(
    os.name != "nt", reason="Safe original mutations require Windows handles"
)


def setup_store(root: Path) -> tuple[TrackedOriginalStore, UploadClaim]:
    binding = OriginalStoreBinding("originals", uuid4())
    (root / ".ai-workshop-original-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": binding.store_id,
                "binding_id": str(binding.binding_id),
            }
        ),
        encoding="utf-8",
    )
    claim = UploadClaim(
        uuid4(), SourceIdentity(uuid4(), uuid4(), uuid4()), uuid4(), None, True, binding, ".txt"
    )
    return TrackedOriginalStore(root, binding), claim


async def content() -> AsyncIterator[bytes]:
    yield b"hello"
    yield b" world"


@windows_mutation
async def test_publish_observe_and_owned_discard(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    empty = store.observe(claim)
    assert empty.canonical is None and not empty.temporary_exists
    stored = await store.publish(claim, content())
    assert stored == StoredObject(
        claim.canonical_key, 11, hashlib.sha256(b"hello world").hexdigest()
    )
    assert (tmp_path / claim.canonical_key).read_bytes() == b"hello world"
    observed = store.observe(claim)
    assert observed.canonical == stored and not observed.temporary_exists
    store.discard(claim, stored)
    assert not (tmp_path / claim.canonical_key).exists()


@pytest.mark.parametrize("which", ["canonical", "temporary", "marker_missing", "binding"])
@windows_mutation
async def test_conflicts_do_not_consume_stream(tmp_path: Path, which: str) -> None:
    store, claim = setup_store(tmp_path)
    marker = tmp_path / ".ai-workshop-original-store.json"
    if which == "marker_missing":
        marker.unlink()
    elif which == "binding":
        marker.write_text(marker.read_text().replace("originals", "another"))
    else:
        path = tmp_path / (claim.canonical_key if which == "canonical" else claim.temporary_key)
        path.parent.mkdir(parents=True)
        path.write_bytes(b"foreign")
    consumed = []

    async def stream() -> AsyncIterator[bytes]:
        consumed.append(True)
        yield b"foreign"

    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, stream())
    assert not consumed
    if which in {"canonical", "temporary"}:
        assert path.read_bytes() == b"foreign"
    if which == "marker_missing":
        assert not marker.exists()


@pytest.mark.parametrize("error", [RuntimeError("stream failed"), asyncio.CancelledError()])
@windows_mutation
async def test_stream_failure_closes_and_removes_only_current_temporary(
    tmp_path: Path,
    error: BaseException,
) -> None:
    store, claim = setup_store(tmp_path)
    foreign = tmp_path / "foreign.tmp"
    foreign.write_bytes(b"keep")

    async def stream() -> AsyncIterator[bytes]:
        yield b"partial"
        raise error

    with pytest.raises(type(error)):
        await store.publish(claim, stream())
    assert not (tmp_path / claim.temporary_key).exists()
    assert not (tmp_path / claim.canonical_key).exists()
    assert foreign.read_bytes() == b"keep"


@windows_mutation
async def test_late_collision_is_preserved(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)

    async def stream() -> AsyncIterator[bytes]:
        yield b"hello"
        (tmp_path / claim.canonical_key).write_bytes(b"foreign")

    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, stream())
    assert (tmp_path / claim.canonical_key).read_bytes() == b"foreign"
    assert not (tmp_path / claim.temporary_key).exists()


@windows_mutation
async def test_discard_does_not_adopt_observed_file(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    stored = await store.publish(claim, content())
    observer = TrackedOriginalStore(tmp_path, claim.binding)
    assert (observer.observe(claim)).canonical == stored
    with pytest.raises(UploadOwnershipError):
        observer.discard(claim, stored)
    assert (tmp_path / claim.canonical_key).exists()


@pytest.mark.parametrize("replacement", ["content", "inode", "hardlink", "binding", "expected"])
@windows_mutation
async def test_discard_rejects_changed_ownership(tmp_path: Path, replacement: str) -> None:
    store, claim = setup_store(tmp_path)
    stored = await store.publish(claim, content())
    path = tmp_path / claim.canonical_key
    if replacement == "content":
        path.write_bytes(b"foreign")
    elif replacement == "inode":
        backup = path.with_name("backup")
        path.rename(backup)
        path.write_bytes(b"hello world")
    elif replacement == "hardlink":
        os.link(path, path.with_name("unexpected-link"))
    elif replacement == "binding":
        marker = tmp_path / ".ai-workshop-original-store.json"
        marker.write_text(marker.read_text().replace("originals", "other"))
    else:
        stored = replace(stored, sha256="0" * 64)
    with pytest.raises(UploadOwnershipError):
        store.discard(claim, stored)
    assert path.exists()


@pytest.mark.parametrize("kind", ["directory", "hardlink", "case_alias", "symlink"])
async def test_observe_rejects_wrong_file_instead_of_reporting_absent(
    tmp_path: Path, kind: str
) -> None:
    store, claim = setup_store(tmp_path)
    path = tmp_path / claim.canonical_key
    path.parent.mkdir(parents=True)
    if kind == "directory":
        path.mkdir()
    elif kind == "case_alias":
        path.with_name(path.name.upper()).write_bytes(b"foreign")
    else:
        foreign = tmp_path / "foreign"
        foreign.write_bytes(b"foreign")
        if kind == "hardlink":
            os.link(foreign, path)
        else:
            try:
                path.symlink_to(foreign)
            except OSError:
                pytest.skip("Creating symlinks requires host privileges")
    with pytest.raises(UploadOwnershipError):
        store.observe(claim)


@windows_mutation
async def test_traversal_claim_is_rejected(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    object.__setattr__(claim, "suffix", "/../../foreign")
    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, content())
    assert not (tmp_path / "foreign").exists()


@windows_mutation
async def test_fsync_failure_removes_temporary_and_does_not_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)

    def fail_fsync(fd: int) -> None:
        raise OSError("synthetic flush failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, content())
    assert not (tmp_path / claim.canonical_key).exists()
    assert not (tmp_path / claim.temporary_key).exists()


@windows_mutation
async def test_observation_failure_after_publication_preserves_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)

    def fail_describe(path: Path, key: str) -> StoredObject:
        raise UploadOwnershipError("store_unavailable")

    monkeypatch.setattr(store, "_describe", fail_describe)
    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, content())
    assert (tmp_path / claim.canonical_key).read_bytes() == b"hello world"
    assert not (tmp_path / claim.temporary_key).exists()


@windows_mutation
async def test_replaced_temporary_is_not_removed(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)

    async def stream() -> AsyncIterator[bytes]:
        yield b"first"
        path = tmp_path / claim.temporary_key
        # Windows disallows renaming an open handle without delete sharing.
        # A new hardlink still simulates an unowned alias while writer is open.
        os.link(path, path.with_name("foreign-link"))
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await store.publish(claim, stream())
    assert (tmp_path / claim.temporary_key).read_bytes() == b"first"
    assert not (tmp_path / claim.canonical_key).exists()


@windows_mutation
async def test_same_bytes_in_other_document_are_not_shared(tmp_path: Path) -> None:
    store, first = setup_store(tmp_path)
    second = replace(
        first,
        attempt_id=uuid4(),
        source=SourceIdentity(
            first.source.workspace_id,
            uuid4(),
            uuid4(),
        ),
    )
    first_stored = await store.publish(first, content())
    second_stored = await store.publish(second, content())
    store.discard(first, first_stored)
    assert (tmp_path / second.canonical_key).read_bytes() == b"hello world"
    assert (store.observe(second)).canonical == second_stored


@windows_mutation
async def test_parent_case_alias_is_rejected_without_consuming(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    (tmp_path / str(claim.source.workspace_id).upper()).mkdir()
    consumed = []

    async def stream() -> AsyncIterator[bytes]:
        consumed.append(True)
        yield b"hello"

    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, stream())
    assert not consumed


@pytest.mark.parametrize(
    "value", ["not json", "{}", "x" * 4097, '{"schema_version": true, "store_id": "originals"}']
)
async def test_invalid_markers_fail_closed(tmp_path: Path, value: str) -> None:
    store, claim = setup_store(tmp_path)
    (tmp_path / ".ai-workshop-original-store.json").write_text(value)
    with pytest.raises(UploadOwnershipError):
        store.observe(claim)


@windows_mutation
async def test_failed_writer_cannot_reuse_attempt(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)

    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise RuntimeError("broken stream")

    with pytest.raises(RuntimeError):
        await store.publish(claim, broken())
    consumed = []

    async def replay() -> AsyncIterator[bytes]:
        consumed.append(True)
        yield b"replay"

    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, replay())
    assert not consumed
    assert not (tmp_path / claim.canonical_key).exists()


@pytest.mark.parametrize("reparent", [False, True])
@windows_mutation
async def test_discard_preserves_replacement_after_last_path_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reparent: bool,
) -> None:
    store, claim = setup_store(tmp_path)
    stored = await store.publish(claim, content())
    canonical = tmp_path / claim.canonical_key
    original_plain = store._plain
    checks = 0

    def raced_plain(
        path: Path, *, directory: bool = False, allowed_links: int = 1
    ) -> os.stat_result:
        nonlocal checks
        status = original_plain(path, directory=directory, allowed_links=allowed_links)
        if path == canonical:
            checks += 1
            if checks == 6:
                if reparent:
                    path.parent.rename(path.parent.with_name("detached-parent"))
                    path.parent.mkdir()
                else:
                    path.rename(path.with_name("owned-backup"))
                path.write_bytes(b"foreign-replacement")
        return status

    monkeypatch.setattr(store, "_plain", raced_plain)
    with suppress(UploadOwnershipError):
        store.discard(claim, stored)
    assert checks >= 6
    assert canonical.read_bytes() == b"foreign-replacement"


@windows_mutation
async def test_temporary_cleanup_preserves_replacement_after_last_path_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)
    temporary = tmp_path / claim.temporary_key
    original_plain = store._plain
    checks = 0

    def raced_plain(
        path: Path, *, directory: bool = False, allowed_links: int = 1
    ) -> os.stat_result:
        nonlocal checks
        status = original_plain(path, directory=directory, allowed_links=allowed_links)
        if path == temporary:
            checks += 1
            if checks == 2:
                path.rename(path.with_name("owned-backup"))
                path.write_bytes(b"foreign-replacement")
        return status

    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise RuntimeError("broken stream")

    monkeypatch.setattr(store, "_plain", raced_plain)
    with pytest.raises(RuntimeError):
        await store.publish(claim, broken())
    assert checks >= 2
    assert temporary.read_bytes() == b"foreign-replacement"


@pytest.mark.parametrize("target", ["file", "parent", "root", "marker", "bytes"])
@windows_mutation
async def test_windows_deletion_holds_file_and_ancestor_handles_until_os_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    store, claim = setup_store(tmp_path)
    stored = await store.publish(claim, content())
    canonical = tmp_path / claim.canonical_key
    original_delete = store._mark_delete
    rejected = []

    def race_at_os_delete(fd: int) -> None:
        try:
            if target == "bytes":
                canonical.write_bytes(b"foreign bytes")
            else:
                path = {
                    "file": canonical,
                    "parent": canonical.parent,
                    "root": tmp_path,
                    "marker": tmp_path / ".ai-workshop-original-store.json",
                }[target]
                path.rename(path.with_name("replacement-backup"))
        except OSError:
            rejected.append(target)
        original_delete(fd)

    monkeypatch.setattr(store, "_mark_delete", race_at_os_delete)
    store.discard(claim, stored)
    assert rejected == [target]
    assert not canonical.exists()


@pytest.mark.parametrize("reparent", [False, True])
@windows_mutation
async def test_temporary_cleanup_holds_handle_at_os_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reparent: bool,
) -> None:
    store, claim = setup_store(tmp_path)
    temporary = tmp_path / claim.temporary_key
    original_delete = store._mark_delete
    rejected = []

    def race_at_os_delete(fd: int) -> None:
        path = temporary.parent if reparent else temporary
        try:
            path.rename(path.with_name("replacement-backup"))
        except OSError:
            rejected.append(True)
        original_delete(fd)

    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise asyncio.CancelledError()

    monkeypatch.setattr(store, "_mark_delete", race_at_os_delete)
    with pytest.raises(asyncio.CancelledError):
        await store.publish(claim, broken())
    assert rejected == [True]
    assert not temporary.exists()


async def test_unsupported_platform_preserves_reads_and_refuses_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)
    path = tmp_path / claim.canonical_key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"hello world")
    stored = StoredObject(claim.canonical_key, 11, hashlib.sha256(b"hello world").hexdigest())
    monkeypatch.setattr(originals, "os", SimpleNamespace(**(vars(os) | {"name": "posix"})))
    assert store.observe(claim).canonical == stored
    with pytest.raises(UploadOwnershipError, match="store_unavailable"):
        store.discard(claim, stored)
    consumed = []

    async def stream() -> AsyncIterator[bytes]:
        consumed.append(True)
        yield b"hello"

    second = replace(claim, attempt_id=uuid4())
    with pytest.raises(UploadOwnershipError, match="store_unavailable"):
        await store.publish(second, stream())
    assert not consumed
    assert not (tmp_path / second.temporary_key).exists()
    assert (tmp_path / claim.canonical_key).read_bytes() == b"hello world"


@windows_mutation
async def test_publish_pins_root_before_exclusive_create(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)
    temporary = tmp_path / claim.temporary_key
    marker_bytes = (tmp_path / ".ai-workshop-original-store.json").read_bytes()
    original_open = Path.open
    attempted = []
    blocked = []

    def raced_open(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path == temporary and mode == "xb":
            attempted.append(True)
            try:
                tmp_path.rename(tmp_path.with_name(tmp_path.name + "-detached"))
            except OSError:
                blocked.append(True)
            else:
                temporary.parent.mkdir(parents=True)
                (tmp_path / ".ai-workshop-original-store.json").write_bytes(marker_bytes)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", raced_open)
    with suppress(UploadOwnershipError):
        await store.publish(claim, content())
    assert attempted == [True]
    assert blocked == [True]
    assert (tmp_path / claim.canonical_key).read_bytes() == b"hello world"


@windows_mutation
async def test_publish_pins_source_before_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)
    original_link = os.link
    blocked = []

    def raced_link(source: Path, destination: Path) -> None:
        try:
            source.rename(source.with_name("owned-backup"))
        except OSError:
            blocked.append(True)
        else:
            source.write_bytes(b"foreign-replacement")
        original_link(source, destination)

    monkeypatch.setattr(os, "link", raced_link)
    with suppress(UploadOwnershipError):
        await store.publish(claim, content())
    assert blocked == [True]
    assert (tmp_path / claim.canonical_key).read_bytes() == b"hello world"


@windows_mutation
async def test_publish_pins_workspace_before_document_directory_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)
    workspace = tmp_path / str(claim.source.workspace_id)
    document = workspace / str(claim.source.document_id)
    original_mkdir = Path.mkdir
    blocked = []

    def raced_mkdir(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == document:
            try:
                workspace.rename(workspace.with_name("detached-workspace"))
            except OSError:
                blocked.append(True)
            else:
                original_mkdir(workspace)
        original_mkdir(path, mode, parents, exist_ok)

    monkeypatch.setattr(Path, "mkdir", raced_mkdir)
    await store.publish(claim, content())
    assert blocked == [True]
    assert (tmp_path / claim.canonical_key).read_bytes() == b"hello world"


@windows_mutation
async def test_replaced_root_during_pin_acquisition_never_consumes_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)
    original_fd = store._windows_fd
    marker = (tmp_path / ".ai-workshop-original-store.json").read_bytes()
    consumed = []

    def raced_fd(path: Path, *, directory: bool = False, delete: bool = False) -> int:
        if path == tmp_path:
            tmp_path.rename(tmp_path.with_name(tmp_path.name + "-detached"))
            tmp_path.mkdir()
            (tmp_path / ".ai-workshop-original-store.json").write_bytes(marker)
        return original_fd(path, directory=directory, delete=delete)

    async def stream() -> AsyncIterator[bytes]:
        consumed.append(True)
        yield b"private bytes"

    monkeypatch.setattr(store, "_windows_fd", raced_fd)
    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, stream())
    assert not consumed
    assert not (tmp_path / claim.temporary_key).exists()


@windows_mutation
async def test_replaced_source_in_close_to_pin_gap_is_not_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, claim = setup_store(tmp_path)
    original_fd = store._windows_fd
    temporary = tmp_path / claim.temporary_key

    def raced_fd(path: Path, *, directory: bool = False, delete: bool = False) -> int:
        if path == temporary and not delete:
            path.rename(path.with_name("owned-backup"))
            path.write_bytes(b"foreign-replacement")
        return original_fd(path, directory=directory, delete=delete)

    monkeypatch.setattr(store, "_windows_fd", raced_fd)
    with pytest.raises(UploadOwnershipError):
        await store.publish(claim, content())
    assert temporary.read_bytes() == b"foreign-replacement"
    assert not (tmp_path / claim.canonical_key).exists()


def test_observe_empty_and_present_original_without_mutation_support(tmp_path: Path) -> None:
    store, claim = setup_store(tmp_path)
    empty = store.observe(claim)
    assert empty.canonical is None and not empty.temporary_exists
    path = tmp_path / claim.canonical_key
    path.parent.mkdir(parents=True)
    path.write_bytes(b"hello world")
    observation = store.observe(claim)
    assert observation.canonical == StoredObject(
        claim.canonical_key,
        11,
        hashlib.sha256(b"hello world").hexdigest(),
    )
    assert not observation.temporary_exists
