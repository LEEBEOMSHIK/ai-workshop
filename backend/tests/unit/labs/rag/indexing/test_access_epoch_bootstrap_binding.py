"""Bind bootstrap grammar to independently issued observations and committed state."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap_retirement import (
    bootstrap_case,  # noqa: F401
)


async def factory_case(c, monkeypatch):
    from ai_workshop.labs.rag.indexing import access_epoch_bootstrap_binding as module
    from ai_workshop.labs.rag.indexing.access_epoch_original_security import (
        OriginalSecurityAbsenceReader,
    )

    class Identity:
        async def observe_original(self, snapshot):
            return c.builder.epoch.original

    class Security:
        async def read(self, path):
            return []

    reader = OriginalSecurityAbsenceReader(Identity(), Security())
    absence = await reader.observe(c.builder.epoch.binding.claim.snapshot)
    monkeypatch.setattr(module, "PROJECT_ROOT", c.journal.root)
    factory = module.BootstrapBindingFactory(c.repo, c.journal, c.builder, reader)
    permissions = AccessEpochPermissions(
        "synthetic", ((UUID(c.builder.epoch.binding.access_epoch_id), None),)
    )
    return SimpleNamespace(factory=factory, absence=absence, permissions=permissions)


async def test_only_exact_observations_and_settled_bootstrap_create_builder(
    bootstrap_case,  # noqa: F811
    monkeypatch,
):
    c = bootstrap_case
    f = await factory_case(c, monkeypatch)
    result = await f.factory.create(c.bootstrap, f.absence, f.permissions)
    assert result.binding.container_id == c.bootstrap.container_id
    assert result.binding.original_security_absent is True
    assert f.factory.assert_issued(result) is None
    assert c.native.calls == []


@pytest.mark.parametrize(
    "change",
    [
        "copied_bootstrap",
        "copied_absence",
        "boolean",
        "unsettled",
        "wrong_manifest",
        "wrong_generation",
        "wrong_root",
        "wrong_scope",
    ],
)
async def test_unbound_bootstrap_never_creates_command_grammar(
    bootstrap_case,  # noqa: F811
    monkeypatch,
    change,
):
    c = bootstrap_case
    f = await factory_case(c, monkeypatch)
    bootstrap, absence = c.bootstrap, f.absence
    if change == "copied_bootstrap":
        bootstrap = replace(bootstrap)
    elif change == "copied_absence":
        absence = replace(absence)
    elif change == "boolean":
        absence = True
    elif change in {"unsettled", "wrong_manifest"}:
        actions = tuple(
            replace(x, outcome="pending")
            if change == "unsettled" and x.action.action_id == bootstrap.action_id
            else replace(x, manifest_json="{}")
            if change == "wrong_manifest" and x.action.action_id == bootstrap.action_id
            else x
            for x in c.repo.state.actions
        )
        c.repo.state = replace(c.repo.state, actions=actions)
    elif change == "wrong_generation":
        c.repo.state = replace(c.repo.state, executor_generation="wrong")
    elif change == "wrong_scope":
        monkeypatch.setattr(type(c.journal.lock), "scope_sha256", property(lambda self: "a" * 64))
    else:
        c.journal.root = c.journal.root / "unrelated"
    with pytest.raises(ValueError, match="bootstrap_binding_unverified"):
        await f.factory.create(bootstrap, absence, f.permissions)
    assert c.native.calls == []
