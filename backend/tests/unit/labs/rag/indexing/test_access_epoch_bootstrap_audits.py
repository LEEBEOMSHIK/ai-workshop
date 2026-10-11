"""Bootstrap audits are actual recorded reads, never a successful reset guess."""

import json
from dataclasses import replace

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_admin_process import (
    admin_case,  # noqa: F401
    reserve,
)
from tests.unit.labs.rag.indexing.test_access_epoch_bootstrap import response


def authenticated():
    return {
        "username": "elastic",
        "roles": ["superuser"],
        "full_name": None,
        "email": None,
        "metadata": {"_reserved": True},
        "enabled": True,
        "authentication_type": "realm",
        "authentication_realm": {"name": "reserved", "type": "reserved"},
        "lookup_realm": {"name": "reserved", "type": "reserved"},
    }


async def audit_case(c):
    from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_audits import (
        RecordedBootstrapAudits,
    )

    action, ticket = await reserve(c)
    credential = await c.runner.run(action, ticket)
    auth = authenticated()
    user = {
        k: v
        for k, v in auth.items()
        if k not in {"authentication_type", "authentication_realm", "lookup_realm"}
    }
    c.native.outputs = [
        response(auth),
        response({"elastic": user}),
        response({"api_keys": []}),
        b"# comments\n",
        b"",
    ]
    original = c.native.wait

    def wait(token, timeout):
        c.native.output = c.native.outputs.pop(0)
        return original(token, timeout)

    c.native.wait = wait
    runner = RecordedBootstrapAudits(c.runner, c.factory, c.repo, c.journal, c.native)
    return runner, action, credential


async def test_bootstrap_admin_audits_require_five_recorded_actual_reads(admin_case):  # noqa: F811
    c = admin_case
    runner, action, credential = await audit_case(c)
    result = await runner.run(action, credential)
    assert runner.assert_issued(result) is None
    public = json.loads(result.manifest_json)
    assert public["administrator_authentication"] == "reserved_elastic"
    assert public["file_realm"] == "empty"
    assert public["historical_api_keys"] == "empty"
    assert len([x for x in c.native.calls if x[0] == "create"]) == 6
    assert c.repo.state.actions[-1].outcome == "pending"
    with pytest.raises(ValueError):
        runner.assert_issued(replace(result))
    result_again = await runner.run(action, credential)
    assert result_again.manifest_json == result.manifest_json
    assert len([x for x in c.native.calls if x[0] == "create"]) == 6


@pytest.mark.parametrize(
    "failure",
    [
        "copied_credential",
        "changed_generation",
        "key_present",
        "file_user",
        "timeout",
        "owner_loss",
    ],
)
async def test_unknown_security_or_helper_never_passes_bootstrap_audit(admin_case, failure):  # noqa: F811
    c = admin_case
    runner, action, credential = await audit_case(c)
    if failure == "copied_credential":
        credential = replace(credential)
    elif failure == "changed_generation":
        c.repo.state = replace(c.repo.state, executor_generation="other")
    elif failure == "key_present":
        c.native.outputs[2] = response({"api_keys": [{"id": "unapproved"}]})
    elif failure == "file_user":
        c.native.outputs[3] = b"user:private-hash"
    elif failure == "timeout":
        c.native.wait = lambda *args: (_ for _ in ()).throw(TimeoutError("private-error"))
    else:
        resume = c.native.resume

        def lose(token):
            resume(token)
            c.lock.close(c.owner)

        c.native.resume = lose
    with pytest.raises(ValueError, match="bootstrap_security_audit_unverified"):
        await runner.run(action, credential)
    calls = len(c.native.calls)
    with pytest.raises(ValueError):
        await runner.run(action, credential)
    assert len(c.native.calls) == calls


@pytest.mark.parametrize(
    "change",
    ["missing_capture", "nonempty_file_capture", "other_purpose", "other_child", "other_parent"],
)
async def test_completed_audit_recovery_rechecks_the_actual_protected_response(admin_case, change):  # noqa: F811
    c = admin_case
    runner, action, credential = await audit_case(c)
    await runner.run(action, credential)
    catalog_path = runner._path(action, f"{action.action_id}.security-audits.dpapi")
    packet = json.loads(c.memory.unprotect(c.memory.files[catalog_path]))
    step = packet["steps"][3]
    output_path = runner._path(action, f"{step['action_id']}.security-output.dpapi")
    if change == "missing_capture":
        c.memory.files.pop(output_path)
    else:
        import base64

        capture = json.loads(c.memory.unprotect(c.memory.files[output_path]))
        if change == "nonempty_file_capture":
            capture["stdout"] = base64.b64encode(b"unexpected-user:private").decode()
        elif change == "other_purpose":
            capture["binding"]["purpose"] = "api_keys"
        elif change == "other_parent":
            capture["binding"]["parent_action_id"] = "00000000-0000-4000-8000-000000000001"
        else:
            capture["binding"]["child"]["pid"] += 1
        from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json

        c.memory.files[output_path] = c.memory.protect(canonical_json(capture).encode())
    calls = len(c.native.calls)
    with pytest.raises(ValueError, match="bootstrap_security_audit_unverified"):
        await runner.run(action, credential)
    assert len(c.native.calls) == calls


async def test_owner_loss_during_protection_never_writes_private_audit_packet(admin_case):  # noqa: F811
    c = admin_case
    runner, action, credential = await audit_case(c)
    protect = c.memory.protect
    before_files = dict(c.memory.files)

    def lose_owner(data):
        result = protect(data)
        c.lock.close(c.owner)
        return result

    c.memory.protect = lose_owner
    calls = len(c.native.calls)
    with pytest.raises(ValueError):
        await runner.run(action, credential)
    assert c.memory.files == before_files
    assert len(c.native.calls) == calls
