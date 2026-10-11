"""Role group orchestration: durable reservations, private capture and reconciliation."""

import base64
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import (
    BootstrapBinding,
    BootstrapCommands,
)
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError
from tests.unit.labs.rag.indexing.test_access_epoch_keys import group


@pytest.mark.parametrize("change", ["epoch", "execution", "parent_kind", "parent_execution"])
async def test_group_binding_change_denies_before_any_key_command(change):
    from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind

    c = await case()
    if change == "epoch":
        c.builder.binding = replace(c.builder.binding, epoch_id=UUID(int=500))
    elif change == "execution":
        c.builder.binding = replace(c.builder.binding, execution_id=UUID(int=500))
    elif change == "parent_kind":
        c.controller.parent = replace(c.parent, kind=CutoverActionKind.BOOTSTRAP_ADMIN)
    else:
        c.controller.parent = replace(c.parent, execution_id=UUID(int=500))
    with pytest.raises(AliasRecoveryError, match="rag_alias_proof_invalid"):
        await c.controller.advance()
    assert c.commands.posts == []


def encoded(key_id):
    return base64.b64encode((key_id + ":synthetic-secret").encode()).decode()


def response(value):
    return json.dumps(value).encode() + b"\n200"


async def case():
    from ai_workshop.labs.rag.indexing.access_epoch_role_keys import (
        BootstrapRoleKeyGroup,
        PrivateBootstrapResult,
    )

    db, repo, keys, epoch, parent = await group()
    permissions = AccessEpochPermissions("rag", ((UUID(int=2), None),))
    builder = BootstrapCommands(
        BootstrapBinding(
            DOCKER_EXE,
            "npipe:////./pipe/dockerDesktopLinuxEngine",
            "d" * 64,
            UUID(epoch.binding.access_epoch_id),
            UUID(epoch.binding.execution_id),
            True,
        ),
        permissions,
    )

    class Commands:
        def __init__(self):
            self.posts = []
            self.rows = {}
            self.lose_issue_ack = False
            self.lose_invalidation_ack = False
            self.fail_lookup = False

        async def execute(self, command, reservation):
            stdin = command.private_stdin.decode()
            if 'request = "POST"' in stdin:
                assert reservation is not None and reservation.kind == "issue"
                readback = await keys.readback(epoch, parent)
                assert readback[-1].action == reservation and readback[-1].outcome == "pending"
                self.posts.append(reservation.issuance_id)
                key_id = "synthetic-" + reservation.issuance_id.hex
                payload = {
                    "id": key_id,
                    "name": command.key_name,
                    "api_key": "synthetic-secret",
                    "encoded": encoded(key_id),
                }
                self.rows[command.key_name] = {
                    "id": key_id,
                    "name": command.key_name,
                    "creation": 1,
                    "invalidated": False,
                    "username": "elastic",
                    "realm": "reserved",
                    "type": "rest",
                    "metadata": {
                        "ai_workshop_epoch": epoch.binding.access_epoch_id,
                        "ai_workshop_issuance": str(reservation.issuance_id),
                        "ai_workshop_role": reservation.role,
                    },
                    "role_descriptors": {
                        reservation.role: permissions.descriptor(reservation.role)
                    },
                }
                if self.lose_issue_ack:
                    self.lose_issue_ack = False
                    raise OSError("synthetic-private-body")
                return PrivateBootstrapResult(0, response(payload))
            if 'request = "DELETE"' in stdin:
                assert reservation is not None and reservation.kind == "invalidate"
                row = next(x for x in self.rows.values() if x["id"] == reservation.key_id)
                row["invalidated"] = True
                if self.lose_invalidation_ack:
                    self.lose_invalidation_ack = False
                    raise OSError("synthetic-private-body")
                return PrivateBootstrapResult(
                    0,
                    response(
                        {
                            "invalidated_api_keys": [row["id"]],
                            "previously_invalidated_api_keys": [],
                            "error_count": 0,
                        }
                    ),
                )
            assert reservation is None
            if self.fail_lookup:
                raise OSError("synthetic-private-body")
            return PrivateBootstrapResult(
                0,
                response(
                    {
                        "api_keys": [self.rows[command.key_name]]
                        if command.key_name in self.rows
                        else []
                    }
                ),
            )

    class Store:
        def __init__(self):
            self.rows = {}
            self.lose_ack = False

        def put(self, value):
            self.rows[value.role] = value
            if self.lose_ack:
                self.lose_ack = False
                raise OSError("synthetic-private-body")

        def read_prepared(self, epoch_id, ordinal, role, key_id):
            row = self.rows.get(role)
            return (
                row
                if row and (row.epoch_id, row.ordinal, row.key_id) == (epoch_id, ordinal, key_id)
                else None
            )

    commands, store = Commands(), Store()
    owned = []

    def assert_owned():
        owned.append(True)

    controller = BootstrapRoleKeyGroup(
        epoch,
        parent,
        keys,
        builder,
        commands,
        store,
        assert_owned,
        SecretStr("Synthetic20Character"),
    )
    return SimpleNamespace(
        db=db,
        repo=repo,
        keys=keys,
        epoch=epoch,
        parent=parent,
        builder=builder,
        commands=commands,
        store=store,
        controller=controller,
        owned=owned,
    )


async def test_three_keys_are_private_and_durable_before_parent_can_complete():
    c = await case()
    manifest = await c.controller.advance()
    assert manifest is not None and set(manifest["keys"]) == {"reader", "writer", "collector"}
    assert len(c.commands.posts) == 3 and len(set(c.commands.posts)) == 3
    assert all(
        row.secret.get_secret_value() not in json.dumps(manifest) for row in c.store.rows.values()
    )
    assert c.owned


async def test_lost_issue_ack_is_looked_up_invalidated_then_replaced_once():
    c = await case()
    c.commands.lose_issue_ack = True
    assert await c.controller.advance() is None
    assert len(c.commands.posts) == 1
    result = await c.controller.advance()
    assert result is not None and len(c.commands.posts) == 4
    rows = await c.keys.readback(c.epoch, c.parent)
    assert rows[0].result.result == "issued_inaccessible"
    assert rows[1].action.kind == "invalidate" and rows[1].result.result == "invalidated"
    assert rows[2].action.replaces_issuance_id == rows[0].action.issuance_id


async def test_lost_private_store_ack_recovers_same_key_without_second_post():
    c = await case()
    c.store.lose_ack = True
    assert await c.controller.advance() is None
    assert len(c.commands.posts) == 1
    result = await c.controller.advance()
    assert result is not None and len(c.commands.posts) == 3
    assert all(row.action.kind == "issue" for row in await c.keys.readback(c.epoch, c.parent))


async def test_unknown_lookup_preserves_group_and_never_reposts():
    c = await case()
    c.commands.lose_issue_ack = True
    assert await c.controller.advance() is None
    c.commands.fail_lookup = True
    for _ in range(2):
        assert await c.controller.advance() is None
    assert len(c.commands.posts) == 1
    assert len(await c.keys.readback(c.epoch, c.parent)) == 1


async def test_invalidation_ack_loss_resolves_read_only_before_replacement():
    c = await case()
    c.commands.lose_issue_ack = True
    assert await c.controller.advance() is None
    c.commands.lose_invalidation_ack = True
    assert await c.controller.advance() is None
    assert len(c.commands.posts) == 1
    assert await c.controller.advance() is not None
    assert len(c.commands.posts) == 4
