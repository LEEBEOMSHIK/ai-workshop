"""Final credential binding uses settled child truth and protected material."""

import base64
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import CredentialEnvelope
from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    KeyActionReadback,
    KeyResult,
    ReservedKeyAction,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_repository import ActionReadback
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    canonical_json,
)
from tests.unit.labs.rag.indexing import test_access_epoch_deployment as fixtures
from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_binding import factory_case
from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_retirement import (
    bootstrap_case,  # noqa: F401
)


async def binding_case(c, monkeypatch):
    from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import (
        FinalAuthBindingFactory,
    )

    f = await factory_case(c, monkeypatch)
    commands = await f.factory.create(c.bootstrap, f.absence, f.permissions)
    final_action = replace(
        fixtures.action(c.builder, CutoverActionKind.START_SECURED),
        executor_generation=c.journal.owner.executor_generation,
    )
    final = fixtures.observation(
        c.builder,
        final_action,
        fixtures.container_json(c.builder, final_action, "f" * 64),
        c.bootstrap,
    )
    parent = next(
        x.action for x in c.repo.state.actions if x.action.kind == CutoverActionKind.ISSUE_ROLE_KEY
    )
    rows, envelopes = [], {}
    for i, role in enumerate(("reader", "writer", "collector")):
        issuance = uuid4()
        key_id = "synthetic-key-" + role
        descriptor = sha256(
            canonical_json(commands.permissions_descriptor(role)).encode()
        ).hexdigest()
        action = ReservedKeyAction(
            uuid4(),
            parent.execution_id,
            parent.action_id,
            i * 2 + 1,
            parent.executor_generation,
            role,
            issuance,
            "issue",
            None,
            None,
            descriptor,
        )
        rows.append(
            KeyActionReadback(
                action,
                "settled",
                KeyResult("issued", key_id, role, issuance, descriptor, fixtures.NOW),
            )
        )
        envelopes[role] = CredentialEnvelope(
            UUID(c.builder.epoch.binding.access_epoch_id),
            c.builder.epoch.binding.ordinal,
            role,
            key_id,
            SecretStr(base64.b64encode((key_id + ":private").encode()).decode()),
        )
    group = {
        "schema_version": 1,
        "execution_id": str(parent.execution_id),
        "parent_action_id": str(parent.action_id),
        "keys": {x.action.role: x.result.key_id for x in rows},
        "issuances": {x.action.role: str(x.action.issuance_id) for x in rows},
        "permissions": {x.action.role: x.action.permissions_sha256 for x in rows},
    }
    actions = []
    for i, kind in enumerate(CUTOVER_ORDER[:-1]):
        action = replace(
            parent,
            action_id=uuid4(),
            sequence=2 * i + 1,
            kind=kind,
            expected=ControlExpectedIdentity("{}", 2 * i),
        )
        payload = "{}"
        if kind == CutoverActionKind.ISSUE_ROLE_KEY:
            action, payload = parent, canonical_json(group)
        elif kind == CutoverActionKind.PREPARE_TLS:
            payload = c.builder.tls.manifest_json
        elif kind == CutoverActionKind.START_BOOTSTRAP:
            action, payload = c.repo.state.actions[i].action, c.bootstrap.manifest_json
        elif kind == CutoverActionKind.START_SECURED:
            action = replace(
                final_action,
                sequence=2 * i + 1,
                expected=replace(final_action.expected, preceding_sequence=2 * i),
            )
            payload = final.manifest_json
        actions.append(
            ActionReadback(
                action, "settled", payload, fixtures.NOW + timedelta(seconds=2), 2 * i + 2
            )
        )
    c.repo.state = replace(c.repo.state, phase="secured_started", actions=tuple(actions))

    class Keys:
        parent = c.repo

        async def read_completed(self, epoch, actual_parent):
            assert actual_parent == parent
            return tuple(rows)

    class Store:
        def read_prepared(self, epoch, ordinal, role, key_id):
            return envelopes[role]

    class Tls:
        async def read_settled(self, action):
            return c.builder.tls

        def assert_issued(self, assets):
            assert assets is c.builder.tls

    monkeypatch.setattr(
        "ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding.PROJECT_ROOT", c.journal.root
    )
    factory = FinalAuthBindingFactory(
        c.repo, Keys(), c.journal, c.builder, f.factory, commands, Tls(), Store()
    )
    return SimpleNamespace(factory=factory, final=final, rows=rows, envelopes=envelopes)


async def test_exact_final_daemon_and_completed_keys_produce_issued_binding(
    bootstrap_case, monkeypatch  # noqa: F811
):  # noqa: F811
    c = bootstrap_case
    b = await binding_case(c, monkeypatch)
    binding = await b.factory.create(b.final)
    assert binding.container_id == b.final.container_id
    assert {x.role for x in binding.keys} == {"reader", "writer", "collector"}
    assert b.factory.assert_issued(binding) is None
    with pytest.raises(ValueError):
        b.factory.assert_issued(replace(binding))
    assert c.native.calls == []


@pytest.mark.parametrize(
    "change",
    [
        "copied_final",
        "wrong_parent_manifest",
        "pending_key",
        "wrong_descriptor",
        "wrong_secret_identity",
        "changed_generation",
    ],
)
async def test_unbound_or_unsettled_final_keys_never_mint_capability(
    bootstrap_case, monkeypatch, change  # noqa: F811
):  # noqa: F811
    c = bootstrap_case
    b = await binding_case(c, monkeypatch)
    final = b.final
    if change == "copied_final":
        final = replace(final)
    elif change == "wrong_parent_manifest":
        c.repo.state = replace(
            c.repo.state,
            actions=tuple(
                replace(x, manifest_json="{}")
                if x.action.kind == CutoverActionKind.ISSUE_ROLE_KEY
                else x
                for x in c.repo.state.actions
            ),
        )
    elif change == "pending_key":
        b.rows[0] = replace(b.rows[0], outcome="pending", result=None)
    elif change == "wrong_descriptor":
        b.rows[0] = replace(
            b.rows[0], action=replace(b.rows[0].action, permissions_sha256="a" * 64)
        )
    elif change == "wrong_secret_identity":
        b.envelopes["reader"] = replace(b.envelopes["reader"], key_id="other")
    else:
        c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
    with pytest.raises(ValueError, match="final_auth_binding_unverified"):
        await b.factory.create(final)
    assert c.native.calls == []
