"""Actual fixed assembly/NativePrivate/Store/Source over low transports only."""

import asyncio
import base64
import json
import os
from copy import copy
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_secured_read import NativeSecuredReadSource
from ai_workshop.labs.rag.indexing.alias_models import AliasRecoveryReceiptRecord
from tests.unit.labs.rag.indexing import native_private_material_transport_support as material_wire

pytestmark = pytest.mark.asyncio
pytest_plugins = ["tests.unit.labs.rag.indexing.native_secured_read_graph_support"]


@pytest.fixture
def graph(material_graph: Any) -> Any:
    return material_graph


async def test_actual_source_verified_bind_retained_and_revalidate(graph: Any) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    source.assert_bound(cap)
    await source.revalidate(cap)
    assert cap.phase == "verified" and store.dml_count == store.commit_count == 0
    assert material.dpapi_reads > 0 and material.acl_reads > 0
    assert deps.store.files is deps.store.protection is deps.private
    deps.private.assert_origin()
    assert not material.retained


async def test_actual_blob_transform_and_checked_private_read(graph: Any) -> None:
    _, _, deps, _, material = graph
    plaintext = b"synthetic-public-material"
    ciphertext = deps.private.protect(plaintext)
    assert deps.private.unprotect(ciphertext) == plaintext
    checked = deps.private.read_protected(str(material.private / "floor.dpapi"), limit=8192)
    assert checked.data.startswith(b"synthetic:")
    assert material.opens == 1 and not material.retained


@pytest.mark.parametrize("graph", ["receipted"], indirect=True)
async def test_actual_source_initial_receipted_binding(graph: Any) -> None:
    store, assembly, deps, c, _ = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    assert cap.phase == "receipted"
    await source.revalidate(cap)
    assert store.dml_count == store.commit_count == 0


async def test_actual_source_retains_binding_across_exact_receipt_transition(graph: Any) -> None:
    store, assembly, deps, c, _ = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    await c.repository.close_access_epoch(c.claim, c.proof)
    receipt = next(row for key, row in c.db.rows.items() if key[0] is AliasRecoveryReceiptRecord)
    receipt.access_epoch_id = UUID(c.epoch.binding.access_epoch_id)
    receipt.execution_id = UUID(c.epoch.binding.execution_id)
    for rows in store.tables.values():
        rows.clear()
    for record in c.db.rows.values():
        store.seed(record)
    await source.revalidate(cap)
    source.assert_bound(cap)
    assert cap.phase == "verified" and store.dml_count == store.commit_count == 0


def corrupt(graph: Any, change: str) -> None:
    _, _, deps, c, material = graph
    if change == "owner":
        material.owner_valid = False
    elif change == "acl":
        material.acl_valid = False
    elif change == "floor_missing":
        (material.files / "floor.dpapi").unlink()
    elif change == "floor_cipher":
        (material.files / "floor.dpapi").write_bytes(b"unrecognized-synthetic-ciphertext")
    elif change == "reader_cipher":
        (material.files / str(c.epoch.binding.access_epoch_id) / "reader.dpapi").write_bytes(
            b"invalid"
        )
    elif change == "claim":
        object.__setattr__(c.claim, "revision", True)
    elif change == "shared_key_parent":
        deps.keys.parent = copy(deps.repository)
    elif change == "cancel":
        material.cancel_decrypt = True
    else:
        raise AssertionError("unknown_synthetic_fault")


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "acl",
        "floor_missing",
        "floor_cipher",
        "reader_cipher",
        "claim",
        "shared_key_parent",
        "cancel",
    ],
)
async def test_actual_source_failed_initial_binding_issues_no_cap(graph: Any, change: str) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    corrupt(graph, change)
    with pytest.raises(asyncio.CancelledError if change == "cancel" else ValueError):
        await source.bind_verified(c.claim)
    assert not source._issued
    assert not material.retained and store.dml_count == store.commit_count == 0


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "acl",
        "floor_missing",
        "floor_cipher",
        "reader_cipher",
        "claim",
        "shared_key_parent",
        "cancel",
    ],
)
async def test_actual_source_revalidate_refuses_changed_material_or_association(
    graph: Any, change: str
) -> None:
    store, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    corrupt(graph, change)
    with pytest.raises(asyncio.CancelledError if change == "cancel" else ValueError):
        await source.revalidate(cap)
    assert not material.retained and store.dml_count == store.commit_count == 0


async def test_source_component_and_dependency_copies_do_not_gain_origin(graph: Any) -> None:
    _, assembly, deps, c, _ = graph
    with pytest.raises(ValueError):
        NativeSecuredReadSource._from_committed_dependencies(assembly, copy(deps))
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    with pytest.raises(ValueError):
        copy(source)._assert_committed_dependencies()
    with pytest.raises(ValueError):
        source.assert_bound(copy(cap))


async def test_valid_same_key_secret_change_is_not_reblessed(graph: Any) -> None:
    _, assembly, deps, c, material = graph
    source = NativeSecuredReadSource._from_committed_dependencies(assembly, deps)
    cap = await source.bind_verified(c.claim)
    file = material.files / c.epoch.binding.access_epoch_id / "reader.dpapi"
    payload = json.loads(deps.private.unprotect(file.read_bytes()))
    payload["secret"] = base64.b64encode(
        (payload["key_id"] + ":synthetic-changed-secret").encode()
    ).decode()
    file.write_bytes(deps.private.protect(json.dumps(payload, sort_keys=True).encode()))
    with pytest.raises(ValueError, match="^secured_read_binding_denied$"):
        await source.revalidate(cap)
    assert not material.retained


@pytest.mark.parametrize("operation", ["mkdir", "unlink", "replace"])
async def test_fixed_original_private_mutation_cannot_fall_through(
    protected_transport: material_wire.MaterialTransport, operation: str
) -> None:
    fixed = protected_transport.private / "synthetic-unpublished.dpapi"
    with pytest.raises(AssertionError, match="^synthetic_private_write_denied$"):
        if operation == "mkdir":
            fixed.mkdir()
        elif operation == "unlink":
            fixed.unlink()
        else:
            os.replace(fixed, fixed.with_name("synthetic-other.dpapi"))
